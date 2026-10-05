"""Thread-safe in-memory store for comparison sessions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from app.models import ComparisonContext, ComparisonResult, TopologySnapshot


@dataclass
class CompareSession:
    session_id: str
    left: ComparisonContext
    right: ComparisonContext
    left_snapshot: TopologySnapshot
    right_snapshot: TopologySnapshot
    result: ComparisonResult


@dataclass
class BrowseSession:
    session_id: str
    context: ComparisonContext
    snapshot: TopologySnapshot


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, CompareSession] = {}
        self._browse: dict[str, BrowseSession] = {}
        self._lock = RLock()

    def put(self, session: CompareSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            if len(self._sessions) > 20:
                oldest = next(iter(self._sessions))
                del self._sessions[oldest]

    def get(self, session_id: str) -> CompareSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def put_browse(self, session: BrowseSession) -> None:
        with self._lock:
            self._browse[session.session_id] = session
            if len(self._browse) > 20:
                oldest = next(iter(self._browse))
                del self._browse[oldest]

    def get_browse(self, session_id: str) -> BrowseSession | None:
        with self._lock:
            return self._browse.get(session_id)

    def new_id(self) -> str:
        return str(uuid4())


session_store = SessionStore()
