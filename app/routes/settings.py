"""Settings — environment scheduler bindings and config preview."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    EnvironmentEntry,
    get_settings,
    load_environments,
    resolve_scheduler,
    save_environments,
)
from app.models import SchedulerType

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _read_config_text(path: Path) -> str:
    if not path.exists():
        return "# (file not found)\n"
    return path.read_text(encoding="utf-8")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = 0):
    settings = get_settings()
    config_dir = settings.config_dir
    env_yaml = _read_config_text(config_dir / "environments.yaml")
    identity_yaml = _read_config_text(config_dir / "identity_map.yaml")
    envs = load_environments()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "environments": envs,
            "resolved_schedulers": {e.id: resolve_scheduler(e).value for e in envs},
            "env_yaml": env_yaml,
            "identity_yaml": identity_yaml,
            "use_mock_adapters": settings.use_mock_adapters,
            "config_dir": str(config_dir),
            "identity_map_path": str(config_dir / "identity_map.yaml"),
            "saved": bool(saved),
            "scheduler_choices": [
                (SchedulerType.AUTOSYS.value, "AutoSys"),
                (SchedulerType.PROCESS_SCHEDULER.value, "Process Scheduler"),
            ],
        },
    )


@router.post("/api/settings/environments", response_class=RedirectResponse)
async def save_environment_schedulers(request: Request):
    form = await request.form()
    allow_endpoint_edit = get_settings().use_mock_adapters
    updated: list[EnvironmentEntry] = []
    for entry in load_environments():
        sched = form.get(f"scheduler_{entry.id}")
        if sched not in (SchedulerType.AUTOSYS.value, SchedulerType.PROCESS_SCHEDULER.value):
            sched = resolve_scheduler(entry).value
        endpoint_url = entry.endpoint_url
        if allow_endpoint_edit:
            endpoint_url = (form.get(f"endpoint_url_{entry.id}") or "").strip()
        updated.append(
            EnvironmentEntry(
                id=entry.id,
                display_name=entry.display_name,
                region=entry.region,
                connector_profile=entry.connector_profile,
                scheduler=sched,
                endpoint_url=endpoint_url,
            )
        )
    save_environments(updated)
    return RedirectResponse(url="/settings?saved=1", status_code=303)
