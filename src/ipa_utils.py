from __future__ import annotations

import plistlib
import time
import zipfile
from pathlib import Path

# IPA cache lives under data_dir()/downloads (AppData), not next to the .exe —
# so a custom install folder cannot break cleanup or leave orphan caches.
IPA_CACHE_MAX_AGE_DAYS = 7

# Старые bundle ID в каталоге, которые всё ещё относятся к тому же приложению.
_BUNDLE_EQUIVALENTS: tuple[frozenset[str], ...] = (
    frozenset({"ru.avito.Avito", "ru.avito.app"}),
    frozenset({"ru.mail.mailapp", "ru.mail.mail"}),
)


def bundle_id_matches(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return True
    if expected == actual:
        return True
    for group in _BUNDLE_EQUIVALENTS:
        if expected in group and actual in group:
            return True
    return False


def _main_app_info_plist_path(names: list[str]) -> str | None:
    for name in names:
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == "Payload" and parts[1].endswith(".app") and parts[2] == "Info.plist":
            return name
    return None


def read_ipa_bundle_id(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            info_path = _main_app_info_plist_path(archive.namelist())
            if not info_path:
                return None
            info = plistlib.loads(archive.read(info_path))
            bundle_id = info.get("CFBundleIdentifier")
            return str(bundle_id) if bundle_id else None
    except (zipfile.BadZipFile, OSError, KeyError, plistlib.InvalidFileException, ValueError):
        return None


def is_valid_ipa(path: Path, *, expected_bundle_id: str | None = None) -> bool:
    if not path.is_file():
        return False

    size = path.stat().st_size
    if size < 64 * 1024:
        return False

    with path.open("rb") as handle:
        if handle.read(2) != b"PK":
            return False

    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if not names:
                return False
            if not any(name.startswith("Payload/") and ".app/" in name for name in names):
                return False
            if archive.testzip() is not None:
                return False
            if expected_bundle_id:
                bundle_id = read_ipa_bundle_id(path)
                # Fail closed: if we cannot read CFBundleIdentifier, reject the IPA.
                if not bundle_id or not bundle_id_matches(expected_bundle_id, bundle_id):
                    return False
    except (zipfile.BadZipFile, OSError, KeyError):
        return False

    return True


def cleanup_download_artifacts(downloads_dir: Path, app_id: int) -> int:
    """Удаляет битые IPA и .tmp — ipatool докачивает .tmp и ломается на повреждённом файле."""
    removed = 0
    app_id_text = str(app_id)

    patterns = (
        f"{app_id_text}_*.ipa",
        f"{app_id_text}_*.ipa.tmp",
        f"*_{app_id_text}_*.ipa",
        f"*_{app_id_text}_*.ipa.tmp",
    )
    seen: set[Path] = set()
    for pattern in patterns:
        for path in downloads_dir.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    for path in downloads_dir.glob("*.ipa.tmp"):
        if app_id_text in path.name:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    return removed


def purge_stale_ipa_cache(
    downloads_root: Path,
    *,
    max_age_days: int = IPA_CACHE_MAX_AGE_DAYS,
) -> int:
    """Delete *.ipa / *.ipa.tmp older than max_age_days. Never raises."""
    removed = 0
    try:
        if not downloads_root.is_dir():
            return 0
        cutoff = time.time() - max(1, max_age_days) * 86400
        for path in downloads_root.rglob("*"):
            try:
                if not path.is_file():
                    continue
                name = path.name.lower()
                if not (name.endswith(".ipa") or name.endswith(".ipa.tmp")):
                    continue
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        # Remove empty account folders left behind.
        for path in sorted(downloads_root.rglob("*"), reverse=True):
            try:
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except OSError:
                continue
    except OSError:
        return removed
    return removed


def purge_stale_staging(
    staging_dir: Path,
    *,
    max_age_days: int = 1,
) -> int:
    """Best-effort cleanup of leftover staged IPA copies in %TEMP%."""
    removed = 0
    try:
        if not staging_dir.is_dir():
            return 0
        cutoff = time.time() - max(1, max_age_days) * 86400
        for path in staging_dir.glob("*.ipa"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    return removed
