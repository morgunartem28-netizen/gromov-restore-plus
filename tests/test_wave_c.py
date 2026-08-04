"""Wave C unit tests: dates, manifest sig, recent, categories, virtual batch."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app_settings import RECENT_INSTALL_LIMIT, AppSettings  # noqa: E402
from date_format import format_relative_install  # noqa: E402
from manifest_crypto import (  # noqa: E402
    ManifestSignatureError,
    canonical_manifest_bytes,
    maybe_verify_manifest,
    verify_manifest_ed25519,
)
from virtual_list import BatchCatalogList, DEFAULT_BATCH  # noqa: E402


class DateFormatTests(unittest.TestCase):
    def test_relative(self) -> None:
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        today = now.isoformat()
        yesterday = (now - timedelta(days=1)).isoformat()
        three = (now - timedelta(days=3)).isoformat()
        self.assertIn("сегодня", format_relative_install(today, now=now))
        self.assertIn("вчера", format_relative_install(yesterday, now=now))
        self.assertIn("3", format_relative_install(three, now=now))


class RecentLimitTests(unittest.TestCase):
    def test_limit_10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with mock.patch("app_settings.data_dir", return_value=data):
                settings = AppSettings()
                for i in range(15):
                    settings.remember_install(f"app-{i}")
                self.assertEqual(len(settings.recent_installs), RECENT_INSTALL_LIMIT)
                self.assertEqual(settings.recent_installs[0], "app-14")
                settings.clear_recent_installs()
                self.assertEqual(settings.recent_installs, [])

    def test_install_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with mock.patch("app_settings.data_dir", return_value=data):
                settings = AppSettings()
                settings.record_install_result("max", title="MAX", result="ok")
                settings.record_install_result("vk", title="VK", result="error", error="fail")
                hist = settings.install_history
                self.assertEqual(hist[0]["id"], "vk")
                self.assertEqual(hist[0]["result"], "error")
                self.assertIn("max", settings.recent_installs)


class ManifestCryptoTests(unittest.TestCase):
    def test_canonical_stable(self) -> None:
        a = canonical_manifest_bytes(
            {"version": "1.4.0", "sha256": "ABC", "setup_url": "https://x"}
        )
        b = canonical_manifest_bytes(
            {"setup_url": "https://x", "version": "1.4.0", "setup_sha256": "ABC"}
        )
        self.assertEqual(a, b)

    def test_verify_roundtrip(self) -> None:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("cryptography not installed")
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes_raw()
        payload = {
            "version": "1.4.0",
            "sha256": "a" * 64,
            "setup_url": "https://github.com/x/y/releases/download/1.4.0/Setup.exe",
        }
        sig = key.sign(canonical_manifest_bytes(payload))
        payload["signature"] = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
        pub_b64 = base64.urlsafe_b64encode(pub).decode("ascii").rstrip("=")
        verify_manifest_ed25519(payload, public_key_b64=pub_b64)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "key.txt"
            path.write_text(pub_b64, encoding="utf-8")
            self.assertEqual(
                maybe_verify_manifest(payload, pubkey_path=path, require=True),
                "ok:ed25519",
            )
            bad = dict(payload)
            bad["signature"] = base64.urlsafe_b64encode(b"\x00" * 64).decode("ascii")
            with self.assertRaises(ManifestSignatureError):
                maybe_verify_manifest(bad, pubkey_path=path, require=True)

    def test_skip_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.ed25519"
            status = maybe_verify_manifest({"version": "1"}, pubkey_path=path, require=False)
            self.assertEqual(status, "skip:no-pubkey")


class VirtualListTests(unittest.TestCase):
    def test_batch_constants(self) -> None:
        self.assertGreaterEqual(DEFAULT_BATCH, 20)


class CategoryConfigTests(unittest.TestCase):
    def test_order_and_hidden(self) -> None:
        from catalog_tabs import parse_catalog_tabs
        from config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            (config / "apps.json").write_text(
                json.dumps({"apps": [{"id": "max", "title": "MAX", "bundleId": "x", "appId": 1}]}),
                encoding="utf-8",
            )
            (config / "banking_apps.json").write_text(json.dumps({"apps": []}), encoding="utf-8")
            (config / "catalog.json").write_text(
                json.dumps(
                    {
                        "tabs": [{"id": "all", "title": "Все", "kind": "all"}],
                        "categories": [
                            {"id": "z", "title": "Z", "order": 9, "match": {"appIds": []}},
                            {
                                "id": "hidden",
                                "title": "Hidden",
                                "order": 1,
                                "hidden": True,
                                "match": {"appIds": ["max"]},
                            },
                            {"id": "a", "title": "A", "order": 1, "match": {"appIds": ["max"]}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            data = root / "data"
            data.mkdir()
            (data / "user_apps.json").write_text(
                (config / "apps.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with mock.patch("config_manager.resource_dir", return_value=root), mock.patch(
                "config_manager.data_dir", return_value=data
            ), mock.patch("config_manager.install_dir", return_value=root):
                cm = ConfigManager()
                cats = cm.catalog_categories()
                self.assertEqual([c["id"] for c in cats], ["a", "z"])
                self.assertEqual(cm.category_app_count("a"), 1)
                tabs = parse_catalog_tabs(cm.catalog_tabs_raw())
                self.assertEqual(tabs[0].id, "all")


class DpapiPlaintextTests(unittest.TestCase):
    def test_rejects_plain_prefix(self) -> None:
        from dpapi_store import load_secret

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            path.write_bytes(b"plain:should-not-load")
            self.assertIsNone(load_secret(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
