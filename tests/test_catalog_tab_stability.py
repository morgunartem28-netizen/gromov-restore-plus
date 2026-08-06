"""Catalog tab stability / batch-list stress for 1.4 UX fix."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from virtual_list import BatchCatalogList, DEFAULT_BATCH  # noqa: E402


class _FakeCanvas:
    def __init__(self) -> None:
        self._binds: list[tuple[str, object]] = []

    def bind(self, sequence: str, func: object, add: str | None = None) -> None:
        self._binds.append((sequence, func))

    def yview(self) -> tuple[float, float]:
        return (0.0, 0.5)


class _FakeHost:
    def __init__(self) -> None:
        self._parent_canvas = _FakeCanvas()
        self._after: list[tuple[int, object]] = []

    def after(self, ms: int, callback: object) -> str:
        self._after.append((ms, callback))
        return "1"


class BatchListStabilityTests(unittest.TestCase):
    def test_cancel_stops_further_render(self) -> None:
        host = _FakeHost()
        rendered: list[int] = []

        def render(item: int, index: int) -> None:
            rendered.append(item)

        batch = BatchCatalogList(host, render_item=render, batch_size=5)  # type: ignore[arg-type]
        batch.reset(list(range(40)), token=1)
        # Constructor clamps batch_size to min 10.
        self.assertEqual(len(rendered), 10)
        batch.cancel()
        # Flush pending after callbacks — cancelled batch must not render more.
        for _ms, cb in list(host._after):
            if callable(cb):
                cb()
        self.assertEqual(len(rendered), 10)
        self.assertEqual(batch.remaining, 0)

    def test_only_active_batch_receives_host_slot(self) -> None:
        host = _FakeHost()
        a = BatchCatalogList(host, render_item=lambda *_: None, batch_size=10)  # type: ignore[arg-type]
        b = BatchCatalogList(host, render_item=lambda *_: None, batch_size=10)  # type: ignore[arg-type]
        a.reset(list(range(20)), token=1)
        b.reset(list(range(20)), token=2)
        self.assertIs(getattr(host, "_gromov_active_batch"), b)
        a.cancel()
        # Cancelling inactive must not clear the active pointer.
        self.assertIs(getattr(host, "_gromov_active_batch"), b)
        b.cancel()
        self.assertIsNone(getattr(host, "_gromov_active_batch"))

    def test_scroll_bind_once(self) -> None:
        host = _FakeHost()
        a = BatchCatalogList(host, render_item=lambda *_: None, batch_size=10)  # type: ignore[arg-type]
        b = BatchCatalogList(host, render_item=lambda *_: None, batch_size=10)  # type: ignore[arg-type]
        a.reset([1, 2, 3], token=1)
        binds_after_first = len(host._parent_canvas._binds)
        b.reset([1, 2, 3], token=2)
        self.assertEqual(len(host._parent_canvas._binds), binds_after_first)

    def test_max_rendered_soft_cap(self) -> None:
        host = _FakeHost()
        rendered: list[int] = []

        def render(item: int, _index: int) -> None:
            rendered.append(item)

        batch = BatchCatalogList(
            host,
            render_item=render,
            batch_size=10,
            max_rendered=25,
        )  # type: ignore[arg-type]
        batch.reset(list(range(100)), token=1)
        # First batch is 10; keep calling load_more until soft cap.
        while not batch.state.capped and batch.state.rendered < 25:
            batch.load_more()
        self.assertEqual(len(rendered), 25)
        self.assertTrue(batch.state.capped)
        self.assertFalse(batch.is_complete)

    def test_default_batch_constant(self) -> None:
        self.assertEqual(DEFAULT_BATCH, 40)


class PanelCompleteLogicTests(unittest.TestCase):
    """Simulate incomplete-cache rule used by main._refresh_app_list."""

    def test_incomplete_panels_are_not_reusable(self) -> None:
        complete = {"tab:all": False, "tab:popular": True}
        panels = {"tab:all": object(), "tab:popular": object()}

        def reusable(key: str) -> bool:
            return key in panels and complete.get(key, False) and not key.startswith("search:")

        self.assertFalse(reusable("tab:all"))
        self.assertTrue(reusable("tab:popular"))

        # Purge incomplete
        for key in list(panels):
            if not complete.get(key, False):
                panels.pop(key, None)
                complete.pop(key, None)
        self.assertNotIn("tab:all", panels)
        self.assertIn("tab:popular", panels)


if __name__ == "__main__":
    unittest.main()
