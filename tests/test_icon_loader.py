"""Icon loader: LRU cache + shared executor (no unbounded Thread spawn)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from icon_loader import IconLoader, _CTK_CACHE_MAX  # noqa: E402


def _app(app_id: str = "demo") -> SimpleNamespace:
    return SimpleNamespace(
        id=app_id,
        appId=123,
        title="Demo",
        maskTitle="Demo",
        iconFile="",
        iconUrl="",
    )


class IconLoaderTests(unittest.TestCase):
    def test_peek_miss_returns_none(self) -> None:
        loader = IconLoader()
        self.assertIsNone(loader.peek_app_icon(_app(), size=44))

    def test_placeholder_cached(self) -> None:
        loader = IconLoader()
        a = loader.placeholder_app_icon(size=40)
        b = loader.placeholder_app_icon(size=40)
        self.assertIs(a, b)

    def test_lru_evicts(self) -> None:
        loader = IconLoader()
        # Inject fake CTk images into cache beyond limit.
        for i in range(_CTK_CACHE_MAX + 5):
            loader._lru_put_ctk(f"k{i}:44", MagicMock(name=f"img{i}"))
        with loader._lock:
            self.assertLessEqual(len(loader._cache), _CTK_CACHE_MAX)
            self.assertNotIn("k0:44", loader._cache)
            self.assertIn(f"k{_CTK_CACHE_MAX + 4}:44", loader._cache)

    def test_schedule_uses_executor_not_raw_thread(self) -> None:
        loader = IconLoader()
        scheduled: list = []

        def schedule(cb) -> None:
            scheduled.append(cb)

        with patch.object(IconLoader, "_pool") as pool_cls:
            pool = MagicMock()
            pool_cls.return_value = pool
            result = loader.schedule_app_icon(
                _app("x"),
                size=44,
                on_ready=lambda _p: None,
                schedule=schedule,
            )
            self.assertIsNone(result)
            pool.submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
