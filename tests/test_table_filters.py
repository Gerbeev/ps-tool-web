"""Table filter semantics and topology index consistency."""

from app.adapters.mock_data import apply_root_scope, build_autosys_snapshot
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import compare_contexts
from app.services.table_rows import iter_table_rows
from app.services.topology_index import ensure_topology_indexes, get_child_nodes


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


def test_matched_filter_lists_all_pairs():
    result = compare_contexts(_default_left_context(), _default_right_context())
    matched_rows = iter_table_rows(result, filter_name="matched")
    assert len(matched_rows) == result.summary.matched
    assert all(row.kind == "pair" for row in matched_rows)


def test_apply_root_scope_rebuilds_stale_child_index():
    ctx = _default_left_context()
    full = build_autosys_snapshot(ctx)
    ensure_topology_indexes(full)
    scoped = apply_root_scope(full, "RISK_DAILY_BOX")
    ensure_topology_indexes(scoped)
    box_uid = scoped.flat_jobs[0].job_uid
    children = get_child_nodes(scoped, box_uid)
    assert len(children) == len(scoped.roots[0].children)
    assert {c.job.job_uid for c in children} == {c.job.job_uid for c in scoped.roots[0].children}
