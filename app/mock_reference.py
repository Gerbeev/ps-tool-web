"""Deterministic environment projections of the canonical 2500-job mock fixture."""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.autosys_reference import AutoSysJobDefinition, AutoSysJobReference, AutoSysRunInstance
from app.config import get_environment, get_settings
from app.models import (
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    JobNode,
    JobStatus,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)
from app.process_scheduler_reference import ProcessSchedulerJobReference

_REFERENCE_DATASET = "reference_2500"
_DISABLED_SCENARIOS = {"", "none", "off", "disabled", "false", "0"}

_AUTOSYS_STATUS = {
    JobStatus.SUCCESS: "SU",
    JobStatus.FAILURE: "FA",
    JobStatus.RUNNING: "RU",
    JobStatus.PENDING: "IN",
    JobStatus.DISABLED: "OI",
    JobStatus.KILLED: "TE",
    JobStatus.UNKNOWN: "UN",
    JobStatus.NOT_RUN: "IN",
}

_PS_STATUS = {
    JobStatus.SUCCESS: "Success",
    JobStatus.FAILURE: "Failed",
    JobStatus.RUNNING: "Running",
    JobStatus.PENDING: "Waiting",
    JobStatus.DISABLED: "OnIce",
    JobStatus.KILLED: "Cancelled",
    JobStatus.UNKNOWN: "Unknown",
    JobStatus.NOT_RUN: "Inactive",
}


def reference_mock_enabled() -> bool:
    return get_settings().mock_dataset == _REFERENCE_DATASET


@lru_cache(maxsize=4)
def _load_reference(path_text: str) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    path = Path(path_text)
    if not path.is_file():
        raise FileNotFoundError(f"Mock reference fixture not found: {path}")

    metadata: dict[str, Any] | None = None
    jobs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            record_type = row.get("record_type")
            if record_type == "metadata":
                if metadata is not None:
                    raise ValueError(f"Duplicate metadata record in {path}")
                metadata = row
            elif record_type == "job":
                jobs.append(row)
            else:
                raise ValueError(f"Unknown record_type {record_type!r} at {path}:{line_number}")

    if metadata is None:
        raise ValueError(f"Missing metadata record in {path}")
    expected = int(metadata.get("job_count", -1))
    if expected != len(jobs):
        raise ValueError(f"Fixture job_count={expected} but contains {len(jobs)} jobs")
    if expected != 2500:
        raise ValueError(f"Reference fixture must contain exactly 2500 jobs, got {expected}")
    return metadata, tuple(jobs)


