"""Endpoint adapter boundary and URL safety checks."""

import pytest

from app.adapters.base import EndpointSchedulerAdapter
from app.config import EnvironmentEntry
from app.models import SchedulerType


class _EndpointAdapter(EndpointSchedulerAdapter):
    scheduler_type = SchedulerType.AUTOSYS

    def health_check(self, environment_id: str) -> bool:
        return True

    def fetch_topology(self, context):
        raise NotImplementedError

    def fetch_job_detail(self, context, job_uid):
        return None


def test_endpoint_adapter_accepts_absolute_https_base_url():
    env = EnvironmentEntry(
        id="uat",
        display_name="UAT",
        endpoint_url="https://scheduler.internal/api/",
    )
    adapter = _EndpointAdapter(env)
    assert adapter.endpoint_url == "https://scheduler.internal/api"


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "scheduler.internal/api",
        "file:///etc/passwd",
        "https://user:secret@scheduler.internal/api",
        "https://scheduler.internal/api?target=other",
        "https://scheduler.internal/api#fragment",
    ],
)
def test_endpoint_adapter_rejects_unsafe_base_urls(endpoint_url: str):
    env = EnvironmentEntry(id="uat", display_name="UAT", endpoint_url=endpoint_url)
    with pytest.raises(ValueError):
        _EndpointAdapter(env)
