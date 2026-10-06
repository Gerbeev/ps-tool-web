import os

import pytest

# Existing unit/route tests exercise the compact legacy fixture unless a test explicitly
# opts into the canonical 2500-job reference dataset. The application runtime default
# remains reference_2500.
os.environ.setdefault("MOCK_DATASET", "legacy_small")


@pytest.fixture(autouse=True)
def _reset_cached_settings():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
