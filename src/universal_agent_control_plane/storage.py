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
                """
            )

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
