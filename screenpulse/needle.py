"""
Pass 3 of the pipeline: a cheap local "is this a meaningful event" gate that runs
*before* spending a vision-model call.

Needle 2 integration is not wired up in v1 (the local model/runtime isn't a hard
dependency and its API is still rough). This module falls back to a heuristic
built on the diff signal plus a simple rate limit.

TODO(v1): replace `HeuristicGate` with a real Needle 2 classifier when available.
"""

from __future__ import annotations

import time


class HeuristicGate:
    """
    Flags a frame as worth analyzing when the change is large enough to plausibly
    be a window switch / new content, and enough time has passed since the last
    vision call to stay within budget.
    """

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
