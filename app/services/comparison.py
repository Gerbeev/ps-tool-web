"""Pairwise job comparison and diff summary."""

from __future__ import annotations

from collections import defaultdict

from app.adapters.factory import get_adapter
from app.autosys_reference import compare_reference_parameter, load_compare_parameters
from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    ComparisonResult,
    ComparisonSummary,
    FieldEvidence,
    FieldSupport,
    IdentityConflict,
    JobPair,
    JobStatus,
    MatchConfidence,
    NotComparableParameter,
    ParameterMismatch,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)
from app.services.identity import annotate_snapshot_jobs, structured_logical_id
from app.services.snapshot_cache import SnapshotCache, snapshot_cache
from app.services.snapshot_validation import validate_snapshot
from app.services.topology_index import ensure_topology_indexes

_JOB_STATUS_CSS: dict[JobStatus, str] = {
    JobStatus.SUCCESS: "status-success",
    JobStatus.FAILURE: "status-failure",
    JobStatus.RUNNING: "status-running",
    JobStatus.PENDING: "status-pending",
    JobStatus.NOT_RUN: "status-pending",
    JobStatus.KILLED: "status-killed",
    JobStatus.UNKNOWN: "status-unknown",
    JobStatus.DISABLED: "status-unknown",
}

_RUNTIME_PARAMETERS = {"status", "resolved_command", "exit_code", "actual_start", "actual_end"}
_SYNTHETIC_DEFINITION_PARAMETERS = {"dependencies", "topology_parent"}


def fetch_snapshot(
    context: ComparisonContext,
    cache: SnapshotCache | None = None,
    *,
    force_refresh: bool = False,
) -> tuple[TopologySnapshot, str]:
    """Fetch, normalize metadata, validate, and optionally cache a topology snapshot."""
    c = cache or snapshot_cache
    adapter = get_adapter(context.scheduler, context.environment_id)
    key = SnapshotCache.context_key(context, context.scheduler.value)
    snap = None if force_refresh else c.get(key)
    if snap is None:
        snap = adapter.fetch_topology(context)
        snap.capabilities = adapter.capabilities()
        should_cache = True
    else:
        # Capabilities are part of the captured source contract. A fresh adapter
        # instance may not have contacted an out-of-process connector yet, so
        # overwriting a cached snapshot here would silently lose field support.
        should_cache = False

    snap.metadata["match_confidence_by_uid"] = annotate_snapshot_jobs(
        snap.flat_jobs, context.scheduler
    )
    ensure_topology_indexes(snap)
    validation = validate_snapshot(snap)
    snap.metadata["validation_report"] = {
        "is_valid": validation.is_valid,
        "error_count": validation.error_count,
        "warning_count": validation.warning_count,
        "issues": [issue.model_dump(mode="json") for issue in validation.issues],
    }
    if should_cache:
        c.set(key, snap)
    return snap, key


def compare_contexts(
    left: ComparisonContext,
    right: ComparisonContext,
    *,
    cache: SnapshotCache | None = None,
) -> ComparisonResult:
    left_snap, _ = fetch_snapshot(left, cache)
    right_snap, _ = fetch_snapshot(right, cache)
    return compare_snapshots(left_snap, right_snap)


