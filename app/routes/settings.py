"""Settings shell — config preview and adapter mode."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings, load_environments

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _read_config_text(path: Path) -> str:
    if not path.exists():
        return "# (file not found)\n"
    return path.read_text(encoding="utf-8")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    settings = get_settings()
    config_dir = settings.config_dir
    env_yaml = _read_config_text(config_dir / "environments.yaml")
    identity_yaml = _read_config_text(config_dir / "identity_map.yaml")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "environments": load_environments(),
            "env_yaml": env_yaml,
            "identity_yaml": identity_yaml,
            "use_mock_adapters": settings.use_mock_adapters,
            "config_dir": str(config_dir),
            "identity_map_path": str(config_dir / "identity_map.yaml"),
        },
    )
