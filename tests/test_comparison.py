"""Tests for comparison and identity matching."""

from app.models import (
    AsOf,
    AsOfKind,
    ComparisonContext,
    JobStatus,
    SchedulerType,
)
from app.services.comparison import compare_contexts


def test_compare_finds_status_mismatch_and_orphans():
    left = ComparisonContext(
        environment_id="uat-rd",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )
    right = ComparisonContext(
        environment_id="test-rd",
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )
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
