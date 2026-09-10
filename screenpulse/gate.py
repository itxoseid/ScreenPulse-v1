"""
The gate between the diff filter and the vision call.

Even after the pixel-diff check, not every changed frame is worth an AI call:
tiny animations, a blinking cursor, a scrolling ticker. This gate holds the call
back unless the change is large enough to look like a real switch of content,
and enough time has passed since the last call to stay within budget.
"""

from __future__ import annotations

import time


class HeuristicGate:
    def __init__(
        self,
        *,
        significant_change: float = 0.06,
        min_seconds_between_calls: float = 8.0,
    ) -> None:
        self.significant_change = significant_change
        self.min_seconds_between_calls = min_seconds_between_calls
        self._last_call_ts: float = 0.0

    def should_analyze(self, changed_fraction: float) -> bool:
        now = time.monotonic()
        if changed_fraction < self.significant_change:
            return False
        if now - self._last_call_ts < self.min_seconds_between_calls:
            return False
        return True

    def mark_analyzed(self) -> None:
        self._last_call_ts = time.monotonic()
