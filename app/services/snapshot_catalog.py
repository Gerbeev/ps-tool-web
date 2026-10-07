"""Durable immutable snapshot catalog used by Snapshots, Browse, and Compare."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import get_settings
from app.models import ComparisonContext, SchedulerType, TopologySnapshot
from app.services.topology_index import ensure_topology_indexes


class SnapshotRecord(BaseModel):
    """Small durable catalog entry for one immutable topology snapshot."""

    schema_version: int = 1
    snapshot_id: str
    captured_at: datetime
    fetched_at: datetime
    scheduler: SchedulerType
    environment_id: str
    context: ComparisonContext
    job_count: int
    edge_count: int
    topology_id: str | None = None
    business_date: str | None = None
    filename: str
    sha256: str

    @property
    def source_scope(self) -> str:
        if self.scheduler == SchedulerType.PROCESS_SCHEDULER:
            return self.topology_id or "—"
        return self.business_date or self.context.as_of.value or "—"

    @property
    def label(self) -> str:
        scheduler = "AutoSys" if self.scheduler == SchedulerType.AUTOSYS else "Process Scheduler"
        scope_label = "date" if self.scheduler == SchedulerType.AUTOSYS else "topology"
        short_id = self.snapshot_id[:8]
        captured = self.captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"{scheduler} · {scope_label} {self.source_scope} · {captured} · {short_id}"


class SnapshotCatalogIndex(BaseModel):
    schema_version: int = 1
    snapshots: list[SnapshotRecord] = Field(default_factory=list)


class SnapshotCatalogStore:
    """Persist snapshots as immutable gzip payloads with an atomically written index."""

    _EPHEMERAL_METADATA_KEYS = {
        "children_index",
        "jobs_by_uid",
        "match_confidence_by_uid",
    }

    def __init__(self) -> None:
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return get_settings().snapshot_dir

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

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

    @staticmethod
    def _write_bytes_atomic(path: Path, data: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _read_index(self) -> SnapshotCatalogIndex:
        try:
            raw = self.index_path.read_text(encoding="utf-8")
            return SnapshotCatalogIndex.model_validate_json(raw)
        except (FileNotFoundError, OSError, ValueError):
            return SnapshotCatalogIndex()

    def _write_index(self, index: SnapshotCatalogIndex) -> None:
        data = json.dumps(index.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8")
        self._write_bytes_atomic(self.index_path, data)

    def save(self, snapshot: TopologySnapshot) -> SnapshotRecord:
        """Persist a new immutable snapshot and append it to the catalog."""
        data = self._snapshot_bytes(snapshot)
        snapshot_id = snapshot.snapshot_id
        filename = f"{snapshot_id}.snapshot.json.gz"
        topology_id = snapshot.context.filters.topology_id or snapshot.context.filters.root_box
        business_date = (
            snapshot.context.as_of.value
            if snapshot.context.scheduler == SchedulerType.AUTOSYS
            else None
        )
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            captured_at=datetime.now(timezone.utc),
            fetched_at=snapshot.fetched_at,
            scheduler=snapshot.context.scheduler,
            environment_id=snapshot.context.environment_id,
            context=snapshot.context,
            job_count=len(snapshot.flat_jobs),
            edge_count=len(snapshot.edges),
            topology_id=(
                topology_id
                if snapshot.context.scheduler == SchedulerType.PROCESS_SCHEDULER
                else None
            ),
            business_date=business_date,
            filename=filename,
            sha256=self._sha256(data),
        )

        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / filename
            if target.exists():
                raise ValueError(f"Snapshot {snapshot_id!r} already exists")
            self._write_bytes_atomic(target, data)
            index = self._read_index()
            if any(item.snapshot_id == snapshot_id for item in index.snapshots):
                try:
                    target.unlink()
                except OSError:
                    pass
                raise ValueError(f"Snapshot {snapshot_id!r} already exists in catalog")
            index.snapshots.append(record)
            self._write_index(index)
        return record

    def list(
        self,
        *,
        environment_id: str | None = None,
        scheduler: SchedulerType | None = None,
    ) -> list[SnapshotRecord]:
        with self._lock:
            records = list(self._read_index().snapshots)
        if environment_id is not None:
            records = [item for item in records if item.environment_id == environment_id]
        if scheduler is not None:
            records = [item for item in records if item.scheduler == scheduler]
        records.sort(key=lambda item: item.captured_at, reverse=True)
        return records

    def get_record(self, snapshot_id: str) -> SnapshotRecord | None:
        with self._lock:
            for item in self._read_index().snapshots:
                if item.snapshot_id == snapshot_id:
                    return item
        return None

    def load(self, snapshot_id: str) -> tuple[TopologySnapshot, SnapshotRecord] | None:
        with self._lock:
            record = self.get_record(snapshot_id)
            if record is None:
                return None
            try:
                data = (self.root / record.filename).read_bytes()
            except OSError:
                return None
            if self._sha256(data) != record.sha256:
                return None
            try:
                snapshot = self._snapshot_from_bytes(data)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return None
        return snapshot, record

    def clear(self) -> None:
        """Test/admin helper. Runtime UI does not delete historical snapshots."""
        with self._lock:
            if not self.root.exists():
                return
            for path in self.root.iterdir():
                if path.is_file():
                    try:
                        path.unlink()
                    except OSError:
                        pass


snapshot_catalog = SnapshotCatalogStore()
