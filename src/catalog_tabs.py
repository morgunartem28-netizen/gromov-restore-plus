"""Catalog tab registry — config-driven sections for GROMOV Restore+ 1.4."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CatalogTab:
    id: str
    title: str
    kind: str  # popular | new | recent | banks | all | category
    category_id: str = ""


DEFAULT_TABS: tuple[CatalogTab, ...] = (
    CatalogTab("popular", "Популярные", "popular"),
    CatalogTab("new", "Новые", "new"),
    CatalogTab("recent", "Недавние", "recent"),
    CatalogTab("banks", "Банки", "banks"),
    CatalogTab("all", "Все", "all"),
)


def parse_catalog_tabs(raw: Any) -> list[CatalogTab]:
    """Parse tabs from catalog.json; fall back to DEFAULT_TABS."""
    if not isinstance(raw, list) or not raw:
        return list(DEFAULT_TABS)
    tabs: list[CatalogTab] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tab_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        kind = str(item.get("kind") or tab_id or "").strip() or "all"
        if not tab_id or not title:
            continue
        category_id = str(item.get("categoryId") or item.get("category_id") or "").strip()
        tabs.append(CatalogTab(id=tab_id, title=title, kind=kind, category_id=category_id))
    return tabs or list(DEFAULT_TABS)


def tab_labels(tabs: list[CatalogTab]) -> list[str]:
    return [tab.title for tab in tabs]


def tab_by_label(tabs: list[CatalogTab], label: str) -> CatalogTab | None:
    for tab in tabs:
        if tab.title == label:
            return tab
    return None


def tab_by_id(tabs: list[CatalogTab], tab_id: str) -> CatalogTab | None:
    for tab in tabs:
        if tab.id == tab_id:
            return tab
    return None
