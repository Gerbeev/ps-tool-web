from pathlib import Path

import yaml

from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.mock_reference import build_reference_snapshot
from app.process_scheduler_reference import ProcessSchedulerJobReference


def _ps_ctx(environment_id: str = "ps-u5") -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def _autosys_ctx(environment_id: str = "autosys-u1") -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=SchedulerType.AUTOSYS,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value="2026-10-02"),
    )


def test_captured_process_scheduler_detail_fixture_preserves_wire_fields():
    path = Path("examples/process_scheduler_endpoint/job_detail.IB_CT_CVA_1109_U5_Admin_Box.sample.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    wire = payload["raw_wire_fields"]

    assert list(wire) == [
        "Box",
        "ConditionExpression",
        "Context",
        "Description",
        "JobType",
        "LastFinishTime",
        "LastStartTime",
        "Name",
        "Owner",
        "Schedule",
        "StartAtTime",
        "StartAtTimeForce",
        "Status",
    ]

    ref = ProcessSchedulerJobReference.from_wire(wire)
    assert ref.box == "DataPlatform_20261001_Friday"
    assert ref.context == "DataPlatform_20261001_Friday"
    assert ref.condition_expression is None
    assert ref.job_type == "Box"
    assert ref.schedule == "Tuesday,Wednesday,Thursday,Friday,Saturday"
    assert ref.start_at_time == "00:01"
    assert ref.start_at_time_force is False
    assert ref.status == "Failed"
    assert ref.last_start_time is not None
    assert ref.last_start_time.utcoffset().total_seconds() == 7200
    assert ref.model_dump(by_alias=True)["Name"] == "IB_CT_CVA_1109_U5_Admin_Box"


def test_reference_ps_snapshot_exposes_native_detail_and_safe_schedule_projection(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()
    snapshot = build_reference_snapshot(_ps_ctx())
    job = next(item for item in snapshot.flat_jobs if item.attributes["reference_job_ref"] == "business-4001/admin-box")

    assert job.process_scheduler is not None
    assert job.process_scheduler.name == job.scheduler_job_name
    assert job.process_scheduler.status == job.status_raw
    assert job.process_scheduler.context == "DataPlatform_REFERENCE"
    assert job.process_scheduler.box.endswith("_Application_Box")
    assert job.process_scheduler.schedule == "Tuesday,Wednesday,Thursday,Friday,Saturday"
    assert job.process_scheduler.start_at_time == "00:01"
    assert job.process_scheduler.start_at_time_force is False

    assert job.autosys.jil.days_of_week == job.process_scheduler.schedule
    assert job.autosys.jil.start_times == job.process_scheduler.start_at_time
    assert job.autosys.jil.date_conditions == 1
    assert job.scheduled_start is not None
    assert (job.scheduled_start.hour, job.scheduled_start.minute) == (0, 1)


def test_reference_autosys_snapshot_does_not_fake_process_scheduler_source_detail(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()
    snapshot = build_reference_snapshot(_autosys_ctx())

    assert all(job.process_scheduler is None for job in snapshot.flat_jobs)
