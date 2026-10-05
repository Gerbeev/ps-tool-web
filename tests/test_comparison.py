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
