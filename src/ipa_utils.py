from __future__ import annotations

import plistlib
import zipfile
from pathlib import Path

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
                if bundle_id and not bundle_id_matches(expected_bundle_id, bundle_id):
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
