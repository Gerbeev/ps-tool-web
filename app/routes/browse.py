"""Single-environment browse page and HTMX fragments."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.adapters.factory import get_adapter
from app.config import load_environments
from app.models import AsOf, AsOfKind, ComparisonContext, ContextFilters, SchedulerType
from app.search.sqlite_fts import search_index
from app.services.comparison import fetch_snapshot, job_status_css
from app.services.topology_index import child_count, get_child_nodes, lazy_roots
from app.session_store import BrowseSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css
templates.env.globals["tree_child_count"] = child_count


def _env_options():
    return load_environments()


def _topology_options(environment_id: str, scheduler: str) -> list[str]:
    if scheduler != SchedulerType.PROCESS_SCHEDULER.value:
        return []
    adapter = get_adapter(SchedulerType.PROCESS_SCHEDULER, environment_id)
    ctx = ComparisonContext(environment_id=environment_id, scheduler=SchedulerType.PROCESS_SCHEDULER)
    return adapter.list_roots(ctx)


def _parse_browse_context(
    environment_id: str,
    scheduler: str,
    as_of: str,
    topology: str,
) -> ComparisonContext:
    sched = SchedulerType(scheduler)
    filters = ContextFilters()
    if sched == SchedulerType.PROCESS_SCHEDULER and topology:
        filters.topology_id = topology
        filters.root_box = topology
    elif sched == SchedulerType.AUTOSYS:
        filters.root_box = "RISK_DAILY_BOX"
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=sched,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=as_of or "2026-10-02"),
        filters=filters,
    )


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request):
    envs = _env_options()
    default_env = envs[0].id if envs else "uat-rd"
    scheduler = SchedulerType.PROCESS_SCHEDULER.value
    topologies = _topology_options(default_env, scheduler)
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "environments": envs,
            "environment_id": default_env,
            "scheduler": scheduler,
            "as_of": "2026-10-02",
            "topology": topologies[0] if topologies else "",
            "topologies": topologies,
            "session_id": None,
            "snapshot": None,
        },
    )


@router.get("/api/browse/form", response_class=HTMLResponse)
async def browse_form_partial(
    request: Request,
    environment_id: str = "uat-rd",
    scheduler: str = SchedulerType.PROCESS_SCHEDULER.value,
    as_of: str = "2026-10-02",
    topology: str = "",
):
    topologies = _topology_options(environment_id, scheduler)
    if not topology and topologies:
        topology = topologies[0]
    return templates.TemplateResponse(
        request,
        "partials/browse_form_fields.html",
        {
            "scheduler": scheduler,
            "as_of": as_of,
            "topology": topology,
            "topologies": topologies,
        },
    )


@router.post("/api/browse/load", response_class=HTMLResponse)
async def browse_load(
    request: Request,
    environment_id: str = Form(...),
    scheduler: str = Form(...),
    as_of: str = Form("2026-10-02"),
    topology: str = Form(""),
):
    context = _parse_browse_context(environment_id, scheduler, as_of, topology)
    snapshot, _ = fetch_snapshot(context)
    search_index.rebuild(snapshot, "left")
    sid = session_store.new_id()
    session_store.put_browse(BrowseSession(session_id=sid, context=context, snapshot=snapshot))
    meta = snapshot.metadata or {}
    return templates.TemplateResponse(
        request,
        "partials/browse_results.html",
        {
            "snapshot": snapshot,
            "session_id": sid,
            "context": context,
            "meta_line": _meta_line(context, meta),
        },
    )


def _meta_line(context: ComparisonContext, meta: dict) -> str:
    if context.scheduler == SchedulerType.AUTOSYS:
        bd = meta.get("business_date") or context.as_of.value
        return f"AutoSys · business date {bd}"
    topo = meta.get("topology_id") or context.filters.topology_id or "—"
    return f"Process Scheduler · topology {topo}"


@router.get("/api/browse/job/{uid}", response_class=HTMLResponse)
async def browse_job_detail(request: Request, uid: str, session_id: str):
    session = session_store.get_browse(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Load the environment again.</p>", status_code=404)
    job = next((j for j in session.snapshot.flat_jobs if j.job_uid == uid), None)
    if not job:
        return HTMLResponse("<p>Job not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/job_detail.html",
        {"job": job, "side": "browse", "panel_mode": "browse"},
    )


@router.get("/api/browse/tree", response_class=HTMLResponse)
async def browse_tree(request: Request, session_id: str, parent_uid: str = ""):
    session = session_store.get_browse(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Load the environment again.</p>", status_code=404)
    snap = session.snapshot
    if not parent_uid:
        nodes = lazy_roots(snap)
    else:
        nodes = get_child_nodes(snap, parent_uid)
    return templates.TemplateResponse(
        request,
        "partials/tree_browse_nodes.html",
        {
            "nodes": nodes,
            "session_id": session_id,
            "snapshot": snap,
            "tree_api_base": "/api/browse/tree",
            "job_api_base": "/api/browse/job",
        },
    )
