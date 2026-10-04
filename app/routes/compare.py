"""Compare page and HTMX fragments."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import load_environments
from app.models import AsOf, AsOfKind, ComparisonContext, ContextFilters, SchedulerType
from app.search.sqlite_fts import search_index
from app.services.comparison import compare_contexts, fetch_snapshot, job_status_css
from app.services.export_csv import export_topology_csv
from app.session_store import CompareSession, session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["job_status_css"] = job_status_css


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
    return templates.TemplateResponse(
        request,
        "partials/compare_results.html",
        {
            "result": result,
            "left_snapshot": left_snap,
            "right_snapshot": right_snap,
            "session_id": sid,
        },
    )


@router.get("/api/tree/{side}", response_class=HTMLResponse)
async def tree_partial(request: Request, side: str, session_id: str, parent_uid: str = ""):
    session = session_store.get(session_id)
    if not session:
        return HTMLResponse("<p>Session expired. Run Compare again.</p>", status_code=404)
    snap = session.left_snapshot if side == "left" else session.right_snapshot
    nodes = snap.roots if not parent_uid else _find_children(snap, parent_uid)
    return templates.TemplateResponse(
        request,
        "partials/tree_nodes.html",
        {"nodes": nodes, "side": side, "session_id": session_id, "depth": 0},
    )


def _find_children(snap, parent_uid: str):
    from app.models import JobNode

    parent = next((j for j in snap.flat_jobs if j.job_uid == parent_uid), None)
    if not parent:
        return []

    def walk(nodes):
        for n in nodes:
            if n.job.job_uid == parent_uid:
                return n.children
            found = walk(n.children)
            if found is not None:
                return found
        return None

    return walk(snap.roots) or []


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
