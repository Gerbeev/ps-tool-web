"""Shared mock topology helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import (
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    JobNode,
    JobStatus,
    NormalizedJob,
    TopologySnapshot,
)


def _uid(*parts: str) -> str:
    return "-".join(parts)


def _job(
    side: str,
    name: str,
    path_labels: list[str],
    job_type: str,
    status: JobStatus,
    status_raw: str,
    *,
    parent_uid: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    exit_code: int | None = None,
    machine: str = "batch01",
    log_suffix: str = ".log",
) -> NormalizedJob:
    uid = _uid(side, *path_labels)
    duration = None
    if start and end:
        duration = (end - start).total_seconds()
    return NormalizedJob(
        job_uid=uid,
        scheduler_job_name=name,
        parent_uid=parent_uid,
        job_type=job_type,
        status=status,
        status_raw=status_raw,
        actual_start=start,
        actual_end=end,
        duration_sec=duration,
        exit_code=exit_code,
        machine=machine,
        log_path=f"/logs/{side}/{name}{log_suffix}",
        path_labels=list(path_labels),
    )


def _parse_business_date(context: ComparisonContext) -> datetime:
    raw = (context.as_of.value or "2026-10-02").strip()
    try:
        parts = [int(p) for p in raw.split("-")]
        return datetime(parts[0], parts[1], parts[2], 6, 0, 0)
    except (ValueError, IndexError):
        return datetime(2026, 10, 2, 6, 0, 0)


def build_autosys_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Realistic Risk Analytics AutoSys box tree for demos."""
    base = _parse_business_date(context)
    side = "left"
    business_date = context.as_of.value or base.strftime("%Y-%m-%d")
    recon_failed = business_date == "2026-10-02"

    box = _job(
        side,
        "RISK_DAILY_BOX",
        ["RISK_DAILY_BOX"],
        "box",
        JobStatus.SUCCESS,
        "SUCCESS",
        start=base,
        end=base + timedelta(hours=2),
    )
    etl = _job(
        side,
        "RISK_DAILY_ETL",
        ["RISK_DAILY_BOX", "RISK_DAILY_ETL"],
        "cmd",
        JobStatus.SUCCESS,
        "SUCCESS",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=5),
        end=base + timedelta(minutes=45),
        exit_code=0,
    )
    recon = _job(
        side,
        "RISK_DAILY_RECON",
        ["RISK_DAILY_BOX", "RISK_DAILY_RECON"],
        "cmd",
        JobStatus.FAILURE if recon_failed else JobStatus.SUCCESS,
        "FAILURE" if recon_failed else "SUCCESS",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=50),
        end=base + timedelta(minutes=55),
        exit_code=8 if recon_failed else 0,
    )
    file_wait = _job(
        side,
        "RISK_FILE_WAIT_INCOMING",
        ["RISK_DAILY_BOX", "RISK_FILE_WAIT_INCOMING"],
        "file_wait",
        JobStatus.SUCCESS,
        "SUCCESS",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=1),
        end=base + timedelta(minutes=4),
    )
    dotnet = _job(
        side,
        "RISK_DOTNET_CALC",
        ["RISK_DAILY_BOX", "RISK_DOTNET_CALC"],
        "dotnet",
        JobStatus.SUCCESS,
        "SUCCESS",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=46),
        end=base + timedelta(minutes=49),
    )
    legacy_only = _job(
        side,
        "RISK_LEGACY_REPORT",
        ["RISK_DAILY_BOX", "RISK_LEGACY_REPORT"],
        "cmd",
        JobStatus.SUCCESS,
        "SUCCESS",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=56),
        end=base + timedelta(minutes=58),
    )

    roots = [
        JobNode(
            job=box,
            children=[
                JobNode(job=etl),
                JobNode(job=file_wait),
                JobNode(job=dotnet),
                JobNode(job=recon),
                JobNode(job=legacy_only),
            ],
        )
    ]
    flat = [box, etl, file_wait, dotnet, recon, legacy_only]
    edges = [
        DependencyEdge(from_uid=box.job_uid, to_uid=etl.job_uid),
        DependencyEdge(from_uid=box.job_uid, to_uid=file_wait.job_uid),
        DependencyEdge(from_uid=etl.job_uid, to_uid=dotnet.job_uid),
        DependencyEdge(from_uid=dotnet.job_uid, to_uid=recon.job_uid),
        DependencyEdge(from_uid=box.job_uid, to_uid=legacy_only.job_uid),
    ]
    return TopologySnapshot(
        context=context,
        roots=roots,
        flat_jobs=flat,
        edges=edges,
        metadata={
            "adapter": "autosys_mock",
            "connector_version": "0.0-mock",
            "business_date": business_date,
        },
    )


def _ps_topology_id(context: ComparisonContext) -> str:
    return (
        context.filters.topology_id
        or context.filters.root_box
        or "risk_daily_topology"
    )


