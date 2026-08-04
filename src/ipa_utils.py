from __future__ import annotations

import plistlib
import struct
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

# IPA cache lives under data_dir()/downloads (AppData), not next to the .exe —
# so a custom install folder cannot break cleanup or leave orphan caches.
IPA_CACHE_MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class FairPlayMarkers:
    """Lightweight FairPlay / Customer-IPA signals (no decrypt)."""

    apple_id: str | None
    has_sinf: bool
    sinf_count: int
    cryptid: int | None
    bundle_id: str | None

    @property
    def looks_customer_ipa(self) -> bool:
        return bool(self.has_sinf and self.cryptid == 1)

# Старые bundle ID в каталоге, которые всё ещё относятся к тому же приложению.
_BUNDLE_EQUIVALENTS: tuple[frozenset[str], ...] = (
    frozenset({"ru.avito.Avito", "ru.avito.app"}),
    frozenset({"ru.mail.mailapp", "ru.mail.mail"}),
    # В IPA VK Видео — com.vk.vkvideo.prod (не com.vk.vkvideo как на Android).
    frozenset({"com.vk.vkvideo", "com.vk.vkvideo.prod"}),
    # VK Музыка: старый выдуманный catalog-id ↔ реальный iOS bundle.
    frozenset({"com.vk.vkclient.music", "com.music.vk"}),
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


def _macho_cryptids(data: bytes) -> list[int]:
    """Return cryptid values from LC_ENCRYPTION_INFO(_64); empty if not Mach-O."""
    if len(data) < 8:
        return []
    mh64, mh64_cigam = 0xFEEDFACF, 0xCFFAEDFE
    mh32, mh32_cigam = 0xFEEDFACE, 0xCEFAEDFE
    lc_enc, lc_enc64 = 0x21, 0x2C
    magic_be = struct.unpack(">I", data[:4])[0]
    offsets: list[int] = []
    if magic_be in (0xCAFEBABE, 0xBEBAFECA):
        le = magic_be == 0xBEBAFECA
        nfat = struct.unpack("<I" if le else ">I", data[4:8])[0]
        for i in range(min(nfat, 8)):
            off = 8 + i * 20
            chunk = data[off : off + 20]
            if len(chunk) < 20:
                break
            _, _, offset, _, _ = struct.unpack("<IIIII" if le else ">IIIII", chunk)
            offsets.append(offset)
    else:
        offsets = [0]

    found: list[int] = []
    for base in offsets:
        if base + 28 > len(data):
            continue
        magic_l = struct.unpack_from("<I", data, base)[0]
        if magic_l in (mh64, mh32):
            endian = "<"
        elif magic_l in (mh64_cigam, mh32_cigam):
            endian = ">"
            magic_l = struct.unpack_from(">I", data, base)[0]
        else:
            continue
        is64 = magic_l in (mh64, mh64_cigam)
        hdr = 32 if is64 else 28
        ncmds = struct.unpack_from(endian + "I", data, base + 16)[0]
        pos = base + hdr
        for _ in range(min(ncmds, 256)):
            if pos + 8 > len(data):
                break
            cmd, cmdsize = struct.unpack_from(endian + "II", data, pos)
            if cmd in (lc_enc, lc_enc64) and cmdsize >= 20:
                cryptid = struct.unpack_from(endian + "I", data, pos + 16)[0]
                found.append(int(cryptid))
            if cmdsize < 8:
                break
            pos += cmdsize
    return found


def inspect_fairplay_markers(path: Path) -> FairPlayMarkers | None:
    """Read apple-id / .sinf / cryptid from a Customer IPA. Never raises."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            sinfs = [n for n in names if n.endswith(".sinf")]
            apple_id: str | None = None
            meta_name = next(
                (n for n in names if n.rstrip("/").endswith("iTunesMetadata.plist")),
                None,
            )
            if meta_name:
                meta = plistlib.loads(archive.read(meta_name))
                raw = meta.get("apple-id") or meta.get("appleId") or meta.get("userName")
                if isinstance(raw, str) and raw.strip():
                    apple_id = raw.strip()

            info_path = _main_app_info_plist_path(names)
            bundle_id: str | None = None
            cryptid: int | None = None
            if info_path:
                info = plistlib.loads(archive.read(info_path))
                bid = info.get("CFBundleIdentifier")
                bundle_id = str(bid) if bid else None
                exe = info.get("CFBundleExecutable")
                if exe:
                    exe_path = f"{info_path.rsplit('/', 1)[0]}/{exe}"
                    if exe_path in names:
                        ids = _macho_cryptids(archive.read(exe_path))
                        if ids:
                            cryptid = ids[0]
            return FairPlayMarkers(
                apple_id=apple_id,
                has_sinf=bool(sinfs),
                sinf_count=len(sinfs),
                cryptid=cryptid,
                bundle_id=bundle_id,
            )
    except (zipfile.BadZipFile, OSError, KeyError, plistlib.InvalidFileException, ValueError, struct.error):
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
    """Delete *.ipa / *.ipa.tmp older than max_age_days. max_age_days=0 deletes all. Never raises."""
    removed = 0
    try:
        if not downloads_root.is_dir():
            return 0
        if max_age_days <= 0:
            cutoff = time.time() + 1  # delete everything
        else:
            cutoff = time.time() - max_age_days * 86400
        for path in downloads_root.rglob("*"):
            try:
                if not path.is_file():
                    continue
                name = path.name.lower()
                if not (name.endswith(".ipa") or name.endswith(".ipa.tmp")):
                    continue
                if max_age_days > 0 and path.stat().st_mtime >= cutoff:
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