def compare_snapshots(
    left_snap: TopologySnapshot,
    right_snap: TopologySnapshot,
) -> ComparisonResult:
    """Compare already-fetched snapshots without repeating adapter/cache work."""
    cfg = load_compare_parameters()
    timing_threshold_sec = cfg.timing_threshold_sec
    execution_time_threshold_sec = cfg.execution_time_threshold_sec

    left_confidence_by_uid = _confidence_by_uid(left_snap, left_snap.context.scheduler)
    right_confidence_by_uid = _confidence_by_uid(right_snap, right_snap.context.scheduler)
    ensure_topology_indexes(left_snap)
    ensure_topology_indexes(right_snap)

    left_by_logical, left_conflicts = _unique_jobs_by_logical(left_snap, "left")
    right_by_logical, right_conflicts = _unique_jobs_by_logical(right_snap, "right")
    identity_conflicts = [*left_conflicts, *right_conflicts]

    left_confidence = _confidence_by_logical(left_by_logical, left_confidence_by_uid)
    right_confidence = _confidence_by_logical(right_by_logical, right_confidence_by_uid)
    left_dependencies = _dependency_predecessors_by_logical(left_snap)
    right_dependencies = _dependency_predecessors_by_logical(right_snap)
    left_parents = _topology_parent_by_logical(left_snap)
    right_parents = _topology_parent_by_logical(right_snap)
    definition_parameters = set(cfg.jil_parameters) | _SYNTHETIC_DEFINITION_PARAMETERS

    all_keys = set(left_by_logical) | set(right_by_logical)
    pairs: list[JobPair] = []
    left_only: list[SnapshotJob] = []
    right_only: list[SnapshotJob] = []
    status_mismatches: list[JobPair] = []
    timing_deltas: list[JobPair] = []
    execution_time_deltas: list[JobPair] = []
    definition_mismatches: list[JobPair] = []
    parameter_mismatches: list[ParameterMismatch] = []
    not_comparable: list[NotComparableParameter] = []
    param_counts: dict[str, int] = {}

    for logical_id in sorted(all_keys):
        left_job = left_by_logical.get(logical_id)
        right_job = right_by_logical.get(logical_id)
        confidence = MatchConfidence.UNMATCHED
        if left_job and right_job:
            confidence = _best_confidence(
                left_confidence.get(logical_id), right_confidence.get(logical_id)
            )
        elif left_job:
            confidence = left_confidence.get(logical_id, MatchConfidence.NAME_ONLY)
        elif right_job:
            confidence = right_confidence.get(logical_id, MatchConfidence.NAME_ONLY)

        pair = JobPair(
            left=left_job,
            right=right_job,
            logical_id=logical_id,
            match_kind=confidence,
            confidence=confidence,
        )
        if left_job and right_job:
            pairs.append(pair)

            status_skip = _not_comparable_for_field(
                logical_id,
                "status",
                left_job,
                right_job,
                left_snap,
                right_snap,
                left_value=left_job.status.value,
                right_value=right_job.status.value,
            )
            if status_skip:
                not_comparable.append(status_skip)
            elif left_job.status != right_job.status:
                status_mismatches.append(pair)

            if _runtime_timing_comparable(left_job, right_job, left_snap, right_snap):
                delta = _timing_delta_sec(left_job, right_job)
                if delta is not None and delta > timing_threshold_sec:
                    timing_deltas.append(pair)

            if _execution_time_comparable(left_job, right_job, left_snap, right_snap):
                exec_delta = pair.execution_time_delta_sec
                if (
                    exec_delta is not None
                    and abs(exec_delta) > execution_time_threshold_sec
                ):
                    execution_time_deltas.append(pair)

            mismatches, skipped = compare_job_parameters_detailed(
                left_job,
                right_job,
                logical_id,
                left_snapshot=left_snap,
                right_snapshot=right_snap,
                config=cfg,
            )
            not_comparable.extend(skipped)

            dep_mismatch, dep_skip = _compare_dependencies(
                logical_id=logical_id,
                left=left_dependencies.get(logical_id, ()),
                right=right_dependencies.get(logical_id, ()),
                left_job=left_job,
                right_job=right_job,
                left_snapshot=left_snap,
                right_snapshot=right_snap,
            )
            if dep_mismatch:
                mismatches.append(dep_mismatch)
            if dep_skip:
                not_comparable.append(dep_skip)

            parent_mismatch, parent_skip = _compare_topology_parent(
                logical_id=logical_id,
                left=left_parents.get(logical_id, ""),
                right=right_parents.get(logical_id, ""),
                left_job=left_job,
                right_job=right_job,
                left_snapshot=left_snap,
                right_snapshot=right_snap,
            )
            if parent_mismatch:
                mismatches.append(parent_mismatch)
            if parent_skip:
                not_comparable.append(parent_skip)

            if mismatches:
                if any(m.parameter in definition_parameters for m in mismatches):
                    definition_mismatches.append(pair)
                parameter_mismatches.extend(mismatches)
                for mismatch in mismatches:
                    param_counts[mismatch.parameter] = param_counts.get(mismatch.parameter, 0) + 1
        elif left_job:
            left_only.append(left_job)
        elif right_job:
            right_only.append(right_job)

    not_comparable_counts: dict[str, int] = {}
    for skipped in not_comparable:
        not_comparable_counts[skipped.parameter] = (
            not_comparable_counts.get(skipped.parameter, 0) + 1
        )

    summary = ComparisonSummary(
        total_left=len(left_snap.flat_jobs),
        total_right=len(right_snap.flat_jobs),
        matched=len(pairs),
        mismatched_status=len(status_mismatches),
        mismatched_parameters=len(parameter_mismatches),
        parameter_mismatch_counts=param_counts,
        mismatched_timing=len(timing_deltas),
        mismatched_execution_time=len(execution_time_deltas),
        left_only_count=len(left_only),
        right_only_count=len(right_only),
        not_comparable_parameters=len(not_comparable),
        not_comparable_counts=not_comparable_counts,
        identity_conflicts=len(identity_conflicts),
    )

    return ComparisonResult(
        left_snapshot_id=left_snap.snapshot_id,
        right_snapshot_id=right_snap.snapshot_id,
        pairs=pairs,
        left_only=left_only,
        right_only=right_only,
        status_mismatches=status_mismatches,
        timing_deltas=timing_deltas,
        execution_time_deltas=execution_time_deltas,
        definition_mismatches=definition_mismatches,
        parameter_mismatches=parameter_mismatches,
        not_comparable=not_comparable,
        identity_conflicts=identity_conflicts,
        summary=summary,
    )


