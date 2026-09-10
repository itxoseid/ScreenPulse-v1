"""Configuration and shared constants for ScreenPulse."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _data_dir() -> Path:
    # Keep everything under the user's local app data on Windows, ~/.screenpulse elsewhere.
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "ScreenPulse" if base else Path.home() / ".screenpulse"
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_DIR = _data_dir()
DB_PATH = Path(os.environ.get("SCREENPULSE_DB", DATA_DIR / "screenpulse.db"))

# Local Ollama server. No API keys, no cloud calls.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

# moondream describes a screenshot; the text model turns that description into
# clean structured JSON and also powers the summary / search / report commands.
VISION_MODEL = os.environ.get("SCREENPULSE_VISION_MODEL", "moondream")
TEXT_MODEL = os.environ.get("SCREENPULSE_TEXT_MODEL", "llama3.2:3b")

# Categories the classifier is asked to bucket activity into.
CATEGORIES = [
    "coding",
    "communication",
    "browsing",
    "reading",
    "writing",
    "design",
    "media",
    "meeting",
    "gaming",
    "system",
    "idle",
    "other",
]


@dataclass(frozen=True)
class Settings:
    """Runtime knobs for the capture pipeline."""

    capture_interval: float = 1.5          # seconds between frames
    diff_threshold: float = 0.02           # fraction of changed pixels to count as "changed"
    diff_downscale: int = 16               # downscale factor before diffing
    min_seconds_between_calls: float = 8.0 # rate-limit the (local) vision calls
    jpeg_quality: int = 60                 # quality for the frame sent to moondream

    @classmethod
    def from_env(cls) -> "Settings":
        def _f(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return float(raw) if raw else default

        return cls(
            capture_interval=_f("SCREENPULSE_INTERVAL", cls.capture_interval),
            diff_threshold=_f("SCREENPULSE_DIFF_THRESHOLD", cls.diff_threshold),
            min_seconds_between_calls=_f(
                "SCREENPULSE_MIN_CALL_GAP", cls.min_seconds_between_calls
            ),
        )
