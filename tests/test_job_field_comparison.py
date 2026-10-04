"""Tests for extended job definition and run-field comparison."""

from app.adapters.example_jobs import load_autosys_example_jobs, load_ps_example_jobs, schedule_from_row
from app.models import ComparedField, JobSchedule, JobStatus, NormalizedJob
from app.services.comparison import _compare_job_fields, compare_contexts
from tests.test_comparison import _default_left_context, _default_right_context


def test_example_yaml_loads_schedule_and_resolved_command():
    autosys = load_autosys_example_jobs()
    etl = autosys["RISK_DAILY_ETL"]
    sched = schedule_from_row(etl)
    assert sched is not None
    assert sched.expression == "5 6 * * *"
    assert etl["resolved_command"].endswith("2026-10-02")

    ps = load_ps_example_jobs()
    ps_etl = ps["RiskDaily.EtlJob"]
    assert ps_etl["schedule"]["expression"] == "5 6 * * *"


def test_compare_reports_schedule_and_command_mismatches():
    left = NormalizedJob(
        job_uid="l1",
        scheduler_job_name="A",
        job_type="cmd",
        status=JobStatus.SUCCESS,
        schedule=JobSchedule(expression="0 6 * * *", calendar="every_day"),
        command="cmd_a",
        log_paths=["/logs/a.log"],
    )
    right = NormalizedJob(
        job_uid="r1",
        scheduler_job_name="B",
        job_type="cmd",
        status=JobStatus.SUCCESS,
        schedule=JobSchedule(expression="5 6 * * *", calendar="every_day"),
        command="cmd_b",
        log_paths=["/logs/b.log"],
    )
    mismatches = _compare_job_fields(left, right, "logical-a", 60.0)
    fields = {m.field for m in mismatches}
    assert ComparedField.SCHEDULE in fields
    assert ComparedField.COMMAND in fields
    assert ComparedField.LOG_PATHS in fields


def test_compare_mock_context_schedule_parity_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl_schedule = [
        m
        for m in result.field_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.field == ComparedField.SCHEDULE
    ]
    assert etl_schedule == []


def test_compare_mock_context_resolved_command_parity_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl_resolved = [
        m
        for m in result.field_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.field == ComparedField.RESOLVED_COMMAND
    ]
    assert etl_resolved == []


def test_compare_mock_context_command_syntax_diff_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl_cmd = [
        m
        for m in result.field_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.field == ComparedField.COMMAND
    ]
    assert len(etl_cmd) == 1
