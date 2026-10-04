"""Browse page smoke tests."""

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_browse_page_renders():
    resp = client.get("/browse")
    assert resp.status_code == 200
    assert "Browse environment" in resp.text
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
    assert "browse-job-row" in html
    assert 'hx-trigger="revealed once"' in html

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
