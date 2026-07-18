from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_paths import data_dir, resource_dir
from security_utils import is_trusted_update_url
from version import APP_VERSION

_CHECK_TIMEOUT_SEC = 20
_DOWNLOAD_TIMEOUT_SEC = 120
_HASH_CHUNK = 1024 * 1024
_MAX_FETCH_ATTEMPTS = 3
_RETRY_DELAY_SEC = 0.8

# Fallback mirrors when raw.githubusercontent.com is blocked (common in RU).
_BUILTIN_MANIFEST_FALLBACKS = (
    "https://cdn.jsdelivr.net/gh/morgunartem28-netizen/gromov-restore-plus@main/release/version.json",
    "https://github.com/morgunartem28-netizen/gromov-restore-plus/raw/main/release/version.json",
)


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


def _ssl_context() -> ssl.SSLContext:
    """Build a TLS context that works both in source and frozen builds."""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _request_headers() -> dict[str, str]:
    return {
        "User-Agent": f"GROMOV-RestorePlus/{APP_VERSION} (+https://github.com/morgunartem28-netizen/gromov-restore-plus)",
        "Accept": "application/json,application/octet-stream,*/*",
        "Cache-Control": "no-cache",
    }


def _reason_text(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if reason is None:
        return str(exc).strip()
    if isinstance(reason, BaseException):
        return f"{type(reason).__name__}: {reason}".strip()
    return str(reason).strip()


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    text = _reason_text(exc).lower()
    return "timed out" in text or "timeout" in text


def _is_ssl_failure(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError):
        return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "ssl",
            "certificate",
            "certifi",
            "handshake",
            "wrong version number",
        )
    )


def _is_dns_failure(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror):
        return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "getaddrinfo",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
        )
    )


def _is_offline_failure(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ConnectionError):
        errno = getattr(reason, "errno", None)
        # Windows: 10051 network unreachable, 10050 network down, 10065 host unreachable
        if errno in {10050, 10051, 10065, 51, 65, 101, 113}:
            return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "network is unreachable",
            "network is down",
            "no route to host",
            "connectex",
            "failed to establish a new connection",
            "connection refused",
            "actively refused",
            "errno 10051",
            "errno 10050",
            "errno 10061",
        )
    )


def _format_transport_error(exc: BaseException, *, action: str) -> str:
    """Map low-level transport failures to accurate Russian UX copy."""
    if _is_timeout(exc):
        return (
            f"{action} не завершилась вовремя.\n"
            "Сервер обновлений отвечает слишком медленно.\n"
            "Повторите попытку через минуту."
        )
    if _is_ssl_failure(exc):
        return (
            f"{action} не удалась из-за ошибки защищённого соединения (TLS/SSL).\n"
            "Проверьте дату/время на ПК, антивирус HTTPS-сканирование "
            "или корпоративный прокси.\n"
            "Это не обязательно означает отсутствие интернета."
        )
    if _is_dns_failure(exc):
        return (
            f"{action} не удалась: не удалось найти сервер обновлений (DNS).\n"
            "Интернет может работать, но GitHub/CDN недоступны.\n"
            "Попробуйте другую сеть, VPN или DNS (например 1.1.1.1)."
        )
    if _is_offline_failure(exc):
        return (
            "Нет подключения к интернету.\n"
            "Проверьте Wi-Fi/кабель, отключите режим «в самолёте» "
            "и повторите проверку обновлений."
        )

    detail = _reason_text(exc)
    if detail and len(detail) < 160:
        return (
            f"{action} не удалась.\n"
            f"Причина: {detail}\n"
            "Интернет может быть доступен, но сервер обновлений недоступен "
            "(блокировка, прокси, фаервол)."
        )
    return (
        f"{action} не удалась.\n"
        "Не удалось связаться с сервером обновлений.\n"
        "Проверьте доступ к GitHub или смените сеть/VPN."
    )


