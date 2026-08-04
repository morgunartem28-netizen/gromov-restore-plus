"""Search correctness for 1.4 pre-release audit."""
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
from config_manager import ConfigManager  # noqa: E402


class SearchAuditTests(unittest.TestCase):
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
                            "id": "vk",
                            "title": "ВКонтакте",
                            "bundleId": "com.vk.vkclient",
                            "appId": 1,
                            "description": "Официальное приложение VK.",
                            "aliases": ["vk", "вк"],
                        },
                        {
                            "id": "max",
                            "title": "MAX",
                            "bundleId": "ru.max",
                            "appId": 2,
                            "description": "Официальный мессенджер.",
                            "aliases": ["макс", "max.ru"],
                        },
                        {
                            "id": "avito",
                            "title": "Авито",
                            "bundleId": "ru.avito",
                            "appId": 3,
                            "description": "Официальное приложение Авито.",
                            "aliases": ["avito"],
                            "versionGroup": "avito",
                        },
                        {
                            "id": "sber",
                            "title": "СБОЛ",
                            "maskTitle": "Сбербанк",
                            "bundleId": "ru.sber",
                            "appId": 4,
                            "description": "Официальное приложение банка.",
                            "bankGroup": "sber",
                            "category": "Банковские приложения",
                        },
                        {
                            "id": "alfa",
                            "title": "А-Ключ",
                            "maskTitle": "Альфа-Банк",
                            "bundleId": "ru.alfa",
                            "appId": 5,
                            "description": "Официальное приложение банка.",
                            "bankGroup": "alfa",
                            "category": "Банковские приложения",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.config_dir / "banking_apps.json").write_text(
            json.dumps({"category": "Банковские приложения", "apps": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.config_dir / "catalog.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "tabs": [
                        {"id": "popular", "title": "Популярные", "kind": "popular"},
                        {"id": "banks", "title": "Банки", "kind": "banks"},
                        {"id": "all", "title": "Все", "kind": "all"},
                    ],
                    "popular": ["max", "avito", "@bank:sber", "@bank:alfa"],
                    "searchAliases": {
                        "сбер": ["сбербанк", "sber"],
                        "авито": ["avito"],
                        "альфа": ["alfa", "альфа-банк"],
                        "max": ["макс"],
                        "макс": ["max"],
                    },
                    "bankGroups": [
                        {"id": "sber", "title": "Сбербанк", "color": "#21A038", "letter": "С"},
                        {"id": "alfa", "title": "Альфа-Банк", "color": "#EF3124", "letter": "A"},
                    ],
                    "categories": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = self.root / "data"
        data.mkdir()
        (data / "user_apps.json").write_text("{}", encoding="utf-8")
        (data / "settings.json").write_text("{}", encoding="utf-8")
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

    def test_case_insensitive_same_hits(self) -> None:
        a = {x.id for x in self.cm.search_apps("Сбер")}
        b = {x.id for x in self.cm.search_apps("сбер")}
        c = {x.id for x in self.cm.search_apps("СБЕР")}
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        self.assertIn("sber", a)

    def test_partial_and_latin_aliases(self) -> None:
        self.assertTrue(any(a.id == "sber" for a in self.cm.search_apps("сбе")))
        self.assertTrue(any(a.id == "sber" for a in self.cm.search_apps("sber")))
        self.assertTrue(any(a.id == "avito" for a in self.cm.search_apps("ави")))
        self.assertTrue(any(a.id == "avito" for a in self.cm.search_apps("avito")))
        self.assertTrue(any(a.id == "max" for a in self.cm.search_apps("max")))
        self.assertTrue(any(a.id == "max" for a in self.cm.search_apps("мак")))

    def test_short_query_does_not_hit_oficialnoe(self) -> None:
        """Regression: «аль» matched «официальное» in descriptions."""
        ids = {a.id for a in self.cm.search_apps("аль")}
        self.assertIn("alfa", ids)
        self.assertNotIn("vk", ids)
        self.assertNotIn("avito", ids)
        self.assertNotIn("max", ids)

    def test_typos_return_empty(self) -> None:
        self.assertEqual(self.cm.search_apps("автио"), [])
        self.assertEqual(self.cm.search_apps("сбре"), [])

    def test_section_scope_banks(self) -> None:
        self.catalog.set_tab("banks")
        banks = self.catalog.search("max", scope="section")
        self.assertFalse(any(a.id == "max" for a in banks))
        sber = self.catalog.search("сбер", scope="section")
        self.assertTrue(any(a.id == "sber" for a in sber))

    def test_yo_normalization(self) -> None:
        # Alias key uses ё in real catalog; ensure normalize maps ё→е symmetrically.
        self.assertEqual(
            ConfigManager.normalize_search_text("Ёлка"),
            ConfigManager.normalize_search_text("елка"),
        )


if __name__ == "__main__":
    unittest.main()
