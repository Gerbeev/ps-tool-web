"""CSV export routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.models import AsOf, AsOfKind, ComparisonContext, SchedulerType
from app.services.comparison import compare_contexts, fetch_snapshot
from app.services.export_csv import export_comparison_csv, export_topology_csv
from app.session_store import session_store

router = APIRouter()


def _ctx(env: str, sched: str, as_of: str) -> ComparisonContext:
    return ComparisonContext(
        environment_id=env,
        scheduler=SchedulerType(sched),
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=as_of),
    )


@router.get("/api/export/left.csv")
async def export_left(
    session_id: str | None = None,
    environment_id: str | None = Query(None),
    scheduler: str | None = Query(None),
    as_of: str = Query("2026-10-02"),
):
    snap = _snapshot_for_export(session_id, "left", environment_id, scheduler, as_of)
    body = export_topology_csv(snap)
    fname = f"topology_export_left_{snap.context.environment_id}_{as_of}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/export/right.csv")
async def export_right(
    session_id: str | None = None,
    environment_id: str | None = Query(None),
    scheduler: str | None = Query(None),
    as_of: str = Query("2026-10-02"),
):
    snap = _snapshot_for_export(session_id, "right", environment_id, scheduler, as_of)
    body = export_topology_csv(snap)
    fname = f"topology_export_right_{snap.context.environment_id}_{as_of}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/export/comparison.csv")
async def export_comparison(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    body = export_comparison_csv(session.result)
    return Response(
        content=body,
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
