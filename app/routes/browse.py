"""Browse immutable generated snapshots only; never access scheduler sources."""

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
from app.models import SchedulerType
from app.search.sqlite_fts import search_index
from app.services.comparison import job_status_css
from app.services.snapshot_catalog import SnapshotRecord, snapshot_catalog
from app.services.topology_index import child_count, get_child_nodes, get_job, lazy_roots
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


def _snapshot_options(environment_id: str) -> list[SnapshotRecord]:
    return snapshot_catalog.list(environment_id=environment_id)


@router.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request):
    envs = _env_options()
    default_env = envs[0].id if envs else ""
    snapshots = _snapshot_options(default_env) if default_env else []
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "environments": envs,
            "environment_id": default_env,
            "snapshots": snapshots,
            "selected_snapshot_id": snapshots[0].snapshot_id if snapshots else "",
            "session_id": None,
            "snapshot": None,
        },
    )


@router.get("/api/browse/form", response_class=HTMLResponse)
async def browse_form_partial(
    request: Request,
    environment_id: str = "",
):
    snapshots = _snapshot_options(environment_id) if environment_id else []
    return templates.TemplateResponse(
        request,
        "partials/browse_form_fields.html",
        {
            "snapshots": snapshots,
            "selected_snapshot_id": snapshots[0].snapshot_id if snapshots else "",
        },
    )


@router.post("/api/browse/load", response_class=HTMLResponse)
async def browse_load(
    request: Request,
    environment_id: str = Form(...),
    snapshot_id: str = Form(""),
):
    if not snapshot_id:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>No snapshot selected.</strong></p>'
            '<p class="muted small">Generate or select a snapshot first.</p></div>'
        )
    loaded = snapshot_catalog.load(snapshot_id)
    if loaded is None:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>Snapshot not found or corrupted.</strong></p>'
            '<p class="muted small">Generate a new snapshot from the Snapshots tab.</p></div>'
        )
    snapshot, record = loaded
    if record.environment_id != environment_id:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>Snapshot/environment mismatch.</strong></p></div>',
            status_code=400,
        )

    search_index.rebuild(snapshot, "left")
    sid = session_store.new_id()
    session_store.put_browse(
        BrowseSession(session_id=sid, context=snapshot.context, snapshot=snapshot)
    )
    meta = snapshot.metadata or {}
    return templates.TemplateResponse(
        request,
        "partials/browse_results.html",
        {
            "snapshot": snapshot,
            "snapshot_record": record,
            "session_id": sid,
            "context": snapshot.context,
            "meta_line": _meta_line(snapshot.context, meta),
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
        return HTMLResponse("<p>Session expired. Load the snapshot again.</p>", status_code=404)
    job = get_job(session.snapshot, uid)
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
        return HTMLResponse("<p>Session expired. Load the snapshot again.</p>", status_code=404)
    snap = session.snapshot
    nodes = lazy_roots(snap) if not parent_uid else get_child_nodes(snap, parent_uid)
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
