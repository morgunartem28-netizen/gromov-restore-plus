from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app_paths import data_dir, resource_dir
from security_utils import is_trusted_update_url
from version import APP_VERSION

_CHECK_TIMEOUT_SEC = 20
_DOWNLOAD_TIMEOUT_SEC = 120
_HASH_CHUNK = 1024 * 1024
_MAX_FETCH_ATTEMPTS = 3
_RETRY_DELAY_SEC = 0.8
_DEBUG_SNIPPET_MAX = 400
_DEBUG_LOCK = threading.Lock()

GITHUB_RELEASES_LATEST = (
    "https://github.com/morgunartem28-netizen/gromov-restore-plus/releases/latest"
)

# Fallback mirrors when raw.githubusercontent.com is blocked (common in RU)
# or returns a stale cached copy of version.json.
_BUILTIN_MANIFEST_FALLBACKS = (
    "https://cdn.jsdelivr.net/gh/morgunartem28-netizen/gromov-restore-plus@main/release/version.json",
    "https://github.com/morgunartem28-netizen/gromov-restore-plus/raw/main/release/version.json",
    # GitHub Contents API is typically fresher than raw.githubusercontent.com CDN.
    "https://api.github.com/repos/morgunartem28-netizen/gromov-restore-plus/contents/release/version.json?ref=main",
)


def resolve_browser_download_url(setup_url: str | None = None) -> str:
    """Prefer a trusted setup_url; otherwise open the GitHub Releases page."""
    url = (setup_url or "").strip()
    if url and is_trusted_update_url(url):
        return url
    return GITHUB_RELEASES_LATEST


def update_debug_log_path() -> Path:
    """Field diagnostics for update check/download (AppData when frozen)."""
    return data_dir() / "update_debug.log"


def _debug_snippet(data: bytes | str, *, limit: int = _DEBUG_SNIPPET_MAX) -> str:
    if isinstance(data, bytes):
        text = data.decode("utf-8", errors="replace")
    else:
        text = data
    text = text.replace("\r", "\\r").replace("\n", "\\n").strip()
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _debug_log(message: str) -> None:
    """Append one line (or multi-line block) to update_debug.log. Never raises."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = update_debug_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def _debug_exception(message: str, exc: BaseException) -> None:
    """Log exception type/message + stacktrace to file only (never for UI)."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    _debug_log(
        f"{message}\n"
        f"  exception_type={type(exc).__name__}\n"
        f"  exception_message={exc}\n"
        f"  stacktrace:\n{tb}"
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
    """TLS context: bundled/certifi CAs plus OS/Windows trust store.

    Certifi-only breaks when antivirus HTTPS inspection or an enterprise proxy
    MITMs TLS with a root that the browser trusts but Mozilla's CA bundle does
    not. Frozen builds still prefer the shipped cacert.pem under
    ``_internal/certifi/``; system CAs are always merged on top.
    """
    candidates: list[Path] = []
    # PyInstaller onedir ships cacert.pem under _internal/certifi/ (see *.spec datas).
    bundled = resource_dir() / "certifi" / "cacert.pem"
    if bundled.is_file():
        candidates.append(bundled)
    try:
        import certifi  # type: ignore

        certifi_path = Path(certifi.where())
        if certifi_path not in candidates:
            candidates.append(certifi_path)
    except Exception:
        pass

    ctx: ssl.SSLContext | None = None
    for cafile in candidates:
        try:
            if cafile.is_file():
                ctx = ssl.create_default_context(cafile=str(cafile))
                break
        except Exception:
            continue
    if ctx is None:
        ctx = ssl.create_default_context()

    # Merge Windows/system CA store (AV MITM roots, corp CAs) — not certifi-only.
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


def _request_headers(url: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": f"GROMOV-RestorePlus/{APP_VERSION} (+https://github.com/morgunartem28-netizen/gromov-restore-plus)",
        "Accept": "application/json,application/octet-stream,*/*",
        "Cache-Control": "no-cache",
    }
    # Return file bytes, not the base64 Contents API envelope.
    if url and "api.github.com/repos/" in url.lower() and "/contents/" in url.lower():
        headers["Accept"] = "application/vnd.github.raw"
    return headers


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
    # Windows: WSAHOST_NOT_FOUND / WSANO_DATA often surface as OSError 11001/11004.
    for candidate in (exc, reason):
        if candidate is None:
            continue
        winerror = getattr(candidate, "winerror", None)
        errno = getattr(candidate, "errno", None)
        if winerror in {11001, 11004} or errno in {11001, 11004}:
            return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "getaddrinfo",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "errno 11001",
            "winerror 11001",
        )
    )


