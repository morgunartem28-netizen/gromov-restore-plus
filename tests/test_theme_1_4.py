"""Theme mode + palette unit tests (no GUI). Dark-only product."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app_settings import ALLOWED_THEME_MODES, AppSettings  # noqa: E402
from theme import (  # noqa: E402
    DARK_THEME,
    THEME,
    apply_theme,
    get_appearance,
    get_theme_mode,
    is_dark_theme,
    normalize_theme_mode,
    theme_mode_from_label,
    theme_mode_label,
)


class ThemeNormalizeTests(unittest.TestCase):
    def test_normalize_theme_mode_always_dark(self) -> None:
        self.assertEqual(normalize_theme_mode("light"), "dark")
        self.assertEqual(normalize_theme_mode("DARK"), "dark")
        self.assertEqual(normalize_theme_mode("system"), "dark")
        self.assertEqual(normalize_theme_mode("weird"), "dark")
        self.assertEqual(normalize_theme_mode(None), "dark")


class ThemeApplyTests(unittest.TestCase):
    def test_apply_theme_always_dark(self) -> None:
        for mode in ("light", "dark", "system", None, "weird"):
            self.assertEqual(apply_theme(mode), "dark")
            self.assertEqual(get_theme_mode(), "dark")
            self.assertEqual(get_appearance(), "dark")
            self.assertTrue(is_dark_theme())
            self.assertEqual(THEME["accent"], DARK_THEME["accent"])
            self.assertEqual(THEME["bg"], DARK_THEME["bg"])

    def test_dark_palette_has_glass_layers(self) -> None:
        apply_theme("dark")
        for key in (
            "glass",
            "glass_outer",
            "glass_inner",
            "glass_highlight",
            "glass_rim",
            "accent_glow",
            "accent_end",
            "card_idle",
            "bg_soft",
        ):
            self.assertIn(key, THEME)
            self.assertTrue(str(THEME[key]).startswith("#"))
        # Cards must not be near-white on dark chrome.
        inner = str(THEME["glass_inner"]).lstrip("#")
        r, g, b = int(inner[0:2], 16), int(inner[2:4], 16), int(inner[4:6], 16)
        self.assertLess(r + g + b, 200)
        # Atmosphere must not be pure black bricks.
        self.assertNotEqual(THEME["bg"], "#000000")
        # Accent stays Apple blue (not purple CTA).
        self.assertEqual(THEME["accent"], "#0A84FF")

    def test_theme_labels_dark_only(self) -> None:
        self.assertEqual(theme_mode_label("light"), "Тёмная")
        self.assertEqual(theme_mode_label("dark"), "Тёмная")
        self.assertEqual(theme_mode_label("system"), "Тёмная")
        self.assertEqual(theme_mode_from_label("Светлая"), "dark")
        self.assertEqual(theme_mode_from_label("Тёмная"), "dark")
        self.assertEqual(theme_mode_from_label("Система"), "dark")


class AppSettingsThemeTests(unittest.TestCase):
    def test_theme_migrates_to_dark(self) -> None:
        self.assertEqual(ALLOWED_THEME_MODES, ("dark",))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            s = AppSettings()
            s.path = path
            s._data = {"theme_mode": "light"}
            self.assertEqual(s.theme_mode, "dark")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("theme_mode"), "dark")

            s.theme_mode = "system"
            self.assertEqual(s.theme_mode, "dark")
            s.theme_mode = "dark"
            self.assertEqual(s.theme_mode, "dark")


if __name__ == "__main__":
    unittest.main()
