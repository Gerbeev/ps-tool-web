"""Compare page and HTMX fragments."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings, load_environments
from app.context_helpers import (
    default_business_date,
    environment_scheduler_value,
    parse_compare_side_context,
    scheduler_label,
    topology_options,
)
from app.search.sqlite_fts import search_index
from app.services.comparison import compare_contexts, fetch_snapshot, job_status_css
from app.services.table_rows import iter_table_rows, page_table_rows
from app.services.topology_index import child_count, get_child_nodes, lazy_roots
from app.session_store import CompareSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css
templates.env.globals["tree_child_count"] = child_count


def _side_form_context(environment_id: str, as_of: str = "", topology: str = ""):
    scheduler = environment_scheduler_value(environment_id)
    if not as_of:
        as_of = default_business_date()
    topologies = topology_options(environment_id, scheduler)
    if not topology and topologies:
        topology = topologies[0]
    return {
        "scheduler": scheduler,
        "scheduler_label": scheduler_label(scheduler),
        "as_of": as_of,
        "topology": topology,
        "topologies": topologies,
    }


def _env_options():
    return load_environments()


def _parameter_mismatches_by_logical_id(result) -> dict[str, list]:
    out: dict[str, list] = {}
    for m in result.parameter_mismatches:
        if not m.logical_id:
            continue
        out.setdefault(m.logical_id, []).append(m)
    return out


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
        lid = job.logical_id or job.scheduler_job_name
        ids.add(lid)
    for job in result.right_only:
        lid = job.logical_id or job.scheduler_job_name
        ids.add(lid)
    for m in result.parameter_mismatches:
        if m.logical_id:
            ids.add(m.logical_id)
    return ids


@router.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request):
    envs = _env_options()
    default_env = envs[0].id if envs else "uat-rd"
    left_env = default_env
    right_env = envs[2].id if len(envs) > 2 else default_env
    left_ctx = _side_form_context(left_env)
    right_ctx = _side_form_context(right_env)
    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "environments": envs,
            "left_env": left_env,
            "right_env": right_env,
            "left": left_ctx,
            "right": right_ctx,
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
    left_as_of: str = Query(""),
    right_as_of: str = Query(""),
    left_topology: str = Query(""),
    right_topology: str = Query(""),
):
    env_id = environment_id or (left_env if side == "left" else right_env)
    as_of = left_as_of if side == "left" else right_as_of
    topology = left_topology if side == "left" else right_topology
    ctx = _side_form_context(env_id, as_of=as_of, topology=topology)
    return templates.TemplateResponse(
        request,
        "partials/compare_side_fields.html",
        {"side": side, **ctx},
    )


@router.post("/api/compare", response_class=HTMLResponse)
async def run_compare(
    request: Request,
    left_env: str = Form(...),
    left_scheduler: str = Form(""),
    left_as_of: str = Form(""),
    left_topology: str = Form(""),
    right_env: str = Form(...),
    right_scheduler: str = Form(""),
    right_as_of: str = Form(""),
    right_topology: str = Form(""),
):
    if not left_scheduler:
        left_scheduler = environment_scheduler_value(left_env)
    if not right_scheduler:
        right_scheduler = environment_scheduler_value(right_env)
    left = parse_compare_side_context(left_env, left_scheduler, left_as_of, left_topology)
    right = parse_compare_side_context(right_env, right_scheduler, right_as_of, right_topology)
    left_snap, _ = fetch_snapshot(left)
    right_snap, _ = fetch_snapshot(right)
    result = compare_contexts(left, right)
    search_index.rebuild(left_snap, "left")
    search_index.rebuild(right_snap, "right")
    sid = session_store.new_id()
    session_store.put(
        CompareSession(
            session_id=sid,
            left=left,
            right=right,
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
            "param_mismatches_by_id": _parameter_mismatches_by_logical_id(session.result),
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
    job = next((j for j in snap.flat_jobs if j.job_uid == uid), None)
    if not job:
        return HTMLResponse("<p>Job not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/job_detail.html",
        {"job": job, "side": side},
    )
