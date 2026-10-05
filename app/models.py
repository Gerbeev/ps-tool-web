"""Domain models for scheduler comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.autosys_reference import AutoSysJobReference


class SchedulerType(str, Enum):
    AUTOSYS = "autosys"
    PROCESS_SCHEDULER = "process_scheduler"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    KILLED = "killed"
    UNKNOWN = "unknown"
    NOT_RUN = "not_run"
    DISABLED = "disabled"


class DependencyKind(str, Enum):
    FINISH_TO_START = "finish_to_start"
    START_TO_START = "start_to_start"
    FILE_TRIGGER = "file_trigger"
    CUSTOM = "custom"


class MatchConfidence(str, Enum):
    MAPPED = "mapped"
    NORMALIZED = "normalized"
    NAME_ONLY = "name_only"
    UNMATCHED = "unmatched"


class AsOfKind(str, Enum):
    BUSINESS_DATE = "business_date"
    RUN_ID = "run_id"
    LATEST = "latest"


class AsOf(BaseModel):
    kind: AsOfKind = AsOfKind.BUSINESS_DATE
    value: str = ""


class ContextFilters(BaseModel):
    root_box: str | None = None
    topology_id: str | None = None


class ComparisonContext(BaseModel):
    environment_id: str
    host: str = ""
    scheduler: SchedulerType
    as_of: AsOf = Field(default_factory=lambda: AsOf(kind=AsOfKind.BUSINESS_DATE, value=""))
    filters: ContextFilters = Field(default_factory=ContextFilters)


class SnapshotJob(BaseModel):
    """Topology job: identity + run instance UI fields + AutoSys reference view."""

    job_uid: str
    logical_id: str | None = None
    scheduler_job_name: str
    scheduler_native_id: str | None = None
    parent_uid: str | None = None
    path_labels: list[str] = Field(default_factory=list)
    status: JobStatus
    status_raw: str = ""
    scheduled_start: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    duration_sec: float | None = None
    exit_code: int | None = None
    autosys: AutoSysJobReference = Field(default_factory=AutoSysJobReference)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def job_type(self) -> str:
        raw = self.autosys.jil.job_type or self.attributes.get("native_job_type") or ""
        return str(raw).lower()

    @property
    def machine(self) -> str | None:
        return self.autosys.jil.machine

    @property
    def box_name(self) -> str | None:
        return self.autosys.jil.box_name

    @property
    def log_path(self) -> str | None:
        return self.autosys.jil.std_out_file or self.attributes.get("log_path")

    @property
    def log_paths(self) -> list[str]:
        paths: list[str] = []
        for key in (self.autosys.jil.std_out_file, self.autosys.jil.std_err_file):
            if key:
                paths.append(key)
        return paths

    @property
    def start_time(self) -> datetime | None:
        return self.actual_start

    @property
    def end_time(self) -> datetime | None:
        return self.actual_end


class DependencyEdge(BaseModel):
    from_uid: str
    to_uid: str
    kind: DependencyKind = DependencyKind.FINISH_TO_START
    condition: str | None = None


class JobNode(BaseModel):
    job: SnapshotJob
    children: list[JobNode] = Field(default_factory=list)


class TopologySnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    context: ComparisonContext
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    roots: list[JobNode] = Field(default_factory=list)
    flat_jobs: list[SnapshotJob] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobPair(BaseModel):
    left: SnapshotJob | None = None
    right: SnapshotJob | None = None
    match_kind: MatchConfidence = MatchConfidence.UNMATCHED
    confidence: MatchConfidence = MatchConfidence.UNMATCHED
    logical_id: str | None = None


class ParameterMismatch(BaseModel):
    logical_id: str | None = None
    parameter: str
    left_value: str = ""
    right_value: str = ""


class ComparisonSummary(BaseModel):
    total_left: int = 0
    total_right: int = 0
    matched: int = 0
    mismatched_status: int = 0
    mismatched_parameters: int = 0
    parameter_mismatch_counts: dict[str, int] = Field(default_factory=dict)
    mismatched_timing: int = 0
    left_only_count: int = 0
    right_only_count: int = 0


class ComparisonResult(BaseModel):
    left_snapshot_id: str
    right_snapshot_id: str
    pairs: list[JobPair] = Field(default_factory=list)
    left_only: list[SnapshotJob] = Field(default_factory=list)
    right_only: list[SnapshotJob] = Field(default_factory=list)
    status_mismatches: list[JobPair] = Field(default_factory=list)
    timing_deltas: list[JobPair] = Field(default_factory=list)
    definition_mismatches: list[JobPair] = Field(default_factory=list)
    parameter_mismatches: list[ParameterMismatch] = Field(default_factory=list)
    summary: ComparisonSummary = Field(default_factory=ComparisonSummary)


class SearchHit(BaseModel):
    job_uid: str
    side: str
    snapshot_id: str
    score: float
    snippet: str
    scheduler_job_name: str
    path: str
    status: str
