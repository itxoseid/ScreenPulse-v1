"""Cheap frame-to-frame change detection using a downscaled pixel delta."""

from __future__ import annotations

import numpy as np
from PIL import Image


def _prepare(img: Image.Image, downscale: int) -> np.ndarray:
    w, h = img.size
    small = img.convert("L").resize(
        (max(1, w // downscale), max(1, h // downscale)), Image.BILINEAR
    )
    return np.asarray(small, dtype=np.int16)


class FrameDiffer:
    """Tracks the previous frame and reports the fraction of changed pixels."""

    def __init__(self, downscale: int = 16, per_pixel_threshold: int = 12) -> None:
        self.downscale = downscale
        self.per_pixel_threshold = per_pixel_threshold
        self._prev: np.ndarray | None = None

    def changed_fraction(self, img: Image.Image) -> float:
        cur = _prepare(img, self.downscale)
        if self._prev is None or self._prev.shape != cur.shape:
            self._prev = cur
            return 1.0
        delta = np.abs(cur - self._prev)
        frac = float(np.mean(delta > self.per_pixel_threshold))
        self._prev = cur
        return frac
