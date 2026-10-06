"""Scheduler-specific environment bindings from config."""

from app.config import (
    EnvironmentEntry,
    endpoint_for_environment,
    host_for_environment,
    load_scheduler_environments,
    resolve_scheduler,
)
from app.context_helpers import parse_browse_context
from app.models import SchedulerType


def test_resolve_scheduler_from_yaml_field():
    entry = EnvironmentEntry(id="x", display_name="X", scheduler="process_scheduler")
    assert resolve_scheduler(entry) == SchedulerType.PROCESS_SCHEDULER


def test_resolve_scheduler_from_connector_profile():
    entry = EnvironmentEntry(id="t", display_name="T", connector_profile="test_ps")
    assert resolve_scheduler(entry) == SchedulerType.PROCESS_SCHEDULER


def test_process_scheduler_catalog_matches_reference_capture():
    envs = load_scheduler_environments("process_scheduler")
    assert len(envs) == 14
    assert [e.environment for e in envs] == [
        "BB", "DV", "DZ", "P1", "PA", "PB", "PY", "U1", "U5", "UW", "UX", "UZ", "XY", "XZ"
    ]
    u5 = next(e for e in envs if e.environment == "U5")
    assert u5.host == "npb14716831u5p1.ubscloud-prod.msad.ubs.net:9001"
    assert u5.description == "UAT"
    assert u5.transport == "WCF"


def test_compare_side_form_loads_topology_for_ps():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/compare/side-form?side=right&right_env=ps-u5")
    assert resp.status_code == 200
    assert 'name="right_topology"' in resp.text
    assert "option" in resp.text
    assert "Process Scheduler" in resp.text


def test_host_for_environment_from_scheduler_specific_yaml():
    expected = "npb14716831u5p1.ubscloud-prod.msad.ubs.net:9001"
    assert endpoint_for_environment("ps-u5") == expected
    assert host_for_environment("ps-u5") == expected


def test_browse_context_includes_process_scheduler_host():
    ctx = parse_browse_context("ps-u5", "process_scheduler", "2026-10-02", "risk_daily_topology")
    assert ctx.endpoint_url == "npb14716831u5p1.ubscloud-prod.msad.ubs.net:9001"
    assert ctx.host == ctx.endpoint_url


def test_autosys_reference_environment_is_separate():
    envs = load_scheduler_environments("autosys")
    assert len(envs) == 1
    assert envs[0].id == "autosys-u1"
    assert envs[0].environment == "U1"
    assert envs[0].host == "autosys.ldn.swissbank.com"
    assert resolve_scheduler(envs[0]) == SchedulerType.AUTOSYS


def test_compare_side_form_shows_business_date_for_autosys():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/compare/side-form?side=left&left_env=autosys-u1")
    assert resp.status_code == 200
    assert 'name="left_as_of"' in resp.text
    assert 'type="date"' in resp.text
    assert "AutoSys" in resp.text


def test_environment_entry_accepts_legacy_host_key():
    entry = EnvironmentEntry.model_validate({
        "id": "legacy",
        "display_name": "Legacy",
        "host": "https://legacy.example/api",
    })
    assert entry.endpoint_url == "https://legacy.example/api"


def test_settings_has_separate_scheduler_tabs_and_hosts():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'data-settings-tab="process_scheduler"' in resp.text
    assert 'data-settings-tab="autosys"' in resp.text
    assert "npb14716831u5p1.ubscloud-prod.msad.ubs.net:9001" in resp.text
    assert "autosys.ldn.swissbank.com" in resp.text
