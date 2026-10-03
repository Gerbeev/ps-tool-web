"""In-memory store for the latest comparison session (Phase 2 dev)."""

from __future__ import annotations

from dataclasses import dataclass, field
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


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, CompareSession] = {}

    def put(self, session: CompareSession) -> None:
        self._sessions[session.session_id] = session
        if len(self._sessions) > 20:
            oldest = next(iter(self._sessions))
            del self._sessions[oldest]

    def get(self, session_id: str) -> CompareSession | None:
        return self._sessions.get(session_id)

    def new_id(self) -> str:
        return str(uuid4())


session_store = SessionStore()
