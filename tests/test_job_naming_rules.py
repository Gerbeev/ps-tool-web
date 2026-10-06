from pathlib import Path

import yaml


def _rules() -> dict:
    path = Path(__file__).resolve().parents[1] / "config" / "job_naming_rules.yaml"
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_job_naming_rule_structure_is_generic_and_machine_readable():
    rules = _rules()

    assert rules["structure"]["order"] == [
        "common_prefix",
        "business_code",
        "environment",
        "job_specific_name",
    ]
    assert rules["structure"]["business_code"]["format"] == "digits"
    assert rules["structure"]["business_code"]["length"] == 4
    assert rules["structure"]["environment"]["accepted_lengths"] == [2, 4]
    assert rules["structure"]["common_prefix"]["literal"] is None


def test_cross_environment_identity_excludes_environment_but_keeps_business_code():
    identity = _rules()["cross_environment_identity"]

    assert identity["include"] == ["business_code", "job_specific_name"]
    assert "environment" in identity["exclude"]
    assert "common_prefix" in identity["exclude"]
    assert identity["require_same_business_code"] is True


def test_rules_do_not_embed_captured_business_or_environment_examples():
    text = (Path(__file__).resolve().parents[1] / "config" / "job_naming_rules.yaml").read_text(
        encoding="utf-8"
    )

    for captured_literal in ("1109", "1251", "U5", "P1", "PROD"):
        assert captured_literal not in text


def test_structured_identity_ignores_only_environment_token():
    from app.models import JobStatus, SchedulerType, SnapshotJob
    from app.services.identity import logical_id_for_job, parse_structured_job_name

    left = SnapshotJob(
        job_uid="left",
        scheduler_job_name="STD_PREFIX_4321_UA_Load_Data",
        status=JobStatus.SUCCESS,
    )
    right = SnapshotJob(
        job_uid="right",
        scheduler_job_name="STD_PREFIX_4321_PROD_Load_Data",
        status=JobStatus.SUCCESS,
    )

    parsed_left = parse_structured_job_name(left.scheduler_job_name)
    parsed_right = parse_structured_job_name(right.scheduler_job_name)
    assert parsed_left is not None
    assert parsed_right is not None
    assert parsed_left.business_code == parsed_right.business_code == "4321"
    assert parsed_left.environment == "UA"
    assert parsed_right.environment == "PROD"

    left_id, _ = logical_id_for_job(left, SchedulerType.AUTOSYS)
    right_id, _ = logical_id_for_job(right, SchedulerType.PROCESS_SCHEDULER)
    assert left_id == right_id == "structured:4321|Load_Data"


def test_structured_identity_keeps_business_code_in_identity():
    from app.models import JobStatus, SchedulerType, SnapshotJob
    from app.services.identity import logical_id_for_job

    first = SnapshotJob(
        job_uid="first",
        scheduler_job_name="STD_PREFIX_4321_UA_Load_Data",
        status=JobStatus.SUCCESS,
    )
    second = SnapshotJob(
        job_uid="second",
        scheduler_job_name="STD_PREFIX_9876_UB_Load_Data",
        status=JobStatus.SUCCESS,
    )

    first_id, _ = logical_id_for_job(first, SchedulerType.AUTOSYS)
    second_id, _ = logical_id_for_job(second, SchedulerType.PROCESS_SCHEDULER)
    assert first_id != second_id


def test_structured_identity_keeps_job_specific_name_in_identity():
    from app.models import JobStatus, SchedulerType, SnapshotJob
    from app.services.identity import logical_id_for_job

    first = SnapshotJob(
        job_uid="first",
        scheduler_job_name="STD_PREFIX_4321_UA_Load_Data",
        status=JobStatus.SUCCESS,
    )
    second = SnapshotJob(
        job_uid="second",
        scheduler_job_name="STD_PREFIX_4321_UB_Validate_Data",
        status=JobStatus.SUCCESS,
    )

    first_id, _ = logical_id_for_job(first, SchedulerType.AUTOSYS)
    second_id, _ = logical_id_for_job(second, SchedulerType.PROCESS_SCHEDULER)
    assert first_id != second_id
