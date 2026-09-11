"""System tray front-end for the watch pipeline.

Runs the same Pipeline as `watch --no-tui`, but with a tray icon instead of a
console: right-click for pause/resume, the log, the data folder, and quit. The
icon colour reflects status (watching / paused / error), and hovering it shows
the most recent entry.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime

import pystray
from PIL import Image, ImageDraw

from .config import DATA_DIR, LOG_PATH, Settings
from .pipeline import Event, Pipeline

_ACTIVE = (90, 200, 130)   # green: watching
_PAUSED = (230, 190, 90)   # amber: paused
_ERROR = (230, 90, 90)     # red: something went wrong


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
            self.settings, on_event=self._on_event, on_status=self._on_status
        )
        self._thread = threading.Thread(target=self.pipeline.run, daemon=True)
        self._dashboard_port: int | None = None
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
        icon.icon = _dot(_PAUSED if paused else _ACTIVE)
        icon.title = "ScreenPulse — paused" if paused else "ScreenPulse — watching"
        _log("paused" if paused else "resumed")

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
        self.pipeline.stop()
        icon.stop()

    def _on_event(self, e: Event) -> None:
        _log(f"[{e.category}] {e.app}: {e.activity_summary}")
        if not self.pipeline.paused:
            self.icon.title = f"ScreenPulse — {e.category}: {e.app}"[:127]
            self.icon.icon = _dot(_ACTIVE)

    def _on_status(self, status: str) -> None:
        _log(status)
        if status.lower().startswith("error"):
            self.icon.icon = _dot(_ERROR)
            self.icon.title = f"ScreenPulse — {status}"[:127]

    # ------------------------------------------------------------------- run

    def run(self) -> None:
        self._thread.start()
        self.icon.run()  # blocks until Quit; the pipeline thread is a daemon


def run_tray(settings: Settings | None = None) -> None:
    TrayApp(settings).run()
