"""Dependency graph parity tests for AutoSys vs Process Scheduler topologies."""

from app.models import (
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    JobStatus,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)
from app.services.comparison import compare_snapshots


def _snapshot(scheduler: SchedulerType, *, with_edge: bool) -> TopologySnapshot:
    context = ComparisonContext(environment_id=scheduler.value, scheduler=scheduler)
    first = SnapshotJob(
        job_uid=f"{scheduler.value}-first",
        scheduler_job_name="FIRST",
        logical_id="first",
        status=JobStatus.SUCCESS,
    )
    second = SnapshotJob(
        job_uid=f"{scheduler.value}-second",
        scheduler_job_name="SECOND",
        logical_id="second",
        status=JobStatus.SUCCESS,
    )
    edges = []
    if with_edge:
        edges.append(
            DependencyEdge(
                from_uid=first.job_uid,
                to_uid=second.job_uid,
                kind=DependencyKind.FINISH_TO_START,
                condition="success",
            )
        )
    return TopologySnapshot(context=context, flat_jobs=[first, second], edges=edges)


def test_dependency_graph_difference_is_a_definition_mismatch():
    left = _snapshot(SchedulerType.AUTOSYS, with_edge=True)
    right = _snapshot(SchedulerType.PROCESS_SCHEDULER, with_edge=False)

    result = compare_snapshots(left, right)
    dependency_diffs = [m for m in result.parameter_mismatches if m.parameter == "dependencies"]
    assert len(dependency_diffs) == 1
    assert dependency_diffs[0].logical_id == "SECOND"
