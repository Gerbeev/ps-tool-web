"""Compare immutable generated snapshots only; never access scheduler sources."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings, load_environments
from app.search.sqlite_fts import search_index
from app.services.comparison import compare_snapshots, job_status_css
from app.services.snapshot_catalog import SnapshotRecord, snapshot_catalog
from app.services.table_rows import (
    iter_table_rows,
    page_table_rows,
    parameter_mismatches_by_logical_id,
)
from app.services.topology_index import child_count, get_child_nodes, get_job, lazy_roots
from app.session_store import CompareSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css
templates.env.globals["tree_child_count"] = child_count


def _env_options():
    return load_environments()


def _snapshot_options(environment_id: str) -> list[SnapshotRecord]:
    return snapshot_catalog.list(environment_id=environment_id)


def _side_form_context(environment_id: str) -> dict:
    snapshots = _snapshot_options(environment_id) if environment_id else []
    return {
        "snapshots": snapshots,
        "selected_snapshot_id": snapshots[0].snapshot_id if snapshots else "",
    }


def _snapshot_for_side(session: CompareSession, side: str):
    if side == "left":
        return session.left_snapshot
    if side == "right":
        return session.right_snapshot
    raise HTTPException(status_code=404, detail="Unknown side; use left or right")


def _mismatch_logical_ids(result) -> set[str]:
    ids: set[str] = set()
    for pair in result.status_mismatches:
        if pair.logical_id:
            ids.add(pair.logical_id)
    for job in result.left_only:
        ids.add(job.logical_id or job.scheduler_job_name)
    for job in result.right_only:
        ids.add(job.logical_id or job.scheduler_job_name)
    for mismatch in result.parameter_mismatches:
        if mismatch.logical_id:
            ids.add(mismatch.logical_id)
    for pair in result.execution_time_deltas:
        if pair.logical_id:
            ids.add(pair.logical_id)
    return ids


@router.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request):
    envs = _env_options()
    default_env = envs[0].id if envs else ""
    left_env = default_env
    right_env = envs[1].id if len(envs) > 1 else default_env
    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "environments": envs,
            "left_env": left_env,
            "right_env": right_env,
            "left": _side_form_context(left_env),
            "right": _side_form_context(right_env),
            "result": None,
            "session_id": None,
        },
    )


@router.get("/api/compare/side-form", response_class=HTMLResponse)
async def compare_side_form(
    request: Request,
    side: str = Query(..., pattern="^(left|right)$"),
    environment_id: str = Query(""),
    left_env: str = Query(""),
    right_env: str = Query(""),
):
    env_id = environment_id or (left_env if side == "left" else right_env)
    return templates.TemplateResponse(
        request,
        "partials/compare_side_fields.html",
        {"side": side, **_side_form_context(env_id)},
    )


@router.post("/api/compare", response_class=HTMLResponse)
async def run_compare(
    request: Request,
    left_env: str = Form(...),
    left_snapshot_id: str = Form(""),
    right_env: str = Form(...),
    right_snapshot_id: str = Form(""),
):
    if not left_snapshot_id or not right_snapshot_id:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>Select a snapshot on both sides.</strong></p>'
            '<p class="muted small">Generate missing snapshots from the Snapshots tab.</p></div>'
        )
    left_loaded = snapshot_catalog.load(left_snapshot_id)
    right_loaded = snapshot_catalog.load(right_snapshot_id)
    if left_loaded is None or right_loaded is None:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>One or both snapshots are missing or corrupted.</strong></p>'
            '<p class="muted small">Generate replacements from the Snapshots tab.</p></div>'
        )

    left_snap, left_record = left_loaded
    right_snap, right_record = right_loaded
    if left_record.environment_id != left_env or right_record.environment_id != right_env:
        return HTMLResponse(
            '<div class="box__section box__pad"><p><strong>Snapshot/environment mismatch.</strong></p></div>',
            status_code=400,
        )

    result = compare_snapshots(left_snap, right_snap)
    search_index.rebuild(left_snap, "left")
    search_index.rebuild(right_snap, "right")
    sid = session_store.new_id()
    session_store.put(
        CompareSession(
            session_id=sid,
            left=left_snap.context,
            right=right_snap.context,
            left_snapshot=left_snap,
            right_snapshot=right_snap,
            result=result,
        )
    )
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "partials/compare_results.html",
        {
            "result": result,
            "session_id": sid,
            "table_filter": "all",
            "table_limit": settings.table_page_size_default,
            "mismatch_ids": _mismatch_logical_ids(result),
            "left_record": left_record,
            "right_record": right_record,
        },
    )


@router.get("/api/compare/table", response_class=HTMLResponse)
async def compare_table(
    request: Request,
    session_id: str,
    filter: str = Query("all", alias="filter"),
    offset: int = Query(0, ge=0),
    limit: int = Query(0, ge=0),
    q_prefix: str = Query(""),
):
    session = session_store.get(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Run Compare again.</p>", status_code=404)
    rows = iter_table_rows(session.result, filter_name=filter, q_prefix=q_prefix)
    page, total = page_table_rows(rows, offset=offset, limit=limit or None)
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "partials/table.html",
        {
            "rows": page,
            "session_id": session_id,
            "filter": filter,
            "offset": offset,
            "limit": limit,
            "total": total,
            "q_prefix": q_prefix,
            "default_limit": settings.table_page_size_default,
            "param_mismatches_by_id": parameter_mismatches_by_logical_id(session.result),
            "execution_time_mismatch_ids": {
                pair.logical_id
                for pair in session.result.execution_time_deltas
                if pair.logical_id
            },
        },
    )


@router.get("/api/compare/trees", response_class=HTMLResponse)
async def compare_trees(request: Request, session_id: str):
    session = session_store.get(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Run Compare again.</p>", status_code=404)
    mismatch_ids = _mismatch_logical_ids(session.result)
    return templates.TemplateResponse(
        request,
        "partials/compare_trees.html",
        {
            "left_snapshot": session.left_snapshot,
            "right_snapshot": session.right_snapshot,
            "left_roots": lazy_roots(session.left_snapshot),
            "right_roots": lazy_roots(session.right_snapshot),
            "session_id": session_id,
            "mismatch_ids": mismatch_ids,
        },
    )


@router.get("/api/tree/{side}", response_class=HTMLResponse)
async def tree_partial(request: Request, side: str, session_id: str, parent_uid: str = ""):
    session = session_store.get(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Run Compare again.</p>", status_code=404)
    snap = _snapshot_for_side(session, side)
    mismatch_ids = _mismatch_logical_ids(session.result)
    if not parent_uid:
        nodes = lazy_roots(snap)
    else:
        nodes = get_child_nodes(snap, parent_uid)
    return templates.TemplateResponse(
        request,
        "partials/tree_nodes.html",
        {
            "nodes": nodes,
            "side": side,
            "session_id": session_id,
            "snapshot": snap,
            "mismatch_ids": mismatch_ids,
            "tree_api_base": f"/api/tree/{side}",
            "job_api_base": f"/api/job/{side}",
        },
    )


@router.get("/api/job/{side}/{uid}", response_class=HTMLResponse)
async def job_detail(request: Request, side: str, uid: str, session_id: str):
    session = session_store.get(session_id)
    if not session:
        return HTMLResponse("<p>Session expired.</p>", status_code=404)
    snap = _snapshot_for_side(session, side)
    job = get_job(snap, uid)
    if not job:
        return HTMLResponse("<p>Job not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/job_detail.html",
        {"job": job, "side": side},
    )
