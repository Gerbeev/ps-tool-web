"""Frozen external connector protocol v1 and translation into engine models.

This module is the compatibility boundary between the portable web application and
bank-local connector scripts. Protocol v1 is append-only: breaking changes require a
new protocol version instead of changing existing field meanings.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.autosys_reference import AutoSysJobDefinition, AutoSysJobReference, AutoSysRunInstance
from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    FieldEvidence,
    FieldSupport,
    JobStatus,
    SnapshotJob,
)
from app.process_scheduler_reference import ProcessSchedulerJobReference

BRIDGE_PROTOCOL = "scheduler-bridge"
BRIDGE_VERSION = 1


class BridgeOperation(str, Enum):
    HEALTH = "health"
    LIST_ROOTS = "list_roots"
    FETCH_TOPOLOGY = "fetch_topology"
    FETCH_JOB_DETAIL = "fetch_job_detail"


class BridgeRequestContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    environment: str = ""
    scheduler: Literal["autosys", "process_scheduler"]
    host: str = ""
    as_of_kind: Literal["business_date", "run_id", "latest"] = "business_date"
    as_of_value: str = ""
    root_box: str | None = None
    topology_id: str | None = None


class BridgeRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["scheduler-bridge"] = BRIDGE_PROTOCOL
    version: Literal[1] = BRIDGE_VERSION
    request_id: str
    operation: BridgeOperation
    context: BridgeRequestContextV1
    job_uid: str | None = None


class BridgeErrorV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class BridgeCapabilitiesV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology: bool = True
    dependencies: bool = True
    runtime: bool = True
    job_detail: bool = True
    root_listing: bool = True
    autosys_projection: bool = True
    strict_parameter_support: bool = True
    parameter_support: dict[str, Literal["supported", "unsupported", "unknown", "not_applicable"]] = Field(
        default_factory=dict
    )


class BridgeEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    locator: str = ""
    note: str = ""


class BridgeJobV1(BaseModel):
    """Stable wire job representation.

    ``autosys_jil`` / ``autosys_run`` and ``process_scheduler`` deliberately use open
    dictionaries. Known v1 fields keep their meaning forever, while newly observed
    source fields can be added without changing the transport envelope.
    """

    model_config = ConfigDict(extra="forbid")

    job_uid: str
    scheduler_job_name: str
    scheduler_native_id: str | None = None
    parent_uid: str | None = None
    path_labels: list[str] = Field(default_factory=list)
    status: Literal[
        "pending",
        "running",
        "success",
        "failure",
        "killed",
        "unknown",
        "not_run",
        "disabled",
    ] = "unknown"
    status_raw: str = ""
    scheduled_start: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    duration_sec: float | None = None
    exit_code: int | None = None
    autosys_jil: dict[str, Any] = Field(default_factory=dict)
    autosys_run: dict[str, Any] = Field(default_factory=dict)
    process_scheduler: dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    comparison_support: dict[
        str, Literal["supported", "unsupported", "unknown", "not_applicable"]
    ] = Field(default_factory=dict)
    comparison_evidence: dict[str, BridgeEvidenceV1] = Field(default_factory=dict)


class BridgeDependencyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_uid: str
    to_uid: str
    kind: Literal["finish_to_start", "start_to_start", "file_trigger", "custom"] = (
        "finish_to_start"
    )
    condition: str | None = None


class BridgeTopologyDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fetched_at: datetime | None = None
    jobs: list[BridgeJobV1] = Field(default_factory=list)
    dependencies: list[BridgeDependencyV1] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BridgeJobDetailDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: BridgeJobV1 | None = None


class BridgeRootsDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roots: list[str] = Field(default_factory=list)


class BridgeHealthDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    healthy: bool
    message: str = ""


class BridgeResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["scheduler-bridge"] = BRIDGE_PROTOCOL
    version: Literal[1] = BRIDGE_VERSION
    request_id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: BridgeErrorV1 | None = None
    capabilities: BridgeCapabilitiesV1 | None = None


def request_context_from_engine(
    context: ComparisonContext,
    *,
    environment: str,
    host: str,
) -> BridgeRequestContextV1:
    return BridgeRequestContextV1(
        environment_id=context.environment_id,
        environment=environment,
        scheduler=context.scheduler.value,
        host=host,
        as_of_kind=context.as_of.kind.value,
        as_of_value=context.as_of.value,
        root_box=context.filters.root_box,
        topology_id=context.filters.topology_id,
    )


def capabilities_to_engine(value: BridgeCapabilitiesV1 | None) -> AdapterCapabilities:
    if value is None:
        return AdapterCapabilities(strict_parameter_support=False)
    return AdapterCapabilities(
        topology=value.topology,
        dependencies=value.dependencies,
        runtime=value.runtime,
        job_detail=value.job_detail,
        root_listing=value.root_listing,
        autosys_projection=value.autosys_projection,
        strict_parameter_support=value.strict_parameter_support,
        parameter_support={key: FieldSupport(item) for key, item in value.parameter_support.items()},
    )


def job_to_engine(value: BridgeJobV1) -> SnapshotJob:
    process_scheduler = (
        ProcessSchedulerJobReference.from_wire(value.process_scheduler)
        if value.process_scheduler is not None
        else None
    )
    return SnapshotJob(
        job_uid=value.job_uid,
        scheduler_job_name=value.scheduler_job_name,
        scheduler_native_id=value.scheduler_native_id,
        parent_uid=value.parent_uid,
        path_labels=list(value.path_labels),
        status=JobStatus(value.status),
        status_raw=value.status_raw,
        scheduled_start=value.scheduled_start,
        actual_start=value.actual_start,
        actual_end=value.actual_end,
        duration_sec=value.duration_sec,
        exit_code=value.exit_code,
        autosys=AutoSysJobReference(
            jil=AutoSysJobDefinition.from_mapping(value.autosys_jil),
            run=AutoSysRunInstance.from_mapping(value.autosys_run),
        ),
        process_scheduler=process_scheduler,
        attributes=dict(value.attributes),
        comparison_support={key: FieldSupport(item) for key, item in value.comparison_support.items()},
        comparison_evidence={
            key: FieldEvidence(source=item.source, locator=item.locator, note=item.note)
            for key, item in value.comparison_evidence.items()
        },
    )


def dependency_to_engine(value: BridgeDependencyV1) -> DependencyEdge:
    return DependencyEdge(
        from_uid=value.from_uid,
        to_uid=value.to_uid,
        kind=DependencyKind(value.kind),
        condition=value.condition,
    )
