from pathlib import Path

from app.mock_reference import build_reference_snapshot, reference_metadata
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import compare_snapshots


def _ctx(environment_id: str) -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=SchedulerType.PROCESS_SCHEDULER,
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
    assert meta["schema_version"] == 2
    assert sum(1 for _ in path.open(encoding="utf-8")) == 2501

    text = path.read_text(encoding="utf-8")
    for environment_literal in ('"U5"', '"P1"', '"PROD"'):
        assert environment_literal not in text


def test_reference_tree_has_expected_shape_and_job_types(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()
    snapshot = build_reference_snapshot(_ctx("ps-u5"))

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
    assert all(job.autosys.jil.days_of_week for job in snapshot.flat_jobs)
    assert all(job.autosys.jil.start_times == "00:01" for job in snapshot.flat_jobs)
    assert all(job.process_scheduler is not None for job in snapshot.flat_jobs)


def test_u5_and_p1_reference_projections_compare_as_exact_baseline(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_DATASET", "reference_2500")
    get_settings.cache_clear()

    u5 = build_reference_snapshot(_ctx("ps-u5"))
    p1 = build_reference_snapshot(_ctx("ps-p1"))
    result = compare_snapshots(u5, p1)

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
    assert "_U5_" in pair.left.scheduler_job_name
    assert "_P1_" in pair.right.scheduler_job_name
    assert pair.left.autosys.jil.box_name != pair.right.autosys.jil.box_name
