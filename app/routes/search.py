"""Search API and HTMX partial."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.search.sqlite_fts import search_index
from app.session_store import session_store

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _snapshot_ids_for_session(session_id: str) -> list[str] | None:
    compare = session_store.get(session_id)
    if compare:
        return [compare.left_snapshot.snapshot_id, compare.right_snapshot.snapshot_id]
    browse = session_store.get_browse(session_id)
    if browse:
        return [browse.snapshot.snapshot_id]
    return None


@router.get("/api/search")
async def search_jobs(
    request: Request,
    q: str = "",
    limit: int = 50,
    format: str = "html",
    session_id: str | None = None,
    side: str | None = None,
):
    if not session_id:
        hits = []
    else:
        snapshot_ids = _snapshot_ids_for_session(session_id)
        if snapshot_ids is None:
            hits = []
        else:
            hits = search_index.search(
                q,
                limit=limit,
                snapshot_ids=snapshot_ids,
                side=side,
            )
    if format == "json":
        return JSONResponse([h.model_dump() for h in hits])
    return templates.TemplateResponse(
        request,
        "partials/search_results.html",
        {"hits": hits, "query": q},
    )
