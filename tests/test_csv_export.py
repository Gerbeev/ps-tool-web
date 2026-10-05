"""CSV export schema tests."""

import csv
import io

from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import compare_contexts, fetch_snapshot
from app.services.export_csv import (
    TOPOLOGY_COLUMNS,
    export_comparison_csv,
    export_topology_csv,
    iter_comparison_csv_lines,
    iter_topology_csv_lines,
)


def test_topology_csv_headers_and_sort():
    ctx = ComparisonContext(
        environment_id="uat-rd",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )
    snap, _ = fetch_snapshot(ctx)
    text = export_topology_csv(snap)
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == TOPOLOGY_COLUMNS
    rows = list(reader)
    assert len(rows) == len(snap.flat_jobs)
    paths = [r["path"] for r in rows]
    assert paths == sorted(paths)


def test_comparison_csv_includes_diff_kinds():
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
    text = export_comparison_csv(result)
    reader = csv.DictReader(io.StringIO(text))
    kinds = {row["diff_kind"] for row in reader}
    assert "status_mismatch" in kinds
    assert "left_only" in kinds or "right_only" in kinds


def test_streaming_csv_matches_buffered_export():
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
    snapshot, _ = fetch_snapshot(left)
    result = compare_contexts(left, right)

    assert "".join(iter_topology_csv_lines(snapshot)) == export_topology_csv(snapshot)
    assert "".join(iter_comparison_csv_lines(result)) == export_comparison_csv(result)
