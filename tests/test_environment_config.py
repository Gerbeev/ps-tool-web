"""Environment scheduler bindings from config."""

from app.config import EnvironmentEntry, host_for_environment, resolve_scheduler
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
    assert host_for_environment("uat-rd") == "autosys-uat.emea.example"


def test_browse_context_includes_host():
    ctx = parse_browse_context("test-rd", "process_scheduler", "2026-10-02", "risk_daily_topology")
    assert ctx.host == "ps-scheduler-test.emea.example"


def test_compare_side_form_shows_business_date_for_autosys():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/compare/side-form?side=left&left_env=uat-rd")
    assert resp.status_code == 200
    assert 'name="left_as_of"' in resp.text
    assert 'type="date"' in resp.text
