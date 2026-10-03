"""Pairwise job comparison and diff summary."""

from __future__ import annotations

from app.adapters.factory import get_adapter
from app.models import (
    ComparisonContext,
    ComparisonResult,
    ComparisonSummary,
    JobPair,
    JobStatus,
    MatchConfidence,
    NormalizedJob,
)
from app.services.identity import annotate_snapshot_jobs, logical_id_for_job
from app.services.snapshot_cache import SnapshotCache, snapshot_cache


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
        c.set(key, snap)
    else:
        annotate_snapshot_jobs(snap.flat_jobs, context.scheduler)
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
        elif lj:
            left_only.append(lj)
        elif rj:
            right_only.append(rj)

    summary = ComparisonSummary(
        total_left=len(left_snap.flat_jobs),
        total_right=len(right_snap.flat_jobs),
        matched=len(pairs),
        mismatched_status=len(status_mismatches),
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
        summary=summary,
    )


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


def job_status_css(status: JobStatus) -> str:
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
