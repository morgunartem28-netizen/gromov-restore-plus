from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from app_paths import data_dir, install_dir, resource_dir
from ipa_utils import bundle_id_matches, cleanup_download_artifacts, is_valid_ipa


BANKING_CATEGORY = "Банковские приложения"
BANKS_FOLDER_TITLE = "Банки"


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
)


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

    @classmethod
    def from_dict(cls, data: dict) -> "AppEntry":
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
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_banking(self) -> bool:
        return self.category == BANKING_CATEGORY

    def version_label(self) -> str:
        if self.maskTitle:
            return self.maskTitle
        return f"ID {self.appId}"


class ConfigManager:
    def __init__(self) -> None:
        self.base_dir = install_dir()
        self.default_apps_path = resource_dir() / "config" / "apps.json"
        self.banking_apps_path = resource_dir() / "config" / "banking_apps.json"
        self.user_apps_path = data_dir() / "user_apps.json"
        self.cache_dir = data_dir()
        self.downloads_root = self.cache_dir / "downloads"
        self._apple_account_email: str | None = None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_root.mkdir(parents=True, exist_ok=True)
        self._ensure_user_config()
        self._migrate_known_app_ids()

    @property
    def apple_account_email(self) -> str | None:
        return self._apple_account_email

    def set_apple_account(self, email: str | None) -> None:
        normalized = (email or "").strip().lower()
        self._apple_account_email = normalized or None

    @staticmethod
    def account_dir_name(email: str) -> str:
        normalized = email.strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in "@._-+'" else "_" for ch in normalized)
        return safe or "unknown"

    def account_downloads_dir(self) -> Path | None:
        if not self._apple_account_email:
            return None
        path = self.downloads_root / self.account_dir_name(self._apple_account_email)
        path.mkdir(parents=True, exist_ok=True)
        return path

    _APP_ID_FIXES: dict[str, int] = {
        # Раньше ошибочно стоял ID Облака Mail вместо Почты.
        "mailru": 511310430,
    }

    _BUNDLE_ID_FIXES: dict[str, str] = {
        # В IPA Авито реальный bundle ID — ru.avito.app.
        "avito": "ru.avito.app",
        # У Почты Mail.ru (511310430) в IPA bundle ID — ru.mail.mail.
        "mailru": "ru.mail.mail",
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
                )
                changed = True
        if changed:
            self._write_apps_file(self.user_apps_path, apps)

    def _ensure_user_config(self) -> None:
        if not self.user_apps_path.exists():
            shutil.copy(self.default_apps_path, self.user_apps_path)

    def _read_apps_file(self, path: Path) -> list[AppEntry]:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return [AppEntry.from_dict(item) for item in payload.get("apps", [])]

    def _write_apps_file(self, path: Path, apps: list[AppEntry]) -> None:
        payload = {"version": 1, "apps": [app.to_dict() for app in apps]}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _read_banking_apps(self) -> list[AppEntry]:
        if not self.banking_apps_path.exists():
            return []
        with self.banking_apps_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        category = str(payload.get("category") or BANKING_CATEGORY)
        apps: list[AppEntry] = []
        for item in payload.get("apps", []):
            entry = AppEntry.from_dict(item)
            if not entry.category:
                entry.category = category
            apps.append(entry)
        return apps

    def list_general_apps(self) -> list[AppEntry]:
        return [app for app in self.list_apps() if not app.is_banking]

    def list_banking_apps(self) -> list[AppEntry]:
        return ConfigManager.sort_banking_apps(
            [app for app in self.list_apps() if app.is_banking]
        )

    def list_bank_groups(self) -> list[BankGroup]:
        counts = self.banking_app_counts()
        return [group for group in BANK_GROUPS if counts.get(group.id, 0) > 0]

    def banking_app_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for app in self.list_banking_apps():
            if app.bankGroup:
                counts[app.bankGroup] = counts.get(app.bankGroup, 0) + 1
        return counts

    def get_bank_group(self, bank_group_id: str) -> BankGroup | None:
        for group in BANK_GROUPS:
            if group.id == bank_group_id:
                return group
        return None

    def list_banking_apps_for_group(self, bank_group: str) -> list[AppEntry]:
        apps = [app for app in self.list_banking_apps() if app.bankGroup == bank_group]
        return ConfigManager.sort_banking_apps(apps)

    def list_apps(self) -> list[AppEntry]:
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
                )
            else:
                merged[app.id] = app
        return list(merged.values())

    @staticmethod
    def sort_banking_apps(apps: list[AppEntry]) -> list[AppEntry]:
        banking = list(apps)
        banking.sort(key=lambda item: item.released or "", reverse=True)
        banking.sort(key=lambda item: item.title.lower())
        return banking

    @staticmethod
    def sort_apps(apps: list[AppEntry]) -> list[AppEntry]:
        general = sorted(
            [app for app in apps if not app.is_banking],
            key=lambda item: item.title.lower(),
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