def _confidence_by_uid(
    snapshot: TopologySnapshot,
    scheduler: SchedulerType,
) -> dict[str, MatchConfidence]:
    confidence = snapshot.metadata.get("match_confidence_by_uid")
    job_uids = {job.job_uid for job in snapshot.flat_jobs}
    if isinstance(confidence, dict) and set(confidence) == job_uids:
        return confidence
    confidence = annotate_snapshot_jobs(snapshot.flat_jobs, scheduler)
    snapshot.metadata["match_confidence_by_uid"] = confidence
    return confidence


def _unique_jobs_by_logical(
    snapshot: TopologySnapshot,
    side: str,
) -> tuple[dict[str, SnapshotJob], list[IdentityConflict]]:
    grouped: dict[str, list[SnapshotJob]] = defaultdict(list)
    for job in snapshot.flat_jobs:
        if job.logical_id:
            grouped[job.logical_id].append(job)

    unique: dict[str, SnapshotJob] = {}
    conflicts: list[IdentityConflict] = []
    for logical_id, jobs in grouped.items():
        if len(jobs) == 1:
            unique[logical_id] = jobs[0]
            continue
        conflicts.append(
            IdentityConflict(
                side=side,
                logical_id=logical_id,
                job_uids=[job.job_uid for job in jobs],
                job_names=[job.scheduler_job_name for job in jobs],
            )
        )
    return unique, conflicts


def _confidence_by_logical(
    jobs_by_logical: dict[str, SnapshotJob],
    confidence_by_uid: dict[str, MatchConfidence],
) -> dict[str, MatchConfidence]:
    return {
        logical_id: confidence_by_uid.get(job.job_uid, MatchConfidence.NAME_ONLY)
        for logical_id, job in jobs_by_logical.items()
    }


def compare_job_parameters(
    left: SnapshotJob,
    right: SnapshotJob,
    logical_id: str | None,
    *,
    config=None,
) -> list[ParameterMismatch]:
    mismatches, _ = compare_job_parameters_detailed(
        left,
        right,
        logical_id,
        config=config,
    )
    return mismatches


def compare_job_parameters_detailed(
    left: SnapshotJob,
    right: SnapshotJob,
    logical_id: str | None,
    *,
    left_snapshot: TopologySnapshot | None = None,
    right_snapshot: TopologySnapshot | None = None,
    config=None,
) -> tuple[list[ParameterMismatch], list[NotComparableParameter]]:
    cfg = config or load_compare_parameters()
    left_capabilities = left_snapshot.capabilities if left_snapshot else AdapterCapabilities()
    right_capabilities = right_snapshot.capabilities if right_snapshot else AdapterCapabilities()
    mismatches: list[ParameterMismatch] = []
    skipped: list[NotComparableParameter] = []

    # Common fast path for fully comparable jobs whose normalized AutoSys projection
    # is identical. Avoid re-normalizing every configured field for large snapshots.
    if (
        left.autosys == right.autosys
        and not left.comparison_support
        and not right.comparison_support
        and _all_parameters_implicitly_supported(left_capabilities)
        and _all_parameters_implicitly_supported(right_capabilities)
    ):
        return mismatches, skipped

    for parameter in cfg.all_parameters:
        left_value, right_value, equal = compare_reference_parameter(
            left.autosys,
            right.autosys,
            parameter,
            timing_threshold_sec=cfg.timing_threshold_sec,
        )
        if parameter == "box_name" and left_value and right_value:
            left_parent_id = structured_logical_id(left_value)
            right_parent_id = structured_logical_id(right_value)
            if left_parent_id is not None and right_parent_id is not None:
                equal = left_parent_id == right_parent_id
        skip = _not_comparable_for_field(
            logical_id,
            parameter,
            left,
            right,
            left_snapshot,
            right_snapshot,
            left_value=left_value,
            right_value=right_value,
            left_capabilities=left_capabilities,
            right_capabilities=right_capabilities,
        )
        if skip:
            skipped.append(skip)
            continue
        if not equal:
            mismatches.append(
                ParameterMismatch(
                    logical_id=logical_id,
                    parameter=parameter,
                    left_value=left_value,
                    right_value=right_value,
                    left_evidence=left.comparison_evidence.get(parameter),
                    right_evidence=right.comparison_evidence.get(parameter),
                )
            )
    return mismatches, skipped