def build_ps_weekly_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Secondary PS topology for browse demos."""
    base = _parse_business_date(context)
    side = "right"
    topo_name = "risk_weekly_topology"

    topo = _job(
        side,
        topo_name,
        [topo_name],
        "topology",
        JobStatus.RUNNING,
        "Running",
        start=base,
    )
    rollup = _job(
        side,
        "RiskWeekly.RollupJob",
        [topo_name, "RiskWeekly.RollupJob"],
        "dotnet",
        JobStatus.SUCCESS,
        "Completed",
        parent_uid=topo.job_uid,
        start=base + timedelta(minutes=10),
        end=base + timedelta(minutes=40),
    )
    archive = _job(
        side,
        "RiskWeekly.ArchiveJob",
        [topo_name, "RiskWeekly.ArchiveJob"],
        "cmd",
        JobStatus.PENDING,
        "Pending",
        parent_uid=topo.job_uid,
    )
    roots = [JobNode(job=topo, children=[JobNode(job=rollup), JobNode(job=archive)])]
    flat = [topo, rollup, archive]
    return TopologySnapshot(
        context=context,
        roots=roots,
        flat_jobs=flat,
        edges=[DependencyEdge(from_uid=topo.job_uid, to_uid=rollup.job_uid)],
        metadata={
            "adapter": "process_scheduler_mock",
            "connector_version": "0.0-mock",
            "topology_id": topo_name,
        },
    )


def build_ps_daily_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Process Scheduler daily topology — intentional diffs vs AutoSys mock."""
    base = _parse_business_date(context)
    side = "right"

    topo = _job(
        side,
        "risk_daily_topology",
        ["risk_daily_topology"],
        "topology",
        JobStatus.SUCCESS,
        "Completed",
        start=base,
        end=base + timedelta(hours=2, minutes=3),
    )
    etl = _job(
        side,
        "RiskDaily.EtlJob",
        ["risk_daily_topology", "RiskDaily.EtlJob"],
        "dotnet",
        JobStatus.SUCCESS,
        "Completed",
        parent_uid=topo.job_uid,
        start=base + timedelta(minutes=5),
        end=base + timedelta(minutes=44),
        exit_code=0,
    )
    recon = _job(
        side,
        "RiskDaily.ReconJob",
        ["risk_daily_topology", "RiskDaily.ReconJob"],
        "dotnet",
        JobStatus.SUCCESS,
        "Completed",
        parent_uid=topo.job_uid,
        start=base + timedelta(minutes=52),
        end=base + timedelta(minutes=57),
        exit_code=0,
    )
    file_wait = _job(
        side,
        "RiskDaily.FileWaitIncoming",
        ["risk_daily_topology", "RiskDaily.FileWaitIncoming"],
        "file_wait",
        JobStatus.SUCCESS,
        "Completed",
        parent_uid=topo.job_uid,
        start=base + timedelta(minutes=1),
        end=base + timedelta(minutes=4),
    )
    dotnet = _job(
        side,
        "RiskDaily.DotNetCalc",
        ["risk_daily_topology", "RiskDaily.DotNetCalc"],
        "dotnet",
        JobStatus.SUCCESS,
        "Completed",
        parent_uid=topo.job_uid,
        start=base + timedelta(minutes=46, seconds=30),
        end=base + timedelta(minutes=50),
    )
    extra = _job(
        side,
        "RiskDaily.PostProcess",
        ["risk_daily_topology", "RiskDaily.PostProcess"],
        "dotnet",
        JobStatus.PENDING,
        "Pending",
        parent_uid=topo.job_uid,
    )
    orphan = _job(
        side,
        "RiskDaily.AdHocCheck",
        ["RiskDaily.AdHocCheck"],
        "cmd",
        JobStatus.NOT_RUN,
        "NotRun",
    )

    roots = [
        JobNode(
            job=topo,
            children=[
                JobNode(job=etl),
                JobNode(job=file_wait),
                JobNode(job=dotnet),
                JobNode(job=recon),
                JobNode(job=extra),
            ],
        ),
        JobNode(job=orphan),
    ]
    flat = [topo, etl, file_wait, dotnet, recon, extra, orphan]
    edges = [
        DependencyEdge(from_uid=topo.job_uid, to_uid=etl.job_uid, kind=DependencyKind.FINISH_TO_START),
        DependencyEdge(from_uid=topo.job_uid, to_uid=file_wait.job_uid, kind=DependencyKind.FILE_TRIGGER),
        DependencyEdge(from_uid=etl.job_uid, to_uid=dotnet.job_uid),
        DependencyEdge(from_uid=dotnet.job_uid, to_uid=recon.job_uid),
        DependencyEdge(from_uid=topo.job_uid, to_uid=extra.job_uid),
    ]
    return TopologySnapshot(
        context=context,
        roots=roots,
        flat_jobs=flat,
        edges=edges,
        metadata={
            "adapter": "process_scheduler_mock",
            "connector_version": "0.0-mock",
            "topology_id": "risk_daily_topology",
        },
    )


def build_ps_snapshot(context: ComparisonContext) -> TopologySnapshot:
    topo_id = _ps_topology_id(context)
    if topo_id == "risk_weekly_topology":
        return build_ps_weekly_snapshot(context)
    return build_ps_daily_snapshot(context)


def list_ps_topology_names() -> list[str]:
    return ["risk_daily_topology", "risk_weekly_topology"]
