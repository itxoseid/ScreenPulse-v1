"""Wires capture -> diff -> gate -> vision+text -> SQLite into a single loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from .analyzer import Analysis, VisionAnalyzer
from .capture import ScreenCapturer, to_jpeg_bytes
from .config import Settings
from .db import connect, insert_event
from .diff import FrameDiffer
from .needle import HeuristicGate
from .ollama import OllamaClient


@dataclass
class Event:
    id: int
    ts: datetime
    app: str
    activity_summary: str
    category: str


# Called by the TUI (or CLI) for each analyzed event, and for status lines.
EventSink = Callable[[Event], None]
StatusSink = Callable[[str], None]


class Pipeline:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        on_event: Optional[EventSink] = None,
        on_status: Optional[StatusSink] = None,
        client: Optional[OllamaClient] = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.on_event = on_event or (lambda e: None)
        self.on_status = on_status or (lambda s: None)
        self._analyzer = VisionAnalyzer(client=client)
        self._differ = FrameDiffer(downscale=self.settings.diff_downscale)
        self._gate = HeuristicGate(
            min_seconds_between_calls=self.settings.min_seconds_between_calls
        )
        self._stop = False
        self._recent_summaries: list[str] = []

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        self._stop = False
        self.on_status("Capture loop started. Press Ctrl+C to stop.")
        with ScreenCapturer() as cap, connect() as conn:
            while not self._stop:
                loop_started = time.monotonic()
                try:
                    frame = cap.grab()
                    frac = self._differ.changed_fraction(frame)

                    if frac >= self.settings.diff_threshold and self._gate.should_analyze(frac):
                        self.on_status(f"Change {frac:.0%} — analyzing…")
                        jpeg = to_jpeg_bytes(frame, quality=self.settings.jpeg_quality)
                        context = " | ".join(self._recent_summaries[-3:])
                        analysis = self._analyzer.analyze(jpeg, context=context)
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
        self.on_status("Capture loop stopped.")

    def _store(self, conn, analysis: Analysis) -> None:
        now = datetime.now()
        event_id = insert_event(
            conn,
            app=analysis.app,
            activity_summary=analysis.activity_summary,
            category=analysis.category,
            ts=now,
        )
        self._recent_summaries.append(analysis.activity_summary)
        self._recent_summaries = self._recent_summaries[-10:]
        self.on_event(
            Event(
                id=event_id,
                ts=now,
                app=analysis.app,
                activity_summary=analysis.activity_summary,
                category=analysis.category,
            )
        )
