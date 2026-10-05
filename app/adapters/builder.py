"""Small helper for constructing normalized topology snapshots from native adapters."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    JobNode,
    SnapshotJob,
    TopologySnapshot,
)


class TopologySnapshotBuilder:
    """Build a consistent tree + flat list from normalized jobs.

    Adapters remain responsible for retrieving and normalizing native endpoint payloads. This builder
    only removes repetitive topology assembly code and never infers dependencies from
    containment.
    """

    def __init__(
        self,
        context: ComparisonContext,
        *,
        capabilities: AdapterCapabilities | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._context = context
        self._capabilities = capabilities or AdapterCapabilities()
        self._metadata = dict(metadata or {})
        self._jobs: list[SnapshotJob] = []
        self._uids: set[str] = set()
        self._edges: list[DependencyEdge] = []

    def add_job(self, job: SnapshotJob) -> SnapshotJob:
        if job.job_uid in self._uids:
            raise ValueError(f"Duplicate job_uid: {job.job_uid}")
        self._uids.add(job.job_uid)
        self._jobs.append(job)
        return job

    def add_dependency(
        self,
        from_uid: str,
        to_uid: str,
        *,
        kind: DependencyKind = DependencyKind.FINISH_TO_START,
        condition: str | None = None,
    ) -> None:
        self._edges.append(
            DependencyEdge(
                from_uid=from_uid,
                to_uid=to_uid,
                kind=kind,
                condition=condition,
            )
        )

    def build(self) -> TopologySnapshot:
        nodes = {job.job_uid: JobNode(job=job) for job in self._jobs}
        children_by_parent: dict[str, list[SnapshotJob]] = defaultdict(list)
        roots: list[SnapshotJob] = []

        for job in self._jobs:
            if job.parent_uid and job.parent_uid in nodes:
                children_by_parent[job.parent_uid].append(job)
            else:
                roots.append(job)

        def materialize(job: SnapshotJob, active: set[str]) -> JobNode:
            if job.job_uid in active:
                # Validation will report the cycle; keep the snapshot constructible.
                return JobNode(job=job)
            next_active = {*active, job.job_uid}
            return JobNode(
                job=job,
                children=[materialize(child, next_active) for child in children_by_parent[job.job_uid]],
            )

        return TopologySnapshot(
            context=self._context,
            roots=[materialize(job, set()) for job in roots],
            flat_jobs=list(self._jobs),
            edges=list(self._edges),
            capabilities=self._capabilities,
            metadata=dict(self._metadata),
        )
