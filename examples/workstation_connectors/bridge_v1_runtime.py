"""Frozen scheduler-bridge/v1 runtime for bank-local connector scripts.

Stdlib only. Keep this file unchanged after copying it to workstation_connectors/.
Source-specific code belongs in autosys_connector.py / process_scheduler_connector.py.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

PROTOCOL = "scheduler-bridge"
VERSION = 1
ALLOWED_OPERATIONS = {"health", "list_roots", "fetch_topology", "fetch_job_detail"}
ALLOWED_SCHEDULERS = {"autosys", "process_scheduler"}


@dataclass
class ConnectorError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class Provider(Protocol):
    scheduler: str

    def capabilities(self) -> dict[str, Any]: ...
    def health(self, context: dict[str, Any]) -> dict[str, Any]: ...
    def list_roots(self, context: dict[str, Any]) -> dict[str, Any]: ...
    def fetch_topology(self, context: dict[str, Any]) -> dict[str, Any]: ...
    def fetch_job_detail(self, context: dict[str, Any], job_uid: str) -> dict[str, Any]: ...


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object is not JSON serializable: {type(value).__name__}")


def _response(request_id: str, *, ok: bool, data: dict[str, Any] | None = None,
              error: dict[str, Any] | None = None, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol": PROTOCOL,
        "version": VERSION,
        "request_id": request_id,
        "ok": ok,
        "data": data or {},
        "error": error,
    }
    if capabilities is not None:
        payload["capabilities"] = capabilities
    return payload


def _validate_request(raw: Any, provider: Provider) -> tuple[str, str, dict[str, Any], str | None]:
    if not isinstance(raw, dict):
        raise ConnectorError("invalid_request", "Request must be a JSON object")
    request_id = raw.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ConnectorError("invalid_request", "request_id is required")
    if raw.get("protocol") != PROTOCOL or raw.get("version") != VERSION:
        raise ConnectorError("unsupported_protocol", f"Expected {PROTOCOL}/v{VERSION}")
    operation = raw.get("operation")
    if operation not in ALLOWED_OPERATIONS:
        raise ConnectorError("unsupported_operation", f"Unsupported operation: {operation!r}")
    context = raw.get("context")
    if not isinstance(context, dict):
        raise ConnectorError("invalid_request", "context must be an object")
    scheduler = context.get("scheduler")
    if scheduler not in ALLOWED_SCHEDULERS or scheduler != provider.scheduler:
        raise ConnectorError(
            "scheduler_mismatch",
            f"Connector is {provider.scheduler!r}, request is {scheduler!r}",
        )
    environment_id = context.get("environment_id")
    if not isinstance(environment_id, str) or not environment_id:
        raise ConnectorError("invalid_request", "context.environment_id is required")
    job_uid = raw.get("job_uid")
    if job_uid is not None and not isinstance(job_uid, str):
        raise ConnectorError("invalid_request", "job_uid must be a string")
    return request_id, operation, context, job_uid


def run(provider: Provider) -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    request_id = "unknown"
    try:
        raw_text = sys.stdin.read()
        raw = json.loads(raw_text)
        if isinstance(raw, dict) and isinstance(raw.get("request_id"), str):
            request_id = raw["request_id"]
        request_id, operation, context, job_uid = _validate_request(raw, provider)

        if operation == "health":
            data = provider.health(context)
        elif operation == "list_roots":
            data = provider.list_roots(context)
        elif operation == "fetch_topology":
            data = provider.fetch_topology(context)
        else:
            if not job_uid:
                raise ConnectorError("invalid_request", "job_uid is required for fetch_job_detail")
            data = provider.fetch_job_detail(context, job_uid)

        payload = _response(
            request_id,
            ok=True,
            data=data,
            capabilities=provider.capabilities(),
        )
    except ConnectorError as exc:
        payload = _response(
            request_id,
            ok=False,
            error={
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "details": exc.details or {},
            },
        )
    except Exception as exc:
        # Do not leak tracebacks/source payloads through stdout. Operators may add
        # sanitized diagnostics to stderr locally if required.
        payload = _response(
            request_id,
            ok=False,
            error={
                "code": "connector_internal_error",
                "message": f"{type(exc).__name__}: connector failed",
                "retryable": False,
                "details": {},
            },
        )

    sys.stdout.write(json.dumps(payload, default=_json_default, separators=(",", ":")))
    return 0
