"""Unit tests for GROMOV Restore+ 1.4 catalog foundation (Wave A)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app_settings import AppSettings  # noqa: E402
from catalog_controller import CatalogController  # noqa: E402
from catalog_tabs import parse_catalog_tabs, tab_by_id, tab_labels  # noqa: E402
from config_manager import ConfigManager  # noqa: E402


class CatalogTabsTests(unittest.TestCase):
    def test_default_tabs_when_empty(self) -> None:
        tabs = parse_catalog_tabs([])
        ids = [t.id for t in tabs]
        self.assertIn("popular", ids)
        self.assertIn("recent", ids)
        self.assertIn("banks", ids)

    def test_parse_category_tab(self) -> None:
        tabs = parse_catalog_tabs(
            [
                {"id": "social", "title": "Соцсети", "kind": "category", "categoryId": "social"},
            ]
        )
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0].kind, "category")
        self.assertEqual(tabs[0].category_id, "social")
        self.assertEqual(tab_labels(tabs), ["Соцсети"])
        self.assertIsNotNone(tab_by_id(tabs, "social"))


class CatalogConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        (self.config_dir / "apps.json").write_text(
            json.dumps(
                {
                    "apps": [
                        {
                            "id": "max",
                            "title": "MAX",
                            "bundleId": "ru.max",
                            "appId": 1,
                            "description": "Мессенджер",
                        },
                        {
                            "id": "vk",
                            "title": "VK",
                            "bundleId": "com.vk",
                            "appId": 2,
                            "description": "Соцсеть",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.config_dir / "banking_apps.json").write_text(
            json.dumps(
                {
                    "category": "Банковские приложения",
                    "apps": [
                        {
                            "id": "sber",
                            "title": "СберБанк",
                            "bundleId": "ru.sberbank",
                            "appId": 3,
                            "description": "Банк",
                            "bankGroup": "sber",
                            "maskTitle": "Сбер",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.config_dir / "catalog.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "tabs": [
                        {"id": "popular", "title": "Популярные", "kind": "popular"},
                        {"id": "recent", "title": "Недавние", "kind": "recent"},
                        {"id": "banks", "title": "Банки", "kind": "banks"},
                        {
                            "id": "social",
                            "title": "Соцсети",
                            "kind": "category",
                            "categoryId": "social",
                        },
                        {"id": "all", "title": "Все", "kind": "all"},
                    ],
                    "categories": [
                        {"id": "banks", "title": "Банки", "match": {"isBanking": True}},
                        {"id": "social", "title": "Соцсети", "match": {"appIds": ["max", "vk"]}},
                    ],
                    "bankGroups": [
                        {"id": "sber", "title": "Сбербанк", "color": "#21A038", "letter": "С"},
                    ],
                    "popular": ["max", "vk"],
                    "searchAliases": {"сбер": ["сбербанк"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = self.root / "data"
        data.mkdir()
        (data / "user_apps.json").write_text(
            (self.config_dir / "apps.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        with mock.patch("config_manager.resource_dir", return_value=self.root), mock.patch(
            "config_manager.data_dir", return_value=data
        ), mock.patch("config_manager.install_dir", return_value=self.root):
            self.cm = ConfigManager()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_bank_groups_from_json(self) -> None:
        groups = self.cm.all_bank_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].id, "sber")

    def test_list_apps_for_category(self) -> None:
        social = self.cm.list_apps_for_category("social")
        self.assertEqual({a.id for a in social}, {"max", "vk"})
        banks = self.cm.list_apps_for_category("banks")
        self.assertEqual([a.id for a in banks], ["sber"])

    def test_tabs_raw(self) -> None:
        raw = self.cm.catalog_tabs_raw()
        self.assertEqual(len(raw), 5)


class CatalogControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        (self.config_dir / "apps.json").write_text(
            json.dumps(
                {
                    "apps": [
                        {"id": "max", "title": "MAX", "bundleId": "ru.max", "appId": 1},
                        {"id": "vk", "title": "VK", "bundleId": "com.vk", "appId": 2},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.config_dir / "banking_apps.json").write_text(
            json.dumps(
                {
                    "category": "Банковские приложения",
                    "apps": [
                        {
                            "id": "sber",
                            "title": "СберБанк",
                            "bundleId": "ru.sber",
                            "appId": 3,
                            "bankGroup": "sber",
                            "maskTitle": "Сбер",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.config_dir / "catalog.json").write_text(
            json.dumps(
                {
                    "tabs": [
                        {"id": "popular", "title": "Популярные", "kind": "popular"},
                        {"id": "banks", "title": "Банки", "kind": "banks"},
                        {"id": "all", "title": "Все", "kind": "all"},
                    ],
                    "popular": ["max"],
                    "bankGroups": [{"id": "sber", "title": "Сбер", "color": "#0", "letter": "С"}],
                    "categories": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = self.root / "data"
        data.mkdir()
        (data / "user_apps.json").write_text(
            (self.config_dir / "apps.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        settings_path = data / "settings.json"
        settings_path.write_text("{}", encoding="utf-8")
        with mock.patch("config_manager.resource_dir", return_value=self.root), mock.patch(
            "config_manager.data_dir", return_value=data
        ), mock.patch("config_manager.install_dir", return_value=self.root), mock.patch(
            "app_settings.data_dir", return_value=data
        ):
            self.settings = AppSettings()
            self.cm = ConfigManager()
            self.catalog = CatalogController(self.cm, self.settings)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_section_vs_all(self) -> None:
        self.catalog.set_tab("banks")
        section = self.catalog.search("сбер", scope="section")
        everywhere = self.catalog.search("max", scope="all")
        self.assertTrue(any(a.id == "sber" for a in section))
        self.assertTrue(any(a.id == "max" for a in everywhere))
        section_max = self.catalog.search("max", scope="section")
        self.assertFalse(any(a.id == "max" for a in section_max))

    def test_recent_apps(self) -> None:
        self.settings.remember_install("vk")
        self.settings.remember_install("max")
        apps = self.catalog.list_recent_apps()
        self.assertEqual([a.id for a in apps], ["max", "vk"])
        self.assertTrue(self.catalog.recent_install_at("max"))

    def test_sort_alpha_ru_first(self) -> None:
        apps = self.cm.list_apps()
        sorted_apps = self.catalog.sort_apps(apps, mode="alpha")
        titles = [a.display_title() for a in sorted_apps]
        self.assertEqual(titles[0][0].upper(), "С")

    def test_list_for_tab_banks(self) -> None:
        self.catalog.set_tab("banks")
        self.catalog.set_sort("alpha")
        result = self.catalog.list_for_tab()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(any(a.id == "sber" for a in result.apps))
        self.assertEqual(result.title, "Банки")

    def test_list_for_tab_popular_is_none(self) -> None:
        self.catalog.set_tab("popular")
        self.assertIsNone(self.catalog.list_for_tab())

    def test_set_sort_mode(self) -> None:
        self.catalog.set_sort("popular")
        self.assertEqual(self.catalog.state.sort_mode, "popular")
        self.catalog.set_sort("bogus")
        self.assertEqual(self.catalog.state.sort_mode, "alpha")


class RecentInstallSettingsTests(unittest.TestCase):
    def test_legacy_string_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            path = data / "settings.json"
            path.write_text(json.dumps({"recent_installs": ["a", "b"]}), encoding="utf-8")
            with mock.patch("app_settings.data_dir", return_value=data):
                settings = AppSettings()
                self.assertEqual(settings.recent_installs, ["a", "b"])
                settings.remember_install("c")
                self.assertEqual(settings.recent_installs[0], "c")
                self.assertTrue(settings.recent_install_records[0]["at"])


if __name__ == "__main__":
    unittest.main()
