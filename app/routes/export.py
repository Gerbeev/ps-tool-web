"""CSV exports from frozen sessions or generated snapshots only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.export_csv import iter_comparison_csv_lines, iter_topology_csv_lines
from app.services.snapshot_catalog import snapshot_catalog
from app.session_store import session_store

router = APIRouter()


@router.get("/api/export/left.csv")
async def export_left(
    session_id: str | None = None,
    snapshot_id: str | None = Query(None),
):
    snap = _snapshot_for_export(session_id, "left", snapshot_id)
    fname = f"topology_export_left_{snap.context.environment_id}_{snap.snapshot_id[:8]}.csv"
    return StreamingResponse(
        iter_topology_csv_lines(snap),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/export/right.csv")
async def export_right(
    session_id: str | None = None,
    snapshot_id: str | None = Query(None),
):
    snap = _snapshot_for_export(session_id, "right", snapshot_id)
    fname = f"topology_export_right_{snap.context.environment_id}_{snap.snapshot_id[:8]}.csv"
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


def _snapshot_for_export(session_id: str | None, side: str, snapshot_id: str | None):
    if session_id:
        session = session_store.get(session_id)
        if session:
            return session.left_snapshot if side == "left" else session.right_snapshot
    if snapshot_id:
        loaded = snapshot_catalog.load(snapshot_id)
        if loaded is not None:
            return loaded[0]
        raise HTTPException(status_code=404, detail="Snapshot not found or corrupted")
    raise HTTPException(status_code=400, detail="Provide session_id or generated snapshot_id")
