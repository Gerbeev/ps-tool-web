"""Domain models for scheduler comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.autosys_reference import AutoSysJobReference
from app.process_scheduler_reference import ProcessSchedulerJobReference
from app.time_utils import execution_time_seconds, format_duration_hms


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


class FieldSupport(str, Enum):
    """How confidently an adapter can provide a comparison field."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ComparisonOutcome(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARABLE = "not_comparable"


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


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
    model_config = ConfigDict(populate_by_name=True)

    environment_id: str
    endpoint_url: str = Field(
        default="",
        validation_alias=AliasChoices("endpoint_url", "host"),
    )
    scheduler: SchedulerType
    as_of: AsOf = Field(default_factory=lambda: AsOf(kind=AsOfKind.BUSINESS_DATE, value=""))
    filters: ContextFilters = Field(default_factory=ContextFilters)

    @property
    def host(self) -> str:
        """Backward-compatible alias; endpoint_url is the canonical field."""
        return self.endpoint_url


class FieldEvidence(BaseModel):
    """Human-readable provenance for a normalized comparison field."""

    source: str = ""
    locator: str = ""
    note: str = ""


class AdapterCapabilities(BaseModel):
    """Capabilities declared by an adapter implementation.

    ``parameter_support`` is optional. Missing entries remain backward-compatible and
    are treated as supported unless the job itself explicitly says otherwise.
    """

    topology: bool = True
    dependencies: bool = True
    runtime: bool = True
    job_detail: bool = True
    root_listing: bool = True
    autosys_projection: bool = True
    strict_parameter_support: bool = False
    parameter_support: dict[str, FieldSupport] = Field(default_factory=dict)


class SnapshotJob(BaseModel):
    """Topology job: identity + runtime fields + AutoSys-equivalent reference view."""

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
    process_scheduler: ProcessSchedulerJobReference | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    comparison_support: dict[str, FieldSupport] = Field(default_factory=dict)
    comparison_evidence: dict[str, FieldEvidence] = Field(default_factory=dict)

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

    @property
    def execution_time_sec(self) -> float | None:
        """Canonical execution time derived from actual end minus actual start."""
        return execution_time_seconds(self.actual_start, self.actual_end)

    @property
    def exec_time(self) -> str | None:
        """Human-readable execution time (HH:MM:SS)."""
        seconds = self.execution_time_sec
        return format_duration_hms(seconds) if seconds is not None else None


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
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobPair(BaseModel):
    left: SnapshotJob | None = None
    right: SnapshotJob | None = None
    match_kind: MatchConfidence = MatchConfidence.UNMATCHED
    confidence: MatchConfidence = MatchConfidence.UNMATCHED
    logical_id: str | None = None

    @property
    def execution_time_delta_sec(self) -> float | None:
        """Signed execution-time delta: right minus left; positive means right is slower."""
        if not self.left or not self.right:
            return None
        left_sec = self.left.execution_time_sec
        right_sec = self.right.execution_time_sec
        if left_sec is None or right_sec is None:
            return None
        return right_sec - left_sec

    @property
    def execution_time_delta(self) -> str | None:
        delta = self.execution_time_delta_sec
        return format_duration_hms(delta, signed=True) if delta is not None else None


class ParameterMismatch(BaseModel):
    logical_id: str | None = None
    parameter: str
    left_value: str = ""
    right_value: str = ""
    left_evidence: FieldEvidence | None = None
    right_evidence: FieldEvidence | None = None


class NotComparableParameter(BaseModel):
    logical_id: str | None = None
    parameter: str
    left_value: str = ""
    right_value: str = ""
    left_support: FieldSupport = FieldSupport.UNKNOWN
    right_support: FieldSupport = FieldSupport.UNKNOWN
    reason: str = ""
    left_evidence: FieldEvidence | None = None
    right_evidence: FieldEvidence | None = None


class IdentityConflict(BaseModel):
    side: str
    logical_id: str
    job_uids: list[str] = Field(default_factory=list)
    job_names: list[str] = Field(default_factory=list)


class SnapshotValidationIssue(BaseModel):
    severity: ValidationSeverity
    code: str
    message: str
    job_uid: str | None = None


class SnapshotValidationReport(BaseModel):
    issues: list[SnapshotValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == ValidationSeverity.WARNING for issue in self.issues)


class ComparisonSummary(BaseModel):
    total_left: int = 0
    total_right: int = 0
    matched: int = 0
    mismatched_status: int = 0
    mismatched_parameters: int = 0
    parameter_mismatch_counts: dict[str, int] = Field(default_factory=dict)
    mismatched_timing: int = 0
    mismatched_execution_time: int = 0
    left_only_count: int = 0
    right_only_count: int = 0
    not_comparable_parameters: int = 0
    not_comparable_counts: dict[str, int] = Field(default_factory=dict)
    identity_conflicts: int = 0


class ComparisonResult(BaseModel):
    left_snapshot_id: str
    right_snapshot_id: str
    pairs: list[JobPair] = Field(default_factory=list)
    left_only: list[SnapshotJob] = Field(default_factory=list)
    right_only: list[SnapshotJob] = Field(default_factory=list)
    status_mismatches: list[JobPair] = Field(default_factory=list)
    timing_deltas: list[JobPair] = Field(default_factory=list)
    execution_time_deltas: list[JobPair] = Field(default_factory=list)
    definition_mismatches: list[JobPair] = Field(default_factory=list)
    parameter_mismatches: list[ParameterMismatch] = Field(default_factory=list)
    not_comparable: list[NotComparableParameter] = Field(default_factory=list)
    identity_conflicts: list[IdentityConflict] = Field(default_factory=list)
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
