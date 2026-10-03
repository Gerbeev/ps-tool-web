"""CSV export per spec §9."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable

from app.models import ComparisonContext, ComparisonResult, JobPair, NormalizedJob, TopologySnapshot

TOPOLOGY_COLUMNS = [
    "logical_id",
    "scheduler_job_name",
    "path",
    "parent_name",
    "job_type",
    "status",
    "status_raw",
    "actual_start_utc",
    "actual_end_utc",
    "duration_sec",
    "exit_code",
    "machine",
    "log_path",
    "scheduler",
    "environment_id",
    "as_of",
    "match_confidence",
]

COMPARISON_COLUMNS = [
    "logical_id",
    "left_name",
    "right_name",
    "left_status",
    "right_status",
    "diff_kind",
    "timing_delta_sec",
    "match_confidence",
]


def _as_of_str(context: ComparisonContext) -> str:
    if context.as_of.value:
        return context.as_of.value
    return context.as_of.kind.value


def _parent_name(job: NormalizedJob, by_uid: dict[str, NormalizedJob]) -> str:
    if not job.parent_uid:
        return ""
    parent = by_uid.get(job.parent_uid)
    return parent.scheduler_job_name if parent else ""


def _format_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


def export_topology_csv(snapshot: TopologySnapshot) -> str:
    by_uid = {j.job_uid: j for j in snapshot.flat_jobs}
    jobs = sorted(snapshot.flat_jobs, key=lambda j: "/".join(j.path_labels))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TOPOLOGY_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    ctx = snapshot.context
    for job in jobs:
        writer.writerow(
            {
                "logical_id": job.logical_id or "",
                "scheduler_job_name": job.scheduler_job_name,
                "path": "/".join(job.path_labels),
                "parent_name": _parent_name(job, by_uid),
                "job_type": job.job_type,
                "status": job.status.value,
                "status_raw": job.status_raw,
                "actual_start_utc": _format_dt(job.actual_start),
                "actual_end_utc": _format_dt(job.actual_end),
                "duration_sec": job.duration_sec if job.duration_sec is not None else "",
                "exit_code": job.exit_code if job.exit_code is not None else "",
                "machine": job.machine or "",
                "log_path": job.log_path or "",
                "scheduler": ctx.scheduler.value,
                "environment_id": ctx.environment_id,
                "as_of": _as_of_str(ctx),
                "match_confidence": "",
            }
        )
    return buf.getvalue()


def _timing_delta_pair(pair: JobPair) -> str:
    if not pair.left or not pair.right:
        return ""
    if pair.left.actual_end and pair.right.actual_end:
        return str(abs((pair.left.actual_end - pair.right.actual_end).total_seconds()))
    return ""


def _diff_kind(pair: JobPair) -> str:
    if pair.left and pair.right:
        if pair.left.status != pair.right.status:
            return "status_mismatch"
        return "ok"
    if pair.left:
        return "left_only"
    return "right_only"


def export_comparison_csv(result: ComparisonResult) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)
    writer.writeheader()

    def rows() -> Iterable[JobPair]:
        for p in result.pairs:
            yield p
        for job in result.left_only:
            yield JobPair(left=job, logical_id=job.logical_id)
        for job in result.right_only:
            yield JobPair(right=job, logical_id=job.logical_id)

    for pair in rows():
        writer.writerow(
            {
                "logical_id": pair.logical_id or "",
                "left_name": pair.left.scheduler_job_name if pair.left else "",
                "right_name": pair.right.scheduler_job_name if pair.right else "",
                "left_status": pair.left.status.value if pair.left else "",
                "right_status": pair.right.status.value if pair.right else "",
                "diff_kind": _diff_kind(pair),
                "timing_delta_sec": _timing_delta_pair(pair),
                "match_confidence": pair.confidence.value,
            }
        )
    return buf.getvalue()
