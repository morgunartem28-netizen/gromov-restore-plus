from __future__ import annotations

import json
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from app_paths import data_dir, install_dir, resource_dir
from ipa_utils import cleanup_download_artifacts, is_valid_ipa


BANKING_CATEGORY = "Банковские приложения"
BANKS_FOLDER_TITLE = "Банки"
DEFAULT_NEW_APP_DAYS = 30


@dataclass(frozen=True)
class BankGroup:
    id: str
    title: str
    color: str
    letter: str


BANK_GROUPS: tuple[BankGroup, ...] = (
    BankGroup("sber", "Сбербанк", "#21A038", "С"),
    BankGroup("tbank", "Т-Банк", "#FFDD2D", "T"),
    BankGroup("alfa", "Альфа-Банк", "#EF3124", "A"),
    BankGroup("sovcom", "Совкомбанк", "#003791", "С"),
    BankGroup("gazprom", "Газпромбанк", "#2355D7", "Г"),
    BankGroup("psb", "ПСБ", "#E35205", "П"),
    BankGroup("vtb", "ВТБ", "#002882", "В"),
    BankGroup("mts", "МТС Банк", "#E30611", "M"),
    BankGroup("rshb", "Россельхозбанк", "#006B3F", "Р"),
)


@dataclass(frozen=True)
class VersionOption:
    app_id: str
    label: str
    hint: str = ""


@dataclass(frozen=True)
class VersionGroup:
    id: str
    title: str
    icon_app_id: str
    options: tuple[VersionOption, ...]


@dataclass
class AppEntry:
    id: str
    title: str
    bundleId: str
    appId: int
    description: str = ""
    iconUrl: str = ""
    iconFile: str = ""
    category: str = ""
    maskTitle: str = ""
    bankGroup: str = ""
    released: str = ""
    removed: str = ""
    addedAt: str = ""
    versionGroup: str = ""
    catalogStandalone: bool = False
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "AppEntry":
        raw_aliases = data.get("aliases") or []
        aliases = [str(item).strip() for item in raw_aliases if str(item).strip()] if isinstance(raw_aliases, list) else []
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            bundleId=str(data.get("bundleId", "")),
            appId=int(data["appId"]),
            description=str(data.get("description", "")),
            iconUrl=str(data.get("iconUrl", "")),
            iconFile=str(data.get("iconFile", "")),
            category=str(data.get("category", "")),
            maskTitle=str(data.get("maskTitle", "")),
            bankGroup=str(data.get("bankGroup", "")),
            released=str(data.get("released", "")),
            removed=str(data.get("removed", "")),
            addedAt=str(data.get("addedAt", "")),
            versionGroup=str(data.get("versionGroup", "")),
            catalogStandalone=bool(data.get("catalogStandalone", False)),
            aliases=aliases,
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        if not payload.get("aliases"):
            payload.pop("aliases", None)
        if not payload.get("catalogStandalone"):
            payload.pop("catalogStandalone", None)
        for key in ("addedAt", "versionGroup", "released", "removed", "maskTitle", "bankGroup", "category"):
            if not payload.get(key):
                payload.pop(key, None)
        return payload

    @property
    def is_banking(self) -> bool:
        return self.category == BANKING_CATEGORY

    def version_label(self) -> str:
        if self.maskTitle:
            return self.maskTitle
        return f"ID {self.appId}"

    def display_title(self) -> str:
        return self.maskTitle or self.title

    def freshness_date(self) -> str:
        return self.addedAt or self.released or ""


