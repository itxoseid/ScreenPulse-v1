"""Wires capture -> diff -> gate -> vision+text -> SQLite into a single loop.

Alongside the per-snapshot `events` (one row per AI call), the pipeline also
tracks *sessions*: "you stayed on roughly the same app for a stretch". A
session is built purely from watching the foreground window switch (cheap,
no AI call needed) and is only kept once it runs at least
`Settings.min_session_seconds` — short app-switches don't clutter the log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .analyzer import Analysis, VisionAnalyzer
from .capture import ScreenCapturer, to_jpeg_bytes
from .config import CURRENT_SESSION_PATH, Settings
from .db import connect, insert_event, upsert_session
from .diff import FrameDiffer
from .gate import HeuristicGate
from .ollama import OllamaClient
from .winfocus import focus_hint

# Window/process names that pause capture automatically while they are focused.
_SENSITIVE_HINTS = (
    "1password", "bitwarden", "keepass", "lastpass", "dashlane", "proton pass",
    "windows security", "user account control",
)


@dataclass
class Event:
    id: int
    ts: datetime
    app: str
    activity_summary: str
    category: str
    window_title: str = ""


@dataclass
class Session:
    """A closed, kept session: you were on `app` from start to end."""

    start: datetime
    end: datetime
    app: str
    window_title: str
    category: str
    activity_summary: str
    event_count: int

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class _OpenSession:
    """In-memory, not-yet-committed session being built as the app stays focused."""

    process: str
    start: datetime
    last_seen: datetime
    window_title: str = ""
    app: str = ""
    category: str = "other"
    activity_summary: str = ""
    event_count: int = 0
    events: list[str] = field(default_factory=list)
    db_id: Optional[int] = None


# Called by the TUI (or CLI) for each analyzed event, and for status lines.
EventSink = Callable[[Event], None]
StatusSink = Callable[[str], None]
SessionSink = Callable[[Session], None]


class Pipeline:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        on_event: Optional[EventSink] = None,
        on_status: Optional[StatusSink] = None,
        on_session: Optional[SessionSink] = None,
        client: Optional[OllamaClient] = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.on_event = on_event or (lambda e: None)
        self.on_status = on_status or (lambda s: None)
        self.on_session = on_session or (lambda s: None)
        self._analyzer = VisionAnalyzer(client=client)
        self._differ = FrameDiffer(downscale=self.settings.diff_downscale)
        self._gate = HeuristicGate(
            min_seconds_between_calls=self.settings.min_seconds_between_calls
        )
        self._stop = False
        self.paused = False
        self._recent_summaries: list[str] = []
        self._open: Optional[_OpenSession] = None

    def stop(self) -> None:
        self._stop = True

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        return self.paused

    def current_session(self) -> Optional[dict]:
        """Best-effort snapshot of the in-progress session, for a UI to poll."""
        s = self._open
        if s is None:
            return None
        elapsed = (datetime.now() - s.start).total_seconds()
        return {
            "app": s.app or s.process,
            "window_title": s.window_title,
            "category": s.category,
            "elapsed_seconds": elapsed,
            "recording": elapsed >= self.settings.min_session_seconds,
        }

    def run(self) -> None:
        self._stop = False
        self.on_status("Capture loop started. Press Ctrl+C to stop.")
        with ScreenCapturer() as cap, connect() as conn:
            while not self._stop:
                loop_started = time.monotonic()
                try:
                    hint = focus_hint()

                    if self.paused:
                        self._close_session(conn)
                        self.on_status("Paused — no capture")
                    elif _is_sensitive(hint):
                        self._close_session(conn)  # don't log time spent here
                        self.on_status(f"Auto-paused (sensitive app: {hint.split(' — ')[0]})")
                    else:
                        self._track_session(conn, hint)
                        frame = cap.grab()
                        frac = self._differ.changed_fraction(frame)
                        if frac >= self.settings.diff_threshold and self._gate.should_analyze(frac):
                            self.on_status(f"Change {frac:.0%} — analyzing…")
                            jpeg = to_jpeg_bytes(frame, quality=self.settings.jpeg_quality)
                            context = " | ".join(self._recent_summaries[-3:])
                            analysis = self._analyzer.analyze(
                                jpeg, context=context, focus_hint=hint
                            )
                            self._gate.mark_analyzed()
                            self._store(conn, analysis)
                        else:
                            self.on_status(f"Idle (change {frac:.0%})")
                except KeyboardInterrupt:
                    break
                except Exception as exc:  # keep the loop alive; surface the error
                    self.on_status(f"Error: {exc}")

                elapsed = time.monotonic() - loop_started
                time.sleep(max(0.0, self.settings.capture_interval - elapsed))

            self._close_session(conn)
        self.on_status("Capture loop stopped.")

    # ------------------------------------------------------------ sessions

    def _track_session(self, conn, hint: str) -> None:
        process = hint.split(" — ")[0] if hint else ""
        now = datetime.now()

        if self._open is not None and self._open.process == process:
            self._open.last_seen = now
            self._persist_session(conn)
            return

        # Foreground app changed (or this is the first tick): close the old
        # session, start a fresh one for whatever's focused now.
        self._close_session(conn)
        if process:
            self._open = _OpenSession(
                process=process, start=now, last_seen=now, window_title=hint
            )
            self._persist_session(conn)

    def _persist_session(self, conn) -> None:
        """Write the current session's state to the live-status file, and, once
        it's run long enough to count, to the database too — updated in place
        on every tick so an abrupt kill loses at most a few seconds, not the
        whole session."""
        s = self._open
        if s is None:
            return
        try:
            CURRENT_SESSION_PATH.write_text(
                json.dumps(
                    {
                        "app": s.app or s.process,
                        "window_title": s.window_title,
                        "category": s.category,
                        "start_ts": s.start.isoformat(timespec="seconds"),
                        "last_seen_ts": s.last_seen.isoformat(timespec="seconds"),
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # best-effort; not worth crashing the loop over

        duration = (s.last_seen - s.start).total_seconds()
        if s.db_id is None and duration < self.settings.min_session_seconds:
            return  # not long enough yet to bother writing to the db

        summary = s.activity_summary or " / ".join(dict.fromkeys(s.events)) or ""
        s.db_id = upsert_session(
            conn,
            session_id=s.db_id,
            start_ts=s.start,
            end_ts=s.last_seen,
            app=s.app or s.process,
            window_title=s.window_title,
            category=s.category,
            activity_summary=summary,
            event_count=s.event_count,
        )

    def _close_session(self, conn) -> None:
        s, self._open = self._open, None
        CURRENT_SESSION_PATH.unlink(missing_ok=True)
        if s is None:
            return
        duration = (s.last_seen - s.start).total_seconds()
        if s.db_id is None and duration < self.settings.min_session_seconds:
            return  # too short to bother recording

        summary = s.activity_summary or " / ".join(dict.fromkeys(s.events)) or ""
        upsert_session(
            conn,
            session_id=s.db_id,
            start_ts=s.start,
            end_ts=s.last_seen,
            app=s.app or s.process,
            window_title=s.window_title,
            category=s.category,
            activity_summary=summary,
            event_count=s.event_count,
        )
        self.on_session(
            Session(
                start=s.start,
                end=s.last_seen,
                app=s.app or s.process,
                window_title=s.window_title,
                category=s.category,
                activity_summary=summary,
                event_count=s.event_count,
            )
        )

    # -------------------------------------------------------------- events

    def _store(self, conn, analysis: Analysis) -> None:
        now = datetime.now()
        event_id = insert_event(
            conn,
            app=analysis.app,
            activity_summary=analysis.activity_summary,
            category=analysis.category,
            window_title=analysis.window_title,
            ts=now,
        )
        self._recent_summaries.append(analysis.activity_summary)
        self._recent_summaries = self._recent_summaries[-10:]

        if self._open is not None:
            self._open.app = analysis.app
            self._open.category = analysis.category
            self._open.activity_summary = analysis.activity_summary
            self._open.event_count += 1
            self._open.events.append(analysis.activity_summary)
            self._persist_session(conn)

        self.on_event(
            Event(
                id=event_id,
                ts=now,
                app=analysis.app,
                activity_summary=analysis.activity_summary,
                category=analysis.category,
                window_title=analysis.window_title,
            )
        )


def _is_sensitive(hint: str) -> bool:
    low = hint.lower()
    return any(s in low for s in _SENSITIVE_HINTS)
