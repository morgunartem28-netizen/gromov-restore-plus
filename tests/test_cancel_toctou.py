"""Cancel TOCTOU: clear_cancel must not wipe a racing user Cancel."""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from install_service import clear_tool_cancels_unless_stopped  # noqa: E402
from ipatool_client import IpatoolCancelled  # noqa: E402


class _FakeTool:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self.clear_calls = 0
        self.request_calls = 0

    def request_cancel(self) -> None:
        self.request_calls += 1
        self._cancel.set()

    def clear_cancel(self) -> None:
        self.clear_calls += 1
        self._cancel.clear()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class CancelToctouTests(unittest.TestCase):
    def test_abort_when_already_cancelled(self) -> None:
        stop = threading.Event()
        stop.set()
        tool = _FakeTool()
        tool.request_cancel()
        with self.assertRaises(IpatoolCancelled):
            clear_tool_cancels_unless_stopped(stop, tool)
        self.assertEqual(tool.clear_calls, 0)
        self.assertTrue(tool.cancelled)

    def test_clear_when_idle(self) -> None:
        stop = threading.Event()
        tool = _FakeTool()
        tool.request_cancel()  # leftover from previous job
        clear_tool_cancels_unless_stopped(stop, tool)
        self.assertEqual(tool.clear_calls, 1)
        self.assertFalse(tool.cancelled)

    def test_race_cancel_during_clear_reasserts(self) -> None:
        """Simulate Cancel landing between is_set check and clear completion."""
        stop = threading.Event()
        ipatool = _FakeTool()
        device = _FakeTool()

        original_clear = ipatool.clear_cancel

        def clear_then_user_cancel() -> None:
            # First tool clear succeeds; user Cancel arrives mid-sequence.
            original_clear()
            stop.set()
            ipatool.request_cancel()
            device.request_cancel()

        ipatool.clear_cancel = clear_then_user_cancel  # type: ignore[method-assign]

        with self.assertRaises(IpatoolCancelled):
            clear_tool_cancels_unless_stopped(stop, ipatool, device)

        # Helper must re-assert cancels after detecting the race.
        self.assertTrue(stop.is_set())
        self.assertTrue(ipatool.cancelled)
        self.assertTrue(device.cancelled)
        self.assertGreaterEqual(ipatool.request_calls, 1)
        self.assertGreaterEqual(device.request_calls, 1)

    def test_race_after_all_clears(self) -> None:
        stop = threading.Event()
        tool_a = _FakeTool()
        tool_b = _FakeTool()
        tool_a.request_cancel()
        tool_b.request_cancel()

        calls = {"n": 0}
        orig_b = tool_b.clear_cancel

        def clear_b_and_cancel() -> None:
            orig_b()
            calls["n"] += 1
            stop.set()

        tool_b.clear_cancel = clear_b_and_cancel  # type: ignore[method-assign]

        with self.assertRaises(IpatoolCancelled):
            clear_tool_cancels_unless_stopped(stop, tool_a, tool_b)

        self.assertTrue(tool_a.cancelled)
        self.assertTrue(tool_b.cancelled)
        self.assertEqual(calls["n"], 1)

    def test_none_cancel_event_always_clears(self) -> None:
        tool = _FakeTool()
        tool.request_cancel()
        clear_tool_cancels_unless_stopped(None, tool)
        self.assertFalse(tool.cancelled)

    def test_mock_tools_protocol(self) -> None:
        stop = threading.Event()
        ipatool = MagicMock()
        device = MagicMock()
        clear_tool_cancels_unless_stopped(stop, ipatool, device)
        ipatool.clear_cancel.assert_called_once()
        device.clear_cancel.assert_called_once()
        ipatool.request_cancel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
