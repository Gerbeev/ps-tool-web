"""CSV export per spec §9."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable, Iterator

from app.models import ComparisonContext, ComparisonResult, JobPair, SnapshotJob, TopologySnapshot
from app.services.topology_index import ensure_topology_indexes

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
    "exec_time",
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
    "not_comparable_parameters",
    "timing_delta_sec",
    "left_exec_time",
    "right_exec_time",
    "exec_time_delta",
    "exec_time_delta_sec",
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
    ensure_topology_indexes(snapshot)
    by_uid: dict[str, SnapshotJob] = snapshot.metadata.get("jobs_by_uid") or {}
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
            "exec_time": job.exec_time or "",
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
    yield from _iter_csv_lines(
        iter_topology_rows(snapshot),
        TOPOLOGY_COLUMNS,
        extrasaction="ignore",
    )


def _timing_delta_pair(pair: JobPair) -> str:
    if not pair.left or not pair.right:
        return ""
    if pair.left.actual_end and pair.right.actual_end:
        return str(abs((pair.left.actual_end - pair.right.actual_end).total_seconds()))
    return ""


def _diff_kind(
    pair: JobPair,
    *,
    definition_mismatch_ids: set[str],
    timing_mismatch_ids: set[str],
    execution_time_mismatch_ids: set[str],
) -> str:
    if pair.left and pair.right:
        if pair.left.status != pair.right.status:
            return "status_mismatch"
        if pair.logical_id and pair.logical_id in definition_mismatch_ids:
            return "definition_mismatch"
        if pair.logical_id and pair.logical_id in execution_time_mismatch_ids:
            return "execution_time_mismatch"
        if pair.logical_id and pair.logical_id in timing_mismatch_ids:
            return "timing_mismatch"
        return "ok"
    if pair.left:
        return "left_only"
    return "right_only"


def _parameter_mismatch_summary(
    pair: JobPair,
    parameter_names_by_id: dict[str, set[str]],
) -> str:
    if not pair.logical_id:
        return ""
    names = sorted(parameter_names_by_id.get(pair.logical_id, set()))
    return ";".join(names)


def export_comparison_csv(result: ComparisonResult) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMPARISON_COLUMNS)
    writer.writeheader()
    for row in iter_comparison_rows(result):
        writer.writerow(row)
    return buf.getvalue()


def iter_comparison_rows(result: ComparisonResult):
    parameter_names_by_id: dict[str, set[str]] = {}
    not_comparable_names_by_id: dict[str, set[str]] = {}
    definition_mismatch_ids: set[str] = set()
    for mismatch in result.parameter_mismatches:
        if not mismatch.logical_id:
            continue
        parameter_names_by_id.setdefault(mismatch.logical_id, set()).add(mismatch.parameter)
        if mismatch.parameter not in ("actual_start", "actual_end"):
            definition_mismatch_ids.add(mismatch.logical_id)
    for skipped in result.not_comparable:
        if skipped.logical_id:
            not_comparable_names_by_id.setdefault(skipped.logical_id, set()).add(skipped.parameter)

    timing_mismatch_ids = {
        pair.logical_id for pair in result.timing_deltas if pair.logical_id
    }
    execution_time_mismatch_ids = {
        pair.logical_id for pair in result.execution_time_deltas if pair.logical_id
    }

    for pair in _comparison_row_pairs(result):
        logical_id = pair.logical_id or ""
        yield {
            "logical_id": logical_id,
            "left_name": pair.left.scheduler_job_name if pair.left else "",
            "right_name": pair.right.scheduler_job_name if pair.right else "",
            "left_status": pair.left.status.value if pair.left else "",
            "right_status": pair.right.status.value if pair.right else "",
            "diff_kind": _diff_kind(
                pair,
                definition_mismatch_ids=definition_mismatch_ids,
                timing_mismatch_ids=timing_mismatch_ids,
                execution_time_mismatch_ids=execution_time_mismatch_ids,
            ),
            "parameter_mismatches": _parameter_mismatch_summary(
                pair, parameter_names_by_id
            ),
            "not_comparable_parameters": ";".join(
                sorted(not_comparable_names_by_id.get(logical_id, set()))
            ),
            "timing_delta_sec": _timing_delta_pair(pair),
            "left_exec_time": pair.left.exec_time if pair.left and pair.left.exec_time else "",
            "right_exec_time": pair.right.exec_time if pair.right and pair.right.exec_time else "",
            "exec_time_delta": pair.execution_time_delta or "",
            "exec_time_delta_sec": (
                pair.execution_time_delta_sec
                if pair.execution_time_delta_sec is not None
                else ""
            ),
            "match_confidence": pair.confidence.value,
        }

    for conflict in result.identity_conflicts:
        yield {
            "logical_id": conflict.logical_id,
            "left_name": ";".join(conflict.job_names) if conflict.side == "left" else "",
            "right_name": ";".join(conflict.job_names) if conflict.side == "right" else "",
            "left_status": "",
            "right_status": "",
            "diff_kind": "identity_conflict",
            "parameter_mismatches": "",
            "not_comparable_parameters": "identity",
            "timing_delta_sec": "",
            "left_exec_time": "",
            "right_exec_time": "",
            "exec_time_delta": "",
            "exec_time_delta_sec": "",
            "match_confidence": "unmatched",
        }


def iter_comparison_csv_lines(result: ComparisonResult):
    yield from _iter_csv_lines(iter_comparison_rows(result), COMPARISON_COLUMNS)


def _iter_csv_lines(
    rows: Iterable[dict[str, object]],
    fieldnames: list[str],
    *,
    extrasaction: str = "raise",
) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction=extrasaction)
    writer.writeheader()
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    for row in rows:
        writer.writerow(row)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


def _comparison_row_pairs(result: ComparisonResult) -> Iterable[JobPair]:
    for p in result.pairs:
        yield p
    for job in result.left_only:
        yield JobPair(left=job, logical_id=job.logical_id)
    for job in result.right_only:
        yield JobPair(right=job, logical_id=job.logical_id)
