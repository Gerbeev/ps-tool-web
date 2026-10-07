"""Immutable snapshot catalog and source-isolation contract."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AsOf,
    AsOfKind,
    ComparisonContext,
    JobNode,
    JobStatus,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)
from app.search.sqlite_fts import search_index
from app.services.snapshot_catalog import snapshot_catalog
from app.services.snapshot_generation import generate_snapshot, list_process_scheduler_topologies
from app.services.topology_index import get_job

client = TestClient(app)


def _context(environment: str, scheduler: SchedulerType) -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment,
        scheduler=scheduler,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def _snapshot(context: ComparisonContext, suffix: str) -> TopologySnapshot:
    job = SnapshotJob(
        job_uid=f"job-{suffix}",
        scheduler_job_name=f"STD_PREFIX_4321_U5_JOB_{suffix}",
        status=JobStatus.SUCCESS,
        status_raw="SUCCESS",
    )
    return TopologySnapshot(
        context=context,
        fetched_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        roots=[JobNode(job=job)],
        flat_jobs=[job],
    )


def test_catalog_persists_multiple_immutable_snapshots():
    first = _snapshot(_context("x", SchedulerType.AUTOSYS), "one")
    second = _snapshot(_context("x", SchedulerType.AUTOSYS), "two")

    first_record = snapshot_catalog.save(first)
    second_record = snapshot_catalog.save(second)

    records = snapshot_catalog.list(environment_id="x")
    assert {item.snapshot_id for item in records} == {first_record.snapshot_id, second_record.snapshot_id}
    assert len(list(snapshot_catalog.root.glob("*.snapshot.json.gz"))) == 2

    loaded = snapshot_catalog.load(first_record.snapshot_id)
    assert loaded is not None
    restored, restored_record = loaded
    assert restored_record.snapshot_id == first_record.snapshot_id
    assert get_job(restored, "job-one") is not None


def test_snapshots_page_is_default_ingress_and_generates_both_scheduler_types():
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/snapshots"

    page = client.get("/snapshots")
    assert page.status_code == 200
    assert "Generate snapshot" in page.text
    assert "only workspace that reads AutoSys or Process Scheduler" in page.text

    autosys = client.post("/api/snapshots/generate", data={"environment_id": "autosys-u1"})
    assert autosys.status_code == 200
    assert "Snapshot generated" in autosys.text

    source = client.get("/api/snapshots/source-form", params={"environment_id": "ps-u5"})
    assert source.status_code == 200
    assert 'name="topology_id"' in source.text
    topology = list_process_scheduler_topologies("ps-u5")[0]
    ps = client.post(
        "/api/snapshots/generate",
        data={"environment_id": "ps-u5", "topology_id": topology},
    )
    assert ps.status_code == 200
    assert "Snapshot generated" in ps.text

    records = snapshot_catalog.list()
    assert len(records) == 2
    autosys_record = next(item for item in records if item.scheduler == SchedulerType.AUTOSYS)
    ps_record = next(item for item in records if item.scheduler == SchedulerType.PROCESS_SCHEDULER)
    assert autosys_record.business_date == (date.today() - timedelta(days=1)).isoformat()
    assert ps_record.topology_id == topology
    assert re.fullmatch(r"U1-AutoSys_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", autosys_record.label)
    assert ps_record.label == f"U5-ProcessScheduler_{date.today().isoformat()}_{topology}"
    assert "U1-AutoSys" in page.text
    assert "U5-PS" in page.text


def test_browse_and_compare_use_catalog_only_after_generation(monkeypatch):
    autosys = generate_snapshot("autosys-u1").record
    topology = list_process_scheduler_topologies("ps-u5")[0]
    process_scheduler = generate_snapshot("ps-u5", topology_id=topology).record

    def forbidden_adapter_access(*args, **kwargs):
        raise AssertionError("Browse/Compare must never access adapters or bridge")

    monkeypatch.setattr("app.adapters.factory.get_adapter", forbidden_adapter_access)

    browse = client.post(
        "/api/browse/load",
        data={"environment_id": autosys.environment_id, "snapshot_id": autosys.snapshot_id},
    )
    assert browse.status_code == 200
    assert "No scheduler fetch was performed" in browse.text
    assert "browse-workspace" in browse.text

    compare = client.post(
        "/api/compare",
        data={
            "left_env": autosys.environment_id,
            "left_snapshot_id": autosys.snapshot_id,
            "right_env": process_scheduler.environment_id,
            "right_snapshot_id": process_scheduler.snapshot_id,
        },
    )
    assert compare.status_code == 200
    assert "Compared generated snapshots" in compare.text
    assert "No scheduler fetch was performed" in compare.text
    assert "compare-table-panel" in compare.text


def test_non_ingress_routes_do_not_import_live_source_access():
    import inspect
    import app.routes.browse as browse_route
    import app.routes.compare as compare_route
    import app.routes.export as export_route

    banned = ("get_adapter", "fetch_snapshot", "ExternalBridgeAdapter", "list_roots")
    for module in (browse_route, compare_route, export_route):
        source = inspect.getsource(module)
        for token in banned:
            assert token not in source, f"{module.__name__} must not reference {token}"


def test_snapshot_can_be_deleted_from_catalog_and_ui():
    record = generate_snapshot("autosys-u1").record
    payload = snapshot_catalog.root / record.filename
    assert payload.exists()
    loaded = snapshot_catalog.load(record.snapshot_id)
    assert loaded is not None
    snapshot, _ = loaded
    search_index.rebuild(snapshot, "left")
    query = snapshot.flat_jobs[0].scheduler_job_name.split("_")[0]
    assert search_index.search(query, snapshot_ids=[record.snapshot_id])

    response = client.post("/api/snapshots/delete", data={"snapshot_id": record.snapshot_id})
    assert response.status_code == 200
    assert "Snapshot deleted" in response.text
    assert snapshot_catalog.get_record(record.snapshot_id) is None
    assert not payload.exists()
    assert search_index.search(query, snapshot_ids=[record.snapshot_id]) == []


def test_autosys_business_date_is_previous_calendar_day():
    from app.services.snapshot_generation import autosys_business_date

    assert autosys_business_date(date(2026, 10, 7)) == "2026-10-06"
    assert autosys_business_date(date(2026, 3, 1)) == "2026-02-28"
