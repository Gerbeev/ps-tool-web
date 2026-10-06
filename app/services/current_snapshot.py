"""Single durable current comparison snapshot bundle.

The store intentionally keeps only one active comparison capture. New captures are
written under a new capture id and become visible only after ``manifest.json`` is
atomically replaced. Previous generation files are deleted after a successful commit.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from app.config import get_settings
from app.models import ComparisonContext, TopologySnapshot
from app.services.topology_index import ensure_topology_indexes


class SnapshotSideManifest(BaseModel):
    scheduler: str
    environment_id: str
    context: dict
    fetched_at: datetime
    job_count: int
    edge_count: int
    filename: str
    sha256: str


class CurrentSnapshotManifest(BaseModel):
    schema_version: int = 1
    capture_id: str
    captured_at: datetime
    left: SnapshotSideManifest
    right: SnapshotSideManifest


class CurrentSnapshotStore:
    """Persist and load exactly one active left/right snapshot pair."""

    _EPHEMERAL_METADATA_KEYS = {
        "children_index",
        "jobs_by_uid",
        "match_confidence_by_uid",
    }

    def __init__(self) -> None:
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return get_settings().current_snapshot_dir

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @staticmethod
    def _context_payload(context: ComparisonContext) -> dict:
        return context.model_dump(mode="json")

    @classmethod
    def _snapshot_bytes(cls, snapshot: TopologySnapshot) -> bytes:
        payload = snapshot.model_dump(mode="json")
        metadata = dict(payload.get("metadata") or {})
        for key in cls._EPHEMERAL_METADATA_KEYS:
            metadata.pop(key, None)
        payload["metadata"] = metadata
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return gzip.compress(raw, compresslevel=6, mtime=0)

    @staticmethod
    def _snapshot_from_bytes(data: bytes) -> TopologySnapshot:
        payload = json.loads(gzip.decompress(data).decode("utf-8"))
        snapshot = TopologySnapshot.model_validate(payload)
        ensure_topology_indexes(snapshot)
        return snapshot

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _write_bytes_atomic(self, path: Path, data: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _write_manifest_atomic(self, manifest: CurrentSnapshotManifest) -> None:
        data = json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._write_bytes_atomic(self.manifest_path, data)

    def load_manifest(self) -> CurrentSnapshotManifest | None:
        with self._lock:
            try:
                raw = self.manifest_path.read_text(encoding="utf-8")
                return CurrentSnapshotManifest.model_validate_json(raw)
            except (FileNotFoundError, OSError, ValueError):
                return None

    def save_pair(
        self,
        left: TopologySnapshot,
        right: TopologySnapshot,
    ) -> CurrentSnapshotManifest:
        """Atomically publish a new current pair, then discard the previous generation."""
        capture_id = uuid4().hex
        captured_at = datetime.now(timezone.utc)
        left_name = f"left-{capture_id}.snapshot.json.gz"
        right_name = f"right-{capture_id}.snapshot.json.gz"
        left_data = self._snapshot_bytes(left)
        right_data = self._snapshot_bytes(right)

        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)

            # Generation files are complete before manifest publication. Until the
            # manifest switch, readers continue to see the previous valid capture.
            self._write_bytes_atomic(self.root / left_name, left_data)
            self._write_bytes_atomic(self.root / right_name, right_data)

            manifest = CurrentSnapshotManifest(
                capture_id=capture_id,
                captured_at=captured_at,
                left=SnapshotSideManifest(
                    scheduler=left.context.scheduler.value,
                    environment_id=left.context.environment_id,
                    context=self._context_payload(left.context),
                    fetched_at=left.fetched_at,
                    job_count=len(left.flat_jobs),
                    edge_count=len(left.edges),
                    filename=left_name,
                    sha256=self._sha256(left_data),
                ),
                right=SnapshotSideManifest(
                    scheduler=right.context.scheduler.value,
                    environment_id=right.context.environment_id,
                    context=self._context_payload(right.context),
                    fetched_at=right.fetched_at,
                    job_count=len(right.flat_jobs),
                    edge_count=len(right.edges),
                    filename=right_name,
                    sha256=self._sha256(right_data),
                ),
            )
            self._write_manifest_atomic(manifest)
            self._cleanup_generations(keep={left_name, right_name})
            return manifest

    def _cleanup_generations(self, *, keep: set[str]) -> None:
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return
        for path in entries:
            if path.name == "manifest.json" or path.name in keep:
                continue
            if path.name.endswith(".snapshot.json.gz") or path.name.endswith(".tmp"):
                try:
                    path.unlink()
                except OSError:
                    pass

    def _read_side(self, side: SnapshotSideManifest) -> TopologySnapshot | None:
        try:
            data = (self.root / side.filename).read_bytes()
        except OSError:
            return None
        if self._sha256(data) != side.sha256:
            return None
        try:
            snapshot = self._snapshot_from_bytes(data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        snapshot.metadata["current_snapshot_capture_id"] = side.filename.split("-")[-1].split(".")[0]
        return snapshot

    def pair_status(
        self,
        left: ComparisonContext,
        right: ComparisonContext,
    ) -> Literal["current", "reversed", "stale", "none"]:
        manifest = self.load_manifest()
        if manifest is None:
            return "none"
        left_payload = self._context_payload(left)
        right_payload = self._context_payload(right)
        if manifest.left.context == left_payload and manifest.right.context == right_payload:
            return "current"
        if manifest.left.context == right_payload and manifest.right.context == left_payload:
            return "reversed"
        return "stale"

    def load_pair(
        self,
        left: ComparisonContext,
        right: ComparisonContext,
    ) -> tuple[TopologySnapshot, TopologySnapshot, CurrentSnapshotManifest] | None:
        with self._lock:
            manifest = self.load_manifest()
            if manifest is None:
                return None
            status = self.pair_status(left, right)
            if status not in {"current", "reversed"}:
                return None
            stored_left = self._read_side(manifest.left)
            stored_right = self._read_side(manifest.right)
            if stored_left is None or stored_right is None:
                return None
            if status == "reversed":
                return stored_right, stored_left, manifest
            return stored_left, stored_right, manifest

    def load_for_context(
        self,
        context: ComparisonContext,
    ) -> tuple[TopologySnapshot, CurrentSnapshotManifest, str] | None:
        """Return the matching current side for Browse, if the context is exact."""
        with self._lock:
            manifest = self.load_manifest()
            if manifest is None:
                return None
            payload = self._context_payload(context)
            if manifest.left.context == payload:
                snapshot = self._read_side(manifest.left)
                return (snapshot, manifest, "left") if snapshot is not None else None
            if manifest.right.context == payload:
                snapshot = self._read_side(manifest.right)
                return (snapshot, manifest, "right") if snapshot is not None else None
            return None

    def clear(self) -> None:
        """Test/admin helper. The product UI intentionally exposes no history manager."""
        with self._lock:
            if not self.root.exists():
                return
            for path in self.root.iterdir():
                if path.is_file():
                    try:
                        path.unlink()
                    except OSError:
                        pass


current_snapshot_store = CurrentSnapshotStore()
