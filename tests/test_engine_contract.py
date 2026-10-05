"""Comparison-engine contracts for future real scheduler adapters."""

from app.adapters.builder import TopologySnapshotBuilder
from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    FieldEvidence,
    FieldSupport,
    JobStatus,
    SchedulerType,
    SnapshotJob,
)
from app.services.comparison import compare_snapshots
from app.services.snapshot_validation import validate_snapshot


def _job(uid: str, name: str, logical_id: str, *, parent_uid: str | None = None) -> SnapshotJob:
    return SnapshotJob(
        job_uid=uid,
        scheduler_job_name=name,
        logical_id=logical_id,
        parent_uid=parent_uid,
        status=JobStatus.SUCCESS,
    )


def test_unsupported_parameter_is_not_reported_as_false_mismatch():
    left_context = ComparisonContext(environment_id="a", scheduler=SchedulerType.AUTOSYS)
    right_context = ComparisonContext(
        environment_id="b", scheduler=SchedulerType.PROCESS_SCHEDULER
    )
    left = _job("l", "SAME", "same")
    right = _job("r", "SAME", "same")
    left.autosys.jil.command = "run-a"
    right.autosys.jil.command = None
    right.comparison_support["command"] = FieldSupport.UNSUPPORTED

    # Use separate builders to model independently retrieved snapshots.
    left_builder = TopologySnapshotBuilder(left_context)
    left_builder.add_job(left)
    right_builder = TopologySnapshotBuilder(right_context)
    right_builder.add_job(right)

    result = compare_snapshots(left_builder.build(), right_builder.build())

    assert not any(m.parameter == "command" for m in result.parameter_mismatches)
    skipped = [item for item in result.not_comparable if item.parameter == "command"]
    assert len(skipped) == 1
    assert skipped[0].right_support == FieldSupport.UNSUPPORTED


def test_adapter_capability_can_disable_all_autosys_projection_fields():
    left_context = ComparisonContext(environment_id="a", scheduler=SchedulerType.AUTOSYS)
    right_context = ComparisonContext(
        environment_id="b", scheduler=SchedulerType.PROCESS_SCHEDULER
    )
    left = _job("l", "SAME", "same")
    right = _job("r", "SAME", "same")
    left.autosys.jil.command = "run-a"

    left_builder = TopologySnapshotBuilder(left_context)
    left_builder.add_job(left)
    right_builder = TopologySnapshotBuilder(
        right_context,
        capabilities=AdapterCapabilities(autosys_projection=False, runtime=False),
    )
    right_builder.add_job(right)

    result = compare_snapshots(left_builder.build(), right_builder.build())

    assert not any(m.parameter == "command" for m in result.parameter_mismatches)
    assert any(item.parameter == "command" for item in result.not_comparable)
    assert result.summary.not_comparable_parameters > 0


def test_duplicate_logical_ids_are_reported_instead_of_silently_overwritten():
    left_context = ComparisonContext(environment_id="a", scheduler=SchedulerType.AUTOSYS)
    right_context = ComparisonContext(
        environment_id="b", scheduler=SchedulerType.PROCESS_SCHEDULER
    )
    left_builder = TopologySnapshotBuilder(left_context)
    left_builder.add_job(_job("l1", "DUP", "dup"))
    left_builder.add_job(_job("l2", "DUP", "dup"))
    right_builder = TopologySnapshotBuilder(right_context)
    right_builder.add_job(_job("r1", "DUP", "dup"))

    result = compare_snapshots(left_builder.build(), right_builder.build())

    assert result.summary.identity_conflicts == 1
    assert result.identity_conflicts[0].logical_id == "DUP"
    assert result.summary.matched == 0


def test_snapshot_validation_rejects_dangling_parent_and_dependency():
    context = ComparisonContext(environment_id="a", scheduler=SchedulerType.AUTOSYS)
    builder = TopologySnapshotBuilder(context)
    builder.add_job(_job("job", "A", "a", parent_uid="missing-parent"))
    builder.add_dependency("missing-source", "job")

    report = validate_snapshot(builder.build())
    codes = {issue.code for issue in report.issues}

    assert report.is_valid is False
    assert "missing_parent" in codes
    assert "dangling_dependency_source" in codes


def test_snapshot_builder_does_not_infer_dependency_from_parent_relationship():
    context = ComparisonContext(
        environment_id="b", scheduler=SchedulerType.PROCESS_SCHEDULER
    )
    builder = TopologySnapshotBuilder(context)
    parent = _job("p", "Topology", "topology")
    child = _job("c", "Job", "job", parent_uid="p")
    builder.add_job(parent)
    builder.add_job(child)

    snapshot = builder.build()

    assert len(snapshot.roots) == 1
    assert snapshot.roots[0].children[0].job.job_uid == "c"
    assert snapshot.edges == []


def test_mismatch_keeps_field_provenance():
    left_context = ComparisonContext(environment_id="a", scheduler=SchedulerType.AUTOSYS)
    right_context = ComparisonContext(
        environment_id="b", scheduler=SchedulerType.PROCESS_SCHEDULER
    )
    left = _job("l", "SAME", "same")
    right = _job("r", "SAME", "same")
    left.autosys.jil.command = "left-command"
    right.autosys.jil.command = "right-command"
    right.comparison_evidence["command"] = FieldEvidence(
        source="process_scheduler_xml",
        locator="/Topology/Job[@id='B']/Command",
    )

    left_builder = TopologySnapshotBuilder(left_context)
    left_builder.add_job(left)
    right_builder = TopologySnapshotBuilder(right_context)
    right_builder.add_job(right)
    result = compare_snapshots(left_builder.build(), right_builder.build())

    mismatch = next(m for m in result.parameter_mismatches if m.parameter == "command")
    assert mismatch.right_evidence is not None
    assert mismatch.right_evidence.source == "process_scheduler_xml"


def test_strict_capability_mode_marks_undeclared_fields_unknown():
    context = ComparisonContext(environment_id="strict", scheduler=SchedulerType.AUTOSYS)
    builder = TopologySnapshotBuilder(
        context,
        capabilities=AdapterCapabilities(strict_parameter_support=True),
    )
    builder.add_job(_job("a", "A", "a"))
    snapshot = builder.build()

    report = validate_snapshot(snapshot)

    assert any(issue.code == "incomplete_parameter_support" for issue in report.issues)
    assert report.is_valid is False
