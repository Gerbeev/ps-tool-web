"""Snapshot generation and catalog UI.

This router is the only web surface that may call scheduler adapters/bridge operations.
Browse and Compare consume the durable snapshot catalog only.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import load_environments, scheduler_for_environment
from app.models import SchedulerType
from app.search.sqlite_fts import search_index
from app.services.snapshot_catalog import snapshot_catalog
from app.services.snapshot_generation import (
    SnapshotGenerationError,
    autosys_business_date,
    generate_snapshot,
    list_process_scheduler_topologies,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@dataclass(frozen=True)
class SnapshotEnvironmentOption:
    id: str
    label: str


def _env_options() -> list[SnapshotEnvironmentOption]:
    options: list[SnapshotEnvironmentOption] = []
    for env in load_environments():
        scheduler = scheduler_for_environment(env.id)
        suffix = "PS" if scheduler == SchedulerType.PROCESS_SCHEDULER else "AutoSys"
        options.append(SnapshotEnvironmentOption(id=env.id, label=f"{env.environment}-{suffix}"))
    return options


def _source_form_context(environment_id: str, *, load_topologies: bool) -> dict:
    scheduler = scheduler_for_environment(environment_id)
    topologies: list[str] = []
    topology_error = ""
    if scheduler == SchedulerType.PROCESS_SCHEDULER and load_topologies:
        try:
            topologies = list_process_scheduler_topologies(environment_id)
        except SnapshotGenerationError as exc:
            topology_error = str(exc)
    return {
        "environment_id": environment_id,
        "scheduler": scheduler.value,
        "autosys_business_date": autosys_business_date(),
        "topologies": topologies,
        "topology_error": topology_error,
    }


@router.get("/snapshots", response_class=HTMLResponse)
async def snapshots_page(request: Request):
    environments = _env_options()
    default_env = environments[0].id if environments else ""
    context = _source_form_context(default_env, load_topologies=True) if default_env else {
        "environment_id": "",
        "scheduler": "",
        "autosys_business_date": autosys_business_date(),
        "topologies": [],
        "topology_error": "",
    }
    return templates.TemplateResponse(
        request,
        "snapshots.html",
        {
            "environments": environments,
            **context,
            "snapshots": snapshot_catalog.list(),
        },
    )


@router.get("/api/snapshots/source-form", response_class=HTMLResponse)
async def snapshot_source_form(
    request: Request,
    environment_id: str = Query(...),
):
    context = _source_form_context(environment_id, load_topologies=True)
    return templates.TemplateResponse(
        request,
        "partials/snapshot_source_fields.html",
        context,
    )


@router.post("/api/snapshots/generate", response_class=HTMLResponse)
async def snapshot_generate(
    request: Request,
    environment_id: str = Form(...),
    topology_id: str = Form(""),
):
    try:
        generated = generate_snapshot(environment_id, topology_id=topology_id)
    except SnapshotGenerationError as exc:
        return templates.TemplateResponse(
            request,
            "partials/snapshot_catalog.html",
            {
                "snapshots": snapshot_catalog.list(),
                "generation_error": str(exc),
                "generated": None,
            },
        )

    return templates.TemplateResponse(
        request,
        "partials/snapshot_catalog.html",
        {
            "snapshots": snapshot_catalog.list(),
            "generation_error": "",
            "generated": generated.record,
        },
    )


@router.post("/api/snapshots/delete", response_class=HTMLResponse)
async def snapshot_delete(
    request: Request,
    snapshot_id: str = Form(...),
):
    try:
        deleted = snapshot_catalog.delete(snapshot_id)
    except (OSError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "partials/snapshot_catalog.html",
            {
                "snapshots": snapshot_catalog.list(),
                "catalog_error": str(exc),
                "deleted": None,
            },
        )

    if deleted is not None:
        search_index.delete_snapshot(deleted.snapshot_id)

    return templates.TemplateResponse(
        request,
        "partials/snapshot_catalog.html",
        {
            "snapshots": snapshot_catalog.list(),
            "catalog_error": "" if deleted else "Snapshot was not found.",
            "deleted": deleted,
        },
    )
