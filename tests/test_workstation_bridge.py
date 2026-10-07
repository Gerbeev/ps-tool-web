"""scheduler-bridge/v1 integration tests for isolated workstation connectors."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.adapters.bridge import BridgeConnectorError, BridgeProtocolError, ExternalBridgeAdapter
from app.config import EnvironmentEntry, get_settings
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_connector(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PS_TOOL_CONNECTOR_DIR", str(tmp_path))
    monkeypatch.setenv("PS_TOOL_CONNECTOR_PYTHON", sys.executable)
    monkeypatch.setenv("PS_TOOL_CONNECTOR_TIMEOUT_SEC", "5")
    monkeypatch.setenv("PS_TOOL_CONNECTOR_MAX_RESPONSE_MB", "4")
    get_settings.cache_clear()


def _context() -> ComparisonContext:
    return ComparisonContext(
        environment_id="autosys-u1",
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-07"),
    )


def _environment() -> EnvironmentEntry:
    return EnvironmentEntry(
        id="autosys-u1",
        environment="U1",
        scheduler="autosys",
        host="autosys.internal:9000",
    )


def test_bridge_translates_topology_without_importing_connector_module(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _write_connector(
        tmp_path / "autosys_connector.py",
        r'''
import json, sys
r = json.load(sys.stdin)
assert r["protocol"] == "scheduler-bridge"
assert r["version"] == 1
assert r["context"]["host"] == "autosys.internal:9000"
if r["operation"] == "fetch_topology":
    assert r["context"]["as_of_value"] == "2026-10-07"
ops = {
  "health": {"healthy": True, "message": "ok"},
  "list_roots": {"roots": ["ROOT_BOX"]},
  "fetch_job_detail": {"job": None},
  "fetch_topology": {
    "jobs": [
      {
        "job_uid": "root",
        "scheduler_job_name": "ROOT_BOX",
        "status": "success",
        "status_raw": "SU",
        "autosys_jil": {"job_type": "BOX"}
      },
      {
        "job_uid": "child",
        "scheduler_job_name": "JOB_A",
        "parent_uid": "root",
        "status": "success",
        "status_raw": "SU",
        "exit_code": 0,
        "autosys_jil": {"job_type": "CMD", "command": "run-a"},
        "autosys_run": {"resolved_command": "run-a", "exit_code": 0}
      }
    ],
    "dependencies": [
      {"from_uid": "root", "to_uid": "child", "kind": "finish_to_start"}
    ],
    "metadata": {"source": "test-connector"}
  }
}
response = {
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": r["request_id"],
  "ok": True,
  "data": ops[r["operation"]],
  "error": None,
  "capabilities": {
    "strict_parameter_support": False,
    "parameter_support": {}
  }
}
sys.stdout.write(json.dumps(response))
''',
    )

    adapter = ExternalBridgeAdapter(_environment(), SchedulerType.AUTOSYS)
    snapshot = adapter.fetch_topology(_context())

    assert len(snapshot.flat_jobs) == 2
    assert snapshot.roots[0].job.job_uid == "root"
    assert snapshot.roots[0].children[0].job.job_uid == "child"
    assert snapshot.flat_jobs[1].autosys.jil.command == "run-a"
    assert snapshot.edges[0].from_uid == "root"
    assert snapshot.metadata["source"] == "test-connector"
    assert snapshot.metadata["connector_protocol"] == "scheduler-bridge/v1"
    assert adapter.list_roots(_context()) == ["ROOT_BOX"]
    assert adapter.health_check("autosys-u1") is True


def test_bridge_rejects_request_id_mismatch(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _write_connector(
        tmp_path / "autosys_connector.py",
        r'''
import json, sys
r = json.load(sys.stdin)
sys.stdout.write(json.dumps({
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": "wrong",
  "ok": True,
  "data": {"healthy": True},
  "error": None
}))
''',
    )
    adapter = ExternalBridgeAdapter(_environment(), SchedulerType.AUTOSYS)
    with pytest.raises(BridgeProtocolError, match="request_id"):
        adapter.health_check("autosys-u1")


def test_bridge_surfaces_structured_connector_error(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _write_connector(
        tmp_path / "autosys_connector.py",
        r'''
import json, sys
r = json.load(sys.stdin)
sys.stdout.write(json.dumps({
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": r["request_id"],
  "ok": False,
  "data": {},
  "error": {
    "code": "source_timeout",
    "message": "source unavailable",
    "retryable": True,
    "details": {}
  }
}))
''',
    )
    adapter = ExternalBridgeAdapter(_environment(), SchedulerType.AUTOSYS)
    with pytest.raises(BridgeConnectorError, match="source_timeout"):
        adapter.health_check("autosys-u1")


def test_bridge_rejects_wrong_protocol_version(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _write_connector(
        tmp_path / "autosys_connector.py",
        r'''
import json, sys
r = json.load(sys.stdin)
sys.stdout.write(json.dumps({
  "protocol": "scheduler-bridge",
  "version": 2,
  "request_id": r["request_id"],
  "ok": True,
  "data": {"healthy": True},
  "error": None
}))
''',
    )
    adapter = ExternalBridgeAdapter(_environment(), SchedulerType.AUTOSYS)
    with pytest.raises(BridgeProtocolError, match="Invalid scheduler-bridge/v1 response"):
        adapter.health_check("autosys-u1")


def test_cached_snapshot_keeps_captured_capabilities(monkeypatch):
    import app.services.comparison as comparison
    from app.adapters.base import SchedulerAdapter
    from app.models import AdapterCapabilities, FieldSupport, JobStatus, SnapshotJob
    from app.services.snapshot_cache import SnapshotCache

    class FirstAdapter(SchedulerAdapter):
        scheduler_type = SchedulerType.AUTOSYS

        def capabilities(self):
            return AdapterCapabilities(
                strict_parameter_support=True,
                parameter_support={"command": FieldSupport.UNSUPPORTED},
            )

        def health_check(self, environment_id):
            return True

        def fetch_topology(self, context):
            from app.adapters.builder import TopologySnapshotBuilder

            builder = TopologySnapshotBuilder(context)
            builder.add_job(
                SnapshotJob(job_uid="a", scheduler_job_name="A", status=JobStatus.SUCCESS)
            )
            return builder.build()

        def fetch_job_detail(self, context, job_uid):
            return None

    class SecondAdapter(FirstAdapter):
        def capabilities(self):
            raise AssertionError("cache hit must not replace captured capabilities")

        def fetch_topology(self, context):
            raise AssertionError("cache hit must not fetch topology")

    adapters = iter([FirstAdapter(), SecondAdapter()])
    monkeypatch.setattr(comparison, "get_adapter", lambda scheduler, environment_id: next(adapters))
    cache = SnapshotCache(ttl_sec=60)
    context = _context()

    first, _ = comparison.fetch_snapshot(context, cache)
    second, _ = comparison.fetch_snapshot(context, cache)

    assert first is second
    assert second.capabilities.strict_parameter_support is True
    assert second.capabilities.parameter_support["command"] == FieldSupport.UNSUPPORTED
