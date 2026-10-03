"""In-memory LRU snapshot cache."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from threading import Lock

from app.config import get_settings
from app.models import ComparisonContext, TopologySnapshot


class SnapshotCache:
    def __init__(self, ttl_sec: int | None = None, max_size: int = 32) -> None:
        settings = get_settings()
        self._ttl = ttl_sec if ttl_sec is not None else settings.snapshot_cache_ttl_sec
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, TopologySnapshot]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def context_key(context: ComparisonContext, scheduler: str) -> str:
        payload = context.model_dump(mode="json")
        raw = json.dumps({"scheduler": scheduler, "ctx": payload}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> TopologySnapshot | None:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, snap = entry
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return snap

    def set(self, key: str, snapshot: TopologySnapshot) -> None:
        with self._lock:
            self._store[key] = (time.time(), snapshot)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def invalidate_pair(self, left_key: str, right_key: str) -> None:
        with self._lock:
            self._store.pop(left_key, None)
            self._store.pop(right_key, None)


snapshot_cache = SnapshotCache()
