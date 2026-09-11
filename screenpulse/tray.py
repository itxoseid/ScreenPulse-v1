"""System tray front-end for the watch pipeline.

Runs the same Pipeline as `watch --no-tui`, but with a tray icon instead of a
console: right-click for pause/resume, the dashboard, the log, the data
folder, and quit. The icon colour reflects status — green while watching,
amber while paused, a distinct colour once you've been on the same app long
enough to count as a "session" (see pipeline.py), red on an error — and
hovering it shows what's happening right now.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime

import pystray
from PIL import Image, ImageDraw

from .config import DATA_DIR, LOG_PATH, Settings
from .pipeline import Event, Pipeline, Session

_ACTIVE = (90, 200, 130)     # green: watching
_PAUSED = (230, 190, 90)     # amber: paused
_RECORDING = (235, 130, 60)  # orange: on the same app long enough to be a session
_ERROR = (230, 90, 90)       # red: something went wrong


def _dot(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=color)
    return img


def _log(msg: str) -> None:
    """Best-effort log line to stderr. Safe under pythonw with no console: if
    stderr wasn't redirected to a file (sys.stderr is None), this is a no-op
    rather than a crash."""
    if sys.stderr is None:
        return
    try:
        print(f"{datetime.now():%H:%M:%S}  {msg}", file=sys.stderr, flush=True)
    except OSError:
        pass


class TrayApp:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _log("tray started")
        self.pipeline = Pipeline(
            self.settings,
            on_event=self._on_event,
            on_status=self._on_status,
            on_session=self._on_session,
        )
        self._thread = threading.Thread(target=self.pipeline.run, daemon=True)
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._dashboard_port: int | None = None
        self._last_event_title = "ScreenPulse — watching"
        self._error: str | None = None
        self._running = True
        self.icon = pystray.Icon(
            "screenpulse",
            _dot(_ACTIVE),
            "ScreenPulse — starting…",
            menu=self._build_menu(),
        )

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: "Resume watching" if self.pipeline.paused else "Pause watching",
                self._toggle_pause,
            ),
            pystray.MenuItem("Open dashboard", self._open_dashboard),
            pystray.MenuItem("Open log", self._open_log),
            pystray.MenuItem("Open data folder", self._open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit ScreenPulse", self._quit),
        )

    # -------------------------------------------------------------- callbacks

    def _toggle_pause(self, icon: pystray.Icon, item) -> None:
        paused = self.pipeline.toggle_pause()
        _log("paused" if paused else "resumed")
        self._refresh_icon()

    def _open_dashboard(self, icon: pystray.Icon, item) -> None:
        import webbrowser

        if self._dashboard_port is None:
            from .webui import run_dashboard

            self._dashboard_port = 8765
            threading.Thread(
                target=run_dashboard,
                kwargs={"port": self._dashboard_port, "open_browser": False},
                daemon=True,
            ).start()
        webbrowser.open(f"http://127.0.0.1:{self._dashboard_port}/")

    def _open_log(self, icon: pystray.Icon, item) -> None:
        os.startfile(str(LOG_PATH))  # noqa: S606 (user-initiated, local file)

    def _open_folder(self, icon: pystray.Icon, item) -> None:
        os.startfile(str(DATA_DIR))  # noqa: S606

    def _quit(self, icon: pystray.Icon, item) -> None:
        _log("quit requested")
        self._running = False
        self.pipeline.stop()
        icon.stop()

    def _on_event(self, e: Event) -> None:
        _log(f"[{e.category}] {e.app}: {e.activity_summary}")
        self._error = None
        self._last_event_title = f"ScreenPulse — {e.category}: {e.app}"[:127]
        self._refresh_icon()

    def _on_status(self, status: str) -> None:
        _log(status)
        self._error = status if status.lower().startswith("error") else None
        self._refresh_icon()

    def _on_session(self, s: Session) -> None:
        mins = s.duration_seconds / 60
        _log(f"session closed: {s.app} ({mins:.0f} min) — {s.activity_summary}")

    # ---------------------------------------------------------------- icon

    def _refresh_icon(self) -> None:
        if self.pipeline.paused:
            self.icon.icon = _dot(_PAUSED)
            self.icon.title = "ScreenPulse — paused"
            return

        rec = self.pipeline.current_session()
        if rec and rec["recording"]:
            mins, secs = divmod(int(rec["elapsed_seconds"]), 60)
            self.icon.icon = _dot(_RECORDING)
            self.icon.title = f"ScreenPulse — recording: {rec['app']} ({mins}:{secs:02d})"[:127]
            return

        if self._error:
            self.icon.icon = _dot(_ERROR)
            self.icon.title = f"ScreenPulse — {self._error}"[:127]
            return

        self.icon.icon = _dot(_ACTIVE)
        self.icon.title = self._last_event_title

    def _tick_loop(self) -> None:
        # Ticks the "recording: App (mm:ss)" title even between events/status
        # updates, so the timer visibly counts up while pystray's own loop
        # runs on the main thread.
        while self._running:
            time.sleep(2)
            if self._running:
                self._refresh_icon()

    # ------------------------------------------------------------------- run

    def run(self) -> None:
        self._thread.start()
        self._ticker.start()
        self.icon.run()  # blocks until Quit; the pipeline thread is a daemon


def run_tray(settings: Settings | None = None) -> None:
    TrayApp(settings).run()
