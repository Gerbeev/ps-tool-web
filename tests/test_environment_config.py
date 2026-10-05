"""Environment scheduler bindings from config."""

from app.config import EnvironmentEntry, endpoint_for_environment, host_for_environment, resolve_scheduler
from app.context_helpers import parse_browse_context
from app.models import SchedulerType


def test_resolve_scheduler_from_yaml_field():
    entry = EnvironmentEntry(id="x", display_name="X", scheduler="process_scheduler")
    assert resolve_scheduler(entry) == SchedulerType.PROCESS_SCHEDULER


def test_resolve_scheduler_from_connector_profile():
    entry = EnvironmentEntry(id="t", display_name="T", connector_profile="test_ps")
    assert resolve_scheduler(entry) == SchedulerType.PROCESS_SCHEDULER


def test_compare_side_form_loads_topology_for_ps():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/compare/side-form?side=right&right_env=test-rd")
    assert resp.status_code == 200
    assert 'name="right_topology"' in resp.text
    assert "RISK_ANALYTICS" in resp.text or "option" in resp.text


def test_host_for_environment_from_yaml():
    assert endpoint_for_environment("uat-rd") == "https://autosys-uat.emea.example/api"
    assert host_for_environment("uat-rd") == "https://autosys-uat.emea.example/api"


def test_browse_context_includes_host():
    ctx = parse_browse_context("test-rd", "process_scheduler", "2026-10-02", "risk_daily_topology")
    assert ctx.endpoint_url == "https://ps-scheduler-test.emea.example/api"
    assert ctx.host == ctx.endpoint_url


def test_compare_side_form_shows_business_date_for_autosys():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/compare/side-form?side=left&left_env=uat-rd")
    assert resp.status_code == 200
    assert 'name="left_as_of"' in resp.text
    assert 'type="date"' in resp.text


def test_environment_entry_accepts_legacy_host_key():
    entry = EnvironmentEntry.model_validate({
        "id": "legacy",
        "display_name": "Legacy",
        "host": "https://legacy.example/api",
    })
    assert entry.endpoint_url == "https://legacy.example/api"
