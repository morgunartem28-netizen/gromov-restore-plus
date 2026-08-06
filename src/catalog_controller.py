"""Catalog domain façade — load / filter / sort / search (UI-agnostic)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal

from app_settings import AppSettings
from catalog_tabs import CatalogTab, parse_catalog_tabs, tab_by_id
from config_manager import AppEntry, ConfigManager, VersionGroup

SearchScope = Literal["section", "all"]
SortMode = Literal["alpha", "popular", "new", "recent"]

SORT_LABELS: tuple[tuple[SortMode, str], ...] = (
    ("alpha", "А–Я"),
    ("popular", "Популярность"),
    ("new", "Новизна"),
    ("recent", "Недавние"),
)

SORT_LABEL_TO_MODE: dict[str, SortMode] = {label: mode for mode, label in SORT_LABELS}
SORT_MODE_TO_LABEL: dict[SortMode, str] = {mode: label for mode, label in SORT_LABELS}


@dataclass
class CatalogState:
    tab_id: str = "popular"
    search_query: str = ""
    search_scope: SearchScope = "section"
    sort_mode: SortMode = "alpha"
    bank_group_id: str | None = None
    view: Literal["root", "bank"] = "root"


@dataclass(frozen=True)
class TabListResult:
    """Flat app list for tabs that render via _render_app_cards."""

    apps: list[AppEntry]
    title: str
    subtitle: str
    badge_new: bool = True
    collapse_versions: bool = True
    empty_title: str = ""
    empty_hint: str = ""


class CatalogController:
    """Thin façade over ConfigManager + settings for 1.4 catalog features."""

    def __init__(self, config: ConfigManager, settings: AppSettings) -> None:
        self.config = config
        self.settings = settings
        self.state = CatalogState()
        self._tabs = parse_catalog_tabs(config.catalog_tabs_raw())

    @property
    def tabs(self) -> list[CatalogTab]:
        return list(self._tabs)

    def reload_tabs(self) -> None:
        self._tabs = parse_catalog_tabs(self.config.catalog_tabs_raw())

    def current_tab(self) -> CatalogTab:
        return tab_by_id(self._tabs, self.state.tab_id) or self._tabs[0]

    def set_tab(self, tab_id: str) -> None:
        if tab_by_id(self._tabs, tab_id) is None:
            tab_id = self._tabs[0].id
        self.state.tab_id = tab_id
        self.state.view = "root"
        self.state.bank_group_id = None

    def set_view(self, view: Literal["root", "bank"], *, bank_group_id: str | None = None) -> None:
        """Set catalog drill-down view (root list vs bank group)."""
        if view == "bank":
            self.state.view = "bank"
            self.state.bank_group_id = bank_group_id
            self.state.tab_id = "banks"
        else:
            self.state.view = "root"
            self.state.bank_group_id = None

    def set_bank_group(self, bank_group_id: str | None) -> None:
        if bank_group_id:
            self.set_view("bank", bank_group_id=bank_group_id)
        else:
            self.set_view("root")

    def set_search(self, query: str, *, scope: SearchScope | None = None) -> None:
        self.state.search_query = ConfigManager.normalize_search_text(query)
        if scope is not None:
            self.state.search_scope = scope

    def set_sort(self, mode: SortMode | str) -> None:
        if mode not in SORT_MODE_TO_LABEL:
            mode = "alpha"
        self.state.sort_mode = mode  # type: ignore[assignment]

    def list_recent_apps(self) -> list[AppEntry]:
        apps: list[AppEntry] = []
        seen: set[str] = set()
        for app_id in self.settings.recent_installs:
            if app_id in seen:
                continue
            app = self.config.get_app(app_id)
            if app is None:
                continue
            seen.add(app_id)
            apps.append(app)
        return apps

    def recent_install_at(self, app_id: str) -> str:
        for rec in self.settings.recent_install_records:
            if rec["id"] == app_id:
                return rec.get("at") or ""
        return ""

    def search(
        self,
        query: str,
        *,
        tab: CatalogTab | None = None,
        scope: SearchScope = "section",
    ) -> list[AppEntry]:
        q = ConfigManager.normalize_search_text(query)
        t0 = time.perf_counter()
        empty_reason = ""
        if not q:
            empty_reason = "empty_query"
            result: list[AppEntry] = []
        else:
            tab = tab or self.current_tab()
            if scope == "all":
                result = self.sort_apps(self.config.search_apps(q))
            elif tab.kind == "banks":
                result = self.sort_apps(
                    [
                        app
                        for app in self.config.list_banking_apps()
                        if self.config.app_matches_query(app, q)
                    ]
                )
            elif tab.kind == "new":
                result = self.sort_apps(
                    [
                        app
                        for app in self.config.list_new_apps()
                        if self.config.app_matches_query(app, q)
                    ]
                )
            elif tab.kind == "recent":
                result = self.sort_apps(
                    [
                        app
                        for app in self.list_recent_apps()
                        if self.config.app_matches_query(app, q)
                    ]
                )
            elif tab.kind == "popular":
                popular_ids = set(self.config.popular_item_ids())
                matches: list[AppEntry] = []
                for app in self.config.search_apps(q):
                    if app.id in popular_ids:
                        matches.append(app)
                        continue
                    if app.versionGroup and f"@version:{app.versionGroup}" in popular_ids:
                        matches.append(app)
                        continue
                    if app.bankGroup and f"@bank:{app.bankGroup}" in popular_ids:
                        matches.append(app)
                seen: set[str] = set()
                deduped: list[AppEntry] = []
                for app in matches:
                    key = app.versionGroup or app.id
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(app)
                result = self.sort_apps(deduped)
            elif tab.kind == "category" and tab.category_id:
                result = self.sort_apps(
                    [
                        app
                        for app in self.config.list_apps_for_category(tab.category_id)
                        if self.config.app_matches_query(app, q)
                    ]
                )
            else:
                # «Все» and unknown kinds — full catalog, section-scoped to all apps.
                result = self.sort_apps(self.config.search_apps(q))
            if not result:
                empty_reason = "no_matches_in_section"

        if os.environ.get("GROMOV_SEARCH_DEBUG", "").strip().lower() in {"1", "true", "yes"}:
            tab_id = (tab or self.current_tab()).id if q else self.state.tab_id
            ms = (time.perf_counter() - t0) * 1000
            print(
                f"[search] tab={tab_id} q={query!r} hits={len(result)} "
                f"{ms:.2f}ms reason={empty_reason or 'ok'}",
                flush=True,
            )
        return result

    def sort_apps(self, apps: list[AppEntry], mode: SortMode | None = None) -> list[AppEntry]:
        mode = mode or self.state.sort_mode
        items = list(apps)
        if mode == "new":
            items.sort(key=lambda a: a.freshness_date() or "", reverse=True)
            return items
        if mode == "popular":
            popular = {pid: index for index, pid in enumerate(self.config.popular_item_ids())}
            items.sort(
                key=lambda a: (
                    popular.get(a.id, popular.get(f"@version:{a.versionGroup or ''}", 10_000)),
                    ConfigManager.sort_key_ru_first(a.display_title()),
                )
            )
            return items
        if mode == "recent":
            order = {app_id: index for index, app_id in enumerate(self.settings.recent_installs)}
            items.sort(key=lambda a: order.get(a.id, 10_000))
            return items
        items.sort(key=lambda a: ConfigManager.sort_key_ru_first(a.display_title()))
        return items

    def list_for_tab(self, tab: CatalogTab | None = None) -> TabListResult | None:
        """Sorted apps for flat-list tabs. None = custom UI (popular / all)."""
        tab = tab or self.current_tab()
        if tab.kind in ("popular", "all"):
            return None
        if tab.kind == "new":
            apps = self.sort_apps(self.config.list_new_apps(), mode="alpha")
            days = self.config.new_app_days()
            return TabListResult(
                apps=apps,
                title="Новые",
                subtitle="",
                badge_new=True,
                collapse_versions=True,
                empty_title="Новых приложений нет",
                empty_hint=f"Здесь появляются приложения за последние {days} дней.",
            )
        if tab.kind == "recent":
            apps = self.list_recent_apps()
            return TabListResult(
                apps=apps,
                title="Недавние",
                subtitle="",
                badge_new=False,
                collapse_versions=False,
                empty_title="Пока пусто",
                empty_hint="Здесь появятся приложения после первой установки.",
            )
        if tab.kind == "banks":
            apps = self.sort_apps(list(self.config.list_banking_apps()), mode="alpha")
            return TabListResult(
                apps=apps,
                title="Банки",
                subtitle="",
                badge_new=True,
                collapse_versions=False,
                empty_title="Банки пока пусты",
                empty_hint="Банковские приложения появятся после обновления каталога.",
            )
        if tab.kind == "category" and tab.category_id:
            apps = self.sort_apps(self.config.list_apps_for_category(tab.category_id), mode="alpha")
            return TabListResult(
                apps=apps,
                title=tab.title,
                subtitle="",
                badge_new=True,
                collapse_versions=True,
                empty_title=f"Раздел «{tab.title}» пуст",
                empty_hint="Добавьте приложения в catalog.json → categories.",
            )
        return None

    def resolve_version_group(self, group_id: str) -> VersionGroup | None:
        return self.config.get_version_group(group_id)
