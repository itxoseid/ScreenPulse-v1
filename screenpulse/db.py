"""SQLite storage for analyzed screen events."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Iterator, Optional

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,          -- ISO-8601 local time the frame was captured
    app             TEXT NOT NULL,
    activity_summary TEXT NOT NULL,
    category        TEXT NOT NULL,
    window_title    TEXT NOT NULL DEFAULT ''  -- foreground window title at capture time
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    if "window_title" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN window_title TEXT NOT NULL DEFAULT ''")


@contextmanager
def connect(path: Path | str = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | str = DB_PATH) -> None:
    with connect(path):
        pass


def insert_event(
    conn: sqlite3.Connection,
    *,
    app: str,
    activity_summary: str,
    category: str,
    window_title: str = "",
    ts: Optional[datetime] = None,
) -> int:
    ts = ts or datetime.now()
    cur = conn.execute(
        "INSERT INTO events (ts, app, activity_summary, category, window_title) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts.isoformat(timespec="seconds"), app, activity_summary, category, window_title),
    )
    conn.commit()
    return int(cur.lastrowid)


def prune_events(conn: sqlite3.Connection, keep_days: int) -> int:
    """Delete events older than keep_days. Returns the number removed."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def events_for_day(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    start = datetime.combine(day, datetime.min.time()).isoformat()
    end = datetime.combine(day, datetime.max.time()).isoformat()
    return conn.execute(
        "SELECT * FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts",
        (start, end),
    ).fetchall()


def recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()


def run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute a read-only SELECT. Raises ValueError for anything else."""
    stripped = sql.strip().rstrip(";").lstrip("(")
    if not stripped.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    lowered = stripped.lower()
    for banned in ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma"):
        if f" {banned} " in f" {lowered} ":
            raise ValueError(f"Disallowed keyword in query: {banned}")
    return conn.execute(sql, params).fetchall()
