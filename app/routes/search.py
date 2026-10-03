"""Search API and HTMX partial."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.search.sqlite_fts import search_index

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/api/search")
async def search_jobs(request: Request, q: str = "", limit: int = 50, format: str = "html"):
    hits = search_index.search(q, limit=limit)
    if format == "json":
        return JSONResponse([h.model_dump() for h in hits])
    return templates.TemplateResponse(
        request,
        "partials/search_results.html",
        {"hits": hits, "query": q},
    )
