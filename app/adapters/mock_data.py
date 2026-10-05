"""Shared mock topology helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import get_settings
from app.adapters.example_jobs import (
    autosys_reference_from_example,
    load_autosys_example_jobs,
    load_ps_example_jobs,
)
from app.models import (
    ComparisonContext,
    DependencyEdge,
    DependencyKind,
    JobNode,
    JobStatus,
    SnapshotJob,
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
    examples: dict | None = None,
    scheduler: str = "autosys",
) -> SnapshotJob:
    uid = _uid(side, *path_labels)
    duration = None
    if start and end:
        duration = (end - start).total_seconds()
    ref = autosys_reference_from_example(
        examples or {},
        name,
        path_labels,
        actual_start=start,
        actual_end=end,
        status_raw=status_raw,
        exit_code=exit_code,
        scheduler=scheduler,
    )
    if not ref.jil.job_name:
        ref.jil.job_name = name
    if not examples:
        if not ref.jil.job_type:
            ref.jil.job_type = job_type.upper() if job_type != "box" else "BOX"
        if not ref.jil.machine and machine:
            ref.jil.machine = machine
        if not ref.jil.std_out_file:
            ref.jil.std_out_file = f"/logs/{side}/{name}{log_suffix}"
    if not ref.run.status:
        ref.run.status = status_raw
    native_type = job_type if not examples else None
    return SnapshotJob(
        job_uid=uid,
        scheduler_job_name=name,
        parent_uid=parent_uid,
        status=status,
        status_raw=status_raw,
        actual_start=start,
        actual_end=end,
        duration_sec=duration,
        exit_code=exit_code,
        autosys=ref,
        path_labels=list(path_labels),
        attributes={"native_job_type": native_type} if native_type else {},
    )


def _parse_business_date(context: ComparisonContext) -> datetime:
    raw = (context.as_of.value or "2026-10-02").strip()
    try:
        parts = [int(p) for p in raw.split("-")]
        return datetime(parts[0], parts[1], parts[2], 6, 0, 0)
    except (ValueError, IndexError):
        return datetime(2026, 10, 2, 6, 0, 0)


def apply_root_scope(snap: TopologySnapshot, root_name: str | None) -> TopologySnapshot:
    """Keep only the subtree rooted at root_name (root box / topology id)."""
    if not root_name or not str(root_name).strip():
        return snap
    key = str(root_name).strip().lower()

    def node_matches(node: JobNode) -> bool:
        job = node.job
        if job.scheduler_job_name.lower() == key:
            return True
        return any(label.lower() == key for label in job.path_labels)

    def find_subtree(nodes: list[JobNode]) -> JobNode | None:
        for node in nodes:
            if node_matches(node):
                return node
            found = find_subtree(node.children)
            if found:
                return found
        return None

    subtree = find_subtree(snap.roots)
    if not subtree:
        return snap

    flat: list[SnapshotJob] = []
    edges: list[DependencyEdge] = []

    def flatten(node: JobNode) -> None:
        flat.append(node.job)
        for child in node.children:
            flatten(child)

    flatten(subtree)
    allowed = {j.job_uid for j in flat}
    edges = [e for e in snap.edges if e.from_uid in allowed and e.to_uid in allowed]
    # Drop lazy-tree indexes from the parent snapshot; they refer to the full topology.
    meta = {
        k: v
        for k, v in snap.metadata.items()
        if k not in ("children_index", "jobs_by_uid")
    }
    meta["scoped_root"] = root_name
    return TopologySnapshot(
        context=snap.context,
        roots=[subtree],
        flat_jobs=flat,
        edges=edges,
        capabilities=snap.capabilities,
        metadata=meta,
    )


def build_large_autosys_snapshot(context: ComparisonContext, job_count: int) -> TopologySnapshot:
    """Synthetic flat box with many child jobs for scalability testing."""
    base = _parse_business_date(context)
    side = "left"
    n = max(job_count, 2)
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
    children: list[JobNode] = []
    flat: list[SnapshotJob] = [box]
    edges: list[DependencyEdge] = []
    for i in range(n - 1):
        status = JobStatus.FAILURE if i % 500 == 17 else JobStatus.SUCCESS
        job = _job(
            side,
            f"RISK_JOB_{i:04d}",
            ["RISK_DAILY_BOX", f"RISK_JOB_{i:04d}"],
            "cmd",
            status,
            status.value,
            parent_uid=box.job_uid,
            start=base + timedelta(minutes=1),
            end=base + timedelta(minutes=2),
        )
        flat.append(job)
        children.append(JobNode(job=job))
    return TopologySnapshot(
        context=context,
        roots=[JobNode(job=box, children=children)],
        flat_jobs=flat,
        edges=edges,
        metadata={"adapter": "autosys_mock", "connector_version": "0.0-mock", "synthetic_count": n},
    )


def build_large_ps_snapshot(context: ComparisonContext, job_count: int) -> TopologySnapshot:
    """Synthetic PS topology aligned with large AutoSys mock."""
    base = _parse_business_date(context)
    side = "right"
    n = max(job_count, 2)
    topo = _job(
        side,
        "risk_daily_topology",
        ["risk_daily_topology"],
        "topology",
        JobStatus.SUCCESS,
        "Completed",
        start=base,
        end=base + timedelta(hours=2),
    )
    children: list[JobNode] = []
    flat: list[SnapshotJob] = [topo]
    edges: list[DependencyEdge] = []
    for i in range(n - 1):
        # Deliberate status drift on a subset vs AutoSys mock.
        status = JobStatus.SUCCESS if i % 500 != 17 else JobStatus.FAILURE
        job = _job(
            side,
            f"RiskDaily.Job_{i:04d}",
            ["risk_daily_topology", f"RiskDaily.Job_{i:04d}"],
            "dotnet",
            status,
            "Completed" if status == JobStatus.SUCCESS else "Failed",
            parent_uid=topo.job_uid,
        )
        flat.append(job)
        children.append(JobNode(job=job))
    return TopologySnapshot(
        context=context,
        roots=[JobNode(job=topo, children=children)],
        flat_jobs=flat,
        edges=edges,
        metadata={
            "adapter": "process_scheduler_mock",
            "connector_version": "0.0-mock",
            "topology_id": "risk_daily_topology",
            "synthetic_count": n,
        },
    )


def build_autosys_snapshot(context: ComparisonContext) -> TopologySnapshot:
    """Realistic Risk Analytics AutoSys box tree for demos."""
    settings = get_settings()
    if settings.mock_job_count > 0:
        return apply_root_scope(
            build_large_autosys_snapshot(context, settings.mock_job_count),
            context.filters.root_box,
        )
    base = _parse_business_date(context)
    side = "left"
    business_date = context.as_of.value or base.strftime("%Y-%m-%d")
    recon_failed = business_date == "2026-10-02"
    examples = load_autosys_example_jobs()

    box = _job(
        side,
        "RISK_DAILY_BOX",
        ["RISK_DAILY_BOX"],
        "box",
        JobStatus.SUCCESS,
        "SUCCESS",
        start=base,
        end=base + timedelta(hours=2),
        examples=examples,
        scheduler="autosys",
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
        examples=examples,
        scheduler="autosys",
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
        examples=examples,
        scheduler="autosys",
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
        examples=examples,
        scheduler="autosys",
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
        examples=examples,
        scheduler="autosys",
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
        examples=examples,
        scheduler="autosys",
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
        DependencyEdge(
            from_uid=file_wait.job_uid,
            to_uid=etl.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=etl.job_uid,
            to_uid=dotnet.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=dotnet.job_uid,
            to_uid=recon.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=recon.job_uid,
            to_uid=legacy_only.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
    ]
    snap = TopologySnapshot(
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
    return apply_root_scope(snap, context.filters.root_box)


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
        edges=[],
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
    examples = load_ps_example_jobs()

    topo = _job(
        side,
        "risk_daily_topology",
        ["risk_daily_topology"],
        "topology",
        JobStatus.SUCCESS,
        "Completed",
        start=base,
        end=base + timedelta(hours=2, minutes=3),
        examples=examples,
        scheduler="process_scheduler",
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
        examples=examples,
        scheduler="process_scheduler",
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
        examples=examples,
        scheduler="process_scheduler",
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
        examples=examples,
        scheduler="process_scheduler",
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
        examples=examples,
        scheduler="process_scheduler",
    )
    extra = _job(
        side,
        "RiskDaily.PostProcess",
        ["risk_daily_topology", "RiskDaily.PostProcess"],
        "dotnet",
        JobStatus.PENDING,
        "Pending",
        parent_uid=topo.job_uid,
        examples=examples,
        scheduler="process_scheduler",
    )
    orphan = _job(
        side,
        "RiskDaily.AdHocCheck",
        ["RiskDaily.AdHocCheck"],
        "cmd",
        JobStatus.NOT_RUN,
        "NotRun",
        examples=examples,
        scheduler="process_scheduler",
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
        DependencyEdge(
            from_uid=file_wait.job_uid,
            to_uid=etl.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=etl.job_uid,
            to_uid=dotnet.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=dotnet.job_uid,
            to_uid=recon.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
        DependencyEdge(
            from_uid=recon.job_uid,
            to_uid=extra.job_uid,
            kind=DependencyKind.FINISH_TO_START,
            condition="success",
        ),
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
    settings = get_settings()
    if settings.mock_job_count > 0:
        scoped = context.filters.root_box or context.filters.topology_id
        return apply_root_scope(build_large_ps_snapshot(context, settings.mock_job_count), scoped)
    topo_id = _ps_topology_id(context)
    if topo_id == "risk_weekly_topology":
        snap = build_ps_weekly_snapshot(context)
    else:
        snap = build_ps_daily_snapshot(context)
    scoped = context.filters.root_box or context.filters.topology_id
    return apply_root_scope(snap, scoped)


def list_ps_topology_names() -> list[str]:
    return ["risk_daily_topology", "risk_weekly_topology"]
