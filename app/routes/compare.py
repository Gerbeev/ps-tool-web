"""Compare page and HTMX fragments."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings, load_environments
from app.models import AsOf, AsOfKind, ComparisonContext, ContextFilters, SchedulerType
from app.search.sqlite_fts import search_index
from app.services.comparison import compare_contexts, fetch_snapshot, job_status_css
from app.services.table_rows import iter_table_rows, page_table_rows
from app.services.topology_index import child_count, get_child_nodes, lazy_roots
from app.session_store import CompareSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css
templates.env.globals["tree_child_count"] = child_count


def _parse_context(
    environment_id: str,
    scheduler: str,
    as_of_value: str,
    root_box: str | None,
) -> ComparisonContext:
    return ComparisonContext(
        environment_id=environment_id,
        scheduler=SchedulerType(scheduler),
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=as_of_value or "2026-10-02"),
        filters=ContextFilters(root_box=root_box or None),
    )


def _env_options():
    return load_environments()


def _parameter_mismatches_by_logical_id(result) -> dict[str, list]:
    out: dict[str, list] = {}
    for m in result.parameter_mismatches:
        if not m.logical_id:
            continue
        out.setdefault(m.logical_id, []).append(m)
    return out


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
    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "environments": envs,
            "left_env": default_env,
            "right_env": envs[2].id if len(envs) > 2 else default_env,
            "left_scheduler": SchedulerType.AUTOSYS.value,
            "right_scheduler": SchedulerType.PROCESS_SCHEDULER.value,
            "as_of": "2026-10-02",
            "result": None,
            "session_id": None,
        },
    )


@router.post("/api/compare", response_class=HTMLResponse)
async def run_compare(
    request: Request,
    left_env: str = Form(...),
    left_scheduler: str = Form(...),
    right_env: str = Form(...),
    right_scheduler: str = Form(...),
    as_of: str = Form("2026-10-02"),
    left_root: str = Form(""),
    right_root: str = Form(""),
):
    left = _parse_context(left_env, left_scheduler, as_of, left_root or None)
    right = _parse_context(right_env, right_scheduler, as_of, right_root or None)
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
    snap = session.left_snapshot if side == "left" else session.right_snapshot
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
    snap = session.left_snapshot if side == "left" else session.right_snapshot
    job = next((j for j in snap.flat_jobs if j.job_uid == uid), None)
    if not job:
        return HTMLResponse("<p>Job not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/job_detail.html",
        {"job": job, "side": side},
    )
