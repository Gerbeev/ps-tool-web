"""Adapter factory for mock mode and isolated workstation connector scripts."""

from __future__ import annotations

from app.adapters.autosys import AutoSysMockAdapter
from app.adapters.base import SchedulerAdapter
from app.adapters.bridge import ExternalBridgeAdapter
from app.adapters.process_scheduler import ProcessSchedulerMockAdapter
from app.config import get_environment, get_settings
from app.models import SchedulerType


def get_adapter(scheduler: SchedulerType, environment_id: str) -> SchedulerAdapter:
    """Instantiate the adapter for an environment.

    Production connectivity is intentionally out-of-process. The portable web project
    never imports bank-only connector modules; it talks to fixed workstation scripts
    through scheduler-bridge/v1.
    """
    settings = get_settings()
    if settings.use_mock_adapters:
        if scheduler == SchedulerType.AUTOSYS:
            return AutoSysMockAdapter()
        if scheduler == SchedulerType.PROCESS_SCHEDULER:
            return ProcessSchedulerMockAdapter()
        raise ValueError(f"Unknown scheduler: {scheduler}")

    environment = get_environment(environment_id)
    if environment is None:
        raise LookupError(f"Unknown environment: {environment_id!r}")
    configured_scheduler = environment.scheduler
    if configured_scheduler and configured_scheduler != scheduler.value:
        raise ValueError(
            f"Environment {environment_id!r} is configured for {configured_scheduler!r}, "
            f"but context requests {scheduler.value!r}"
        )
    return ExternalBridgeAdapter(environment, scheduler)