def _is_offline_failure(exc: BaseException) -> bool:
    """True only for local network-down cases — not ISP/GitHub blocks."""
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ConnectionError):
        errno = getattr(reason, "errno", None)
        # Windows: 10051 network unreachable, 10050 network down, 10065 host unreachable.
        # Do NOT treat 10061 (connection refused) as offline — often firewall/DPI block.
        if errno in {10050, 10051, 10065, 51, 65, 101, 113}:
            return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "network is unreachable",
            "network is down",
            "no route to host",
            "errno 10051",
            "errno 10050",
            "errno 10065",
        )
    )


def _is_blocked_or_filtered(exc: BaseException) -> bool:
    """Connection reset/refused often means GitHub/CDN filtered, not a dead NIC."""
    reason = getattr(exc, "reason", None)
    for candidate in (exc, reason):
        if candidate is None:
            continue
        errno = getattr(candidate, "errno", None)
        winerror = getattr(candidate, "winerror", None)
        if errno in {10054, 10061, 104, 111} or winerror in {10054, 10061}:
            return True
        if isinstance(candidate, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)):
            return True
    text = _reason_text(exc).lower()
    return any(
        token in text
        for token in (
            "connection refused",
            "actively refused",
            "connection reset",
            "connection aborted",
            "failed to establish a new connection",
            "connectex",
            "errno 10061",
            "errno 10054",
            "winerror 10061",
            "winerror 10054",
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
    if _is_blocked_or_filtered(exc):
        return (
            f"{action} не удалась: соединение с сервером обновлений сброшено "
            "или отклонено.\n"
            "Часто это блокировка GitHub/CDN у провайдера, фаервол или антивирус — "
            "не обязательно отсутствие интернета.\n"
            "Откройте version.json в браузере, попробуйте VPN или другую сеть."
        )

    detail = _reason_text(exc)
    if detail:
        if len(detail) > 160:
            detail = detail[:157] + "..."
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


def _fetch_bytes(url: str, *, timeout: float, purpose: str = "fetch") -> bytes:
    if not is_trusted_update_url(url):
        raise UpdateCheckError(
            "Небезопасный адрес обновлений.\n"
            "Разрешены только HTTPS-ссылки GitHub и доверенных CDN."
        )
    request = urllib.request.Request(url, headers=_request_headers(url))
    last_error: BaseException | None = None
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        started = time.perf_counter()
        _debug_log(f"{purpose} attempt={attempt}/{_MAX_FETCH_ATTEMPTS} url={url}")
        try:
            with _urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", None) or response.getcode() or 0)
                body = response.read()
            latency_ms = int((time.perf_counter() - started) * 1000)
            _debug_log(
                f"{purpose} ok http={status} latency_ms={latency_ms} "
                f"bytes={len(body)} snippet={_debug_snippet(body)}"
            )
            return body
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            err_body = b""
            try:
                err_body = exc.read(512) or b""
            except Exception:
                pass
            _debug_log(
                f"{purpose} HTTPError http={exc.code} latency_ms={latency_ms} "
                f"url={url} snippet={_debug_snippet(err_body)}"
            )
            _debug_exception(f"{purpose} HTTPError detail", exc)
            # Do not retry client/permanent errors (except a couple of transient ones).
            if exc.code in {408, 425, 429, 500, 502, 503, 504} and attempt < _MAX_FETCH_ATTEMPTS:
                last_error = exc
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(f"Сервер обновлений ответил с ошибкой ({exc.code}).") from exc
        except urllib.error.URLError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _debug_log(f"{purpose} URLError latency_ms={latency_ms} url={url}")
            _debug_exception(f"{purpose} URLError detail", exc)
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS and (_is_timeout(exc) or _is_offline_failure(exc)):
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except (TimeoutError, socket.timeout) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _debug_log(f"{purpose} timeout latency_ms={latency_ms} url={url}")
            _debug_exception(f"{purpose} timeout detail", exc)
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except ssl.SSLError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _debug_log(f"{purpose} SSLError latency_ms={latency_ms} url={url}")
            _debug_exception(f"{purpose} SSLError detail", exc)
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc
        except OSError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _debug_log(f"{purpose} OSError latency_ms={latency_ms} url={url}")
            _debug_exception(f"{purpose} OSError detail", exc)
            last_error = exc
            if attempt < _MAX_FETCH_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SEC * attempt)
                continue
            raise UpdateCheckError(_format_transport_error(exc, action="Проверка обновлений")) from exc

    if last_error is not None:
        raise UpdateCheckError(_format_transport_error(last_error, action="Проверка обновлений")) from last_error
    raise UpdateCheckError("Не удалось связаться с сервером обновлений.")


def _manifest_host(url: str) -> str:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").strip().lower()
        return host or "unknown"
    except Exception:
        return "unknown"


def _with_cache_bust(url: str) -> str:
    """Append a short-lived query param so CDN/raw caches are less sticky."""
    parsed = urllib.parse.urlparse(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in {"t", "_", "cb"}
    ]
    query.append(("t", str(int(time.time()))))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _fetch_manifest(urls: list[str]) -> dict:
    """Fetch all mirrors and prefer the payload with the highest version.

    A stale HTTP 200 from raw.githubusercontent.com must not hide a newer
    manifest already visible on jsDelivr or another mirror.
    """
    errors: list[str] = []
    candidates: list[dict] = []
    _debug_log(f"manifest fetch start mirrors={len(urls)}")
    for url in urls:
        host = _manifest_host(url)
        fetch_url = _with_cache_bust(url)
        _debug_log(f"manifest try host={host} base_url={url}")
        try:
            raw = _fetch_bytes(
                fetch_url, timeout=_CHECK_TIMEOUT_SEC, purpose=f"manifest[{host}]"
            ).decode("utf-8-sig")
        except UpdateCheckError as exc:
            errors.append(f"{host}: {str(exc).split(chr(10), 1)[0]}")
            _debug_log(f"manifest fail host={host} ui_message={errors[-1]}")
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{host}: ответ не JSON")
            _debug_exception(f"manifest JSONDecodeError host={host}", exc)
            continue
        if not isinstance(payload, dict):
            errors.append(f"{host}: ответ не объект JSON")
            _debug_log(f"manifest fail host={host} reason=not_object")
            continue
        version = str(payload.get("version") or "").strip()
        if not version:
            errors.append(f"{host}: нет версии в манифесте")
            _debug_log(f"manifest fail host={host} reason=no_version")
            continue
        _debug_log(f"manifest candidate host={host} version={version}")
        candidates.append(payload)

    if candidates:
        best = max(
            candidates,
            key=lambda item: parse_version(str(item.get("version") or "")),
        )
        _debug_log(
            f"manifest selected version={best.get('version')} "
            f"from {len(candidates)} candidate(s)"
        )
        return best

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
        "Если интернет работает, GitHub/CDN может быть недоступен "
        "(блокировка провайдера/фаервол/антивирус).\n"
        "Откройте ссылку version.json в браузере, попробуйте VPN "
        "или другую сеть и нажмите «Обновить» снова."
    )


