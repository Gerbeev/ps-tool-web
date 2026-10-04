"""CSV export per spec §9."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable

from app.models import ComparisonContext, ComparisonResult, JobPair, SnapshotJob, TopologySnapshot

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
    "jil_job_name",
    "command",
    "condition",
    "start_times",
    "std_out_file",
    "std_err_file",
    "resolved_command",
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
    "parameter_mismatches",
    "timing_delta_sec",
    "match_confidence",
]


def _as_of_str(context: ComparisonContext) -> str:
    if context.as_of.value:
        return context.as_of.value
    return context.as_of.kind.value


def _parent_name(job: SnapshotJob, by_uid: dict[str, SnapshotJob]) -> str:
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
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TOPOLOGY_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in iter_topology_rows(snapshot):
        writer.writerow(row)
    return buf.getvalue()


def iter_topology_rows(snapshot: TopologySnapshot):
    by_uid = {j.job_uid: j for j in snapshot.flat_jobs}
    jobs = sorted(snapshot.flat_jobs, key=lambda j: "/".join(j.path_labels))
    ctx = snapshot.context
    for job in jobs:
        jil = job.autosys.jil
        run = job.autosys.run
        yield {
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
            "jil_job_name": jil.job_name or "",
            "command": jil.command or jil.watch_file or "",
            "condition": jil.condition or "",
            "start_times": jil.start_times or "",
            "std_out_file": jil.std_out_file or "",
            "std_err_file": jil.std_err_file or "",
            "resolved_command": run.resolved_command or "",
            "scheduler": ctx.scheduler.value,
            "environment_id": ctx.environment_id,
            "as_of": _as_of_str(ctx),
            "match_confidence": "",
        }


def iter_topology_csv_lines(snapshot: TopologySnapshot):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TOPOLOGY_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    yield buf.getvalue()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=TOPOLOGY_COLUMNS, extrasaction="ignore")
    for row in iter_topology_rows(snapshot):
        writer.writerow(row)
        yield buf.getvalue()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=TOPOLOGY_COLUMNS, extrasaction="ignore")


def _timing_delta_pair(pair: JobPair) -> str:
    if not pair.left or not pair.right:
        return ""
    if pair.left.actual_end and pair.right.actual_end:
        return str(abs((pair.left.actual_end - pair.right.actual_end).total_seconds()))
    return ""


def _diff_kind(pair: JobPair, result: ComparisonResult | None = None) -> str:
    if pair.left and pair.right:
        if pair.left.status != pair.right.status:
            return "status_mismatch"
        if result and any(
            m.logical_id == pair.logical_id
            for m in result.parameter_mismatches
            if m.parameter not in ("actual_start", "actual_end")
        ):
            return "definition_mismatch"
        if result and pair in result.timing_deltas:
            return "timing_mismatch"
        return "ok"
    if pair.left:
        return "left_only"
    return "right_only"


def _parameter_mismatch_summary(pair: JobPair, result: ComparisonResult | None) -> str:
    if not result or not pair.logical_id:
        return ""
    names = sorted(
        {
            m.parameter
            for m in result.parameter_mismatches
            if m.logical_id == pair.logical_id
        }
    )
    return ";".join(names)


def export_comparison_csv(result: ComparisonResult) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)
    writer.writeheader()
    for row in iter_comparison_rows(result):
        writer.writerow(row)
    return buf.getvalue()


def iter_comparison_rows(result: ComparisonResult):
    for pair in _comparison_row_pairs(result):
        yield {
            "logical_id": pair.logical_id or "",
            "left_name": pair.left.scheduler_job_name if pair.left else "",
            "right_name": pair.right.scheduler_job_name if pair.right else "",
            "left_status": pair.left.status.value if pair.left else "",
            "right_status": pair.right.status.value if pair.right else "",
            "diff_kind": _diff_kind(pair, result),
            "parameter_mismatches": _parameter_mismatch_summary(pair, result),
            "timing_delta_sec": _timing_delta_pair(pair),
            "match_confidence": pair.confidence.value,
        }


def iter_comparison_csv_lines(result: ComparisonResult):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)
    writer.writeheader()
    yield buf.getvalue()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)
    for row in iter_comparison_rows(result):
        writer.writerow(row)
        yield buf.getvalue()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)


def _comparison_row_pairs(result: ComparisonResult) -> Iterable[JobPair]:
    for p in result.pairs:
        yield p
    for job in result.left_only:
        yield JobPair(left=job, logical_id=job.logical_id)
    for job in result.right_only:
        yield JobPair(right=job, logical_id=job.logical_id)
