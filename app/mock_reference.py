"""Deterministic environment projections of the canonical 2500-job mock fixture."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.autosys_reference import AutoSysJobDefinition, AutoSysJobReference, AutoSysRunInstance
from app.config import get_environment, get_settings
from app.process_scheduler_reference import ProcessSchedulerJobReference
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

_REFERENCE_DATASET = "reference_2500"

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


def reference_metadata() -> dict[str, Any]:
    metadata, _ = _load_reference(str(get_settings().mock_reference_path))
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
    return f"{context.scheduler.value}:{context.environment_id}:{job_ref}"


def _runtime_times(
    record: dict[str, Any], base: datetime
) -> tuple[datetime | None, datetime | None, float | None]:
    status = JobStatus(record["status"])
    if status in {JobStatus.PENDING, JobStatus.DISABLED, JobStatus.NOT_RUN}:
        return None, None, None

    start = base + timedelta(seconds=int(record["start_offset_sec"]))
    duration = float(record["duration_sec"])
    if status == JobStatus.RUNNING:
        return start, None, None
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


def build_reference_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Materialize one scheduler/environment view from the environment-neutral fixture."""
    metadata, records_tuple = _load_reference(str(get_settings().mock_reference_path))
    records = list(records_tuple)
    env_token = _environment_token(context)
    base = _business_datetime(context)
    topology_id = str(metadata.get("topology_id") or "DataPlatform_REFERENCE")

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
        status = JobStatus(record["status"])
        start, end, duration = _runtime_times(record, base)
        parent_ref = record.get("parent_ref")
        job_name = name_by_ref[ref]
        parent_name = name_by_ref[parent_ref] if parent_ref else None
        command = record.get("command")
        watch_file = record.get("watch_file")
        status_raw = _status_raw(context.scheduler, status)
        schedule = record.get("schedule")
        start_at_time = record.get("start_at_time")
        scheduled_start = _scheduled_start(record, base)

        definition = AutoSysJobDefinition(
            job_name=job_name,
            job_type=record["job_type"],
            machine=record.get("machine"),
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
            exit_code=record.get("exit_code"),
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
            exit_code=record.get("exit_code"),
            autosys=AutoSysJobReference(jil=definition, run=run),
            process_scheduler=ps_reference,
            attributes={
                "native_job_type": record["job_type"],
                "semantic_type": record["semantic_type"],
                "business_code": record["business_code"],
                "environment_token": env_token,
                "reference_job_ref": ref,
            },
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
        for source_ref in record.get("depends_on", []):
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

    return TopologySnapshot(
        context=context,
        roots=roots,
        flat_jobs=flat_jobs,
        edges=edges,
        metadata={
            "adapter": f"{context.scheduler.value}_mock_reference",
            "connector_version": "reference-fixture-v2",
            "dataset_id": metadata["dataset_id"],
            "synthetic_count": len(flat_jobs),
            "business_group_count": metadata["business_group_count"],
            "environment_token": env_token,
            "topology_id": topology_id,
            "business_date": context.as_of.value,
            "reference_path": str(get_settings().mock_reference_path),
        },
    )


def reference_topology_names() -> list[str]:
    return [str(reference_metadata().get("topology_id") or "DataPlatform_REFERENCE")]
