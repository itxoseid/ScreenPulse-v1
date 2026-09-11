"""Textual TUI: live stream of detected events with a terminal-agent aesthetic."""

from __future__ import annotations

import threading

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from .config import Settings
from .pipeline import Event, Pipeline, Session
from .reports import breakdown

_CATEGORY_COLOR = {
    "coding": "green",
    "communication": "cyan",
    "browsing": "blue",
    "reading": "magenta",
    "writing": "yellow",
    "design": "bright_magenta",
    "media": "bright_blue",
    "meeting": "red",
    "gaming": "bright_green",
    "system": "grey62",
    "idle": "grey42",
    "other": "white",
}


class WatchApp(App):
    TITLE = "ScreenPulse"
    CSS = """
    Screen { background: $surface; }
    #status { height: 1; color: $text-muted; padding: 0 1; }
    #status.paused { color: $text; background: $warning; text-style: bold; }
    #log { border: round $primary; }
    #side { width: 44; border: round $primary; padding: 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "toggle_pause", "Pause"),
        ("b", "refresh_breakdown", "Breakdown"),
    ]

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or Settings.from_env()
        self._pipeline: Pipeline | None = None
        self._thread: threading.Thread | None = None
        self._count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static("starting…", id="status")
            with Horizontal():
                yield RichLog(id="log", wrap=True, markup=True, highlight=False)
                yield Static("", id="side")
        yield Footer()

    def on_mount(self) -> None:
        self._pipeline = Pipeline(
            self._settings,
            on_event=lambda e: self.call_from_thread(self._append_event, e),
            on_status=lambda s: self.call_from_thread(self._set_status, s),
            on_session=lambda s: self.call_from_thread(self._append_session, s),
        )
        self._thread = threading.Thread(target=self._pipeline.run, daemon=True)
        self._thread.start()
        self._last_status = "starting…"
        self.query_one("#log", RichLog).write(
            "[bold green]ScreenPulse[/] — watching your screen. Nothing is saved to disk "
            "except analyzed event summaries.\n"
        )
        self.action_refresh_breakdown()
        self.set_interval(2.0, self._tick_recording)

    def _set_status(self, text: str) -> None:
        self._last_status = text
        self._render_status()

    def _render_status(self) -> None:
        status = self.query_one("#status", Static)
        paused = bool(self._pipeline and self._pipeline.paused)
        status.set_class(paused, "paused")
        rec = self._pipeline.current_session() if self._pipeline else None
        if rec and rec["recording"] and not paused:
            mins, secs = divmod(int(rec["elapsed_seconds"]), 60)
            status.update(f"🔴 recording — {rec['app']} ({mins}:{secs:02d})")
            return
        status.update(f"{'⏸ PAUSED — ' if paused else '● '}{self._last_status}")

    def _tick_recording(self) -> None:
        self._render_status()

    def action_toggle_pause(self) -> None:
        if not self._pipeline:
            return
        paused = self._pipeline.toggle_pause()
        self.query_one("#log", RichLog).write(
            f"[bold yellow]{'⏸ Paused' if paused else '▶ Resumed'}[/] — "
            f"{'capture stopped' if paused else 'watching again'}\n"
        )
        self._set_status("Paused — no capture" if paused else "resuming…")

    def _append_session(self, s: Session) -> None:
        color = _CATEGORY_COLOR.get(s.category, "white")
        mins = s.duration_seconds / 60
        log = self.query_one("#log", RichLog)
        log.write(
            f"[dim]{s.start:%H:%M:%S}–{s.end:%H:%M:%S}[/]  "
            f"[bold {color}]■ {mins:.0f} min[/]  [{color}]{s.category:<11}[/] "
            f"[bold]{s.app}[/]: [italic]{s.activity_summary}[/]\n"
        )

    def _append_event(self, e: Event) -> None:
        self._count += 1
        color = _CATEGORY_COLOR.get(e.category, "white")
        log = self.query_one("#log", RichLog)
        log.write(
            f"[dim]{e.ts:%H:%M:%S}[/]  [{color}]▎{e.category:<13}[/] "
            f"[bold]{e.app}[/]"
        )
        log.write(f"          [italic]{e.activity_summary}[/]\n")
        if self._count % 5 == 0:
            self.action_refresh_breakdown()

    def action_refresh_breakdown(self) -> None:
        try:
            text = breakdown(days=1, group_by="category")
        except Exception as exc:  # noqa: BLE001
            text = f"(breakdown unavailable: {exc})"
        self.query_one("#side", Static).update(text)

    def on_unmount(self) -> None:
        if self._pipeline:
            self._pipeline.stop()


def run_tui(settings: Settings | None = None) -> None:
    WatchApp(settings).run()
