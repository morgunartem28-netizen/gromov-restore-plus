"""Shared download+install pipeline with phase callbacks and cancel."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from config_manager import AppEntry, ConfigManager
from device_installer import DeviceInstallCancelled, DeviceInstaller, DeviceInstallerError
from disk_utils import DiskSpaceError, ensure_download_space
from ipa_utils import inspect_fairplay_markers
from ipatool_client import IpatoolCancelled, IpatoolClient, IpatoolError
from security_utils import mask_email

PhaseCallback = Callable[[str, float, str], None]

# Overall job bar: prepare → auth → download bytes → verify → transfer/install → done.
_AUTH_BAR_START = 0.08
_AUTH_BAR_CAP = 0.11
_DOWNLOAD_BAR_START = 0.12
_DOWNLOAD_BAR_END = 0.55
# When Content-Length is unknown, half of the download band at ~180 MB.
_UNKNOWN_SIZE_HALF_BYTES = 180 * 1024 * 1024


def map_download_progress(downloaded: int, *, known_total: int | None = None) -> float:
    """Map downloaded bytes into the download segment of the overall progress bar."""
    downloaded = max(0, int(downloaded))
    span = _DOWNLOAD_BAR_END - _DOWNLOAD_BAR_START
    if known_total is not None and known_total > 0:
        ratio = min(1.0, downloaded / known_total)
        return _DOWNLOAD_BAR_START + span * ratio
    # Asymptotic toward the end of the band; finalize bumps to _DOWNLOAD_BAR_END.
    ratio = downloaded / (downloaded + _UNKNOWN_SIZE_HALF_BYTES) if downloaded else 0.0
    return _DOWNLOAD_BAR_START + span * ratio * 0.92


def pick_download_artifact(downloads_dir: Path, app_id: int) -> tuple[Path | None, bool]:
    """Newest ipatool artifact for app_id.

    ipatool writes ``{id}_*.ipa.tmp`` while downloading, then renames to ``.ipa``.
    Returns ``(path, is_temp)``.
    """
    app_id_text = str(app_id)
    tmps: list[Path] = []
    finals: list[Path] = []
    for pattern in (
        f"{app_id_text}_*.ipa.tmp",
        f"*_{app_id_text}_*.ipa.tmp",
        f"{app_id_text}_*.ipa",
        f"*_{app_id_text}_*.ipa",
    ):
        for path in downloads_dir.glob(pattern):
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            name = path.name.lower()
            if name.endswith(".ipa.tmp"):
                tmps.append(path)
            elif name.endswith(".ipa"):
                finals.append(path)

    def newest(paths: list[Path]) -> Path | None:
        if not paths:
            return None
        return max(paths, key=lambda item: item.stat().st_mtime)

    tmp = newest(tmps)
    if tmp is not None:
        return tmp, True
    final = newest(finals)
    if final is not None:
        return final, False
    return None, False


def format_download_size(num_bytes: int) -> str:
    if num_bytes < 1024 * 1024:
        return f"{max(1, num_bytes // 1024)} КБ"
    return f"{num_bytes / (1024 * 1024):.0f} МБ"


def clear_tool_cancels_unless_stopped(
    cancel_event: threading.Event | None,
    *tools: object,
) -> None:
    """Clear per-tool cancel flags for a new job without wiping a racing user Cancel.

    TOCTOU: user Cancel between ``is_set()`` and ``clear_cancel()`` would otherwise
    erase freshly set tool flags and let download/install continue after «Отмена».
    After clear, re-check the shared queue event; if set, re-assert tool cancels and abort.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise IpatoolCancelled("Операция отменена.")
    for tool in tools:
        clear = getattr(tool, "clear_cancel", None)
        if callable(clear):
            clear()
    if cancel_event is not None and cancel_event.is_set():
        for tool in tools:
            request = getattr(tool, "request_cancel", None)
            if callable(request):
                request()
        raise IpatoolCancelled("Операция отменена.")


