"""Root box scoping in mock adapters."""

from app.adapters.mock_data import apply_root_scope, build_autosys_snapshot
from app.models import AsOf, AsOfKind, ComparisonContext, ContextFilters, SchedulerType


def test_autosys_root_box_scopes_subtree():
    ctx = ComparisonContext(
        environment_id="uat-rd",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )
    full = build_autosys_snapshot(ctx)
    scoped = apply_root_scope(full, "RISK_DAILY_ETL")
    assert len(scoped.flat_jobs) == 1
    assert scoped.flat_jobs[0].scheduler_job_name == "RISK_DAILY_ETL"

    ctx_scoped = ComparisonContext(
        environment_id="uat-rd",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
        filters=ContextFilters(root_box="RISK_DAILY_BOX"),
    )
    via_filter = build_autosys_snapshot(ctx_scoped)
    assert len(via_filter.flat_jobs) == len(full.flat_jobs)
