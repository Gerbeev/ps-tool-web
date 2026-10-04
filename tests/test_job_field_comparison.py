"""Tests for AutoSys-reference job comparison."""

from app.adapters.example_jobs import load_autosys_example_jobs, load_ps_example_jobs
from app.autosys_reference import AutoSysJobDefinition, AutoSysJobReference, AutoSysRunInstance
from app.models import JobStatus, SnapshotJob
from app.services.comparison import compare_contexts, compare_job_parameters
from tests.test_comparison import _default_left_context, _default_right_context


def test_example_yaml_loads_jil_and_autosys_reference():
    autosys = load_autosys_example_jobs()
    etl = autosys["RISK_DAILY_ETL"]
    assert etl["jil"]["start_times"] == "06:05"
    assert etl["run_instance"]["resolved_command"].endswith("2026-10-02")

    ps = load_ps_example_jobs()
    ps_etl = ps["RiskDaily.EtlJob"]
    assert ps_etl["autosys_reference"]["jil"]["start_times"] == "06:05"


def test_compare_reports_parameter_mismatches():
    left = SnapshotJob(
        job_uid="l1",
        scheduler_job_name="A",
        status=JobStatus.SUCCESS,
        autosys=AutoSysJobReference(
            jil=AutoSysJobDefinition(start_times="06:00", command="cmd_a", std_out_file="/logs/a.out"),
            run=AutoSysRunInstance(resolved_command="cmd_a"),
        ),
    )
    right = SnapshotJob(
        job_uid="r1",
        scheduler_job_name="B",
        status=JobStatus.SUCCESS,
        autosys=AutoSysJobReference(
            jil=AutoSysJobDefinition(start_times="06:05", command="cmd_b", std_out_file="/logs/b.out"),
            run=AutoSysRunInstance(resolved_command="cmd_b"),
        ),
    )
    mismatches = compare_job_parameters(left, right, "logical-a")
    params = {m.parameter for m in mismatches}
    assert "start_times" in params
    assert "command" in params
    assert "std_out_file" in params


def test_compare_mock_context_start_times_parity_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl = [
        m
        for m in result.parameter_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.parameter == "start_times"
    ]
    assert etl == []


def test_compare_mock_context_resolved_command_parity_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl = [
        m
        for m in result.parameter_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.parameter == "resolved_command"
    ]
    assert etl == []


def test_compare_mock_context_command_parameter_diff_for_etl():
    result = compare_contexts(_default_left_context(), _default_right_context())
    etl_cmd = [
        m
        for m in result.parameter_mismatches
        if m.logical_id == "RISK_DAILY_ETL|RiskDaily.EtlJob" and m.parameter == "command"
    ]
    assert len(etl_cmd) == 1