class ConfigManager:
    def __init__(self) -> None:
        self.base_dir = install_dir()
        self.default_apps_path = resource_dir() / "config" / "apps.json"
        self.banking_apps_path = resource_dir() / "config" / "banking_apps.json"
        self.catalog_config_path = resource_dir() / "config" / "catalog.json"
        self.user_apps_path = data_dir() / "user_apps.json"
        self.cache_dir = data_dir()
        self.downloads_root = self.cache_dir / "downloads"
        self._apple_account_email: str | None = None
        self._apps_cache: list[AppEntry] | None = None
        self._apps_cache_key: tuple[float, float, float, float] | None = None
        self._catalog_cfg_cache: dict | None = None
        self._catalog_cfg_mtime: float = 0.0
        self._account_lock = threading.RLock()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_root.mkdir(parents=True, exist_ok=True)
        self._ensure_user_config()
        self._migrate_known_app_ids()

    def invalidate_apps_cache(self) -> None:
        self._apps_cache = None
        self._apps_cache_key = None
        self._catalog_cfg_cache = None
        self._catalog_cfg_mtime = 0.0

    def _apps_source_key(self) -> tuple[float, float, float, float]:
        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        return (
            mtime(self.default_apps_path),
            mtime(self.banking_apps_path),
            mtime(self.user_apps_path),
            mtime(self.catalog_config_path),
        )

    @property
    def apple_account_email(self) -> str | None:
        with self._account_lock:
            return self._apple_account_email

    def set_apple_account(self, email: str | None) -> None:
        normalized = (email or "").strip().lower()
        with self._account_lock:
            self._apple_account_email = normalized or None

    @staticmethod
    def account_dir_name(email: str) -> str:
        """Opaque folder name — do not embed the Apple ID email in the path."""
        import hashlib

        digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]
        return f"acct_{digest}"

    @staticmethod
    def _legacy_account_dir_name(email: str) -> str:
        normalized = email.strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in "@._-+'" else "_" for ch in normalized)
        return safe or "unknown"

    def account_downloads_dir(self) -> Path | None:
        if not self._apple_account_email:
            return None
        path = self.downloads_root / self.account_dir_name(self._apple_account_email)
        legacy = self.downloads_root / self._legacy_account_dir_name(self._apple_account_email)
        if legacy.exists() and not path.exists():
            try:
                legacy.rename(path)
            except OSError:
                path = legacy
        path.mkdir(parents=True, exist_ok=True)
        return path

    _APP_ID_FIXES: dict[str, int] = {
        # Раньше ошибочно стоял ID Облака Mail (696551382) вместо Почты.
        "mailru": 511310430,
    }

    _BUNDLE_ID_FIXES: dict[str, str] = {
        # В IPA Авито реальный bundle ID — ru.avito.app.
        "avito": "ru.avito.app",
        # У Почты Mail.ru (511310430) в IPA bundle ID — ru.mail.mail.
        "mailru": "ru.mail.mail",
        # В IPA VK Видео — com.vk.vkvideo.prod (каталог раньше брал Android-id).
        "vk-video": "com.vk.vkvideo.prod",
        # VK Музыка (1054372220): в каталоге был выдуманный com.vk.vkclient.music;
        # IPA-хабы индексируют как com.music.vk (подтвердить CFBundleIdentifier при появлении IPA).
        "vk-music": "com.music.vk",
    }

    def _migrate_known_app_ids(self) -> None:
        apps = self._read_apps_file(self.user_apps_path)
        changed = False
        for index, app in enumerate(apps):
            fixed_id = self._APP_ID_FIXES.get(app.id)
            fixed_bundle = self._BUNDLE_ID_FIXES.get(app.id)
            new_app_id = fixed_id if fixed_id is not None and app.appId != fixed_id else app.appId
            new_bundle = fixed_bundle if fixed_bundle is not None and app.bundleId != fixed_bundle else app.bundleId
            if new_app_id != app.appId or new_bundle != app.bundleId:
                apps[index] = AppEntry(
                    id=app.id,
                    title=app.title,
                    bundleId=new_bundle,
                    appId=new_app_id,
                    description=app.description,
                    iconUrl=app.iconUrl,
                    iconFile=app.iconFile,
                    category=app.category,
                    maskTitle=app.maskTitle,
                    bankGroup=app.bankGroup,
                    released=app.released,
                    removed=app.removed,
                    addedAt=app.addedAt,
                    versionGroup=app.versionGroup,
                    catalogStandalone=app.catalogStandalone,
                    aliases=list(app.aliases),
                )
                changed = True
        if changed:
            self._write_apps_file(self.user_apps_path, apps)
            self.invalidate_apps_cache()

    def _ensure_user_config(self) -> None:
        if not self.user_apps_path.exists():
            shutil.copy(self.default_apps_path, self.user_apps_path)

    def _read_apps_file(self, path: Path) -> list[AppEntry]:
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Corrupt user/bundled JSON must not crash cold start.
            print(f"[config] failed to read {path.name}: {exc}", flush=True)
            return []
        if not isinstance(payload, dict):
            return []
        apps: list[AppEntry] = []
        for item in payload.get("apps", []) or []:
            try:
                apps.append(AppEntry.from_dict(item))
            except (TypeError, ValueError, KeyError) as exc:
                print(f"[config] skip bad app entry in {path.name}: {exc}", flush=True)
        return apps

    def _write_apps_file(self, path: Path, apps: list[AppEntry]) -> None:
        payload = {"version": 1, "apps": [app.to_dict() for app in apps]}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _read_banking_apps(self) -> list[AppEntry]:
        if not self.banking_apps_path.exists():
            return []
        try:
            with self.banking_apps_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[config] failed to read banking_apps.json: {exc}", flush=True)
            return []
        if not isinstance(payload, dict):
            return []
        category = str(payload.get("category") or BANKING_CATEGORY)
        apps: list[AppEntry] = []
        for item in payload.get("apps", []) or []:
            try:
                entry = AppEntry.from_dict(item)
            except (TypeError, ValueError, KeyError) as exc:
                print(f"[config] skip bad banking entry: {exc}", flush=True)
                continue
            if not entry.category:
                entry.category = category
            apps.append(entry)
        return apps

    def _load_catalog_config(self) -> dict:
        mtime = 0.0
        try:
            mtime = self.catalog_config_path.stat().st_mtime
        except OSError:
            return {}
        if self._catalog_cfg_cache is not None and self._catalog_cfg_mtime == mtime:
            return self._catalog_cfg_cache
        try:
            with self.catalog_config_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            cfg = payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            cfg = {}
        self._catalog_cfg_cache = cfg
        self._catalog_cfg_mtime = mtime
        return cfg

    def new_app_days(self) -> int:
        cfg = self._load_catalog_config()
        try:
            days = int(cfg.get("newDays", DEFAULT_NEW_APP_DAYS))
        except (TypeError, ValueError):
            days = DEFAULT_NEW_APP_DAYS
        return max(1, days)

    def catalog_tabs_raw(self) -> list:
        cfg = self._load_catalog_config()
        raw = cfg.get("tabs") or []
        return raw if isinstance(raw, list) else []

    def catalog_categories(self, *, include_hidden: bool = False) -> list[dict]:
        cfg = self._load_catalog_config()
        raw = cfg.get("categories") or []
        items = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        if not include_hidden:
            items = [item for item in items if not bool(item.get("hidden"))]
        def _order(item: dict) -> tuple[int, str]:
            try:
                order = int(item.get("order", 1000))
            except (TypeError, ValueError):
                order = 1000
            return (order, str(item.get("title") or ""))

        return sorted(items, key=_order)

    def category_app_count(self, category_id: str) -> int:
        return len(self.list_apps_for_category(category_id))

    def _bank_groups_from_config(self) -> tuple[BankGroup, ...]:
        cfg = self._load_catalog_config()
        raw = cfg.get("bankGroups") or []
        if not isinstance(raw, list) or not raw:
            return BANK_GROUPS
        groups: list[BankGroup] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            gid = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not gid or not title:
                continue
            groups.append(
                BankGroup(
                    id=gid,
                    title=title,
                    color=str(item.get("color") or "#888888"),
                    letter=str(item.get("letter") or title[:1] or "?"),
                )
            )
        return tuple(groups) if groups else BANK_GROUPS

    def all_bank_groups(self) -> list[BankGroup]:
        return list(self._bank_groups_from_config())

    def list_apps_for_category(self, category_id: str) -> list[AppEntry]:
        """Resolve apps for a catalog.json category definition."""
        category_id = (category_id or "").strip()
        if not category_id:
            return []
        match: dict = {}
        for item in self.catalog_categories():
            if str(item.get("id") or "") == category_id:
                raw_match = item.get("match") or {}
                match = raw_match if isinstance(raw_match, dict) else {}
                break
        else:
            return []

        apps = self.list_apps()
        if match.get("isBanking") is True:
            return [app for app in apps if app.is_banking]

        app_ids = match.get("appIds") or match.get("app_ids") or []
        if isinstance(app_ids, list) and app_ids:
            wanted = {str(x).strip() for x in app_ids if str(x).strip()}
            return [app for app in apps if app.id in wanted]

        category_names = match.get("categoryNames") or match.get("categories") or []
        if isinstance(category_names, list) and category_names:
            names = {str(x).strip().lower() for x in category_names if str(x).strip()}
            return [app for app in apps if (app.category or "").strip().lower() in names]

        return []

    def popular_item_ids(self) -> list[str]:
        cfg = self._load_catalog_config()
        raw = cfg.get("popular") or []
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def recommended_item_ids(self) -> list[str]:
        cfg = self._load_catalog_config()
        raw = cfg.get("recommended") or []
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def search_alias_map(self) -> dict[str, tuple[str, ...]]:
        cfg = self._load_catalog_config()
        raw = cfg.get("searchAliases") or {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, tuple[str, ...]] = {}
        for key, values in raw.items():
            if not isinstance(values, list):
                continue
            cleaned = tuple(str(item).strip().lower() for item in values if str(item).strip())
            if cleaned:
                result[str(key).strip().lower()] = cleaned
        return result

    def version_groups(self) -> dict[str, VersionGroup]:
        cfg = self._load_catalog_config()
        raw = cfg.get("versionGroups") or {}
        if not isinstance(raw, dict):
            return {}
        groups: dict[str, VersionGroup] = {}
        for group_id, data in raw.items():
            if not isinstance(data, dict):
                continue
            options_raw = data.get("options") or []
            options: list[VersionOption] = []
            if isinstance(options_raw, list):
                for item in options_raw:
                    if not isinstance(item, dict):
                        continue
                    app_id = str(item.get("appId") or "").strip()
                    label = str(item.get("label") or "").strip()
                    if not app_id or not label:
                        continue
                    options.append(
                        VersionOption(
                            app_id=app_id,
                            label=label,
                            hint=str(item.get("hint") or "").strip(),
                        )
                    )
            if not options:
                continue
            groups[str(group_id)] = VersionGroup(
                id=str(group_id),
                title=str(data.get("title") or group_id),
                icon_app_id=str(data.get("iconAppId") or options[0].app_id),
                options=tuple(options),
            )
        return groups

    def get_version_group(self, group_id: str) -> VersionGroup | None:
        return self.version_groups().get(group_id)

    def get_app(self, app_id: str) -> AppEntry | None:
        for app in self.list_apps():
            if app.id == app_id:
                return app
        return None

    def list_general_apps(self) -> list[AppEntry]:
        return [app for app in self.list_apps() if not app.is_banking]

    def list_banking_apps(self) -> list[AppEntry]:
        return ConfigManager.sort_banking_apps(
            [app for app in self.list_apps() if app.is_banking]
        )

    def list_bank_groups(self) -> list[BankGroup]:
        counts = self.banking_app_counts()
        return [group for group in self._bank_groups_from_config() if counts.get(group.id, 0) > 0]

    def get_bank_group(self, bank_group_id: str) -> BankGroup | None:
        for group in self._bank_groups_from_config():
            if group.id == bank_group_id:
                return group
        return None

    def banking_app_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for app in self.list_apps():
            if app.is_banking and app.bankGroup:
                counts[app.bankGroup] = counts.get(app.bankGroup, 0) + 1
        return counts

    def list_banking_apps_for_group(self, bank_group: str) -> list[AppEntry]:
        apps = [app for app in self.list_apps() if app.is_banking and app.bankGroup == bank_group]
        return ConfigManager.sort_banking_apps(apps)

    def list_standalone_catalog_apps(self) -> list[AppEntry]:
        """Banking apps that also appear as their own root-catalog cards."""
        return [
            app
            for app in self.list_apps()
            if app.is_banking and app.catalogStandalone and not app.versionGroup
        ]

    def list_apps(self) -> list[AppEntry]:
        key = self._apps_source_key()
        if self._apps_cache is not None and self._apps_cache_key == key:
            return list(self._apps_cache)

        default_apps = {app.id: app for app in self._read_apps_file(self.default_apps_path)}
        banking_apps = {app.id: app for app in self._read_banking_apps()}
        user_apps = self._read_apps_file(self.user_apps_path)
        merged: dict[str, AppEntry] = dict(default_apps)
        merged.update(banking_apps)
        for app in user_apps:
            base = merged.get(app.id)
            if base:
                merged[app.id] = AppEntry(
                    id=app.id,
                    title=app.title or base.title,
                    bundleId=app.bundleId if app.bundleId else base.bundleId,
                    appId=app.appId or base.appId,
                    description=app.description or base.description,
                    iconUrl=app.iconUrl or base.iconUrl,
                    iconFile=app.iconFile or base.iconFile,
                    category=app.category or base.category,
                    maskTitle=app.maskTitle or base.maskTitle,
                    bankGroup=app.bankGroup or base.bankGroup,
                    released=app.released or base.released,
                    removed=app.removed or base.removed,
                    addedAt=app.addedAt or base.addedAt,
                    versionGroup=app.versionGroup or base.versionGroup,
                    catalogStandalone=app.catalogStandalone or base.catalogStandalone,
                    aliases=list(app.aliases or base.aliases),
                )
            else:
                merged[app.id] = app
        apps = list(merged.values())
        self._apps_cache = apps
        self._apps_cache_key = key
        return list(apps)

    def catalog_app_count(self) -> int:
        """Count of catalog targets for the header (matches «Все» listing style)."""
        return len(self.list_root_all_entries())

    @staticmethod
    def _parse_iso_date(value: str) -> date | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    def is_new_app(self, app: AppEntry, *, today: date | None = None) -> bool:
        stamp = self._parse_iso_date(app.freshness_date())
        if stamp is None:
            return False
        ref = today or date.today()
        return stamp >= ref - timedelta(days=self.new_app_days())

    def list_new_apps(self) -> list[AppEntry]:
        """New installable entries for the «Новые» section (dedupe version groups)."""
        groups = self.version_groups()
        seen_groups: set[str] = set()
        result: list[AppEntry] = []
        sort_dates: dict[str, str] = {}
        for app in self.list_apps():
            if not self.is_new_app(app):
                continue
            if app.versionGroup:
                if app.versionGroup in seen_groups:
                    continue
                seen_groups.add(app.versionGroup)
                group = groups.get(app.versionGroup)
                # Prefer the newest member inside the group as the card representative.
                members = [a for a in self.list_apps() if a.versionGroup == app.versionGroup]
                members.sort(key=lambda item: item.freshness_date(), reverse=True)
                representative = members[0] if members else app
                if group:
                    icon_app = self.get_app(group.icon_app_id)
                    # Keep classic icon when available, but track newest date for sorting.
                    result.append(icon_app or representative)
                    sort_dates[(icon_app or representative).id] = representative.freshness_date()
                else:
                    result.append(representative)
                    sort_dates[representative.id] = representative.freshness_date()
                continue
            if app.is_banking and not app.catalogStandalone:
                continue
            result.append(app)
            sort_dates[app.id] = app.freshness_date()
        result.sort(key=lambda item: sort_dates.get(item.id, item.freshness_date()), reverse=True)
        return result

    @staticmethod
    def normalize_search_text(value: str) -> str:
        """Casefold + ё→е; collapse punctuation/spaces for stable matching."""
        text = (value or "").strip().casefold().replace("ё", "е")
        parts: list[str] = []
        prev_space = False
        for ch in text:
            if ch in "-_./\\|,;:":
                ch = " "
            if ch.isspace():
                if prev_space:
                    continue
                prev_space = True
                parts.append(" ")
                continue
            prev_space = False
            parts.append(ch)
        return "".join(parts).strip()

    def _expand_search_terms(self, query: str) -> set[str]:
        q = self.normalize_search_text(query)
        if not q:
            return set()
        terms = {q}
        aliases = self.search_alias_map()
        # Exact alias key.
        if q in aliases:
            terms.update(aliases[q])
        # Prefix expansion only (never bare substring) — avoids «аль»→half the catalog
        # via accidental hits inside unrelated alias values.
        if len(q) >= 2:
            for key, values in aliases.items():
                key_n = self.normalize_search_text(key)
                if key_n.startswith(q) or q.startswith(key_n):
                    terms.add(key_n)
                    terms.update(values)
                    continue
                for value in values:
                    value_n = self.normalize_search_text(value)
                    if value_n == q or value_n.startswith(q) or q.startswith(value_n):
                        terms.add(key_n)
                        terms.update(values)
                        break
        return {self.normalize_search_text(term) for term in terms if term}

    def app_matches_query(self, app: AppEntry, query: str) -> bool:
        q = self.normalize_search_text(query)
        terms = self._expand_search_terms(q)
        if not terms:
            return True
        # Primary fields only — descriptions like «официальное» contain «аль» as noise.
        primary = self.normalize_search_text(
            " ".join(
                part
                for part in (
                    app.title,
                    app.maskTitle,
                    app.bundleId,
                    str(app.appId),
                    app.bankGroup,
                    " ".join(app.aliases),
                )
                if part
            )
        )
        for term in terms:
            if not term:
                continue
            if len(term) == 1:
                # Single letter: title/alias token prefix only.
                if any(
                    token.startswith(term)
                    for token in primary.split()
                ):
                    return True
                continue
            if term in primary:
                return True
        # Long queries may also match description (min 4 chars per term).
        if len(q) >= 4:
            secondary = self.normalize_search_text(app.description or "")
            for term in terms:
                if len(term) >= 4 and term in secondary:
                    return True
        return False

    def search_apps(self, query: str) -> list[AppEntry]:
        q = self.normalize_search_text(query)
        if not q:
            return []
        return [app for app in self.list_apps() if self.app_matches_query(app, q)]

    def list_root_all_entries(self) -> list[AppEntry | VersionGroup]:
        """All installable catalog targets for «Все приложения».

        Includes general apps, version groups (collapsed), and every banking app/mask.
        Does not include the Banks folder sentinel — banks are a separate root section.
        """
        groups = self.version_groups()
        seen_groups: set[str] = set()
        entries: list[AppEntry | VersionGroup] = []

        for app in self.list_apps():
            if app.versionGroup:
                if app.versionGroup in seen_groups:
                    continue
                seen_groups.add(app.versionGroup)
                group = groups.get(app.versionGroup)
                if group:
                    entries.append(group)
                else:
                    entries.append(app)
            else:
                entries.append(app)

        return entries

    @staticmethod
    def sort_key_ru_first(title: str) -> tuple[int, str]:
        """Sort Russian А–Я first, then Latin A–Z, then other."""
        text = (title or "").strip()
        if not text:
            return (3, "")
        ch = text[0].upper()
        if ch == "Ё":
            ch = "Е"
        folded = text.casefold()
        if "А" <= ch <= "Я":
            return (0, folded)
        if "A" <= ch <= "Z":
            return (1, folded)
        if ch.isdigit():
            return (2, folded)
        return (3, folded)

    @staticmethod
    def sort_title_ru(title: str) -> tuple[int, str]:
        return ConfigManager.sort_key_ru_first(title)

    @staticmethod
    def first_letter_ru(title: str) -> str:
        text = (title or "").strip()
        if not text:
            return "#"
        ch = text[0].upper()
        if "А" <= ch <= "Я" or ch == "Ё":
            return "Е" if ch == "Ё" else ch
        if "A" <= ch <= "Z":
            return ch
        if ch.isdigit():
            return "0-9"
        return "#"

    @staticmethod
    def sort_banking_apps(apps: list[AppEntry]) -> list[AppEntry]:
        banking = list(apps)
        # Newest first by release date, then title.
        banking.sort(key=lambda item: ((item.released or ""), item.title.lower()), reverse=True)
        # Stable secondary: among same released date, title A→Z.
        banking.sort(key=lambda item: item.title.lower())
        banking.sort(key=lambda item: item.released or "", reverse=True)
        return banking

    @staticmethod
    def sort_apps(apps: list[AppEntry]) -> list[AppEntry]:
        general = sorted(
            [app for app in apps if not app.is_banking],
            key=lambda item: ConfigManager.sort_key_ru_first(item.display_title()),
        )
        return general + ConfigManager.sort_banking_apps(
            [app for app in apps if app.is_banking]
        )

    def find_cached_ipa(self, app_id: int, *, expected_bundle_id: str | None = None) -> Path | None:
        downloads_dir = self.account_downloads_dir()
        if downloads_dir is None:
            return None
        candidates = sorted(
            downloads_dir.glob(f"{app_id}_*.ipa"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if is_valid_ipa(path, expected_bundle_id=expected_bundle_id):
                return path
            try:
                path.unlink()
            except OSError:
                pass
        return None

    def remove_cached_ipa(self, app_id: int) -> int:
        downloads_dir = self.account_downloads_dir()
        if downloads_dir is None:
            return 0
        return cleanup_download_artifacts(downloads_dir, app_id)