def _all_parameters_implicitly_supported(capabilities: AdapterCapabilities) -> bool:
    return (
        not capabilities.strict_parameter_support
        and not capabilities.parameter_support
        and capabilities.topology
        and capabilities.dependencies
        and capabilities.runtime
        and capabilities.autosys_projection
    )

def _field_support(
    job: SnapshotJob,
    parameter: str,
    capabilities: AdapterCapabilities,
) -> FieldSupport:
    explicit = job.comparison_support.get(parameter)
    if explicit is not None:
        return explicit
    declared = capabilities.parameter_support.get(parameter)
    if declared is not None:
        return declared
    if parameter == "dependencies" and not capabilities.dependencies:
        return FieldSupport.UNSUPPORTED
    if parameter == "topology_parent" and not capabilities.topology:
        return FieldSupport.UNSUPPORTED
    if parameter in _RUNTIME_PARAMETERS and not capabilities.runtime:
        return FieldSupport.UNSUPPORTED
    if parameter not in _RUNTIME_PARAMETERS and parameter not in _SYNTHETIC_DEFINITION_PARAMETERS:
        if not capabilities.autosys_projection:
            return FieldSupport.UNSUPPORTED
    if capabilities.strict_parameter_support:
        return FieldSupport.UNKNOWN
    return FieldSupport.SUPPORTED


def _not_comparable_for_field(
    logical_id: str | None,
    parameter: str,
    left: SnapshotJob,
    right: SnapshotJob,
    left_snapshot: TopologySnapshot | None,
    right_snapshot: TopologySnapshot | None,
    *,
    left_value: str,
    right_value: str,
    left_capabilities: AdapterCapabilities | None = None,
    right_capabilities: AdapterCapabilities | None = None,
) -> NotComparableParameter | None:
    left_caps = left_capabilities or (
        left_snapshot.capabilities if left_snapshot else AdapterCapabilities()
    )
    right_caps = right_capabilities or (
        right_snapshot.capabilities if right_snapshot else AdapterCapabilities()
    )
    left_support = _field_support(left, parameter, left_caps)
    right_support = _field_support(right, parameter, right_caps)
    if left_support == FieldSupport.SUPPORTED and right_support == FieldSupport.SUPPORTED:
        return None
    return NotComparableParameter(
        logical_id=logical_id,
        parameter=parameter,
        left_value=left_value,
        right_value=right_value,
        left_support=left_support,
        right_support=right_support,
        reason=_support_reason(left_support, right_support),
        left_evidence=left.comparison_evidence.get(parameter),
        right_evidence=right.comparison_evidence.get(parameter),
    )


def _support_reason(left: FieldSupport, right: FieldSupport) -> str:
    return f"left={left.value}; right={right.value}"


def _dependency_predecessors_by_logical(
    snapshot: TopologySnapshot,
) -> dict[str, tuple[str, ...]]:
    """Return canonical predecessor signatures keyed by dependent logical id.

    Topology parent/child membership is intentionally not inferred as a dependency.
    Adapters should put only real execution dependencies into ``snapshot.edges``.
    """
    jobs_by_uid = {job.job_uid: job for job in snapshot.flat_jobs}
    out: dict[str, set[str]] = {}
    for edge in snapshot.edges:
        predecessor = jobs_by_uid.get(edge.from_uid)
        dependent = jobs_by_uid.get(edge.to_uid)
        if not predecessor or not dependent:
            continue
        predecessor_id = predecessor.logical_id
        dependent_id = dependent.logical_id
        if not predecessor_id or not dependent_id:
            continue
        condition = _normalize_dependency_condition(edge.condition)
        signature = f"{predecessor_id}|{edge.kind.value}|{condition}"
        out.setdefault(dependent_id, set()).add(signature)
    return {logical_id: tuple(sorted(values)) for logical_id, values in out.items()}


