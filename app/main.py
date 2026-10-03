"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import compare, export, search

app = FastAPI(title="ps-tool-web", description="AutoSys vs Process Scheduler comparison UI")

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(compare.router)
app.include_router(search.router)
app.include_router(export.router)


@app.get("/health")
def health():
    return {"status": "ok"}
