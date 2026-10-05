"""AutoSys model rules verified against Broadcom job semantics."""

from app.adapters.example_jobs import load_autosys_example_jobs, load_ps_example_jobs
from app.autosys_reference import (
    AutoSysJobDefinition,
    normalize_parameter_value,
    validate_autosys_definition,
)


def test_sample_autosys_jobs_follow_core_schedule_and_type_rules():
    rows = load_autosys_example_jobs()
    checked: set[str] = set()
    for row in rows.values():
        jil = row.get("jil") or {}
        job_name = str(jil.get("job_name") or "")
        if not job_name or job_name in checked:
            continue
        checked.add(job_name)
        assert validate_autosys_definition(AutoSysJobDefinition.from_mapping(jil)) == []


def test_validation_rejects_mutually_exclusive_schedule_fields():
    definition = AutoSysJobDefinition(
        job_type="CMD",
        command="echo ok",
        date_conditions=1,
        days_of_week="all",
        run_calendar="business_days",
        start_times="06:00",
        start_mins="5",
    )
    issues = validate_autosys_definition(definition)
    assert "days_of_week and run_calendar are mutually exclusive" in issues
    assert "start_times and start_mins are mutually exclusive" in issues


def test_validation_requires_file_for_file_watcher():
    issues = validate_autosys_definition(AutoSysJobDefinition(job_type="FW"))
    assert "FW job has no watch_file" in issues


def test_must_times_require_active_date_schedule_and_start_time():
    issues = validate_autosys_definition(
        AutoSysJobDefinition(job_type="CMD", command="echo ok", must_start_times="06:05")
    )
    assert (
        "must_start_times/must_complete_times require date_conditions and start_times/start_mins"
        in issues
    )


def test_process_scheduler_autosys_projection_follows_core_autosys_rules():
    rows = load_ps_example_jobs()
    for row in rows.values():
        block = row.get("autosys_reference") or {}
        jil = block.get("jil") or {}
        if not jil:
            continue
        assert validate_autosys_definition(AutoSysJobDefinition.from_mapping(jil)) == []


def test_days_normalization_preserves_unknown_tokens_without_spurious_separator():
    assert normalize_parameter_value("days_of_week", "mo,custom_day") == "mo,custom_day"


def test_send_notification_preserves_failure_only_mode():
    assert normalize_parameter_value("send_notification", "f") == "2"
    assert normalize_parameter_value("send_notification", 2) == "2"
    assert normalize_parameter_value("send_notification", "y") == "1"
    assert normalize_parameter_value("send_notification", "n") == "0"
    assert normalize_parameter_value("send_notification", "f") != normalize_parameter_value(
        "send_notification", 0
    )


def test_auto_delete_zero_is_not_equivalent_to_omitted():
    assert normalize_parameter_value("auto_delete", 0) == "0"
    assert normalize_parameter_value("auto_delete", None) == ""


def test_notification_template_and_message_are_mutually_exclusive():
    issues = validate_autosys_definition(
        AutoSysJobDefinition(
            job_type="CMD",
            command="echo ok",
            notification_template="standard",
            notification_msg="legacy message",
        )
    )
    assert "notification_template and notification_msg are mutually exclusive" in issues
