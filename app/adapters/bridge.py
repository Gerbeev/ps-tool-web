"""Out-of-process scheduler adapter using the frozen scheduler-bridge v1 protocol."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.adapters.base import SchedulerAdapter
from app.adapters.bridge_contract import (
    BRIDGE_PROTOCOL,
    BRIDGE_VERSION,
    BridgeHealthDataV1,
    BridgeJobDetailDataV1,
    BridgeOperation,
    BridgeRequestV1,
    BridgeResponseV1,
    BridgeRootsDataV1,
    BridgeTopologyDataV1,
    capabilities_to_engine,
    dependency_to_engine,
    job_to_engine,
    request_context_from_engine,
)
from app.adapters.builder import TopologySnapshotBuilder
from app.config import EnvironmentEntry, get_settings
from app.models import AdapterCapabilities, ComparisonContext, SchedulerType, SnapshotJob, TopologySnapshot

_SCRIPT_BY_SCHEDULER = {
    SchedulerType.AUTOSYS: "autosys_connector.py",
    SchedulerType.PROCESS_SCHEDULER: "process_scheduler_connector.py",
}


class BridgeProtocolError(RuntimeError):
    """Connector process ran, but violated the bridge protocol."""


class BridgeConnectorError(RuntimeError):
    """Connector returned a structured source-system failure."""


class ExternalBridgeAdapter(SchedulerAdapter):
    """Generic adapter for bank-local connector scripts.

    The scripts are separate processes and must not import ``app``. They receive one
    JSON request on stdin and return one JSON response on stdout. Diagnostics belong on
    stderr. This keeps bank-only connector code independent from web-engine internals.
    """

    def __init__(self, environment: EnvironmentEntry, scheduler_type: SchedulerType) -> None:
        self.environment = environment
        self.scheduler_type = scheduler_type
        settings = get_settings()
        self._connector_dir = settings.connector_dir.resolve()
        self._python = settings.connector_python or sys.executable
        self._timeout_sec = settings.connector_timeout_sec
        self._max_response_bytes = settings.connector_max_response_mb * 1024 * 1024
        self._capabilities = AdapterCapabilities(strict_parameter_support=False)

    @property
    def script_path(self) -> Path:
        filename = _SCRIPT_BY_SCHEDULER[self.scheduler_type]
        return self._connector_dir / filename

    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    def health_check(self, environment_id: str) -> bool:
        context = ComparisonContext(environment_id=environment_id, scheduler=self.scheduler_type)
        response = self._call(BridgeOperation.HEALTH, context)
        data = BridgeHealthDataV1.model_validate(response.data)
        return data.healthy

    def list_roots(self, context: ComparisonContext) -> list[str]:
        response = self._call(BridgeOperation.LIST_ROOTS, context)
        return BridgeRootsDataV1.model_validate(response.data).roots

    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        response = self._call(BridgeOperation.FETCH_TOPOLOGY, context)
        payload = BridgeTopologyDataV1.model_validate(response.data)
        builder = TopologySnapshotBuilder(
            context,
            capabilities=self._capabilities,
            metadata={
                **payload.metadata,
                "connector_protocol": f"{BRIDGE_PROTOCOL}/v{BRIDGE_VERSION}",
            },
        )
        for item in payload.jobs:
            builder.add_job(job_to_engine(item))
        for item in payload.dependencies:
            edge = dependency_to_engine(item)
            builder.add_dependency(
                edge.from_uid,
                edge.to_uid,
                kind=edge.kind,
                condition=edge.condition,
            )
        snapshot = builder.build()
        if payload.fetched_at is not None:
            snapshot.fetched_at = payload.fetched_at
        return snapshot

    def fetch_job_detail(self, context: ComparisonContext, job_uid: str) -> SnapshotJob | None:
        response = self._call(BridgeOperation.FETCH_JOB_DETAIL, context, job_uid=job_uid)
        data = BridgeJobDetailDataV1.model_validate(response.data)
        return job_to_engine(data.job) if data.job is not None else None

    def _call(
        self,
        operation: BridgeOperation,
        context: ComparisonContext,
        *,
        job_uid: str | None = None,
    ) -> BridgeResponseV1:
        script = self.script_path
        if not script.is_file():
            raise FileNotFoundError(
                f"Workstation connector is missing: {script}. "
                "Copy the v1 connector templates from examples/workstation_connectors/ "
                "and implement the bank-local source calls there."
            )

        request = BridgeRequestV1(
            request_id=str(uuid4()),
            operation=operation,
            context=request_context_from_engine(
                context,
                environment=self.environment.environment,
                host=self.environment.endpoint_url,
            ),
            job_uid=job_uid,
        )
        raw_request = request.model_dump_json(exclude_none=True)
        try:
            completed = subprocess.run(
                [self._python, str(script)],
                input=raw_request,
                text=True,
                encoding="utf-8",
                errors="strict",
                capture_output=True,
                timeout=self._timeout_sec,
                check=False,
                cwd=str(self._connector_dir),
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeConnectorError(
                f"{self.scheduler_type.value} connector timed out after {self._timeout_sec}s"
            ) from exc
        except OSError as exc:
            raise BridgeConnectorError(
                f"Failed to start {self.scheduler_type.value} connector: {exc}"
            ) from exc

        stdout = completed.stdout or ""
        if len(stdout.encode("utf-8")) > self._max_response_bytes:
            raise BridgeProtocolError(
                f"Connector response exceeds {get_settings().connector_max_response_mb} MB limit"
            )
        if completed.returncode != 0:
            raise BridgeConnectorError(
                f"{self.scheduler_type.value} connector exited with code {completed.returncode}"
            )
        if not stdout.strip():
            raise BridgeProtocolError("Connector returned empty stdout")

        try:
            response = BridgeResponseV1.model_validate_json(stdout)
        except (ValidationError, json.JSONDecodeError) as exc:
            # Do not echo the raw connector response or Pydantic input values into
            # application errors: source DTOs may contain sensitive bank data.
            if isinstance(exc, ValidationError):
                locations = [".".join(str(part) for part in item["loc"]) for item in exc.errors(include_input=False)]
                reason = ", ".join(locations[:5]) or "schema mismatch"
            else:
                reason = "invalid JSON"
            raise BridgeProtocolError(
                f"Invalid scheduler-bridge/v1 response ({reason})"
            ) from exc

        if response.request_id != request.request_id:
            raise BridgeProtocolError("Connector response request_id does not match request")
        if response.capabilities is not None:
            self._capabilities = capabilities_to_engine(response.capabilities)
        if not response.ok:
            if response.error is None:
                raise BridgeProtocolError("Connector returned ok=false without error payload")
            raise BridgeConnectorError(
                f"{response.error.code}: {response.error.message}"
                + (" [retryable]" if response.error.retryable else "")
            )
        if response.error is not None:
            raise BridgeProtocolError("Connector returned ok=true together with error payload")
        return response
