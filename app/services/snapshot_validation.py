"""Validation of normalized adapter output before comparison."""

from __future__ import annotations

from collections import Counter, defaultdict, deque

from app.autosys_reference import load_compare_parameters, validate_autosys_definition
from app.models import (
    SnapshotValidationIssue,
    SnapshotValidationReport,
    TopologySnapshot,
    ValidationSeverity,
)


def validate_snapshot(snapshot: TopologySnapshot) -> SnapshotValidationReport:
    issues: list[SnapshotValidationIssue] = []
    jobs = snapshot.flat_jobs
    uid_counts = Counter(job.job_uid for job in jobs)
    jobs_by_uid = {job.job_uid: job for job in jobs}

    for uid, count in uid_counts.items():
        if count > 1:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "duplicate_job_uid",
                    f"job_uid {uid!r} occurs {count} times",
                    uid,
                )
            )

    for job in jobs:
        if job.parent_uid == job.job_uid:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "self_parent",
                    "job cannot be its own topology parent",
                    job.job_uid,
                )
            )
        elif job.parent_uid and job.parent_uid not in jobs_by_uid:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "missing_parent",
                    f"parent_uid {job.parent_uid!r} does not exist in snapshot",
                    job.job_uid,
                )
            )

        for message in validate_autosys_definition(job.autosys.jil):
            issues.append(
                _issue(
                    ValidationSeverity.WARNING,
                    "autosys_semantics",
                    message,
                    job.job_uid,
                )
            )

    issues.extend(_validate_containment_cycles(snapshot))
    issues.extend(_validate_edges(snapshot, jobs_by_uid))
    issues.extend(_validate_identity_collisions(snapshot))
    issues.extend(_validate_parameter_support(snapshot))

    return SnapshotValidationReport(issues=issues)


def _validate_containment_cycles(snapshot: TopologySnapshot) -> list[SnapshotValidationIssue]:
    parent_by_uid = {job.job_uid: job.parent_uid for job in snapshot.flat_jobs}
    issues: list[SnapshotValidationIssue] = []
    reported: set[str] = set()

    for start in parent_by_uid:
        seen: set[str] = set()
        current: str | None = start
        while current and current in parent_by_uid:
            if current in seen:
                if current not in reported:
                    reported.add(current)
                    issues.append(
                        _issue(
                            ValidationSeverity.ERROR,
                            "containment_cycle",
                            "topology parent relationship contains a cycle",
                            current,
                        )
                    )
                break
            seen.add(current)
            current = parent_by_uid[current]
    return issues


def _validate_edges(snapshot: TopologySnapshot, jobs_by_uid: dict) -> list[SnapshotValidationIssue]:
    issues: list[SnapshotValidationIssue] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree = {uid: 0 for uid in jobs_by_uid}

    for edge in snapshot.edges:
        if edge.from_uid not in jobs_by_uid:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "dangling_dependency_source",
                    f"dependency source {edge.from_uid!r} does not exist",
                )
            )
            continue
        if edge.to_uid not in jobs_by_uid:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "dangling_dependency_target",
                    f"dependency target {edge.to_uid!r} does not exist",
                )
            )
            continue
        if edge.from_uid == edge.to_uid:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "self_dependency",
                    "job cannot depend on itself",
                    edge.from_uid,
                )
            )

        key = (edge.from_uid, edge.to_uid, edge.kind.value, edge.condition or "")
        if key in seen_edges:
            issues.append(
                _issue(
                    ValidationSeverity.WARNING,
                    "duplicate_dependency",
                    f"duplicate dependency {edge.from_uid!r} -> {edge.to_uid!r}",
                    edge.to_uid,
                )
            )
        else:
            seen_edges.add(key)

        adjacency[edge.from_uid].append(edge.to_uid)
        indegree[edge.to_uid] += 1

    # Dependency cycles may be valid for exotic scheduler semantics, so warn rather than reject.
    queue = deque(uid for uid, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        uid = queue.popleft()
        visited += 1
        for target in adjacency.get(uid, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if jobs_by_uid and visited < len(jobs_by_uid):
        issues.append(
            _issue(
                ValidationSeverity.WARNING,
                "dependency_cycle",
                "execution dependency graph contains a cycle",
            )
        )

    if not snapshot.capabilities.dependencies and snapshot.edges:
        issues.append(
            _issue(
                ValidationSeverity.WARNING,
                "capability_dependency_conflict",
                "adapter declares dependencies unsupported but emitted dependency edges",
            )
        )
    return issues


def _validate_identity_collisions(snapshot: TopologySnapshot) -> list[SnapshotValidationIssue]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for job in snapshot.flat_jobs:
        if job.logical_id:
            grouped[job.logical_id].append(job.job_uid)
    issues: list[SnapshotValidationIssue] = []
    for logical_id, uids in grouped.items():
        if len(uids) > 1:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "ambiguous_logical_id",
                    f"logical_id {logical_id!r} maps to multiple jobs: {', '.join(uids)}",
                )
            )
    return issues


def _validate_parameter_support(snapshot: TopologySnapshot) -> list[SnapshotValidationIssue]:
    known = set(load_compare_parameters().all_parameters) | {
        "status",
        "dependencies",
        "topology_parent",
    }
    issues: list[SnapshotValidationIssue] = []
    if snapshot.capabilities.strict_parameter_support:
        missing = sorted(known - set(snapshot.capabilities.parameter_support))
        if missing:
            issues.append(
                _issue(
                    ValidationSeverity.ERROR,
                    "incomplete_parameter_support",
                    "strict adapter did not declare support for: " + ", ".join(missing),
                )
            )
    for job in snapshot.flat_jobs:
        for parameter in job.comparison_support:
            if parameter not in known:
                issues.append(
                    _issue(
                        ValidationSeverity.WARNING,
                        "unknown_comparison_parameter",
                        f"comparison_support declares unknown parameter {parameter!r}",
                        job.job_uid,
                    )
                )
    return issues


def _issue(
    severity: ValidationSeverity,
    code: str,
    message: str,
    job_uid: str | None = None,
) -> SnapshotValidationIssue:
    return SnapshotValidationIssue(
        severity=severity,
        code=code,
        message=message,
        job_uid=job_uid,
    )
