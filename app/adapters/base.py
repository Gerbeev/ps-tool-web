"""Scheduler adapter ABC and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    FieldSupport,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)


class SchedulerAdapter(ABC):
    """Boundary between scheduler-specific retrieval and the comparison engine.

    Real adapters should normalize native data into ``TopologySnapshot`` and declare
    any fields they cannot provide instead of fabricating empty values.
    """

    scheduler_type: SchedulerType

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()

    @abstractmethod
    def health_check(self, environment_id: str) -> bool:
        """Quick availability check for API/CLI."""

    @abstractmethod
    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        """Load tree, flat job list, real dependency edges, and normalized fields."""

    @abstractmethod
    def fetch_job_detail(
        self, context: ComparisonContext, job_uid: str
    ) -> SnapshotJob | None:
        """Optional lazy load of extended job fields."""

    def list_roots(self, context: ComparisonContext) -> list[str]:
        """Box/topology roots for UI selection."""
        return []


def complete_parameter_support(
    default: FieldSupport = FieldSupport.SUPPORTED,
    *,
    overrides: dict[str, FieldSupport] | None = None,
) -> dict[str, FieldSupport]:
    """Return an explicit support declaration for every engine comparison field."""
    from app.autosys_reference import load_compare_parameters

    parameters = set(load_compare_parameters().all_parameters)
    parameters.update({"status", "dependencies", "topology_parent"})
    support = {parameter: default for parameter in parameters}
    support.update(overrides or {})
    return support

class EndpointSchedulerAdapter(SchedulerAdapter):
    """Base class for bank adapters backed by a configured HTTP(S) endpoint.

    It intentionally does not prescribe authentication, DTO shape, pagination, or the
    HTTP client. Those remain bank-specific. The only shared responsibility here is
    validating and exposing the configured service boundary.
    """

    def __init__(self, environment) -> None:
        from urllib.parse import urlsplit

        endpoint_url = (environment.endpoint_url or "").strip().rstrip("/")
        if not endpoint_url:
            raise ValueError(f"endpoint_url is required for environment {environment.id!r}")
        parsed = urlsplit(endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"endpoint_url must be an absolute http(s) URL for environment {environment.id!r}"
            )
        if parsed.username or parsed.password:
            raise ValueError("endpoint_url must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("endpoint_url must be a base URL without query or fragment")

        self.environment = environment
        self.endpoint_url = endpoint_url
