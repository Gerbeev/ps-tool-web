"""Pairwise job comparison and diff summary."""

from __future__ import annotations

from datetime import datetime

from app.adapters.factory import get_adapter
from app.models import (
    ComparedField,
    ComparisonContext,
    ComparisonResult,
    ComparisonSummary,
    FieldMismatch,
    JobPair,
    MatchConfidence,
    NormalizedJob,
)
from app.services.identity import annotate_snapshot_jobs, logical_id_for_job
from app.services.snapshot_cache import SnapshotCache, snapshot_cache
from app.services.topology_index import ensure_topology_indexes


TIMING_DELTA_THRESHOLD_SEC = 60.0


def fetch_snapshot(
    context: ComparisonContext,
    cache: SnapshotCache | None = None,
) -> tuple[object, str]:
    """Fetch topology via adapter with optional cache."""
    c = cache or snapshot_cache
    adapter = get_adapter(context.scheduler, context.environment_id)
    key = SnapshotCache.context_key(context, context.scheduler.value)
    snap = c.get(key)
    if snap is None:
        snap = adapter.fetch_topology(context)
        annotate_snapshot_jobs(snap.flat_jobs, context.scheduler)
        ensure_topology_indexes(snap)
        c.set(key, snap)
    else:
        annotate_snapshot_jobs(snap.flat_jobs, context.scheduler)
        ensure_topology_indexes(snap)
    return snap, key


def compare_contexts(
    left: ComparisonContext,
    right: ComparisonContext,
    *,
    cache: SnapshotCache | None = None,
    timing_threshold_sec: float = TIMING_DELTA_THRESHOLD_SEC,
) -> ComparisonResult:
    left_snap, _ = fetch_snapshot(left, cache)
    right_snap, _ = fetch_snapshot(right, cache)

    left_by_logical: dict[str, NormalizedJob] = {}
    left_confidence: dict[str, MatchConfidence] = {}
    for job in left_snap.flat_jobs:
        lid, conf = logical_id_for_job(job, left.scheduler)
        job.logical_id = lid
        if lid:
            left_by_logical[lid] = job
            left_confidence[lid] = conf

    right_by_logical: dict[str, NormalizedJob] = {}
    right_confidence: dict[str, MatchConfidence] = {}
    for job in right_snap.flat_jobs:
        lid, conf = logical_id_for_job(job, right.scheduler)
        job.logical_id = lid
        if lid:
            right_by_logical[lid] = job
            right_confidence[lid] = conf

    all_keys = set(left_by_logical) | set(right_by_logical)
    pairs: list[JobPair] = []
    left_only: list[NormalizedJob] = []
    right_only: list[NormalizedJob] = []
    status_mismatches: list[JobPair] = []
    timing_deltas: list[JobPair] = []
    definition_mismatches: list[JobPair] = []
    field_mismatches: list[FieldMismatch] = []
    schedule_mm = command_mm = condition_mm = log_mm = resolved_cmd_mm = timing_mm = 0

    for lid in sorted(all_keys):
        lj = left_by_logical.get(lid)
        rj = right_by_logical.get(lid)
        conf = MatchConfidence.UNMATCHED
        if lj and rj:
            conf = _best_confidence(left_confidence.get(lid), right_confidence.get(lid))
        elif lj:
            conf = left_confidence.get(lid, MatchConfidence.NAME_ONLY)
        elif rj:
            conf = right_confidence.get(lid, MatchConfidence.NAME_ONLY)

        pair = JobPair(left=lj, right=rj, logical_id=lid, match_kind=conf, confidence=conf)
        if lj and rj:
            pairs.append(pair)
            if lj.status != rj.status:
                status_mismatches.append(pair)
            delta = _timing_delta_sec(lj, rj)
            if delta is not None and delta > timing_threshold_sec:
                timing_deltas.append(pair)
            mismatches = _compare_job_fields(lj, rj, lid, timing_threshold_sec)
            if mismatches:
                definition_mismatches.append(pair)
                field_mismatches.extend(mismatches)
                for m in mismatches:
                    if m.field == ComparedField.SCHEDULE:
                        schedule_mm += 1
                    elif m.field == ComparedField.COMMAND:
                        command_mm += 1
                    elif m.field == ComparedField.CONDITION:
                        condition_mm += 1
                    elif m.field == ComparedField.LOG_PATHS:
                        log_mm += 1
                    elif m.field == ComparedField.RESOLVED_COMMAND:
                        resolved_cmd_mm += 1
                    elif m.field in (ComparedField.START_TIME, ComparedField.END_TIME):
                        timing_mm += 1
        elif lj:
            left_only.append(lj)
        elif rj:
            right_only.append(rj)

    summary = ComparisonSummary(
        total_left=len(left_snap.flat_jobs),
        total_right=len(right_snap.flat_jobs),
        matched=len(pairs),
        mismatched_status=len(status_mismatches),
        mismatched_schedule=schedule_mm,
        mismatched_command=command_mm,
        mismatched_condition=condition_mm,
        mismatched_log_paths=log_mm,
        mismatched_resolved_command=resolved_cmd_mm,
        mismatched_timing=timing_mm,
        left_only_count=len(left_only),
        right_only_count=len(right_only),
    )

    return ComparisonResult(
        left_snapshot_id=left_snap.snapshot_id,
        right_snapshot_id=right_snap.snapshot_id,
        pairs=pairs,
        left_only=left_only,
        right_only=right_only,
        status_mismatches=status_mismatches,
        timing_deltas=timing_deltas,
        definition_mismatches=definition_mismatches,
        field_mismatches=field_mismatches,
        summary=summary,
    )


