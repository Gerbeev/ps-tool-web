"""Indexes for O(1) tree child lookup on large snapshots."""

from __future__ import annotations

from app.models import JobNode, NormalizedJob, TopologySnapshot


def build_children_index(roots: list[JobNode]) -> dict[str, list[str]]:
    """Map parent job_uid -> ordered child job_uids."""
    index: dict[str, list[str]] = {}

    def walk(node: JobNode) -> None:
        if node.children:
            index[node.job.job_uid] = [c.job.job_uid for c in node.children]
            for child in node.children:
                walk(child)

    for root in roots:
        walk(root)
    return index


def ensure_topology_indexes(snapshot: TopologySnapshot) -> None:
    """Populate metadata indexes used by lazy tree and exports."""
    if snapshot.metadata.get("children_index") is not None:
        return
    snapshot.metadata["children_index"] = build_children_index(snapshot.roots)
    snapshot.metadata["jobs_by_uid"] = {j.job_uid: j for j in snapshot.flat_jobs}


def child_count(snapshot: TopologySnapshot, job_uid: str) -> int:
    ensure_topology_indexes(snapshot)
    index = snapshot.metadata.get("children_index") or {}
    return len(index.get(job_uid, []))


def get_child_nodes(snapshot: TopologySnapshot, parent_uid: str) -> list[JobNode]:
    """Return shallow JobNode list (no nested children) for lazy tree expansion."""
    ensure_topology_indexes(snapshot)
    index = snapshot.metadata.get("children_index") or {}
    by_uid: dict[str, NormalizedJob] = snapshot.metadata.get("jobs_by_uid") or {
        j.job_uid: j for j in snapshot.flat_jobs
    }
    child_uids = index.get(parent_uid, [])
    return [JobNode(job=by_uid[uid], children=[]) for uid in child_uids if uid in by_uid]


def lazy_roots(snapshot: TopologySnapshot) -> list[JobNode]:
    """Root nodes without embedded descendants (for lazy SSR)."""
    return [JobNode(job=r.job, children=[]) for r in snapshot.roots]
