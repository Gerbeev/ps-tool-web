"""Single-environment browse page and HTMX fragments."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.browse_status_filters import (
    BROWSE_STATUS_FILTER_ORDER,
    BROWSE_STATUS_INACTIVE_VALUES,
    BROWSE_STATUS_LABELS,
)
from app.config import load_environments
from app.context_helpers import (
    default_business_date,
    environment_scheduler_value,
    parse_browse_context,
    scheduler_label,
    topology_options,
)
from app.models import SchedulerType
from app.search.sqlite_fts import search_index
from app.services.comparison import fetch_snapshot, job_status_css
from app.services.topology_index import child_count, get_child_nodes, lazy_roots
from app.session_store import BrowseSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css
templates.env.globals["tree_child_count"] = child_count
templates.env.globals["browse_status_labels"] = BROWSE_STATUS_LABELS
templates.env.globals["browse_status_inactive_values"] = BROWSE_STATUS_INACTIVE_VALUES
templates.env.globals["browse_status_filter_order"] = BROWSE_STATUS_FILTER_ORDER


def _env_options():
    return load_environments()


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request):
    envs = _env_options()
    default_env = envs[0].id if envs else "uat-rd"
    scheduler = environment_scheduler_value(default_env)
    as_of = default_business_date()
    topologies = topology_options(default_env, scheduler)
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "environments": envs,
            "environment_id": default_env,
            "scheduler": scheduler,
            "scheduler_label": scheduler_label(scheduler),
            "as_of": as_of,
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
    scheduler: str = "",
    as_of: str = "",
    topology: str = "",
):
    if not scheduler:
        scheduler = environment_scheduler_value(environment_id)
    if not as_of:
        as_of = default_business_date()
    topologies = topology_options(environment_id, scheduler)
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
    scheduler: str = Form(""),
    as_of: str = Form(""),
    topology: str = Form(""),
):
    if not scheduler:
        scheduler = environment_scheduler_value(environment_id)
    if not as_of:
        as_of = default_business_date()
    context = parse_browse_context(environment_id, scheduler, as_of, topology)
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


def _meta_line(context, meta: dict) -> str:
    if context.scheduler == SchedulerType.PROCESS_SCHEDULER:
        topo = meta.get("topology_id") or context.filters.topology_id or "—"
        return f"Process Scheduler · topology {topo}"
    bd = meta.get("business_date") or context.as_of.value
    return f"AutoSys · business date {bd}"


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
async def browse_tree(request: Request, session_id: str, parent_uid: str = "", depth: int = 0):
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
            "depth": depth,
        },
    )
