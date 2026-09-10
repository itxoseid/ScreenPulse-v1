"""Textual TUI: live stream of detected events with a terminal-agent aesthetic."""

from __future__ import annotations

import threading

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from .config import Settings
from .pipeline import Event, Pipeline
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
    #log { border: round $primary; }
    #side { width: 44; border: round $primary; padding: 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
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
        )
        self._thread = threading.Thread(target=self._pipeline.run, daemon=True)
        self._thread.start()
        self.query_one("#log", RichLog).write(
            "[bold green]ScreenPulse[/] — watching your screen. Nothing is saved to disk "
            "except analyzed event summaries.\n"
        )
        self.action_refresh_breakdown()

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"● {text}")

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
