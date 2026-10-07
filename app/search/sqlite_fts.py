"""SQLite FTS5 search index."""

from __future__ import annotations

import re
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from threading import RLock

from app.config import get_settings
from app.models import SearchHit, TopologySnapshot


class SearchIndex(ABC):
    @abstractmethod
    def rebuild(self, snapshot: TopologySnapshot, side: str) -> None: ...

    @abstractmethod
    def delete_snapshot(self, snapshot_id: str) -> None: ...

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 50,
        *,
        snapshot_ids: list[str] | None = None,
        side: str | None = None,
    ) -> list[SearchHit]: ...


def _glob_to_fts(query: str) -> str:
    q = query.strip()
    if not q:
        return ""
    parts = re.split(r"\s+", q)
    fts_parts: list[str] = []
    for part in parts:
        token = part.replace("*", "").replace('"', '""')
        if token:
            fts_parts.append(f'"{token}"*')
    return " ".join(fts_parts) if fts_parts else ""


class SQLiteFTSSearchIndex(SearchIndex):
    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._path = db_path or settings.search_db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                    job_uid UNINDEXED,
                    side UNINDEXED,
                    snapshot_id UNINDEXED,
                    name,
                    path,
                    status,
                    body,
                    tokenize='unicode61'
                )
                """
            )

    def rebuild(self, snapshot: TopologySnapshot, side: str) -> None:
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        for job in snapshot.flat_jobs:
            path = "/".join(job.path_labels)
            jil = job.autosys.jil
            run = job.autosys.run
            body = " ".join(
                filter(
                    None,
                    [
                        job.scheduler_job_name,
                        job.logical_id or "",
                        path,
                        job.status.value,
                        job.job_type,
                        jil.job_name or "",
                        jil.command or "",
                        jil.condition or "",
                        jil.watch_file or "",
                        jil.start_times or "",
                        jil.std_out_file or "",
                        run.resolved_command or "",
                        job.log_path or "",
                    ],
                )
            )
            rows.append(
                (
                    job.job_uid,
                    side,
                    snapshot.snapshot_id,
                    job.scheduler_job_name,
                    path,
                    job.status.value,
                    body,
                )
            )

        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM jobs_fts WHERE side = ? AND snapshot_id = ?",
                (side, snapshot.snapshot_id),
            )
            self._conn.executemany(
                """
                INSERT INTO jobs_fts (job_uid, side, snapshot_id, name, path, status, body)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def delete_snapshot(self, snapshot_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM jobs_fts WHERE snapshot_id = ?",
                (snapshot_id,),
            )

    def search(
        self,
        query: str,
        limit: int = 50,
        *,
        snapshot_ids: list[str] | None = None,
        side: str | None = None,
    ) -> list[SearchHit]:
        fts_q = _glob_to_fts(query)
        if not fts_q:
            return []
        if snapshot_ids is not None and not snapshot_ids:
            return []
        sql = """
                SELECT job_uid, side, snapshot_id, name, path, status, body,
                       bm25(jobs_fts) AS rank
                FROM jobs_fts
                WHERE jobs_fts MATCH ?
                """
        params: list[object] = [fts_q]
        if snapshot_ids:
            placeholders = ",".join("?" for _ in snapshot_ids)
            sql += f" AND snapshot_id IN ({placeholders})"
            params.extend(snapshot_ids)
        if side:
            sql += " AND side = ?"
            params.append(side)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        hits: list[SearchHit] = []
        for row in rows:
            hits.append(
                SearchHit(
                    job_uid=row["job_uid"],
                    side=row["side"],
                    snapshot_id=row["snapshot_id"],
                    score=float(row["rank"]),
                    snippet=_snippet(row["body"], query),
                    scheduler_job_name=row["name"],
                    path=row["path"],
                    status=row["status"],
                )
            )
        return hits


def _snippet(body: str, query: str, width: int = 80) -> str:
    needle = query.replace("*", "").strip().lower()
    if not needle:
        return body[:width]
    first = needle.split()[0]
    idx = body.lower().find(first)
    if idx < 0:
        return body[:width]
    start = max(0, idx - 20)
    return body[start : start + width]


search_index = SQLiteFTSSearchIndex()
