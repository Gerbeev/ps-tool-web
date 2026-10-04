"""Pairwise job comparison and diff summary."""

from __future__ import annotations

from app.adapters.factory import get_adapter
from app.autosys_reference import compare_references, load_compare_parameters
from app.models import (
    ComparisonContext,
    ComparisonResult,
    ComparisonSummary,
    JobPair,
    MatchConfidence,
    ParameterMismatch,
    SnapshotJob,
)
from app.services.identity import annotate_snapshot_jobs, logical_id_for_job
from app.services.snapshot_cache import SnapshotCache, snapshot_cache
from app.services.topology_index import ensure_topology_indexes


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
) -> ComparisonResult:
    cfg = load_compare_parameters()
    timing_threshold_sec = cfg.timing_threshold_sec
    left_snap, _ = fetch_snapshot(left, cache)
    right_snap, _ = fetch_snapshot(right, cache)

    left_by_logical: dict[str, SnapshotJob] = {}
    left_confidence: dict[str, MatchConfidence] = {}
    for job in left_snap.flat_jobs:
        lid, conf = logical_id_for_job(job, left.scheduler)
        job.logical_id = lid
        if lid:
            left_by_logical[lid] = job
            left_confidence[lid] = conf

    right_by_logical: dict[str, SnapshotJob] = {}
    right_confidence: dict[str, MatchConfidence] = {}
    for job in right_snap.flat_jobs:
        lid, conf = logical_id_for_job(job, right.scheduler)
        job.logical_id = lid
        if lid:
            right_by_logical[lid] = job
            right_confidence[lid] = conf

    all_keys = set(left_by_logical) | set(right_by_logical)
    pairs: list[JobPair] = []
    left_only: list[SnapshotJob] = []
    right_only: list[SnapshotJob] = []
    status_mismatches: list[JobPair] = []
    timing_deltas: list[JobPair] = []
    definition_mismatches: list[JobPair] = []
    parameter_mismatches: list[ParameterMismatch] = []
    param_counts: dict[str, int] = {}
    timing_mm = 0

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
            mismatches = compare_job_parameters(lj, rj, lid, config=cfg)
            if mismatches:
                definition_mismatches.append(pair)
                parameter_mismatches.extend(mismatches)
                for m in mismatches:
                    param_counts[m.parameter] = param_counts.get(m.parameter, 0) + 1
                    if m.parameter in ("actual_start", "actual_end"):
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
        mismatched_parameters=len(parameter_mismatches),
        parameter_mismatch_counts=param_counts,
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
        parameter_mismatches=parameter_mismatches,
        summary=summary,
    )


def compare_job_parameters(
    left: SnapshotJob,
    right: SnapshotJob,
    logical_id: str | None,
    *,
    config=None,
) -> list[ParameterMismatch]:
    raw = compare_references(left.autosys, right.autosys, logical_id=logical_id, config=config)
    return [
        ParameterMismatch(
            logical_id=logical_id,
            parameter=param,
            left_value=lv,
            right_value=rv,
        )
        for param, lv, rv in raw
    ]


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


def _timing_delta_sec(left: SnapshotJob, right: SnapshotJob) -> float | None:
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
