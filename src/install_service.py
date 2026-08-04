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
    def phase(name: str, value: float, text: str) -> None:
        if cancel_event and cancel_event.is_set():
            raise IpatoolCancelled("Операция отменена.")
        if on_phase:
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
        phase("download", 0.15, f"Получение «{app.maskTitle or app.title}»...")
        stop_poll = threading.Event()
        max_bytes = [0]

        def poll() -> None:
            while not stop_poll.is_set():
                candidates = sorted(
                    downloads_dir.glob(f"{app.appId}_*.ipa"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    size = candidates[0].stat().st_size
                    max_bytes[0] = max(max_bytes[0], size)
                    size_mb = max_bytes[0] / (1024 * 1024)
                    value = min(0.55, 0.15 + (max_bytes[0] / (850 * 1024 * 1024)) * 0.4)
                    phase("download", value, f"Получение... ({size_mb:.0f} МБ)")
                time.sleep(0.5)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        try:
            # Do not clear cancel flags if the queue already requested cancel.
            if cancel_event is not None and cancel_event.is_set():
                raise IpatoolCancelled("Операция отменена.")
            if cancel_event is None or not cancel_event.is_set():
                ipatool.clear_cancel()
                device_installer.clear_cancel()
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
