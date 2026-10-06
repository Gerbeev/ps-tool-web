"""Browse page smoke tests."""

import re

from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus

client = TestClient(app)


def test_browse_page_renders():
    resp = client.get("/browse")
    assert resp.status_code == 200
    assert "Select environment" in resp.text
    assert 'id="browse-env-toggle"' in resp.text
    assert 'id="browse-env-panel"' in resp.text
    assert 'hx-post="/api/browse/load"' in resp.text


def test_browse_load_returns_full_width_tree_and_lazy_nodes():
    resp = client.post(
        "/api/browse/load",
        data={
            "environment_id": "uat-rd",
            "scheduler": "autosys",
            "as_of": "2026-10-02",
            "topology": "",
        },
    )
    assert resp.status_code == 200
    html = resp.text
    assert "browse-workspace" in html
    assert "browse-tree-header" in html
    assert "browse-filters" in html
    assert 'id="browse-filter-search"' in html
    assert 'id="browse-filter-status"' in html
    assert 'browse-status-picker-trigger' in html
    assert 'browse-status-checkbox' in html
    assert 'data-inactive-statuses="' in html
    assert 'data-status-preset="inactive"' in html
    for status in JobStatus:
        assert f'value="{status.value}"' in html
    assert "browse-job-row" in html
    assert 'data-job-name="' in html
    assert 'data-status="' in html
    assert "/static/js/browse-filters.js" in html
    assert "browse-tree-expand-btn" in html
    assert 'hx-trigger="revealed once"' in html
    assert '<details class="browse-tree-branch" open>' in html

    m = re.search(r'id="session-id"[^>]*value="([^"]+)"', html)
    assert m
    sid = m.group(1)
    tree = client.get(f"/api/browse/tree?session_id={sid}")
    assert tree.status_code == 200
    assert "browse-job-row" in tree.text

    job_btn = re.search(r'hx-get="/api/browse/job/([^"?]+)', html)
    assert job_btn
    uid = job_btn.group(1)
    detail = client.get(f"/api/browse/job/{uid}?session_id={sid}")
    assert detail.status_code == 200
    assert "job-detail-card" in detail.text
    assert "JIL definition" in detail.text


def _extract_session_id(html: str) -> str:
    match = re.search(r'id="session-id"[^>]*value="([^"]+)"', html)
    assert match
    return match.group(1)


def _extract_first_job_uid(html: str) -> str:
    match = re.search(r'hx-get="/api/browse/job/([^"?]+)', html)
    assert match
    return match.group(1)


def test_reference_mock_job_details_work_for_autosys_and_process_scheduler(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()

    cases = [
        ("autosys-u1", "autosys", "", "JIL definition"),
        ("ps-u5", "process_scheduler", "DataPlatform_REFERENCE", "Process Scheduler source detail"),
    ]

    for environment_id, scheduler, topology, source_section in cases:
        loaded = client.post(
            "/api/browse/load",
            data={
                "environment_id": environment_id,
                "scheduler": scheduler,
                "as_of": "2026-10-02",
                "topology": topology,
            },
        )
        assert loaded.status_code == 200
        sid = _extract_session_id(loaded.text)

        root_uid = _extract_first_job_uid(loaded.text)
        assert "/" not in root_uid
        root_detail = client.get(f"/api/browse/job/{root_uid}?session_id={sid}")
        assert root_detail.status_code == 200
        assert "Coordinates the complete batch workflow" in root_detail.text
        assert source_section in root_detail.text

        root_children = client.get(
            "/api/browse/tree",
            params={"session_id": sid, "parent_uid": root_uid, "depth": 1},
        )
        assert root_children.status_code == 200
        box_uid = _extract_first_job_uid(root_children.text)
        assert "/" not in box_uid
        box_detail = client.get(f"/api/browse/job/{box_uid}?session_id={sid}")
        assert box_detail.status_code == 200
        assert "Groups and controls" in box_detail.text

        box_children = client.get(
            "/api/browse/tree",
            params={"session_id": sid, "parent_uid": box_uid, "depth": 2},
        )
        assert box_children.status_code == 200
        leaf_uid = _extract_first_job_uid(box_children.text)
        assert "/" not in leaf_uid
        leaf_detail = client.get(f"/api/browse/job/{leaf_uid}?session_id={sid}")
        assert leaf_detail.status_code == 200
        assert "Description" in leaf_detail.text
        assert "Exec Time" in leaf_detail.text
        assert "business application 4001" in leaf_detail.text
        assert source_section in leaf_detail.text
