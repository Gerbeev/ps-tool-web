"""Domain models for scheduler comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


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
    scheduler: SchedulerType
    as_of: AsOf = Field(default_factory=lambda: AsOf(kind=AsOfKind.BUSINESS_DATE, value=""))
    filters: ContextFilters = Field(default_factory=ContextFilters)


class JobSchedule(BaseModel):
    """Normalized schedule: cron/calendar string and optional structure.

    AutoSys: ``run_calendar``, ``start_times`` / ``run_window``, ``days_of_week``.
    Process Scheduler: cron expression or calendar id on the job definition.
    """

    expression: str | None = None
    calendar: str | None = None
    timezone: str | None = None
    raw: str | None = None

    def comparable(self) -> str:
        """Single string for parity comparison across schedulers."""
        parts = [p for p in (self.expression, self.calendar, self.timezone) if p]
        if parts:
            return "|".join(parts)
        return (self.raw or "").strip()


class ComparedField(str, Enum):
    STATUS = "status"
    SCHEDULE = "schedule"
    COMMAND = "command"
    CONDITION = "condition"
    LOG_PATHS = "log_paths"
    RESOLVED_COMMAND = "resolved_command"
    START_TIME = "start_time"
    END_TIME = "end_time"


class NormalizedJob(BaseModel):
    """Unified job metadata + last-run instance fields for snapshots and diff.

    Identity: ``scheduler_job_name``, ``logical_id``, ``path_labels``.
    Definition (migration parity): ``schedule``, ``command``, ``condition``, ``log_paths``.
    Run instance: ``status``, ``actual_start`` / ``actual_end`` (start/end time),
    ``resolved_command``, ``resolved_parameters`` (substituted command line).
    """

    job_uid: str
    logical_id: str | None = None
    scheduler_job_name: str
    scheduler_native_id: str | None = None
    parent_uid: str | None = None
    job_type: str
    status: JobStatus
    status_raw: str = ""
    scheduled_start: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    duration_sec: float | None = None
    exit_code: int | None = None
    machine: str | None = None
    schedule: JobSchedule | None = None
    command: str | None = None
    condition: str | None = None
    log_paths: list[str] = Field(default_factory=list)
    resolved_command: str | None = None
    resolved_parameters: dict[str, Any] = Field(default_factory=dict)
    log_path: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    path_labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_log_paths(self) -> NormalizedJob:
        if self.log_paths and not self.log_path:
            object.__setattr__(self, "log_path", self.log_paths[0])
        elif self.log_path and not self.log_paths:
            object.__setattr__(self, "log_paths", [self.log_path])
        return self

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
    job: NormalizedJob
    children: list[JobNode] = Field(default_factory=list)


class TopologySnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    context: ComparisonContext
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    roots: list[JobNode] = Field(default_factory=list)
    flat_jobs: list[NormalizedJob] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobPair(BaseModel):
    left: NormalizedJob | None = None
    right: NormalizedJob | None = None
    match_kind: MatchConfidence = MatchConfidence.UNMATCHED
    confidence: MatchConfidence = MatchConfidence.UNMATCHED
    logical_id: str | None = None


class FieldMismatch(BaseModel):
    logical_id: str | None = None
    field: ComparedField
    left_value: str = ""
    right_value: str = ""


class ComparisonSummary(BaseModel):
    total_left: int = 0
    total_right: int = 0
    matched: int = 0
    mismatched_status: int = 0
    mismatched_schedule: int = 0
    mismatched_command: int = 0
    mismatched_condition: int = 0
    mismatched_log_paths: int = 0
    mismatched_resolved_command: int = 0
    mismatched_timing: int = 0
    left_only_count: int = 0
    right_only_count: int = 0


class ComparisonResult(BaseModel):
    left_snapshot_id: str
    right_snapshot_id: str
    pairs: list[JobPair] = Field(default_factory=list)
    left_only: list[NormalizedJob] = Field(default_factory=list)
    right_only: list[NormalizedJob] = Field(default_factory=list)
    status_mismatches: list[JobPair] = Field(default_factory=list)
    timing_deltas: list[JobPair] = Field(default_factory=list)
    definition_mismatches: list[JobPair] = Field(default_factory=list)
    field_mismatches: list[FieldMismatch] = Field(default_factory=list)
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
