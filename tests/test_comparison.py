"""Tests for comparison and identity matching."""

from app.models import (
    AsOf,
    AsOfKind,
    ComparisonContext,
    JobStatus,
    SchedulerType,
)
from app.services.comparison import compare_contexts


def _default_left_context() -> ComparisonContext:
    return ComparisonContext(
        environment_id="uat-rd",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def _default_right_context() -> ComparisonContext:
    return ComparisonContext(
        environment_id="test-rd",
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def test_compare_finds_status_mismatch_and_orphans():
    left = _default_left_context()
    right = _default_right_context()
    result = compare_contexts(left, right)
    assert result.summary.total_left == 6
    assert result.summary.total_right == 7
    assert result.summary.mismatched_status >= 1
    assert result.summary.left_only_count >= 1
    assert result.summary.right_only_count >= 1
    recon_pair = next(
        p for p in result.pairs if p.left and p.left.scheduler_job_name == "RISK_DAILY_RECON"
    )
    assert recon_pair.left.status == JobStatus.FAILURE
    assert recon_pair.right.status == JobStatus.SUCCESS


def test_compare_populates_parameter_mismatches():
    result = compare_contexts(_default_left_context(), _default_right_context())
    assert result.summary.mismatched_parameters >= 1
    assert len(result.parameter_mismatches) >= 1
    assert len(result.definition_mismatches) >= 1


def test_regex_identity_rule_pairs_with_target_scheduler_name():
    from app.models import SnapshotJob
    from app.services.identity import logical_id_for_job

    autosys_job = SnapshotJob(
        job_uid="a-regex",
        scheduler_job_name="RISK_FOO_AUTOSYS",
        status=JobStatus.SUCCESS,
    )
    ps_job = SnapshotJob(
        job_uid="p-regex",
        scheduler_job_name="RiskDaily.FOO",
        status=JobStatus.SUCCESS,
    )

    left_id, _ = logical_id_for_job(autosys_job, SchedulerType.AUTOSYS)
    right_id, _ = logical_id_for_job(ps_job, SchedulerType.PROCESS_SCHEDULER)
    assert left_id == right_id == "RiskDaily.FOO"


def test_compare_matches_same_business_job_when_only_environment_token_differs():
    from app.models import SnapshotJob, TopologySnapshot
    from app.services.comparison import compare_snapshots

    left_context = ComparisonContext(
        environment_id="left-env",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.LATEST, value=""),
    )
    right_context = ComparisonContext(
        environment_id="right-env",
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.LATEST, value=""),
    )
    left_job = SnapshotJob(
        job_uid="left-job",
        scheduler_job_name="STD_PREFIX_4321_UA_Load_Data",
        status=JobStatus.SUCCESS,
    )
    right_job = SnapshotJob(
        job_uid="right-job",
        scheduler_job_name="STD_PREFIX_4321_PROD_Load_Data",
        status=JobStatus.SUCCESS,
    )

    result = compare_snapshots(
        TopologySnapshot(context=left_context, flat_jobs=[left_job]),
        TopologySnapshot(context=right_context, flat_jobs=[right_job]),
    )

    assert result.summary.matched == 1
    assert result.summary.left_only_count == 0
    assert result.summary.right_only_count == 0
    assert result.pairs[0].logical_id == "structured:4321|Load_Data"


def test_compare_does_not_match_when_business_code_changes_between_environments():
    from app.models import SnapshotJob, TopologySnapshot
    from app.services.comparison import compare_snapshots

    left_context = ComparisonContext(
        environment_id="left-env",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.LATEST, value=""),
    )
    right_context = ComparisonContext(
        environment_id="right-env",
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.LATEST, value=""),
    )
    left_job = SnapshotJob(
        job_uid="left-job",
        scheduler_job_name="STD_PREFIX_4321_UA_Load_Data",
        status=JobStatus.SUCCESS,
    )
    right_job = SnapshotJob(
        job_uid="right-job",
        scheduler_job_name="STD_PREFIX_9876_PROD_Load_Data",
        status=JobStatus.SUCCESS,
    )

    result = compare_snapshots(
        TopologySnapshot(context=left_context, flat_jobs=[left_job]),
        TopologySnapshot(context=right_context, flat_jobs=[right_job]),
    )

    assert result.summary.matched == 0
    assert result.summary.left_only_count == 1
    assert result.summary.right_only_count == 1
