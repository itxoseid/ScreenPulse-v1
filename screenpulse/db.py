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

-- A session is "you stayed on roughly the same app/window for a stretch",
-- built from watching the foreground window switch, not from AI calls.
-- Only sessions that ran at least Settings.min_session_seconds get kept.
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts        TEXT NOT NULL,
    end_ts          TEXT NOT NULL,
    duration_sec    INTEGER NOT NULL,
    app             TEXT NOT NULL,
    window_title    TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'other',
    activity_summary TEXT NOT NULL DEFAULT '',
    event_count     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);
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
    """Delete events (and sessions) older than keep_days. Returns rows removed."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM sessions WHERE start_ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def insert_session(
    conn: sqlite3.Connection,
    *,
    start_ts: datetime,
    end_ts: datetime,
    app: str,
    window_title: str = "",
    category: str = "other",
    activity_summary: str = "",
    event_count: int = 0,
) -> int:
    duration = max(0, int((end_ts - start_ts).total_seconds()))
    cur = conn.execute(
        "INSERT INTO sessions "
        "(start_ts, end_ts, duration_sec, app, window_title, category, "
        " activity_summary, event_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            start_ts.isoformat(timespec="seconds"),
            end_ts.isoformat(timespec="seconds"),
            duration,
            app,
            window_title,
            category,
            activity_summary,
            event_count,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def recent_sessions(conn: sqlite3.Connection, limit: int = 30) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions ORDER BY start_ts DESC LIMIT ?", (limit,)
    ).fetchall()


def upsert_session(
    conn: sqlite3.Connection,
    *,
    session_id: Optional[int],
    start_ts: datetime,
    end_ts: datetime,
    app: str,
    window_title: str = "",
    category: str = "other",
    activity_summary: str = "",
    event_count: int = 0,
) -> int:
    """Insert a session, or update it in place if `session_id` is given.

    Called repeatedly while a session is still in progress (not just once it
    closes), so a session survives an abrupt kill of the process - all that's
    lost is however many seconds since the last write, not the whole thing.
    """
    if session_id is None:
        return insert_session(
            conn,
            start_ts=start_ts,
            end_ts=end_ts,
            app=app,
            window_title=window_title,
            category=category,
            activity_summary=activity_summary,
            event_count=event_count,
        )
    duration = max(0, int((end_ts - start_ts).total_seconds()))
    conn.execute(
        "UPDATE sessions SET end_ts=?, duration_sec=?, app=?, window_title=?, "
        "category=?, activity_summary=?, event_count=? WHERE id=?",
        (
            end_ts.isoformat(timespec="seconds"),
            duration,
            app,
            window_title,
            category,
            activity_summary,
            event_count,
            session_id,
        ),
    )
    conn.commit()
    return session_id


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
