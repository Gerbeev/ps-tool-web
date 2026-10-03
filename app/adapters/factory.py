"""Adapter factory — swap mock vs real connectors here."""

from __future__ import annotations

from app.adapters.autosys import AutoSysMockAdapter
from app.adapters.base import SchedulerAdapter
from app.adapters.process_scheduler import ProcessSchedulerMockAdapter
from app.config import get_settings
from app.models import SchedulerType


def get_adapter(scheduler: SchedulerType, environment_id: str) -> SchedulerAdapter:
    """Instantiate adapter for scheduler type and environment.

    Real UBS connectors should be wired when ``USE_MOCK_ADAPTERS=false``:
    import connectors.autosys / connectors.process_scheduler and wrap them
    in new SchedulerAdapter implementations alongside the mocks.
    """
    _ = environment_id  # reserved for connector_profile / credentials lookup
    settings = get_settings()
    if settings.use_mock_adapters:
        if scheduler == SchedulerType.AUTOSYS:
            return AutoSysMockAdapter()
        if scheduler == SchedulerType.PROCESS_SCHEDULER:
            return ProcessSchedulerMockAdapter()
        raise ValueError(f"Unknown scheduler: {scheduler}")
    raise NotImplementedError(
        "Real connectors are not bundled in Phase 2. "
        "Set USE_MOCK_ADAPTERS=true or implement adapters in app/adapters/."
    )