def _read_manifest_urls() -> list[str]:
    # Prefer bundled config; allow user override only if still a trusted HTTPS URL.
    candidates: list[Path] = [
        resource_dir() / "config" / "update.json",
        data_dir() / "update.json",
    ]
    configured: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        primary = str(payload.get("manifest_url") or "").strip()
        if primary and is_trusted_update_url(primary):
            configured.append(primary)
        extras = payload.get("manifest_urls") or []
        if isinstance(extras, list):
            for item in extras:
                url = str(item or "").strip()
                if url and is_trusted_update_url(url):
                    configured.append(url)
        if configured:
            break

    urls: list[str] = []
    for url in [*configured, *_BUILTIN_MANIFEST_FALLBACKS]:
        if url and is_trusted_update_url(url) and url not in urls:
            urls.append(url)
    return urls


def _urlopen(request: urllib.request.Request, *, timeout: float):
    context = _ssl_context()
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def _fetch_bytes(url: str, *, timeout: float) -> bytes:
    if not is_trusted_update_url(url):
        raise UpdateCheckError(
            "Небезопасный адрес обновлений.\n"
            "Разрешены только HTTPS-ссылки GitHub и доверенных CDN."
        )
    request = urllib.request.Request(url, headers=_request_headers())
    last_error: BaseException | None = None
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        try:
            with _urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            # Do not retry client/permanent errors (except a couple of transient ones).
            if exc.code in {408, 425, 429, 500, 502, 503, 504} and attempt < _MAX_FETCH_ATTEMPTS:
                last_error = exc
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(f"Сервер обновлений ответил с ошибкой ({exc.code}).") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS and (_is_timeout(exc) or _is_offline_failure(exc)):
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except (TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except ssl.SSLError as exc:
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except OSError as exc:
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc

    if last_error is not None:
        raise UpdateCheckError(_format_transport_error(last_error, action="Проверка обновлений")) from last_error
    raise UpdateCheckError("Не удалось связаться с сервером обновлений.")


def _fetch_manifest(urls: list[str]) -> dict:
    errors: list[str] = []
    for url in urls:
        try:
            raw = _fetch_bytes(url, timeout=_CHECK_TIMEOUT_SEC).decode("utf-8-sig")
        except UpdateCheckError as exc:
            errors.append(str(exc).split("\n", 1)[0])
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            errors.append("ответ не JSON")
            continue
        if not isinstance(payload, dict):
            errors.append("ответ не объект JSON")
            continue
        return payload

    if not errors:
        raise UpdateCheckError(
            "Проверка обновлений не настроена.\n"
            f"Текущая версия: {APP_VERSION}."
        )

    unique = []
    for item in errors:
        if item not in unique:
            unique.append(item)
    summary = "; ".join(unique[:3])
    raise UpdateCheckError(
        "Не удалось получить манифест обновлений ни с одного зеркала.\n"
        f"Детали: {summary}\n\n"
        "Если интернет работает, GitHub может быть недоступен "
        "(блокировка провайдера/фаервол).\n"
        "Попробуйте другую сеть или VPN и нажмите «Обновить» снова."
    )


def check_for_updates(*, current_version: str = APP_VERSION) -> UpdateCheckResult:
    manifest_urls = _read_manifest_urls()
    if not manifest_urls:
        raise UpdateCheckError(
            f"Проверка обновлений не настроена.\nТекущая версия: {current_version}."
        )

    payload = _fetch_manifest(manifest_urls)
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

    request = urllib.request.Request(setup_url, headers=_request_headers())
    digest = hashlib.sha256()
    received = 0
    try:
        with _urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SEC) as response:
            total = int(response.headers.get("Content-Length") or 0)
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
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise UpdateCheckError(
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except ssl.SSLError as exc:
        raise UpdateCheckError(
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except OSError as exc:
        raise UpdateCheckError(f"Не удалось сохранить установщик:\n{exc}") from exc

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
