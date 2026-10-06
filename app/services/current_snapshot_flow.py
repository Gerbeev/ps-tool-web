"""Capture/reuse flow for the single current comparison snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ComparisonContext, TopologySnapshot
from app.services.comparison import fetch_snapshot
from app.services.current_snapshot import (
    CurrentSnapshotManifest,
    current_snapshot_store,
)


class SnapshotCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CurrentPair:
    left: TopologySnapshot
    right: TopologySnapshot
    manifest: CurrentSnapshotManifest
    origin: str  # current | captured


def _require_valid(snapshot: TopologySnapshot, label: str) -> None:
    report = snapshot.metadata.get("validation_report") or {}
    if report.get("is_valid") is False:
        errors = report.get("error_count", 0)
        raise SnapshotCaptureError(f"{label} snapshot validation failed ({errors} errors)")


def get_or_capture_current_pair(
    left: ComparisonContext,
    right: ComparisonContext,
    *,
    refresh: bool = False,
) -> CurrentPair:
    """Reuse the current exact pair, or atomically replace it after fetching both sides."""
    if not refresh:
        loaded = current_snapshot_store.load_pair(left, right)
        if loaded is not None:
            left_snapshot, right_snapshot, manifest = loaded
            return CurrentPair(left_snapshot, right_snapshot, manifest, "current")

    # Fetch both first. Nothing durable is changed unless both fetch/validation steps pass.
    try:
        left_snapshot, _ = fetch_snapshot(left, force_refresh=True)
        _require_valid(left_snapshot, "Left")
        right_snapshot, _ = fetch_snapshot(right, force_refresh=True)
        _require_valid(right_snapshot, "Right")
    except SnapshotCaptureError:
        raise
    except Exception as exc:  # adapters surface their own structured errors when available
        raise SnapshotCaptureError(str(exc)) from exc

    manifest = current_snapshot_store.save_pair(left_snapshot, right_snapshot)
    return CurrentPair(left_snapshot, right_snapshot, manifest, "captured")
