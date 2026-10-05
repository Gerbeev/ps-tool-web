"""Adapter factory for mock and bank-specific connectors."""

from __future__ import annotations

# Import the trusted registration hook once. Bank builds can add explicit adapter
# registrations there without making connector class paths configuration-controlled.
from app.adapters import site as _site  # noqa: F401
from app.adapters.autosys import AutoSysMockAdapter
from app.adapters.base import SchedulerAdapter
from app.adapters.process_scheduler import ProcessSchedulerMockAdapter
from app.adapters.registry import create_registered_adapter
from app.config import get_environment, get_settings
from app.models import SchedulerType


def get_adapter(scheduler: SchedulerType, environment_id: str) -> SchedulerAdapter:
    """Instantiate the adapter configured for an environment."""
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
    profile = (environment.connector_profile or "").strip()
    if not profile:
        raise LookupError(
            f"Environment {environment_id!r} has no connector_profile for a real adapter"
        )
    adapter = create_registered_adapter(profile, environment)
    if adapter.scheduler_type != scheduler:
        raise ValueError(
            f"Adapter profile {profile!r} declares {adapter.scheduler_type.value!r}, "
            f"but context requests {scheduler.value!r}"
        )
    return adapter