@lru_cache(maxsize=4)
def _load_scenario(path_text: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = Path(path_text)
    if not path.is_file():
        raise FileNotFoundError(f"Mock migration scenario not found: {path}")

    metadata: dict[str, Any] | None = None
    issues_by_ref: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            record_type = row.get("record_type")
            if record_type == "metadata":
                if metadata is not None:
                    raise ValueError(f"Duplicate scenario metadata record in {path}")
                metadata = row
            elif record_type == "issue":
                ref = str(row.get("job_ref") or "")
                if not ref:
                    raise ValueError(f"Scenario issue without job_ref at {path}:{line_number}")
                if ref in issues_by_ref:
                    raise ValueError(f"Duplicate scenario issue for {ref!r} in {path}")
                issues_by_ref[ref] = row
            else:
                raise ValueError(f"Unknown scenario record_type {record_type!r} at {path}:{line_number}")

    if metadata is None:
        raise ValueError(f"Missing scenario metadata record in {path}")
    expected = int(metadata.get("issue_count", -1))
    if expected != len(issues_by_ref):
        raise ValueError(
            f"Scenario issue_count={expected} but contains {len(issues_by_ref)} issue records"
        )
    return metadata, issues_by_ref


def reference_metadata() -> dict[str, Any]:
    metadata, _ = _load_reference(str(get_settings().mock_reference_path))
    return dict(metadata)


def reference_scenario_metadata() -> dict[str, Any]:
    settings = get_settings()
    if settings.mock_scenario in _DISABLED_SCENARIOS:
        return {}
    metadata, _ = _load_scenario(str(settings.mock_scenario_path))
    return dict(metadata)


def _environment_token(context: ComparisonContext) -> str:
    entry = get_environment(context.environment_id)
    if entry and entry.environment:
        return entry.environment.strip().upper()
    raw = context.environment_id.rsplit("-", 1)[-1].strip().upper()
    if 2 <= len(raw) <= 4 and raw.isalnum():
        return raw
    return "MOCK"


def _business_datetime(context: ComparisonContext) -> datetime:
    raw = (context.as_of.value or "2026-10-02").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
    except ValueError:
        return datetime(2026, 10, 2)


def _name(record: dict[str, Any], environment_token: str) -> str:
    return (
        f"{record['common_prefix']}{record['business_code']}_"
        f"{environment_token}_{record['job_specific_name']}"
    )


def _uid(context: ComparisonContext, job_ref: str) -> str:
    """Return a stable URL-safe UID while preserving the hierarchical native ref."""
    token = base64.urlsafe_b64encode(job_ref.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{context.scheduler.value}:{context.environment_id}:{token}"


def _base_runtime_times(
    record: dict[str, Any], base: datetime
) -> tuple[datetime, datetime, float]:
    start = base + timedelta(seconds=int(record["start_offset_sec"]))
    duration = float(record["duration_sec"])
    return start, start + timedelta(seconds=duration), duration


def _status_raw(scheduler: SchedulerType, status: JobStatus) -> str:
    if scheduler == SchedulerType.AUTOSYS:
        return _AUTOSYS_STATUS[status]
    return _PS_STATUS[status]


def _scheduled_start(record: dict[str, Any], base: datetime) -> datetime | None:
    raw = str(record.get("start_at_time") or "").strip()
    if not raw:
        return None
    try:
        hour_text, minute_text = raw.split(":", 1)
        return base.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    except (TypeError, ValueError):
        return None


def _ps_job_type(record: dict[str, Any]) -> str:
    # Only Box casing is confirmed by the captured Process Scheduler detail.
    # Other surrogate types remain generic until the real endpoint DTO is inspected.
    return "Box" if record.get("job_type") == "BOX" else str(record.get("job_type") or "")


def _scenario_for_context(
    context: ComparisonContext,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    settings = get_settings()
    if settings.mock_scenario in _DISABLED_SCENARIOS:
        return {}, {}

    metadata, issues_by_ref = _load_scenario(str(settings.mock_scenario_path))
    target_scheduler = str(metadata.get("target_scheduler") or "")
    target_environment = str(metadata.get("target_environment") or "").upper()
    if context.scheduler.value != target_scheduler:
        return metadata, {}
    if _environment_token(context) != target_environment:
        return metadata, {}
    return metadata, issues_by_ref


def _apply_runtime_scenario(
    *,
    record: dict[str, Any],
    base: datetime,
    scheduler: SchedulerType,
    scenario_metadata: dict[str, Any],
    issue: dict[str, Any] | None,
) -> tuple[JobStatus, str, datetime | None, datetime | None, float | None, int | None]:
    status = JobStatus(str((issue or {}).get("status") or record["status"]))
    start, end, duration = _base_runtime_times(record, base)

    normal_shift = int(scenario_metadata.get("normal_target_start_shift_sec", 0) or 0)
    if normal_shift:
        start += timedelta(seconds=normal_shift)
        end += timedelta(seconds=normal_shift)

    if issue:
        start += timedelta(seconds=int(issue.get("start_shift_sec", 0) or 0))
        end += timedelta(seconds=int(issue.get("end_shift_sec", 0) or 0))
        end += timedelta(seconds=int(issue.get("duration_add_sec", 0) or 0))
        if issue.get("clear_start"):
            start = None
        if issue.get("clear_end"):
            end = None

    if status in {JobStatus.PENDING, JobStatus.DISABLED, JobStatus.NOT_RUN}:
        start = None
        end = None
        duration = None
    elif status == JobStatus.RUNNING:
        end = None
        duration = None
    elif start is not None and end is not None:
        duration = (end - start).total_seconds()

    if issue and "exit_code" in issue:
        exit_code = issue.get("exit_code")
    else:
        exit_code = record.get("exit_code")

    raw = str((issue or {}).get("raw_status") or _status_raw(scheduler, status))
    return status, raw, start, end, duration, exit_code


def build_reference_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Materialize one scheduler/environment view from the environment-neutral fixture."""
    metadata, records_tuple = _load_reference(str(get_settings().mock_reference_path))
    all_records = list(records_tuple)
    env_token = _environment_token(context)
    base = _business_datetime(context)
    topology_id = str(metadata.get("topology_id") or "DataPlatform_REFERENCE")
    scenario_metadata, issues_by_ref = _scenario_for_context(context)

    missing_refs = {
        ref for ref, issue in issues_by_ref.items() if issue.get("issue_type") == "missing"
    }
    records = [record for record in all_records if record["job_ref"] not in missing_refs]

    by_ref = {record["job_ref"]: record for record in records}
    name_by_ref = {ref: _name(record, env_token) for ref, record in by_ref.items()}

    path_cache: dict[str, list[str]] = {}

    def path_for(ref: str) -> list[str]:
        cached = path_cache.get(ref)
        if cached is not None:
            return cached
        record = by_ref[ref]
        parent_ref = record.get("parent_ref")
        labels = ([*path_for(parent_ref)] if parent_ref else []) + [name_by_ref[ref]]
        path_cache[ref] = labels
        return labels

    jobs_by_ref: dict[str, SnapshotJob] = {}
    flat_jobs: list[SnapshotJob] = []
    for record in records:
        ref = record["job_ref"]
        issue = issues_by_ref.get(ref)
        status, status_raw, start, end, duration, exit_code = _apply_runtime_scenario(
            record=record,
            base=base,
            scheduler=context.scheduler,
            scenario_metadata=scenario_metadata if issues_by_ref else {},
            issue=issue,
        )
        parent_ref = record.get("parent_ref")
        job_name = name_by_ref[ref]
        parent_name = name_by_ref[parent_ref] if parent_ref else None

        command = record.get("command")
        if command and issue and issue.get("command_suffix"):
            command = f"{command}{issue['command_suffix']}"
        watch_file = record.get("watch_file")
        machine = (issue or {}).get("machine", record.get("machine"))
        schedule = (issue or {}).get("schedule", record.get("schedule"))
        start_at_time = record.get("start_at_time")
        scheduled_start = _scheduled_start(record, base)

        definition = AutoSysJobDefinition(
            job_name=job_name,
            job_type=record["job_type"],
            machine=machine,
            box_name=parent_name,
            command=command,
            watch_file=watch_file,
            date_conditions=1 if schedule and start_at_time else 0,
            start_times=start_at_time,
            days_of_week=schedule,
            timezone=record.get("timezone"),
            std_out_file=(
                f"C:/DataPlatform/log/{record['business_code']}/{record['job_specific_name']}.log"
                if record["job_type"] != "BOX"
                else None
            ),
            std_err_file=(
                f"C:/DataPlatform/log/{record['business_code']}/{record['job_specific_name']}.log"
                if record["job_type"] != "BOX"
                else None
            ),
            owner=record.get("owner"),
            permission=record.get("permission"),
            group=record.get("group"),
            application=record.get("application"),
            description=record.get("description"),
            n_retrys=1 if record["job_type"] != "BOX" else 0,
            alarm_if_fail=1 if record["job_type"] != "BOX" else 0,
            watch_interval=60 if record["job_type"] == "FW" else None,
            watch_file_min_size=1 if record["job_type"] == "FW" else None,
        )
        run = AutoSysRunInstance(
            status=status_raw,
            actual_start=start,
            actual_end=end,
            resolved_command=command,
            resolved_watch_file=watch_file,
            exit_code=exit_code,
        )
        ps_reference = None
        if context.scheduler == SchedulerType.PROCESS_SCHEDULER:
            ps_reference = ProcessSchedulerJobReference(
                Box=parent_name or topology_id,
                ConditionExpression=None,
                Context=topology_id,
                Description=record.get("description"),
                JobType=_ps_job_type(record),
                LastFinishTime=end,
                LastStartTime=start,
                Name=job_name,
                Owner=record.get("owner"),
                Schedule=schedule,
                StartAtTime=start_at_time,
                StartAtTimeForce=bool(record.get("start_at_time_force", False)),
                Status=status_raw,
            )

        attributes: dict[str, Any] = {
            "native_job_type": record["job_type"],
            "semantic_type": record["semantic_type"],
            "business_code": record["business_code"],
            "environment_token": env_token,
            "reference_job_ref": ref,
        }
        if issue:
            attributes["mock_migration_issue"] = issue["issue_type"]

        job = SnapshotJob(
            job_uid=_uid(context, ref),
            scheduler_native_id=ref,
            scheduler_job_name=job_name,
            parent_uid=_uid(context, parent_ref) if parent_ref else None,
            path_labels=path_for(ref),
            status=status,
            status_raw=status_raw,
            scheduled_start=scheduled_start,
            actual_start=start,
            actual_end=end,
            duration_sec=duration,
            exit_code=exit_code,
            autosys=AutoSysJobReference(jil=definition, run=run),
            process_scheduler=ps_reference,
            attributes=attributes,
        )
        jobs_by_ref[ref] = job
        flat_jobs.append(job)

    children: dict[str, list[JobNode]] = defaultdict(list)
    roots: list[JobNode] = []
    nodes = {ref: JobNode(job=job) for ref, job in jobs_by_ref.items()}
    for record in records:
        ref = record["job_ref"]
        parent_ref = record.get("parent_ref")
        if parent_ref:
            children[parent_ref].append(nodes[ref])
        else:
            roots.append(nodes[ref])
    for ref, node in nodes.items():
        node.children = children.get(ref, [])

    edges: list[DependencyEdge] = []
    for record in records:
        target_ref = record["job_ref"]
        target_issue = issues_by_ref.get(target_ref)
        if target_issue and target_issue.get("remove_incoming_dependency"):
            continue
        for source_ref in record.get("depends_on", []):
            if source_ref in missing_refs:
                continue
            if source_ref not in jobs_by_ref:
                raise ValueError(f"Unknown dependency source {source_ref!r} for {target_ref!r}")
            edges.append(
                DependencyEdge(
                    from_uid=_uid(context, source_ref),
                    to_uid=_uid(context, target_ref),
                    kind=DependencyKind.FINISH_TO_START,
                    condition="success",
                )
            )

    role = "neutral"
    if scenario_metadata:
        if (
            context.scheduler.value == scenario_metadata.get("baseline_scheduler")
            and env_token == str(scenario_metadata.get("baseline_environment") or "").upper()
        ):
            role = "healthy_baseline"
        elif issues_by_ref:
            role = "migration_target"

    return TopologySnapshot(
        context=context,
        roots=roots,
        flat_jobs=flat_jobs,
        edges=edges,
        metadata={
            "adapter": f"{context.scheduler.value}_mock_reference",
            "connector_version": "reference-fixture-v4",
            "dataset_id": metadata["dataset_id"],
            "synthetic_count": len(flat_jobs),
            "business_group_count": metadata["business_group_count"],
            "environment_token": env_token,
            "topology_id": topology_id,
            "business_date": context.as_of.value,
            "reference_path": str(get_settings().mock_reference_path),
            "mock_scenario": scenario_metadata.get("scenario_id") if scenario_metadata else None,
            "mock_scenario_role": role,
            "mock_issue_count": len(issues_by_ref),
            "mock_issue_counts": scenario_metadata.get("issue_counts", {}) if issues_by_ref else {},
            "missing_job_count": len(missing_refs),
        },
    )


def reference_topology_names() -> list[str]:
    return [str(reference_metadata().get("topology_id") or "DataPlatform_REFERENCE")]
