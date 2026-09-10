"""Screen capture. Frames stay in memory and are never written to disk."""

from __future__ import annotations

import io

import mss
from PIL import Image


class ScreenCapturer:
    """Grabs the full virtual screen (all monitors) as a PIL image."""

    def __init__(self) -> None:
        self._sct = mss.mss()
        # monitors[0] is the union of every monitor.
        self._monitor = self._sct.monitors[0]

    def grab(self) -> Image.Image:
        shot = self._sct.grab(self._monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapturer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def to_jpeg_bytes(img: Image.Image, quality: int = 60, max_width: int = 1280) -> bytes:
    """Downscale + JPEG-encode a frame for sending to the vision model."""
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
