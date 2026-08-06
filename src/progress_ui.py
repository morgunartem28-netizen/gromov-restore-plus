"""Throttle install/update progress redraws on the Tk UI thread."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class ProgressUICoalescer:
    """Drop redundant progress redraws; force flush on phase change / near-done."""

    def __init__(
        self,
        *,
        after: Callable[[int, Callable[[], None]], Any],
        after_cancel: Callable[[Any], None],
        apply: Callable[[str, float, str], None],
        min_interval_s: float = 0.12,
        jump: float = 0.04,
        text_delta: float = 0.008,
    ) -> None:
        self._after = after
        self._after_cancel = after_cancel
        self._apply = apply
        self._min_interval_s = min_interval_s
        self._jump = jump
        self._text_delta = text_delta
        self.pending: tuple[str, float, str] | None = None
        self.last_at = 0.0
        self.last_phase = ""
        self.last_value = 0.0
        self.last_text = ""
        self.flush_id: Any = None

    def reset(self) -> None:
        self.cancel_pending_flush()
        self.pending = None
        self.last_at = 0.0
        self.last_phase = ""
        self.last_value = 0.0
        self.last_text = ""

    def cancel_pending_flush(self) -> None:
        if self.flush_id is None:
            return
        try:
            self._after_cancel(self.flush_id)
        except (ValueError, Exception):
            pass
        self.flush_id = None

    def coalesce(self, phase: str, value: float, text: str) -> None:
        self.pending = (phase, value, text)
        now = time.monotonic()
        phase_changed = phase != self.last_phase
        big_jump = abs(value - self.last_value) >= self._jump
        text_changed = text != self.last_text
        due = (now - self.last_at) >= self._min_interval_s
        force = phase_changed or big_jump or phase == "done" or value >= 0.99
        if force or (due and (text_changed or abs(value - self.last_value) >= self._text_delta)):
            self.cancel_pending_flush()
            self.flush()
            return
        if self.flush_id is None:
            delay_ms = max(1, int((self._min_interval_s - (now - self.last_at)) * 1000))
            self.flush_id = self._after(delay_ms, self.flush)

    def flush(self) -> None:
        self.flush_id = None
        pending = self.pending
        if pending is None:
            return
        phase, value, text = pending
        self.pending = None
        self.last_at = time.monotonic()
        self.last_phase = phase
        self.last_value = value
        self.last_text = text
        self._apply(phase, value, text)
