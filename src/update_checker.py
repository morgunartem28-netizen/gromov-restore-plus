from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app_paths import data_dir, resource_dir
from version import APP_VERSION

_CHECK_TIMEOUT_SEC = 15


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    setup_url: str
    notes: str

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


def _read_manifest_url() -> str:
    for path in (data_dir() / "update.json", resource_dir() / "config" / "update.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        url = str(payload.get("manifest_url") or "").strip()
        if url:
            return url
    return ""


def _fetch_manifest(url: str) -> dict:
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

    if not latest_version:
        raise UpdateCheckError("В манифесте обновлений не указана версия.")
    if not setup_url and parse_version(latest_version) > parse_version(current_version):
        raise UpdateCheckError("В манифесте обновлений не указана ссылка на установщик.")

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        setup_url=setup_url,
        notes=notes,
    )
