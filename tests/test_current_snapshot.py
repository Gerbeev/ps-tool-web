"""Single-current-snapshot persistence and reuse contract."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
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
from app.services.current_snapshot import current_snapshot_store
from app.services.current_snapshot_flow import (
    SnapshotCaptureError,
    get_or_capture_current_pair,
)
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
        metadata={
            "validation_report": {
                "is_valid": True,
                "error_count": 0,
                "warning_count": 0,
                "issues": [],
            }
        },
    )


def test_current_pair_is_persisted_and_reused_without_refetch(monkeypatch):
    import app.services.current_snapshot_flow as flow

    left = _context("left", SchedulerType.AUTOSYS)
    right = _context("right", SchedulerType.PROCESS_SCHEDULER)
    calls: list[str] = []

    def fake_fetch(context, cache=None, *, force_refresh=False):
        calls.append(context.environment_id)
        return _snapshot(context, context.environment_id), context.environment_id

    monkeypatch.setattr(flow, "fetch_snapshot", fake_fetch)

    first = get_or_capture_current_pair(left, right)
    assert first.origin == "captured"
    assert calls == ["left", "right"]
    first_capture = first.manifest.capture_id

    second = get_or_capture_current_pair(left, right)
    assert second.origin == "current"
    assert second.manifest.capture_id == first_capture
    assert calls == ["left", "right"]
    assert get_job(second.left, "job-left") is not None

    refreshed = get_or_capture_current_pair(left, right, refresh=True)
    assert refreshed.origin == "captured"
    assert refreshed.manifest.capture_id != first_capture
    assert calls == ["left", "right", "left", "right"]

    files = list(current_snapshot_store.root.glob("*.snapshot.json.gz"))
    assert len(files) == 2


def test_failed_refresh_keeps_previous_current_snapshot(monkeypatch):
    import app.services.current_snapshot_flow as flow

    left = _context("left", SchedulerType.AUTOSYS)
    right = _context("right", SchedulerType.PROCESS_SCHEDULER)

    def success_fetch(context, cache=None, *, force_refresh=False):
        return _snapshot(context, context.environment_id), context.environment_id

    monkeypatch.setattr(flow, "fetch_snapshot", success_fetch)
    initial = get_or_capture_current_pair(left, right)
    capture_id = initial.manifest.capture_id

    def partial_failure(context, cache=None, *, force_refresh=False):
        if context.scheduler == SchedulerType.PROCESS_SCHEDULER:
            raise RuntimeError("process scheduler unavailable")
        return _snapshot(context, "new-left"), "left"

    monkeypatch.setattr(flow, "fetch_snapshot", partial_failure)
    with pytest.raises(SnapshotCaptureError):
        get_or_capture_current_pair(left, right, refresh=True)

    manifest = current_snapshot_store.load_manifest()
    assert manifest is not None
    assert manifest.capture_id == capture_id
    loaded = current_snapshot_store.load_pair(left, right)
    assert loaded is not None
    assert loaded[2].capture_id == capture_id


def test_compare_reuses_current_snapshot_and_browse_uses_matching_side():
    payload = {
        "left_env": "uat-rd",
        "left_scheduler": "autosys",
        "left_as_of": "2026-10-02",
        "left_topology": "",
        "right_env": "test-rd",
        "right_scheduler": "process_scheduler",
        "right_as_of": "2026-10-02",
        "right_topology": "RISK_ANALYTICS",
    }

    first = client.post("/api/compare", data=payload)
    assert first.status_code == 200
    assert "Captured new snapshot" in first.text

    second = client.post("/api/compare", data=payload)
    assert second.status_code == 200
    assert "Reused current snapshot" in second.text

    browse = client.post(
        "/api/browse/load",
        data={
            "environment_id": "uat-rd",
            "scheduler": "autosys",
            "as_of": "2026-10-02",
            "topology": "",
        },
    )
    assert browse.status_code == 200
    assert "Using current comparison snapshot" in browse.text
    assert "No scheduler fetch was performed" in browse.text

    refreshed = client.post("/api/compare", data={**payload, "refresh": "true"})
    assert refreshed.status_code == 200
    assert "Captured new snapshot" in refreshed.text


def test_changed_context_is_stale_and_captures_new_pair(monkeypatch):
    import app.services.current_snapshot_flow as flow

    left = _context("left", SchedulerType.AUTOSYS)
    right = _context("right", SchedulerType.PROCESS_SCHEDULER)
    calls: list[str] = []

    def fake_fetch(context, cache=None, *, force_refresh=False):
        calls.append(f"{context.environment_id}:{context.as_of.value}")
        return _snapshot(context, f"{context.environment_id}-{len(calls)}"), context.environment_id

    monkeypatch.setattr(flow, "fetch_snapshot", fake_fetch)
    first = get_or_capture_current_pair(left, right)

    changed_right = right.model_copy(deep=True)
    changed_right.as_of.value = "2026-10-03"
    assert current_snapshot_store.pair_status(left, changed_right) == "stale"

    second = get_or_capture_current_pair(left, changed_right)
    assert second.origin == "captured"
    assert second.manifest.capture_id != first.manifest.capture_id
    assert calls == [
        "left:2026-10-02",
        "right:2026-10-02",
        "left:2026-10-02",
        "right:2026-10-03",
    ]
