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


def test_compare_populates_definition_field_mismatches():
    result = compare_contexts(_default_left_context(), _default_right_context())
    assert result.summary.mismatched_schedule >= 0
    assert len(result.field_mismatches) >= 1
    assert len(result.definition_mismatches) >= 1