def _compare_job_fields(
    left: NormalizedJob,
    right: NormalizedJob,
    logical_id: str | None,
    timing_threshold_sec: float,
) -> list[FieldMismatch]:
    out: list[FieldMismatch] = []

    def record(field: ComparedField, lv: str, rv: str, *, time_field: bool = False) -> None:
        if time_field:
            if _times_within_threshold(lv, rv, timing_threshold_sec):
                return
        elif lv == rv:
            return
        out.append(
            FieldMismatch(logical_id=logical_id, field=field, left_value=lv, right_value=rv)
        )

    record(ComparedField.SCHEDULE, _schedule_repr(left), _schedule_repr(right))
    record(ComparedField.COMMAND, _norm_text(left.command), _norm_text(right.command))
    record(ComparedField.CONDITION, _norm_text(left.condition), _norm_text(right.condition))
    record(
        ComparedField.LOG_PATHS,
        _log_paths_repr(left.log_paths),
        _log_paths_repr(right.log_paths),
    )
    record(
        ComparedField.RESOLVED_COMMAND,
        _norm_text(left.resolved_command),
        _norm_text(right.resolved_command),
    )
    record(
        ComparedField.START_TIME,
        _time_repr(left.actual_start),
        _time_repr(right.actual_start),
        time_field=True,
    )
    record(
        ComparedField.END_TIME,
        _time_repr(left.actual_end),
        _time_repr(right.actual_end),
        time_field=True,
    )
    return out


def _norm_text(value: str | None) -> str:
    return (value or "").strip()


def _schedule_repr(job: NormalizedJob) -> str:
    if job.schedule:
        return job.schedule.comparable()
    return ""


def _log_paths_repr(paths: list[str]) -> str:
    return ";".join(sorted(p.strip() for p in paths if p.strip()))


def _time_repr(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.isoformat()


def _times_within_threshold(left: str, right: str, threshold_sec: float) -> bool:
    if not left and not right:
        return True
    if not left or not right:
        return False
    try:
        ld = datetime.fromisoformat(left.replace("Z", "+00:00"))
        rd = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return left == right
    if ld.tzinfo is None and rd.tzinfo is not None:
        ld = ld.replace(tzinfo=rd.tzinfo)
    if rd.tzinfo is None and ld.tzinfo is not None:
        rd = rd.replace(tzinfo=ld.tzinfo)
    return abs((ld - rd).total_seconds()) <= threshold_sec


def _best_confidence(a: MatchConfidence | None, b: MatchConfidence | None) -> MatchConfidence:
    order = [
        MatchConfidence.MAPPED,
        MatchConfidence.NORMALIZED,
        MatchConfidence.NAME_ONLY,
        MatchConfidence.UNMATCHED,
    ]
    scores = {c: i for i, c in enumerate(order)}
    ca = a or MatchConfidence.UNMATCHED
    cb = b or MatchConfidence.UNMATCHED
    return ca if scores[ca] <= scores[cb] else cb


def _timing_delta_sec(left: NormalizedJob, right: NormalizedJob) -> float | None:
    if left.actual_end and right.actual_end:
        return abs((left.actual_end - right.actual_end).total_seconds())
    if left.actual_start and right.actual_start:
        return abs((left.actual_start - right.actual_start).total_seconds())
    return None


def job_status_css(status) -> str:
    from app.models import JobStatus

    return {
        JobStatus.SUCCESS: "status-success",
        JobStatus.FAILURE: "status-failure",
        JobStatus.RUNNING: "status-running",
        JobStatus.PENDING: "status-pending",
        JobStatus.NOT_RUN: "status-pending",
        JobStatus.KILLED: "status-killed",
        JobStatus.UNKNOWN: "status-unknown",
        JobStatus.DISABLED: "status-unknown",
    }.get(status, "status-unknown")
