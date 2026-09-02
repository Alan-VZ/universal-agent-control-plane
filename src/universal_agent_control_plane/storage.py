from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.database = data_dir / "state.db"
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS state (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, key)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS hook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS hook_events_once
                    ON hook_events (event, session_id);
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def record_hook_event(
        self,
        event: str,
        session_id: str,
        payload: Any,
    ) -> dict[str, Any]:
        """Store one lifecycle event, at most once per session and event.

        Hosts may fire the same lifecycle event more than once, so the
        unique index makes repeat delivery a no-op instead of duplicating
        downstream work.
        """
        self._validate_identifier("event", event)
        self._validate_identifier("session_id", session_id)
        serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 65_536:
            raise ValueError("Hook payload exceeds the 64 KiB limit")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO hook_events (event, session_id, payload_json)
                VALUES (?, ?, ?)
                """,
                (event, session_id, serialized),
            )
            if cursor.rowcount == 0:
                return {"stored": False, "reason": "duplicate-event"}
            connection.execute(
                "INSERT INTO audit (action, namespace, key) VALUES ('hook.event', ?, ?)",
                (event, session_id),
            )
        return {"stored": True, "reason": None}

    def append_journal(
        self,
        session_id: str,
        summary: str,
        tags: list[str] | None = None,
        minimum_length: int = 200,
    ) -> dict[str, Any]:
        """Store a session summary, rejecting entries that would bloat the log.

        Short summaries carry no reusable signal, and a session that was
        already summarized must not be recorded twice.
        """
        self._validate_identifier("session_id", session_id)
        cleaned = summary.strip()
        if len(cleaned) < minimum_length:
            return {"stored": False, "reason": "below-minimum-length"}
        if len(cleaned.encode("utf-8")) > 65_536:
            raise ValueError("Summary exceeds the 64 KiB limit")
        serialized = json.dumps(
            sorted({tag for tag in (tags or []) if isinstance(tag, str) and tag.strip()}),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO journal (session_id, summary, tags_json)
                VALUES (?, ?, ?)
                """,
                (session_id, cleaned, serialized),
            )
            if cursor.rowcount == 0:
                return {"stored": False, "reason": "already-recorded"}
        return {"stored": True, "reason": None}

    def recent_journal(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most recent session summaries, newest first."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, summary, tags_json, created_at
                FROM journal ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "sessionId": row[0],
                "summary": row[1],
                "tags": json.loads(row[2]),
                "createdAt": row[3],
            }
            for row in rows
        ]

    def get(self, namespace: str, key: str) -> Any | None:
        self._validate_identifier("namespace", namespace)
        self._validate_identifier("key", key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM state WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, namespace: str, key: str, value: Any) -> dict[str, str]:
        self._validate_identifier("namespace", namespace)
        self._validate_identifier("key", key)
        serialized = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 65_536:
            raise ValueError("State value exceeds the 64 KiB limit")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO state (namespace, key, value_json)
                VALUES (?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (namespace, key, serialized),
            )
            connection.execute(
                "INSERT INTO audit (action, namespace, key) VALUES ('state.put', ?, ?)",
                (namespace, key),
            )
        return {"status": "stored", "namespace": namespace, "key": key}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _validate_identifier(label: str, value: str) -> None:
        if not value or len(value) > 128:
            raise ValueError(f"{label} must contain 1 to 128 characters")