def run_install_job(
    *,
    app: AppEntry,
    ipatool: IpatoolClient,
    device_installer: DeviceInstaller,
    config_manager: ConfigManager,
    udid: str | None,
    on_phase: PhaseCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    # Throttle identical / near-identical UI callbacks (disk poll can fire ~2 Hz).
    _last_phase: list[tuple[str, float, str, float]] = [("", -1.0, "", 0.0)]

    def phase(name: str, value: float, text: str) -> None:
        if cancel_event and cancel_event.is_set():
            raise IpatoolCancelled("Операция отменена.")
        if on_phase:
            now = time.monotonic()
            prev_name, prev_val, prev_text, prev_at = _last_phase[0]
            same = (
                name == prev_name
                and text == prev_text
                and abs(value - prev_val) < 0.008
                and (now - prev_at) < 0.15
            )
            if same:
                return
            _last_phase[0] = (name, value, text, now)
            on_phase(name, value, text)

    if not config_manager.apple_account_email:
        raise IpatoolError("Сначала войдите в Apple ID.")

    downloads_dir = config_manager.account_downloads_dir()
    if downloads_dir is None:
        raise IpatoolError("Сначала войдите в Apple ID.")

    phase("prepare", 0.05, "Подготовка...")
    cached = config_manager.find_cached_ipa(app.appId, expected_bundle_id=app.bundleId)

    if cached:
        ipa_path = cached
        phase("download", 0.45, "Приложение уже скачано")
    else:
        ensure_download_space(downloads_dir)
        title = app.maskTitle or app.title
        phase("download", _AUTH_BAR_START, f"Запрос лицензии «{title}»...")
        stop_poll = threading.Event()
        max_bytes = [0]
        auth_started = time.monotonic()

        def poll() -> None:
            while not stop_poll.is_set():
                try:
                    artifact, is_temp = pick_download_artifact(downloads_dir, app.appId)
                    if artifact is None:
                        # Auth / purchase / CDN handshake — no .tmp yet.
                        elapsed = time.monotonic() - auth_started
                        creep = min(_AUTH_BAR_CAP, _AUTH_BAR_START + elapsed * 0.003)
                        phase("download", creep, f"Запрос лицензии «{title}»...")
                    else:
                        try:
                            size = artifact.stat().st_size
                        except OSError:
                            size = 0
                        max_bytes[0] = max(max_bytes[0], size)
                        size_label = format_download_size(max_bytes[0])
                        if is_temp:
                            value = map_download_progress(max_bytes[0])
                            phase("download", value, f"Получение... ({size_label})")
                        else:
                            # Rename finished — bytes are complete for this job.
                            phase(
                                "download",
                                _DOWNLOAD_BAR_END,
                                f"Файл получен ({size_label})",
                            )
                except IpatoolCancelled:
                    return
                # 0.7s is enough for a smooth bar without flooding Tk with after(0).
                time.sleep(0.7)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        try:
            clear_tool_cancels_unless_stopped(cancel_event, ipatool, device_installer)
            ipa_path = ipatool.download(
                app_id=app.appId,
                bundle_id=app.bundleId,
                output_dir=downloads_dir,
                purchase=True,
            )
        except (IpatoolCancelled, DiskSpaceError):
            raise
        except IpatoolError:
            raise
        finally:
            stop_poll.set()
            poller.join(timeout=1)

    phase("verify", 0.62, "Проверка файла...")
    markers = inspect_fairplay_markers(ipa_path)
    if markers is None:
        phase("verify", 0.63, "FairPlay: метаданные IPA не прочитаны")
    else:
        apple = mask_email(markers.apple_id) if markers.apple_id else "—"
        sinf = f"sinf×{markers.sinf_count}" if markers.has_sinf else "без .sinf"
        crypt = f"cryptid={markers.cryptid}" if markers.cryptid is not None else "cryptid=?"
        phase(
            "verify",
            0.64,
            f"FairPlay: {apple} · {sinf} · {crypt}",
        )
        if not markers.looks_customer_ipa:
            phase(
                "verify",
                0.65,
                "Предупреждение: IPA без типичных маркеров FairPlay (sinf+cryptid=1)",
            )
    phase("transfer", 0.70, "Передача на iPhone...")

    def progress(value: float, text: str) -> None:
        phase("install", value, text)

    try:
        device_installer.install_ipa(
            ipa_path,
            on_progress=progress,
            expected_bundle_id=app.bundleId,
            udid=udid,
        )
    except DeviceInstallCancelled as exc:
        raise IpatoolCancelled(str(exc)) from exc
    except DeviceInstallerError:
        raise

    phase("done", 1.0, "Готово")
