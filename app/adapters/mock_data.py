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


def build_autosys_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Realistic Risk Analytics AutoSys box tree for demos."""
    base = datetime(2026, 10, 2, 6, 0, 0)
    side = "left"

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
        JobStatus.FAILURE,
        "FAILURE",
        parent_uid=box.job_uid,
        start=base + timedelta(minutes=50),
        end=base + timedelta(minutes=55),
        exit_code=8,
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
        metadata={"adapter": "autosys_mock", "connector_version": "0.0-mock"},
    )


def build_ps_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Process Scheduler topology — intentional diffs vs AutoSys mock."""
    base = datetime(2026, 10, 2, 6, 0, 0)
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
        metadata={"adapter": "process_scheduler_mock", "connector_version": "0.0-mock"},
    )
