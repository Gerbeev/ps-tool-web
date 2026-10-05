"""CSV export routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import endpoint_for_environment
from app.context_helpers import default_business_date
from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import fetch_snapshot
from app.services.export_csv import (
    iter_comparison_csv_lines,
    iter_topology_csv_lines,
)
from app.session_store import session_store

router = APIRouter()


def _ctx(env: str, sched: str, as_of: str) -> ComparisonContext:
    return ComparisonContext(
        environment_id=env,
        endpoint_url=endpoint_for_environment(env),
        scheduler=SchedulerType(sched),
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=as_of or default_business_date()),
    )


@router.get("/api/export/left.csv")
async def export_left(
    session_id: str | None = None,
    environment_id: str | None = Query(None),
    scheduler: str | None = Query(None),
    as_of: str = Query(""),
):
    snap = _snapshot_for_export(session_id, "left", environment_id, scheduler, as_of)
    fname = f"topology_export_left_{snap.context.environment_id}_{snap.context.as_of.value}.csv"
    return StreamingResponse(
        iter_topology_csv_lines(snap),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/export/right.csv")
async def export_right(
    session_id: str | None = None,
    environment_id: str | None = Query(None),
    scheduler: str | None = Query(None),
    as_of: str = Query(""),
):
    snap = _snapshot_for_export(session_id, "right", environment_id, scheduler, as_of)
    fname = f"topology_export_right_{snap.context.environment_id}_{snap.context.as_of.value}.csv"
    return StreamingResponse(
        iter_topology_csv_lines(snap),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/export/comparison.csv")
async def export_comparison(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(
        iter_comparison_csv_lines(session.result),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="comparison_report.csv"'},
    )


def _snapshot_for_export(session_id, side, environment_id, scheduler, as_of):
    if session_id:
        session = session_store.get(session_id)
        if session:
            return session.left_snapshot if side == "left" else session.right_snapshot
    if not environment_id or not scheduler:
        raise HTTPException(status_code=400, detail="Provide session_id or env+scheduler")
    ctx = _ctx(environment_id, scheduler, as_of)
    snap, _ = fetch_snapshot(ctx)
    return snap
