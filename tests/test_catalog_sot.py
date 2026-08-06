"""Catalog controller is the single source of truth for navigation state."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from catalog_controller import CatalogController, CatalogState  # noqa: E402


class CatalogSourceOfTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        config = MagicMock()
        config.catalog_tabs_raw.return_value = [
            {"id": "popular", "title": "Популярные", "kind": "popular"},
            {"id": "banks", "title": "Банки", "kind": "banks"},
            {"id": "all", "title": "Все", "kind": "all"},
            {"id": "new", "title": "Новые", "kind": "new"},
        ]
        settings = MagicMock()
        settings.recent_installs = []
        settings.recent_install_records = []
        self.catalog = CatalogController(config, settings)

    def test_initial_state(self) -> None:
        self.assertEqual(self.catalog.state.tab_id, "popular")
        self.assertEqual(self.catalog.state.view, "root")
        self.assertIsNone(self.catalog.state.bank_group_id)
        self.assertEqual(self.catalog.state.search_query, "")

    def test_set_tab_resets_bank_drilldown(self) -> None:
        self.catalog.set_bank_group("sber")
        self.assertEqual(self.catalog.state.view, "bank")
        self.assertEqual(self.catalog.state.bank_group_id, "sber")
        self.catalog.set_tab("popular")
        self.assertEqual(self.catalog.state.tab_id, "popular")
        self.assertEqual(self.catalog.state.view, "root")
        self.assertIsNone(self.catalog.state.bank_group_id)

    def test_set_bank_group(self) -> None:
        self.catalog.set_bank_group("alfa")
        self.assertEqual(self.catalog.state.tab_id, "banks")
        self.assertEqual(self.catalog.state.view, "bank")
        self.assertEqual(self.catalog.state.bank_group_id, "alfa")

    def test_set_search_normalizes(self) -> None:
        self.catalog.config.normalize_search_text = staticmethod(lambda q: q.strip().lower())
        # Use real normalize via ConfigManager static — patch properly
        from config_manager import ConfigManager

        self.catalog.config.normalize_search_text = ConfigManager.normalize_search_text
        self.catalog.set_search("  Сбер  ")
        self.assertEqual(self.catalog.state.search_query, "сбер")

    def test_state_dataclass_fields(self) -> None:
        state = CatalogState(tab_id="new", search_query="x", view="root")
        self.assertEqual(state.tab_id, "new")
        self.assertEqual(state.search_query, "x")


if __name__ == "__main__":
    unittest.main()
