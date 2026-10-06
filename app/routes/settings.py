"""Settings — scheduler-specific environment connection configuration."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    EnvironmentEntry,
    get_settings,
    load_scheduler_environments,
    save_scheduler_environments,
    scheduler_config_path,
)
from app.models import SchedulerType

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _read_config_text(path: Path) -> str:
    if not path.exists():
        return "# (file not found)\n"
    return path.read_text(encoding="utf-8")


def _scheduler_or_404(value: str) -> SchedulerType:
    try:
        scheduler = SchedulerType(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown scheduler") from exc
    return scheduler


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str = ""):
    settings = get_settings()
    config_dir = settings.config_dir
    autosys = load_scheduler_environments(SchedulerType.AUTOSYS.value)
    process_scheduler = load_scheduler_environments(SchedulerType.PROCESS_SCHEDULER.value)
    autosys_path = scheduler_config_path(SchedulerType.AUTOSYS.value)
    ps_path = scheduler_config_path(SchedulerType.PROCESS_SCHEDULER.value)
    identity_path = config_dir / "identity_map.yaml"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "autosys_environments": autosys,
            "process_scheduler_environments": process_scheduler,
            "autosys_yaml": _read_config_text(autosys_path),
            "process_scheduler_yaml": _read_config_text(ps_path),
            "identity_yaml": _read_config_text(identity_path),
            "use_mock_adapters": settings.use_mock_adapters,
            "allow_connection_config_edit": settings.allow_connection_config_edit,
            "mock_dataset": settings.mock_dataset,
            "mock_reference_path": str(settings.mock_reference_path),
            "config_dir": str(config_dir),
            "autosys_config_path": str(autosys_path),
            "process_scheduler_config_path": str(ps_path),
            "identity_map_path": str(identity_path),
            "saved": saved,
        },
    )


@router.post("/api/settings/environments/{scheduler}", response_class=RedirectResponse)
async def save_environment_connections(request: Request, scheduler: str):
    scheduler_type = _scheduler_or_404(scheduler)
    settings = get_settings()
    if not settings.allow_connection_config_edit:
        raise HTTPException(
            status_code=403,
            detail="Connection editing is disabled by ALLOW_CONNECTION_CONFIG_EDIT",
        )

    form = await request.form()
    updated: list[EnvironmentEntry] = []
    for entry in load_scheduler_environments(scheduler_type.value):
        environment = (form.get(f"environment_{entry.id}") or entry.environment).strip()
        host = (form.get(f"host_{entry.id}") or "").strip()
        description = (form.get(f"description_{entry.id}") or "").strip()
        display_name = (form.get(f"display_name_{entry.id}") or "").strip()
        transport = (form.get(f"transport_{entry.id}") or "").strip()
        connector_profile = (form.get(f"connector_profile_{entry.id}") or "").strip()
        notes = (form.get(f"notes_{entry.id}") or "").strip()
        enabled = form.get(f"enabled_{entry.id}") == "on"

        updated.append(
            EnvironmentEntry(
                id=entry.id,
                environment=environment,
                display_name=display_name or environment or entry.id,
                description=description,
                region=entry.region,
                connector_profile=connector_profile or None,
                scheduler=scheduler_type.value,
                endpoint_url=host,
                transport=transport,
                enabled=enabled,
                source=entry.source,
                notes=notes,
            )
        )

    save_scheduler_environments(scheduler_type.value, updated)
    return RedirectResponse(url=f"/settings?saved={scheduler_type.value}#{scheduler_type.value}", status_code=303)