def check_for_updates(*, current_version: str = APP_VERSION) -> UpdateCheckResult:
    _debug_log(
        f"=== check_for_updates START app_version={current_version} "
        f"log={update_debug_log_path()} ==="
    )
    try:
        manifest_urls = _read_manifest_urls()
        _debug_log(f"manifest URLs tried ({len(manifest_urls)}): {manifest_urls}")
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

        result = UpdateCheckResult(
            current_version=current_version,
            latest_version=latest_version,
            setup_url=setup_url,
            notes=notes,
            sha256=sha256,
        )
        _debug_log(
            f"=== check_for_updates OK current={result.current_version} "
            f"latest={result.latest_version} has_update={result.has_update} "
            f"setup_url={result.setup_url} sha256_present={bool(result.sha256)} ==="
        )
        return result
    except UpdateCheckError as exc:
        _debug_exception("=== check_for_updates FAILED (UpdateCheckError) ===", exc)
        raise
    except Exception as exc:
        _debug_exception("=== check_for_updates FAILED (unexpected) ===", exc)
        raise


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
    _debug_log(
        f"=== download_verified_installer START app_version={APP_VERSION} "
        f"target_version={version} url={setup_url} ==="
    )
    expected = normalize_sha256(expected_sha256)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        exc = UpdateCheckError(
            "В манифесте обновлений нет корректного SHA256 установщика.\n"
            "Обновление прервано для вашей безопасности."
        )
        _debug_exception("download aborted: bad sha256 in manifest", exc)
        raise exc
    if not is_trusted_update_url(setup_url):
        exc = UpdateCheckError("Небезопасная ссылка на установщик.")
        _debug_exception("download aborted: untrusted setup_url", exc)
        raise exc

    updates_dir = data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    safe_version = re.sub(r"[^\d.]+", "_", version.strip()) or "latest"
    dest = updates_dir / f"GROMOV-RestorePlus-Setup-{safe_version}.exe"
    temp = dest.with_suffix(".exe.part")

    if dest.is_file():
        try:
            if file_sha256(dest) == expected:
                _debug_log(f"download cache hit path={dest}")
                return dest
            dest.unlink(missing_ok=True)
            _debug_log("download cache stale (sha mismatch), re-downloading")
        except OSError as exc:
            _debug_exception("download cache check OSError", exc)

    request = urllib.request.Request(setup_url, headers=_request_headers())
    digest = hashlib.sha256()
    received = 0
    started = time.perf_counter()
    _debug_log(f"download attempt url={setup_url} dest={dest}")
    try:
        with _urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SEC) as response:
            status = int(getattr(response, "status", None) or response.getcode() or 0)
            content_type = str(response.headers.get("Content-Type") or "")
            total = int(response.headers.get("Content-Length") or 0)
            _debug_log(
                f"download response http={status} content_type={content_type} "
                f"content_length={total}"
            )
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
        latency_ms = int((time.perf_counter() - started) * 1000)
        _debug_log(
            f"download transfer done latency_ms={latency_ms} "
            f"bytes_received={received}"
        )
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        err_body = b""
        try:
            err_body = exc.read(512) or b""
        except Exception:
            pass
        _debug_log(
            f"download HTTPError http={exc.code} latency_ms={latency_ms} "
            f"snippet={_debug_snippet(err_body)}"
        )
        _debug_exception("download HTTPError detail", exc)
        raise UpdateCheckError(f"Не удалось скачать установщик ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _debug_log(f"download URLError latency_ms={latency_ms}")
        _debug_exception("download URLError detail", exc)
        raise UpdateCheckError(
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _debug_log(f"download timeout latency_ms={latency_ms}")
        _debug_exception("download timeout detail", exc)
        raise UpdateCheckError(
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except ssl.SSLError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _debug_log(f"download SSLError latency_ms={latency_ms}")
        _debug_exception("download SSLError detail", exc)
        raise UpdateCheckError(
            _format_transport_error(exc, action="Загрузка установщика")
            + f"\n\nМожно скачать вручную:\n{setup_url}"
        ) from exc
    except OSError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _debug_log(f"download OSError latency_ms={latency_ms}")
        _debug_exception("download OSError detail", exc)
        raise UpdateCheckError(f"Не удалось сохранить установщик:\n{exc}") from exc

    actual = digest.hexdigest()
    if actual != expected:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        _debug_log(
            f"download sha256 mismatch expected={expected} actual={actual} "
            f"bytes={received}"
        )
        raise UpdateCheckError(
            "Проверка SHA256 не пройдена — файл повреждён или подменён.\n"
            "Обновление отменено."
        )

    try:
        temp.replace(dest)
    except OSError as exc:
        _debug_exception("download replace OSError", exc)
        raise UpdateCheckError(f"Не удалось сохранить установщик:\n{exc}") from exc

    if on_progress:
        on_progress(1.0)
    _debug_log(f"=== download_verified_installer OK path={dest} sha256={actual} ===")
    return dest
