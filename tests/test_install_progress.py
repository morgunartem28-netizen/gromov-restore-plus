"""Unit tests for install download progress mapping (.ipa.tmp vs .ipa)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from install_service import (  # noqa: E402
    _DOWNLOAD_BAR_END,
    _DOWNLOAD_BAR_START,
    format_download_size,
    map_download_progress,
    pick_download_artifact,
)


class DownloadProgressTests(unittest.TestCase):
    def test_map_zero_starts_at_download_band(self) -> None:
        self.assertAlmostEqual(map_download_progress(0), _DOWNLOAD_BAR_START)

    def test_map_known_total_linear(self) -> None:
        total = 100_000_000
        mid = map_download_progress(total // 2, known_total=total)
        expected = _DOWNLOAD_BAR_START + (_DOWNLOAD_BAR_END - _DOWNLOAD_BAR_START) * 0.5
        self.assertAlmostEqual(mid, expected, places=5)
        self.assertAlmostEqual(
            map_download_progress(total, known_total=total),
            _DOWNLOAD_BAR_END,
            places=5,
        )

    def test_map_unknown_grows_but_stays_below_end(self) -> None:
        small = map_download_progress(10 * 1024 * 1024)
        large = map_download_progress(400 * 1024 * 1024)
        self.assertGreater(small, _DOWNLOAD_BAR_START)
        self.assertGreater(large, small)
        self.assertLess(large, _DOWNLOAD_BAR_END)

    def test_format_size(self) -> None:
        self.assertEqual(format_download_size(50_000), "48 КБ")
        self.assertEqual(format_download_size(5 * 1024 * 1024), "5 МБ")

    def test_pick_prefers_tmp_while_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_id = 12345
            final = root / f"{app_id}_1.2.3.ipa"
            growing = root / f"{app_id}_1.2.3.ipa.tmp"
            final.write_bytes(b"x" * 10)
            growing.write_bytes(b"y" * 1000)
            path, is_temp = pick_download_artifact(root, app_id)
            self.assertEqual(path, growing)
            self.assertTrue(is_temp)

    def test_pick_final_ipa_after_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_id = 999
            final = root / f"{app_id}_9.0.ipa"
            final.write_bytes(b"ipa-bytes")
            path, is_temp = pick_download_artifact(root, app_id)
            self.assertEqual(path, final)
            self.assertFalse(is_temp)

    def test_pick_ignores_other_apps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "111_1.0.ipa.tmp").write_bytes(b"a")
            path, is_temp = pick_download_artifact(root, 222)
            self.assertIsNone(path)
            self.assertFalse(is_temp)


if __name__ == "__main__":
    unittest.main()
