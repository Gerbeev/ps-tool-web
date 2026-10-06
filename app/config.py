"""Application configuration loaded from env and scheduler-specific YAML files."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class EnvironmentEntry(BaseModel):
    """One scheduler environment/connection definition.

    ``endpoint_url`` remains the internal canonical field used by adapters and contexts.
    Scheduler-specific YAML files intentionally persist it as ``host`` because that is
    the native operator-facing terminology for the captured Process Scheduler data.
    """

    id: str
    environment: str = ""
    display_name: str = ""
    description: str = ""
    region: str | None = None
    connector_profile: str | None = None
    scheduler: str | None = None
    endpoint_url: str = Field(
        default="",
        validation_alias=AliasChoices("endpoint_url", "host"),
    )
    transport: str = ""
    enabled: bool = True
    source: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def derive_display_name(self) -> "EnvironmentEntry":
        """Build the UI label from the minimal persisted environment fields."""
        if not self.display_name.strip():
            base = self.environment.strip() or self.id
            description = self.description.strip()
            self.display_name = f"{base} ({description})" if description else base
        return self

    @property
    def host(self) -> str:
        """Operator-facing alias for the configured connection target."""
        return self.endpoint_url


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


class JobNamingParsing(BaseModel):
    generic_regex: str
    require_full_match: bool = True
    validate_environment_against_config: bool = False
    on_parse_failure: str = "unresolved"


class CrossEnvironmentIdentity(BaseModel):
    include: list[str] = Field(default_factory=lambda: ["business_code", "job_specific_name"])
    exclude: list[str] = Field(default_factory=lambda: ["common_prefix", "environment"])
    require_same_business_code: bool = True
    compare_job_specific_name: str = "normalized_exact"


class JobNamingNormalization(BaseModel):
    preserve_business_code: bool = True
    remove_environment_token: bool = True
    remove_common_prefix_from_identity: bool = True
    job_specific_name_case_sensitive: bool = True
    trim_outer_whitespace: bool = True


class JobNamingRulesConfig(BaseModel):
    version: int = 1
    scope: str = "scheduler_job_name"
    separator: str = "_"
    parsing: JobNamingParsing
    cross_environment_identity: CrossEnvironmentIdentity = Field(
        default_factory=CrossEnvironmentIdentity
    )
    normalization: JobNamingNormalization = Field(default_factory=JobNamingNormalization)


class AppSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True
    config_dir: Path = Field(default_factory=lambda: _repo_root() / "config")
    data_dir: Path = Field(default_factory=lambda: _repo_root() / "data")
    snapshot_cache_ttl_sec: int = 180
    search_db_path: Path = Field(default_factory=lambda: _repo_root() / "data" / "search.db")
    current_snapshot_dir: Path = Field(default_factory=lambda: _repo_root() / "data" / "runtime" / "current")
    use_mock_adapters: bool = True
    allow_connection_config_edit: bool = True
    mock_job_count: int = 0
    mock_dataset: str = "reference_2500"
    mock_reference_path: Path = Field(default_factory=lambda: _repo_root() / "data" / "mock" / "reference_topology_2500.jsonl")
    mock_scenario: str = "u1_to_u5_migration"
    mock_scenario_path: Path = Field(default_factory=lambda: _repo_root() / "data" / "mock" / "u1_to_u5_migration_overlay.jsonl")
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
        current_snapshot_dir=Path(
            os.getenv("CURRENT_SNAPSHOT_DIR", str(root / "data" / "runtime" / "current"))
        ),
        use_mock_adapters=os.getenv("USE_MOCK_ADAPTERS", "true").lower() in ("1", "true", "yes"),
        allow_connection_config_edit=os.getenv("ALLOW_CONNECTION_CONFIG_EDIT", "true").lower()
        in ("1", "true", "yes"),
        mock_job_count=int(os.getenv("MOCK_JOB_COUNT", "0")),
        mock_dataset=os.getenv("MOCK_DATASET", "reference_2500").strip().lower(),
        mock_reference_path=Path(
            os.getenv(
                "MOCK_REFERENCE_PATH",
                str(root / "data" / "mock" / "reference_topology_2500.jsonl"),
            )
        ),
        mock_scenario=os.getenv("MOCK_SCENARIO", "u1_to_u5_migration").strip().lower(),
        mock_scenario_path=Path(
            os.getenv(
                "MOCK_SCENARIO_PATH",
                str(root / "data" / "mock" / "u1_to_u5_migration_overlay.jsonl"),
            )
        ),
        table_page_size_default=int(os.getenv("TABLE_PAGE_SIZE", "0")),
    )


def _scheduler_config_filename(scheduler: str) -> str:
    if scheduler == "process_scheduler":
        return "process_scheduler_environments.yaml"
    if scheduler == "autosys":
        return "autosys_environments.yaml"
    raise ValueError(f"Unsupported scheduler: {scheduler!r}")


def scheduler_config_path(scheduler: str) -> Path:
    return get_settings().config_dir / _scheduler_config_filename(scheduler)


def _load_environment_file(path: Path, scheduler: str) -> list[EnvironmentEntry]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries: list[EnvironmentEntry] = []
    for raw in data.get("environments", []):
        payload = dict(raw)
        payload.setdefault("scheduler", scheduler)
        payload.setdefault("environment", payload.get("id", ""))
        # Display labels are UI-derived from environment + description, even when
        # loading an older config that persisted a redundant display_name field.
        payload.pop("display_name", None)
        entries.append(EnvironmentEntry.model_validate(payload))
    return entries


@lru_cache
def load_scheduler_environments(scheduler: str) -> list[EnvironmentEntry]:
    """Load all configured entries for one scheduler, including disabled entries."""
    return _load_environment_file(scheduler_config_path(scheduler), scheduler)


@lru_cache
def load_all_environments() -> list[EnvironmentEntry]:
    """Load all scheduler-specific environments for Settings and direct lookup."""
    return [
        *load_scheduler_environments("autosys"),
        *load_scheduler_environments("process_scheduler"),
    ]


@lru_cache
def load_environments() -> list[EnvironmentEntry]:
    """Load enabled environments exposed to Browse/Compare."""
    return [entry for entry in load_all_environments() if entry.enabled]


def invalidate_environment_cache() -> None:
    load_scheduler_environments.cache_clear()
    load_all_environments.cache_clear()
    load_environments.cache_clear()


def get_environment(environment_id: str) -> EnvironmentEntry | None:
    for entry in load_all_environments():
        if entry.id == environment_id:
            return entry
    return None


def endpoint_for_environment(environment_id: str) -> str:
    entry = get_environment(environment_id)
    return (entry.endpoint_url or "").strip() if entry else ""


def host_for_environment(environment_id: str) -> str:
    """Backward-compatible alias for callers that still use ``host`` terminology."""
    return endpoint_for_environment(environment_id)


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


def _environment_to_yaml(entry: EnvironmentEntry) -> dict:
    """Persist only operator-editable connection fields plus the stable technical id."""
    payload: dict[str, object] = {
        "id": entry.id,
        "environment": entry.environment,
        "host": entry.endpoint_url,
        "description": entry.description,
        "enabled": entry.enabled,
    }
    # Internal adapter selection is not an operator-facing table field, but preserve
    # it when a bank deployment explicitly configures one.
    if entry.connector_profile:
        payload["connector_profile"] = entry.connector_profile
    return payload


def save_scheduler_environments(scheduler: str, entries: list[EnvironmentEntry]) -> None:
    path = scheduler_config_path(scheduler)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scheduler": scheduler,
        "environments": [_environment_to_yaml(entry) for entry in entries],
    }
    header = (
        f"# {scheduler.replace('_', ' ').title()} environment connections.\n"
        "# Editable from Settings. Display labels are derived dynamically; secrets/credentials must not be stored here.\n"
    )
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    invalidate_environment_cache()


def save_environments(entries: list[EnvironmentEntry]) -> None:
    """Compatibility helper: split a mixed list into scheduler-specific files."""
    autosys = [e for e in entries if resolve_scheduler(e).value == "autosys"]
    process_scheduler = [e for e in entries if resolve_scheduler(e).value == "process_scheduler"]
    save_scheduler_environments("autosys", autosys)
    save_scheduler_environments("process_scheduler", process_scheduler)


@lru_cache
def load_identity_map() -> IdentityMapConfig:
    path = get_settings().config_dir / "identity_map.yaml"
    if not path.exists():
        return IdentityMapConfig()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return IdentityMapConfig.model_validate(data)


@lru_cache
def load_job_naming_rules() -> JobNamingRulesConfig | None:
    """Load the optional structured scheduler job naming contract.

    The contract is intentionally scheduler-agnostic: the embedded environment token
    is part of a native job name but is excluded from cross-environment identity.
    """
    path = get_settings().config_dir / "job_naming_rules.yaml"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not data:
        return None
    return JobNamingRulesConfig.model_validate(data)
