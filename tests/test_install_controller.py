"""Unit tests for InstallController façade (Wave B + singleton state)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from install_controller import InstallController, InstallUiState  # noqa: E402


class InstallControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctrl = InstallController(worker=MagicMock())

    def test_note_success_clears_failure(self) -> None:
        app = MagicMock()
        self.ctrl.note_failure(app)
        self.ctrl.note_success("MAX")
        self.assertEqual(self.ctrl.last_installed_title, "MAX")
        self.assertIsNone(self.ctrl.last_failed_app)
        self.assertEqual(self.ctrl.ui_state, InstallUiState.COMPLETED)

    def test_card_state(self) -> None:
        self.assertEqual(self.ctrl.card_state(), "idle")
        self.ctrl.note_success("X")
        self.assertEqual(self.ctrl.card_state(), "done")
        self.ctrl.clear_outcome()
        app = MagicMock()
        self.ctrl.note_failure(app)
        self.assertEqual(self.ctrl.card_state(), "error")
        self.assertEqual(self.ctrl.card_state(async_busy=True), "installing")

    def test_installing_title_prefers_active(self) -> None:
        self.ctrl.active_app_title = "Active"
        self.assertEqual(self.ctrl.installing_title("Selected"), "Active")


if __name__ == "__main__":
    unittest.main()
