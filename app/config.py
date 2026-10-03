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
    )


@lru_cache
def load_environments() -> list[EnvironmentEntry]:
    path = get_settings().config_dir / "environments.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [EnvironmentEntry.model_validate(e) for e in data.get("environments", [])]


@lru_cache
def load_identity_map() -> IdentityMapConfig:
    path = get_settings().config_dir / "identity_map.yaml"
    if not path.exists():
        return IdentityMapConfig()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return IdentityMapConfig.model_validate(data)
