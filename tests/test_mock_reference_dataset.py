from collections import Counter
from pathlib import Path

from app.mock_reference import (
    build_reference_snapshot,
    reference_metadata,
    reference_scenario_metadata,
)
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import compare_snapshots


def _ctx(environment_id: str, scheduler: SchedulerType = SchedulerType.PROCESS_SCHEDULER) -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=scheduler,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def test_reference_fixture_is_environment_neutral_and_exactly_2500(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()
    meta = reference_metadata()
    path = Path(get_settings().mock_reference_path)

    assert meta["job_count"] == 2500
    assert meta["business_group_count"] == 25
    assert meta["environment_neutral"] is True
    assert meta["healthy_baseline"] is True
    assert meta["schema_version"] == 4
    assert sum(1 for _ in path.open(encoding="utf-8")) == 2501

    text = path.read_text(encoding="utf-8")
    for environment_literal in ('"U5"', '"P1"', '"PROD"'):
        assert environment_literal not in text


def test_reference_tree_has_expected_shape_and_job_types_without_migration_overlay(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "none")
    get_settings.cache_clear()
    snapshot = build_reference_snapshot(_ctx("ps-p1"))

    assert len(snapshot.flat_jobs) == 2500
    assert len(snapshot.roots) == 25
    assert all(len(root.children) == 9 for root in snapshot.roots)
    assert all(len(section.children) == 10 for root in snapshot.roots for section in root.children)
    assert len(snapshot.edges) == 2225

    job_types = {job.autosys.jil.job_type for job in snapshot.flat_jobs}
    semantic_types = {job.attributes.get("semantic_type") for job in snapshot.flat_jobs}
    assert job_types == {"BOX", "CMD", "FW"}
    assert {"box", "file_watch", "dotnet", "stored_procedure", "report", "publisher"}.issubset(
        semantic_types
    )
    assert all(job.status.value == "success" for job in snapshot.flat_jobs)
    assert all(job.autosys.jil.days_of_week for job in snapshot.flat_jobs)
    assert all(job.autosys.jil.start_times == "00:01" for job in snapshot.flat_jobs)
    assert all(job.process_scheduler is not None for job in snapshot.flat_jobs)
    assert all(job.autosys.jil.description for job in snapshot.flat_jobs)
    assert all(job.process_scheduler.description for job in snapshot.flat_jobs)
    assert all("/" not in job.job_uid for job in snapshot.flat_jobs)
    assert any("/" in (job.scheduler_native_id or "") for job in snapshot.flat_jobs)


def test_two_non_scenario_environment_projections_still_compare_as_exact_baseline(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "u1_to_u5_migration")
    get_settings.cache_clear()

    p1 = build_reference_snapshot(_ctx("ps-p1"))
    pa = build_reference_snapshot(_ctx("ps-pa"))
    result = compare_snapshots(p1, pa)

    assert result.summary.total_left == 2500
    assert result.summary.total_right == 2500
    assert result.summary.matched == 2500
    assert result.summary.left_only_count == 0
    assert result.summary.right_only_count == 0
    assert result.summary.mismatched_status == 0
    assert result.summary.mismatched_parameters == 0
    assert result.summary.mismatched_timing == 0
    assert result.summary.identity_conflicts == 0
    assert result.summary.not_comparable_parameters == 0

    pair = next(p for p in result.pairs if p.logical_id == "structured:4001|Admin_Archive")
    assert "_P1_" in pair.left.scheduler_job_name
    assert "_PA_" in pair.right.scheduler_job_name


def test_u1_autosys_is_healthy_reference_with_varied_realistic_runtime(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "u1_to_u5_migration")
    get_settings.cache_clear()

    u1 = build_reference_snapshot(_ctx("autosys-u1", SchedulerType.AUTOSYS))
    assert len(u1.flat_jobs) == 2500
    assert Counter(job.status for job in u1.flat_jobs) == {u1.flat_jobs[0].status.SUCCESS: 2500}
    assert u1.metadata["mock_scenario_role"] == "healthy_baseline"

    starts = [job.actual_start for job in u1.flat_jobs if job.actual_start]
    ends = [job.actual_end for job in u1.flat_jobs if job.actual_end]
    assert len(starts) == 2500
    assert len(ends) == 2500
    assert len(set(starts)) > 2000
    assert len(set(ends)) > 2000
    assert min(starts).strftime("%H:%M:%S") == "00:01:00"
    assert max(ends).hour >= 4
    assert all(job.exit_code == 0 for job in u1.flat_jobs)


def test_u5_process_scheduler_contains_deterministic_migration_defects(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "u1_to_u5_migration")
    get_settings.cache_clear()

    scenario = reference_scenario_metadata()
    u5 = build_reference_snapshot(_ctx("ps-u5"))

    assert scenario["issue_count"] == 114
    assert scenario["issue_counts"]["missing"] == 12
    assert len(u5.flat_jobs) == 2488
    assert u5.metadata["mock_scenario_role"] == "migration_target"
    assert u5.metadata["missing_job_count"] == 12

    statuses = Counter(job.status.value for job in u5.flat_jobs)
    assert statuses == {
        "success": 2430,
        "pending": 20,
        "failure": 18,
        "running": 10,
        "disabled": 6,
        "killed": 4,
    }
    issues = Counter(
        job.attributes.get("mock_migration_issue")
        for job in u5.flat_jobs
        if job.attributes.get("mock_migration_issue")
    )
    assert issues == {
        "failed": 18,
        "long_running": 10,
        "activated": 12,
        "waiting": 8,
        "on_ice": 6,
        "cancelled": 4,
        "late_success": 15,
        "slow_success": 12,
        "command_drift": 5,
        "machine_drift": 5,
        "schedule_drift": 3,
        "dependency_removed": 4,
    }
    assert sum(1 for job in u5.flat_jobs if job.status_raw == "Activated") == 12
    assert all(job.actual_end is None for job in u5.flat_jobs if job.status == job.status.RUNNING)


def test_u1_to_u5_migration_comparison_has_known_expected_diff(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "u1_to_u5_migration")
    get_settings.cache_clear()

    u1 = build_reference_snapshot(_ctx("autosys-u1", SchedulerType.AUTOSYS))
    u5 = build_reference_snapshot(_ctx("ps-u5"))
    result = compare_snapshots(u1, u5)

    assert result.summary.total_left == 2500
    assert result.summary.total_right == 2488
    assert result.summary.matched == 2488
    assert result.summary.left_only_count == 12
    assert result.summary.right_only_count == 0
    assert result.summary.mismatched_status == 58
    assert result.summary.mismatched_timing == 27
    assert result.summary.mismatched_execution_time == 12
    assert result.summary.identity_conflicts == 0
    assert result.summary.not_comparable_parameters == 0
    assert result.summary.parameter_mismatch_counts == {
        "dependencies": 16,
        "actual_start": 41,
        "actual_end": 63,
        "exit_code": 58,
        "machine": 5,
        "command": 5,
        "resolved_command": 5,
        "days_of_week": 3,
    }


def test_execution_time_is_derived_and_slow_success_has_expected_delta(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    monkeypatch.setenv("MOCK_SCENARIO", "u1_to_u5_migration")
    get_settings.cache_clear()

    u1 = build_reference_snapshot(_ctx("autosys-u1", SchedulerType.AUTOSYS))
    u5 = build_reference_snapshot(_ctx("ps-u5"))
    result = compare_snapshots(u1, u5)

    pair = next(
        pair
        for pair in result.execution_time_deltas
        if pair.logical_id == "structured:4001|Reports_Extract"
    )
    assert pair.left.exec_time == "00:01:18"
    assert pair.right.exec_time == "00:11:18"
    assert pair.execution_time_delta == "+00:10:00"
    assert pair.execution_time_delta_sec == 600
    assert pair.right.attributes["mock_migration_issue"] == "slow_success"