def _topology_parent_by_logical(snapshot: TopologySnapshot) -> dict[str, str]:
    jobs_by_uid = {job.job_uid: job for job in snapshot.flat_jobs}
    out: dict[str, str] = {}
    for job in snapshot.flat_jobs:
        if not job.logical_id:
            continue
        parent = jobs_by_uid.get(job.parent_uid) if job.parent_uid else None
        out[job.logical_id] = parent.logical_id if parent and parent.logical_id else ""
    return out


def _normalize_dependency_condition(value: str | None) -> str:
    if not value:
        return ""
    raw = " ".join(value.strip().split()).lower()
    aliases = {
        "s": "success",
        "success": "success",
        "f": "failure",
        "failure": "failure",
        "d": "done",
        "done": "done",
        "t": "terminated",
        "terminated": "terminated",
    }
    return aliases.get(raw, raw)


def _compare_dependencies(
    *,
    logical_id: str,
    left: tuple[str, ...],
    right: tuple[str, ...],
    left_job: SnapshotJob,
    right_job: SnapshotJob,
    left_snapshot: TopologySnapshot,
    right_snapshot: TopologySnapshot,
) -> tuple[ParameterMismatch | None, NotComparableParameter | None]:
    left_value = ";".join(left)
    right_value = ";".join(right)
    skip = _not_comparable_for_field(
        logical_id,
        "dependencies",
        left_job,
        right_job,
        left_snapshot,
        right_snapshot,
        left_value=left_value,
        right_value=right_value,
    )
    if skip:
        return None, skip
    if left == right:
        return None, None
    return (
        ParameterMismatch(
            logical_id=logical_id,
            parameter="dependencies",
            left_value=left_value,
            right_value=right_value,
            left_evidence=left_job.comparison_evidence.get("dependencies"),
            right_evidence=right_job.comparison_evidence.get("dependencies"),
        ),
        None,
    )


def _compare_topology_parent(
    *,
    logical_id: str,
    left: str,
    right: str,
    left_job: SnapshotJob,
    right_job: SnapshotJob,
    left_snapshot: TopologySnapshot,
    right_snapshot: TopologySnapshot,
) -> tuple[ParameterMismatch | None, NotComparableParameter | None]:
    skip = _not_comparable_for_field(
        logical_id,
        "topology_parent",
        left_job,
        right_job,
        left_snapshot,
        right_snapshot,
        left_value=left,
        right_value=right,
    )
    if skip:
        return None, skip
    if left == right:
        return None, None
    return (
        ParameterMismatch(
            logical_id=logical_id,
            parameter="topology_parent",
            left_value=left,
            right_value=right,
            left_evidence=left_job.comparison_evidence.get("topology_parent"),
            right_evidence=right_job.comparison_evidence.get("topology_parent"),
        ),
        None,
    )


def _runtime_timing_comparable(
    left: SnapshotJob,
    right: SnapshotJob,
    left_snapshot: TopologySnapshot,
    right_snapshot: TopologySnapshot,
) -> bool:
    for parameter in ("actual_start", "actual_end"):
        if (
            _field_support(left, parameter, left_snapshot.capabilities)
            == FieldSupport.SUPPORTED
            and _field_support(right, parameter, right_snapshot.capabilities)
            == FieldSupport.SUPPORTED
        ):
            return True
    return False



def _execution_time_comparable(
    left: SnapshotJob,
    right: SnapshotJob,
    left_snapshot: TopologySnapshot,
    right_snapshot: TopologySnapshot,
) -> bool:
    """Execution time requires both actual start and end on both sides."""
    for parameter in ("actual_start", "actual_end"):
        if (
            _field_support(left, parameter, left_snapshot.capabilities)
            != FieldSupport.SUPPORTED
            or _field_support(right, parameter, right_snapshot.capabilities)
            != FieldSupport.SUPPORTED
        ):
            return False
    return (
        left.execution_time_sec is not None
        and right.execution_time_sec is not None
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


def _timing_delta_sec(left: SnapshotJob, right: SnapshotJob) -> float | None:
    deltas: list[float] = []
    if left.actual_start and right.actual_start:
        deltas.append(abs((left.actual_start - right.actual_start).total_seconds()))
    if left.actual_end and right.actual_end:
        deltas.append(abs((left.actual_end - right.actual_end).total_seconds()))
    return max(deltas) if deltas else None


def job_status_css(status: JobStatus) -> str:
    return _JOB_STATUS_CSS.get(status, "status-unknown")
