"""Application configuration loaded from env and YAML."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class EnvironmentEntry(BaseModel):
    id: str
    display_name: str
    region: str | None = None
    connector_profile: str | None = None
    """autosys | process_scheduler — default scheduler when this env is selected."""
    scheduler: str | None = None
    """Scheduler API / agent host (hostname or URL) for this environment."""
    host: str = ""


class IdentityPair(BaseModel):
    autosys_name: str
    ps_name: str


class IdentityRegexRule(BaseModel):
    pattern: str
    ps_replacement: str
    scheduler: str = "autosys"


class IdentityNormalize(BaseModel):
    strip_prefixes: list[str] = Field(default_factory=list)
    lowercase: bool = False


class IdentityMapConfig(BaseModel):
    pairs: list[IdentityPair] = Field(default_factory=list)
    regex_rules: list[IdentityRegexRule] = Field(default_factory=list)
    normalize: IdentityNormalize = Field(default_factory=IdentityNormalize)


class AppSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True
    config_dir: Path = Field(default_factory=lambda: _repo_root() / "config")
    data_dir: Path = Field(default_factory=lambda: _repo_root() / "data")
    snapshot_cache_ttl_sec: int = 180
    search_db_path: Path = Field(default_factory=lambda: _repo_root() / "data" / "search.db")
    use_mock_adapters: bool = True
    mock_job_count: int = 0
    table_page_size_default: int = 0  # 0 = show all rows on first load


@lru_cache
def get_settings() -> AppSettings:
    root = _repo_root()
    return AppSettings(
        host=os.getenv("PS_TOOL_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("PS_TOOL_WEB_PORT", "8000")),
        reload=os.getenv("PS_TOOL_WEB_RELOAD", "true").lower() in ("1", "true", "yes"),
        config_dir=Path(os.getenv("PS_TOOL_CONFIG_DIR", str(root / "config"))),
        data_dir=Path(os.getenv("PS_TOOL_DATA_DIR", str(root / "data"))),
        snapshot_cache_ttl_sec=int(os.getenv("SNAPSHOT_CACHE_TTL_SEC", "180")),
        search_db_path=Path(os.getenv("SEARCH_DB_PATH", str(root / "data" / "search.db"))),
        use_mock_adapters=os.getenv("USE_MOCK_ADAPTERS", "true").lower() in ("1", "true", "yes"),
        mock_job_count=int(os.getenv("MOCK_JOB_COUNT", "0")),
        table_page_size_default=int(os.getenv("TABLE_PAGE_SIZE", "0")),
    )


@lru_cache
def load_environments() -> list[EnvironmentEntry]:
    path = get_settings().config_dir / "environments.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [EnvironmentEntry.model_validate(e) for e in data.get("environments", [])]


def invalidate_environment_cache() -> None:
    load_environments.cache_clear()


def get_environment(environment_id: str) -> EnvironmentEntry | None:
    for entry in load_environments():
        if entry.id == environment_id:
            return entry
    return None


def host_for_environment(environment_id: str) -> str:
    entry = get_environment(environment_id)
    return (entry.host or "").strip() if entry else ""


def scheduler_for_environment(environment_id: str):
    from app.models import SchedulerType

    entry = get_environment(environment_id)
    if entry:
        return resolve_scheduler(entry)
    return SchedulerType.AUTOSYS


def resolve_scheduler(entry: EnvironmentEntry):
    from app.models import SchedulerType

    if entry.scheduler in (SchedulerType.AUTOSYS.value, SchedulerType.PROCESS_SCHEDULER.value):
        return SchedulerType(entry.scheduler)
    profile = (entry.connector_profile or "").lower()
    if profile.endswith("_ps") or "_ps_" in profile or profile == "test_ps":
        return SchedulerType.PROCESS_SCHEDULER
    return SchedulerType.AUTOSYS


def save_environments(entries: list[EnvironmentEntry]) -> None:
    path = get_settings().config_dir / "environments.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environments": [
            {k: v for k, v in entry.model_dump().items() if v is not None and v != ""}
            for entry in entries
        ]
    }
    header = "# Environment definitions — host & scheduler editable in Settings UI\n"
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    invalidate_environment_cache()


@lru_cache
def load_identity_map() -> IdentityMapConfig:
    path = get_settings().config_dir / "identity_map.yaml"
    if not path.exists():
        return IdentityMapConfig()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return IdentityMapConfig.model_validate(data)
