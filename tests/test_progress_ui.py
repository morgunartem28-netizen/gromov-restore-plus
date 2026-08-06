"""ProgressUICoalescer throttling behaviour."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from progress_ui import ProgressUICoalescer  # noqa: E402


class ProgressUICoalescerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.applied: list[tuple[str, float, str]] = []
        self.scheduled: list[tuple[int, object]] = []

        def after(ms: int, cb):  # noqa: ANN001
            self.scheduled.append((ms, cb))
            return f"id-{len(self.scheduled)}"

        def after_cancel(_id) -> None:  # noqa: ANN001
            pass

        self.coalescer = ProgressUICoalescer(
            after=after,
            after_cancel=after_cancel,
            apply=lambda p, v, t: self.applied.append((p, v, t)),
            min_interval_s=0.12,
        )

    def test_phase_change_flushes_immediately(self) -> None:
        self.coalescer.coalesce("download", 0.1, "a")
        self.coalescer.coalesce("install", 0.5, "b")
        self.assertEqual(self.applied[-1], ("install", 0.5, "b"))

    def test_tiny_steps_schedule_flush(self) -> None:
        self.coalescer.last_at = 1e12  # far future → not "due"
        self.coalescer.last_phase = "download"
        self.coalescer.last_value = 0.10
        self.coalescer.last_text = "x"
        self.coalescer.coalesce("download", 0.101, "x")
        self.assertEqual(len(self.applied), 0)
        self.assertTrue(self.scheduled)


if __name__ == "__main__":
    unittest.main()
