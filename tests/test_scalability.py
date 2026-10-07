"""Scalability quick wins: table paging, lazy tree index, large mock compare."""

import time

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import (
    AsOf,
    AsOfKind,
    ComparisonContext,
    JobNode,
    JobStatus,
    SnapshotJob,
    SchedulerType,
    TopologySnapshot,
)
from app.services.comparison import compare_contexts
from app.services.table_rows import iter_table_rows, page_table_rows
from app.services.snapshot_generation import generate_snapshot, list_process_scheduler_topologies
from app.services.topology_index import (
    build_children_index,
    ensure_topology_indexes,
    get_child_nodes,
    get_job,
)
import app.services.comparison as cmp


client = TestClient(app)


def test_table_page_default_returns_all_rows():
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
    rows = iter_table_rows(result, filter_name="all")
    page, total = page_table_rows(rows, offset=0, limit=0)
    assert total == len(rows)
    assert len(page) == total
    assert total >= result.summary.matched


def test_compare_table_endpoint_all_by_default():
    left_record = generate_snapshot("autosys-u1").record
    topology = list_process_scheduler_topologies("ps-u5")[0]
    right_record = generate_snapshot("ps-u5", topology_id=topology).record
    resp = client.post(
        "/api/compare",
        data={
            "left_env": left_record.environment_id,
            "left_snapshot_id": left_record.snapshot_id,
            "right_env": right_record.environment_id,
            "right_snapshot_id": right_record.snapshot_id,
        },
    )
    assert resp.status_code == 200
    html = resp.text
    assert "compare-table-panel" in html
    assert 'limit=0' in html or "filter=all" in html
    assert "details[target.open]" not in html
    assert 'hx-trigger="revealed once"' in html
    # Trees should not be fully inlined anymore
    assert "RISK_DAILY_ETL" not in html or "Loading table" in html

    start = html.find('id="session-id"')
    assert start != -1
    # Extract session id from hidden input
    import re

    m = re.search(r'id="session-id"[^>]*value="([^"]+)"', html)
    assert m
    sid = m.group(1)
    table = client.get(f"/api/compare/table?session_id={sid}&filter=all&limit=0")
    assert table.status_code == 200
    assert "compare-table" in table.text
    assert "Left Exec Time" in table.text
    assert "Right Exec Time" in table.text
    assert "Exec Δ (R−L)" in table.text

    bad_side = client.get(f"/api/tree/not-a-side?session_id={sid}")
    assert bad_side.status_code == 404


def test_children_index_o1_lookup():
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
    from app.services.comparison import fetch_snapshot

    snap, _ = fetch_snapshot(left)
    index = snap.metadata.get("children_index")
    assert index is not None
    box_uid = snap.roots[0].job.job_uid
    assert len(index.get(box_uid, [])) >= 1
    children = get_child_nodes(snap, box_uid)
    assert children and children[0].job.parent_uid == box_uid
    assert get_job(snap, children[0].job.job_uid) is children[0].job


def test_large_compare_under_one_second(monkeypatch):
    get_settings.cache_clear()

    def snap(n, sched):
        ctx = ComparisonContext(
            environment_id="uat-rd",
            scheduler=sched,
            as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
        )
        jobs = [
            SnapshotJob(
                job_uid=f"j{i}",
                scheduler_job_name=f"RISK_JOB_{i:04d}",
                status=JobStatus.SUCCESS,
                status_raw="OK",
                path_labels=["RISK_DAILY_BOX", f"RISK_JOB_{i:04d}"],
            )
            for i in range(n)
        ]
        roots = [JobNode(job=jobs[0], children=[JobNode(job=j) for j in jobs[1:]])]
        ts = TopologySnapshot(context=ctx, roots=roots, flat_jobs=jobs)
        ensure_topology_indexes(ts)
        return ts

    n = 3000
    left = snap(n, SchedulerType.AUTOSYS)
    right = snap(n, SchedulerType.PROCESS_SCHEDULER)

    def fake_fetch(ctx, cache=None):
        return (left, "k1") if ctx.scheduler == SchedulerType.AUTOSYS else (right, "k2")

    monkeypatch.setattr(cmp, "fetch_snapshot", fake_fetch)
    t0 = time.perf_counter()
    result = compare_contexts(left.context, right.context)
    elapsed = time.perf_counter() - t0
    assert result.summary.total_left == n
    assert elapsed < 1.0


def test_search_requires_session_id():
    empty = client.get("/api/search?q=RISK&format=json")
    assert empty.status_code == 200
    assert empty.json() == []

    left_record = generate_snapshot("autosys-u1").record
    topology = list_process_scheduler_topologies("ps-u5")[0]
    right_record = generate_snapshot("ps-u5", topology_id=topology).record
    resp = client.post(
        "/api/compare",
        data={
            "left_env": left_record.environment_id,
            "left_snapshot_id": left_record.snapshot_id,
            "right_env": right_record.environment_id,
            "right_snapshot_id": right_record.snapshot_id,
        },
    )
    import re

    m = re.search(r'id="session-id"[^>]*value="([^"]+)"', resp.text)
    sid = m.group(1)
    hits = client.get(f"/api/search?q=RISK&format=json&session_id={sid}")
    assert hits.status_code == 200
    assert isinstance(hits.json(), list)
