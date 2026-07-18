from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_paths import data_dir, resource_dir
from security_utils import is_trusted_update_url
from version import APP_VERSION

_CHECK_TIMEOUT_SEC = 15
_DOWNLOAD_TIMEOUT_SEC = 120
_HASH_CHUNK = 1024 * 1024


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    setup_url: str
    notes: str
    sha256: str = ""

    @property
    def is_up_to_date(self) -> bool:
        return parse_version(self.latest_version) <= parse_version(self.current_version)

    @property
    def has_update(self) -> bool:
        return not self.is_up_to_date


def parse_version(value: str) -> tuple[int, ...]:
    text = value.strip().lstrip("vV")
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    if not match:
        return (0,)
    parts: list[int] = []
    for piece in match.group(1).split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


def normalize_sha256(value: str) -> str:
    text = (value or "").strip().lower().replace(" ", "")
    if text.startswith("sha256:"):
        text = text[7:]
    return text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest_url() -> str:
    # Prefer bundled config; allow user override only if still a trusted HTTPS URL.
    candidates: list[Path] = [
        resource_dir() / "config" / "update.json",
        data_dir() / "update.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        url = str(payload.get("manifest_url") or "").strip()
        if url and is_trusted_update_url(url):
            return url
    return ""


def _fetch_manifest(url: str) -> dict:
    if not is_trusted_update_url(url):
        raise UpdateCheckError(
            "Небезопасный адрес манифеста обновлений.\n"
            "Разрешены только HTTPS-ссылки GitHub."
        )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"GROMOV-RestorePlus/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_CHECK_TIMEOUT_SEC) as response:
            raw = response.read().decode("utf-8-sig")
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(f"Сервер обновлений ответил с ошибкой ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(
            "Не удалось связаться с сервером обновлений.\nПроверьте подключение к интернету."
        ) from exc
    except TimeoutError as exc:
        raise UpdateCheckError("Сервер обновлений не ответил вовремя.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateCheckError(
            "Сервер вернул некорректный ответ (не JSON).\n"
            "Проверьте manifest_url в config/update.json."
        ) from exc
    if not isinstance(payload, dict):
        raise UpdateCheckError("Сервер вернул некорректный ответ.")
    return payload


def check_for_updates(*, current_version: str = APP_VERSION) -> UpdateCheckResult:
    manifest_url = _read_manifest_url()
    if not manifest_url:
        raise UpdateCheckError(
            f"Проверка обновлений не настроена.\nТекущая версия: {current_version}."
        )

    payload = _fetch_manifest(manifest_url)
    latest_version = str(payload.get("version") or "").strip()
    setup_url = str(payload.get("setup_url") or payload.get("download_url") or "").strip()
    notes = str(payload.get("notes") or payload.get("changelog") or "").strip()
    sha256 = normalize_sha256(str(payload.get("sha256") or payload.get("setup_sha256") or ""))

    if not latest_version:
        raise UpdateCheckError("В манифесте обновлений не указана версия.")
    if setup_url and not is_trusted_update_url(setup_url):
        raise UpdateCheckError(
            "В манифесте указана небезопасная ссылка на установщик.\n"
            "Ожидается HTTPS-ссылка GitHub Releases."
        )
    if not setup_url and parse_version(latest_version) > parse_version(current_version):
        raise UpdateCheckError("В манифесте обновлений не указана ссылка на установщик.")

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        setup_url=setup_url,
        notes=notes,
        sha256=sha256,
    )


def download_verified_installer(
    *,
    setup_url: str,
    expected_sha256: str,
    version: str,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """Download Setup.exe into AppData and verify SHA-256 before returning the path.

    Always uses data_dir()/updates — independent of where the app is installed.
    """
    expected = normalize_sha256(expected_sha256)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise UpdateCheckError(
            "В манифесте обновлений нет корректного SHA256 установщика.\n"
            "Обновление прервано для вашей безопасности."
        )
    if not is_trusted_update_url(setup_url):
        raise UpdateCheckError("Небезопасная ссылка на установщик.")

    updates_dir = data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    safe_version = re.sub(r"[^\d.]+", "_", version.strip()) or "latest"
    dest = updates_dir / f"GROMOV-RestorePlus-Setup-{safe_version}.exe"
    temp = dest.with_suffix(".exe.part")

    if dest.is_file():
        try:
            if file_sha256(dest) == expected:
                return dest
            dest.unlink(missing_ok=True)
        except OSError:
            pass

    request = urllib.request.Request(
        setup_url,
        headers={"User-Agent": f"GROMOV-RestorePlus/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SEC) as response:
            total = int(response.headers.get("Content-Length") or 0)
            digest = hashlib.sha256()
            received = 0
            with temp.open("wb") as handle:
                while True:
                    chunk = response.read(_HASH_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if on_progress and total > 0:
                        on_progress(min(0.99, received / total))
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(f"Не удалось скачать установщик ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(
            "Не удалось скачать установщик.\nПроверьте подключение к интернету."
        ) from exc
    except OSError as exc:
        raise UpdateCheckError(f"Не удалось сохранить установщик:\n{exc}") from exc
    except TimeoutError as exc:
        raise UpdateCheckError("Скачивание установщика прервалось по таймауту.") from exc

    actual = digest.hexdigest()
    if actual != expected:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise UpdateCheckError(
            "Проверка SHA256 не пройдена — файл повреждён или подменён.\n"
            "Обновление отменено."
        )

    try:
        temp.replace(dest)
    except OSError as exc:
        raise UpdateCheckError(f"Не удалось сохранить установщик:\n{exc}") from exc

    if on_progress:
        on_progress(1.0)
    return dest
