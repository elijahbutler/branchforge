from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, path: str | Path = "branchforge.db"):
        self.path = str(path)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                stage TEXT,
                branch_id TEXT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, sequence)")
        self._connection.commit()

    def transaction(
        self,
        statements: list[tuple[str, tuple[Any, ...]]],
    ) -> list[int]:
        """Execute statements atomically and return their row IDs."""
        row_ids: list[int] = []
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                for sql, parameters in statements:
                    cursor = self._connection.execute(sql, parameters)
                    row_ids.append(int(cursor.lastrowid or 0))
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
        return row_ids

    def query(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(sql, parameters).fetchall()

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], *, stage: str | None = None, branch_id: str | None = None) -> int:
        return self.transaction([(
            "INSERT INTO events(run_id, stage, branch_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, stage, branch_id, event_type, json.dumps(payload, default=str), datetime.now(UTC).isoformat()),
        )])[0]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM events WHERE run_id = ? ORDER BY sequence", (run_id,))
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def run_ids(self) -> list[str]:
        rows = self.query("SELECT run_id FROM events GROUP BY run_id ORDER BY MAX(sequence) DESC")
        return [str(row[0]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()
