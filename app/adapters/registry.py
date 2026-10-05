"""Trusted in-process registry for bank-specific adapter implementations."""

from __future__ import annotations

from collections.abc import Callable

from app.adapters.base import SchedulerAdapter
from app.config import EnvironmentEntry

AdapterFactory = Callable[[EnvironmentEntry], SchedulerAdapter]

_FACTORIES: dict[str, AdapterFactory] = {}


def register_adapter(profile: str, factory: AdapterFactory) -> None:
    key = profile.strip()
    if not key:
        raise ValueError("adapter profile must not be empty")
    if key in _FACTORIES:
        raise ValueError(f"adapter profile already registered: {key}")
    _FACTORIES[key] = factory


def create_registered_adapter(profile: str, environment: EnvironmentEntry) -> SchedulerAdapter:
    try:
        factory = _FACTORIES[profile]
    except KeyError as exc:
        available = ", ".join(sorted(_FACTORIES)) or "<none>"
        raise LookupError(
            f"No real adapter registered for connector_profile={profile!r}. "
            f"Registered profiles: {available}"
        ) from exc
    return factory(environment)


def registered_profiles() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))
