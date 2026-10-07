import os

import pytest

# Existing unit tests exercise the compact fixture unless a test explicitly opts into
# the canonical 2500-job dataset. Runtime default remains reference_2500.
os.environ.setdefault("MOCK_DATASET", "legacy_small")


@pytest.fixture(autouse=True)
def _reset_cached_settings(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
