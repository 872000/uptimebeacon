"""SQLite storage: check history and the incident log.

An *incident* opens automatically when a target fails a check and closes
automatically on the first passing check afterwards, giving every outage
a start, end and duration with zero manual bookkeeping.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass


@dataclass
class Incident:
    id: int
    target: str
    started_at: float
    ended_at: float | None
    cause: str | None

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def duration_s(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)


SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT NOT NULL,
    ts          REAL NOT NULL,
    ok          INTEGER NOT NULL,
    latency_ms  REAL,
    status_code INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_target_ts ON checks (target, ts);

CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at   REAL,
    cause      TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_target ON incidents (target, started_at);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- checks ---------------------------------------------------------
    def log_check(self, target: str, ts: float, ok: bool,
                  latency_ms: float | None, status_code: int | None,
                  error: str | None) -> None:
        """Record a check result and maintain the incident log."""
        with self.conn:
            self._log_check(target, ts, ok, latency_ms, status_code, error)

    def log_many(self, entries) -> None:
        """Record many check results inside a single transaction.

        `entries`: iterable of (target, ts, ok, latency_ms, status_code, error)
        tuples. Much faster than `log_check` in a loop (one fsync total).
        """
        with self.conn:
            for entry in entries:
                self._log_check(*entry)

    def _log_check(self, target: str, ts: float, ok: bool,
                   latency_ms: float | None, status_code: int | None,
                   error: str | None) -> None:
        self.conn.execute(
            "INSERT INTO checks (target, ts, ok, latency_ms, status_code, error)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (target, ts, 1 if ok else 0, latency_ms, status_code, error),
        )
        if ok:
            self._close_open_incident(target, ts)
        else:
            self._open_incident_if_needed(target, ts, error)

    def _open_incident_if_needed(self, target: str, ts: float, cause: str | None) -> None:
        row = self.conn.execute(
            "SELECT id FROM incidents WHERE target = ? AND ended_at IS NULL",
            (target,),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO incidents (target, started_at, ended_at, cause)"
                " VALUES (?, ?, NULL, ?)",
                (target, ts, cause),
            )

    def _close_open_incident(self, target: str, ts: float) -> None:
        self.conn.execute(
            "UPDATE incidents SET ended_at = ? WHERE target = ? AND ended_at IS NULL",
            (ts, target),
        )

    def get_checks(self, target: str, since: float | None = None,
                   limit: int | None = None):
        sql = "SELECT * FROM checks WHERE target = ?"
        args: list = [target]
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        sql += " ORDER BY ts ASC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return self.conn.execute(sql, args).fetchall()

    def latest_check(self, target: str):
        return self.conn.execute(
            "SELECT * FROM checks WHERE target = ? ORDER BY ts DESC LIMIT 1",
            (target,),
        ).fetchone()

    def targets(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT target FROM checks ORDER BY target")
        return [r["target"] for r in rows]

    # -- incidents ------------------------------------------------------
    def get_incidents(self, target: str | None = None,
                      since: float | None = None, limit: int = 100) -> list[Incident]:
        sql = "SELECT * FROM incidents"
        args: list = []
        clauses = []
        if target is not None:
            clauses.append("target = ?")
            args.append(target)
        if since is not None:
            clauses.append("started_at >= ?")
            args.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        return [self._row_to_incident(r) for r in self.conn.execute(sql, args)]

    def open_incidents(self, target: str | None = None) -> list[Incident]:
        sql = "SELECT * FROM incidents WHERE ended_at IS NULL"
        args: list = []
        if target is not None:
            sql += " AND target = ?"
            args.append(target)
        sql += " ORDER BY started_at DESC"
        return [self._row_to_incident(r) for r in self.conn.execute(sql, args)]

    @staticmethod
    def _row_to_incident(row: sqlite3.Row) -> Incident:
        return Incident(
            id=row["id"],
            target=row["target"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            cause=row["cause"],
        )
