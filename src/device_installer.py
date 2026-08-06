from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_paths import data_dir, is_frozen, tools_dir
from ipa_utils import is_valid_ipa, read_ipa_bundle_id
from subprocess_utils import popen_hidden, run_hidden


class DeviceInstallerError(RuntimeError):
    pass


class DeviceInstallCancelled(DeviceInstallerError):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    udid: str
    name: str
    model: str
    ios_version: str
    connection: str = "USB"
    battery: str = ""

    @property
    def label(self) -> str:
        parts = [self.name or "iPhone"]
        if self.model:
            parts.append(self.model)
        if self.ios_version:
            parts.append(f"iOS {self.ios_version}")
        return " · ".join(parts)

    @property
    def detail_lines(self) -> str:
        lines = [
            f"Имя: {self.name or '—'}",
            f"Модель: {self.model or '—'}",
            f"iOS: {self.ios_version or '—'}",
            f"Подключение: USB",
            f"UDID: {self.udid}",
        ]
        if self.battery:
            lines.append(f"Заряд: {self.battery}")
        return "\n".join(lines)

    @property
    def is_usb(self) -> bool:
        return is_usb_connection(self.connection)


_USB_BLOCKED_MARKERS = (
    "network",
    "wifi",
    "wi-fi",
    "wireless",
    "bonjour",
    "mdns",
    "m-dns",
    "tunnel",
    "remote",
)


def is_usb_connection(value: str | None) -> bool:
    """True only for explicit physical USB — never Wi-Fi / Network / tunnel / unknown."""
    raw = (value or "").strip().lower()
    if not raw:
        return False
    if any(marker in raw for marker in _USB_BLOCKED_MARKERS):
        return False
    # Whitelist only — unknown values must NOT pass (safer than blocklist).
    if raw in {"usb", "usbmux", "usbmuxd"}:
        return True
    # Allow "USB " / "usb0" / "ConnectionTypeUSB" style labels from older tools.
    if raw.startswith("usb") or raw.endswith("usb"):
        return True
    return False


def _dedupe_usb_devices(devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """Keep one entry per UDID; prefer richer USB metadata."""
    by_udid: dict[str, DeviceInfo] = {}
    order: list[str] = []
    for device in devices:
        if not device.is_usb:
            continue
        existing = by_udid.get(device.udid)
        if existing is None:
            by_udid[device.udid] = device
            order.append(device.udid)
            continue
        score = lambda d: (bool(d.name and d.name != "iPhone"), bool(d.model), bool(d.ios_version))
        if score(device) > score(existing):
            by_udid[device.udid] = device
    return [by_udid[u] for u in order]


class DeviceInstaller:
    def __init__(self) -> None:
        self.go_ios_path = self._resolve_go_ios()
        self.pymobiledevice3_available = self._has_pymobiledevice3()
        self.staging_dir = data_dir() / "staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._active_proc: subprocess.Popen[str] | None = None
        self._proc_lock = threading.Lock()
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()
        with self._proc_lock:
            proc = self._active_proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def clear_cancel(self) -> None:
        self._cancel.clear()

    def _resolve_go_ios(self) -> str | None:
        if not is_frozen():
            from_env = os.environ.get("GO_IOS_PATH")
            if from_env and Path(from_env).exists():
                return from_env
            found = shutil.which("ios")
            if found:
                return found
        local = tools_dir() / "ios.exe"
        if local.exists():
            return str(local)
        return None

    def _has_pymobiledevice3(self) -> bool:
        try:
            import pymobiledevice3  # noqa: F401
        except ImportError:
            return False
        return True

    def _stage_ipa(self, ipa_path: Path) -> Path:
        safe_stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in ipa_path.stem)[:80] or "app"
        fd, staged_name = tempfile.mkstemp(prefix=f"{safe_stem}_", suffix=".ipa", dir=self.staging_dir)
        os.close(fd)
        staged = Path(staged_name)
        shutil.copy2(ipa_path, staged)
        return staged

    @staticmethod
    def _cleanup_staged(staged: Path | None) -> None:
        if staged is None:
            return
        try:
            if staged.exists():
                staged.unlink()
        except OSError:
            pass

    def backend_name(self) -> str:
        if self.go_ios_path:
            return "go-ios"
        if self.pymobiledevice3_available:
            return "pymobiledevice3"
        return "не настроен"

    def _device_name(self, udid: str) -> str:
        if not self.go_ios_path:
            return "iPhone"
        try:
            completed = run_hidden(
                [self.go_ios_path, "devicename", f"--udid={udid}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            return "iPhone"
        if completed.returncode != 0:
            return "iPhone"
        try:
            payload = json.loads(completed.stdout or "{}")
            name = payload.get("devicename") or payload.get("DeviceName")
            if name:
                return str(name)
        except json.JSONDecodeError:
            text = (completed.stdout or "").strip()
            if text:
                return text
        return "iPhone"

    def list_device_infos(self, *, usb_only: bool = True) -> list[DeviceInfo]:
        """List connected iPhones.

        By default returns **USB-only** devices. Wi-Fi / Network / tunnel entries
        from go-ios are ignored so installs never target a phone on the LAN.
        """
        if self.go_ios_path:
            try:
                completed = run_hidden(
                    [self.go_ios_path, "list", "--details"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=12,
                )
            except subprocess.TimeoutExpired as exc:
                raise DeviceInstallerError(
                    "Не удалось получить список USB-устройств (таймаут).\n"
                    "Подключите iPhone кабелем, разблокируйте и нажмите «Доверять»."
                ) from exc
            if completed.returncode != 0:
                # Plain list has no ConnectionType — unsafe for USB-only installs.
                # Do not fall back to it when usb_only=True (would include Wi-Fi).
                if usb_only:
                    raise DeviceInstallerError(
                        "Не удалось получить список USB-устройств.\n"
                        "Подключите iPhone кабелем, разблокируйте и нажмите «Доверять»."
                    )
                try:
                    plain = run_hidden(
                        [self.go_ios_path, "list"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=12,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise DeviceInstallerError(
                        "Не удалось получить список USB-устройств (таймаут).\n"
                        "Подключите iPhone кабелем, разблокируйте и нажмите «Доверять»."
                    ) from exc
                if plain.returncode != 0:
                    raise DeviceInstallerError((completed.stderr or completed.stdout or plain.stderr or "").strip())
                try:
                    payload = json.loads(plain.stdout or "{}")
                    udids = payload.get("deviceList") or []
                except json.JSONDecodeError:
                    udids = [line.strip() for line in (plain.stdout or "").splitlines() if line.strip()]
                devices: list[DeviceInfo] = []
                for item in udids:
                    udid = str(item)
                    devices.append(
                        DeviceInfo(
                            udid=udid,
                            name=self._device_name(udid),
                            model="",
                            ios_version="",
                            connection="unknown",
                        )
                    )
                return devices

            try:
                payload = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise DeviceInstallerError("Не удалось прочитать список устройств.") from exc

            devices: list[DeviceInfo] = []
            raw_list = payload.get("deviceList") or payload.get("devices") or []
            for item in raw_list:
                if isinstance(item, str):
                    # String UDID without connection metadata — skip when USB-only.
                    if usb_only:
                        continue
                    devices.append(
                        DeviceInfo(udid=item, name=self._device_name(item), model="", ios_version="", connection="unknown")
                    )
                    continue
                if not isinstance(item, dict):
                    continue

                udid = str(item.get("Udid") or item.get("udid") or "").strip()
                if not udid:
                    continue

                # Newer go-ios may expose transports[]; treat as USB if any transport is usb.
                transports = item.get("transports") or item.get("Transports") or []
                connection = str(
                    item.get("ConnectionType")
                    or item.get("connectionType")
                    or item.get("connection")
                    or ""
                ).strip()
                if not connection and isinstance(transports, list):
                    types = []
                    for tr in transports:
                        if isinstance(tr, dict):
                            types.append(str(tr.get("type") or tr.get("Type") or "").strip())
                        elif isinstance(tr, str):
                            types.append(tr.strip())
                    if any(is_usb_connection(t) for t in types):
                        connection = "USB"
                    elif types:
                        connection = types[0]

                if usb_only and not is_usb_connection(connection):
                    continue
                if not connection:
                    # Missing ConnectionType: only keep if not usb_only.
                    if usb_only:
                        continue
                    connection = "unknown"

                model = str(item.get("ProductType") or item.get("productType") or item.get("model") or "")
                ios_version = str(
                    item.get("ProductVersion") or item.get("productVersion") or item.get("ios_version") or ""
                )
                name = str(
                    item.get("DeviceName")
                    or item.get("deviceName")
                    or item.get("Name")
                    or item.get("name")
                    or ""
                ).strip()
                if not name:
                    name = self._device_name(udid)
                devices.append(
                    DeviceInfo(
                        udid=udid,
                        name=name,
                        model=model,
                        ios_version=ios_version,
                        connection="USB" if is_usb_connection(connection) else connection,
                    )
                )

            if usb_only:
                return _dedupe_usb_devices(devices)
            return devices

        if self.pymobiledevice3_available:
            # usbmux list is USB/usbmux only — OK for usb_only.
            return self._list_pymobiledevice3_usb()

        raise DeviceInstallerError(
            "Не настроена установка на iPhone.\n"
            "Переустановите приложение из официального Setup (нужен tools\\ios.exe)."
        )

    def _list_pymobiledevice3_usb(self) -> list[DeviceInfo]:
        """Parse pymobiledevice3 usbmux list into real UDID entries (USB only)."""
        command = [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"]
        completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise DeviceInstallerError((completed.stderr or completed.stdout).strip())
        raw = (completed.stdout or "").strip()
        if not raw:
            return []

        items: list[object] = []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: one UDID per non-empty line (no connection metadata → USB usbmux only).
            for line in raw.splitlines():
                udid = line.strip()
                if udid:
                    items.append({"SerialNumber": udid})
            payload = items
        else:
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                nested = (
                    payload.get("devices")
                    or payload.get("ConnectedDevices")
                    or payload.get("deviceList")
                    or []
                )
                if isinstance(nested, list) and nested:
                    items = nested
                else:
                    items = [payload]
            else:
                items = []

        devices: list[DeviceInfo] = []
        for item in items:
            if isinstance(item, str):
                udid = item.strip()
                name = "iPhone"
                model = ""
                ios_version = ""
            elif isinstance(item, dict):
                udid = str(
                    item.get("SerialNumber")
                    or item.get("serialNumber")
                    or item.get("UDID")
                    or item.get("udid")
                    or item.get("UniqueDeviceID")
                    or ""
                ).strip()
                name = str(
                    item.get("DeviceName") or item.get("deviceName") or item.get("name") or "iPhone"
                ).strip() or "iPhone"
                model = str(item.get("ProductType") or item.get("productType") or item.get("model") or "")
                ios_version = str(
                    item.get("ProductVersion") or item.get("productVersion") or item.get("ios_version") or ""
                )
            else:
                continue
            if not udid or udid.lower() == "pymobiledevice3":
                continue
            devices.append(
                DeviceInfo(
                    udid=udid,
                    name=name,
                    model=model,
                    ios_version=ios_version,
                    connection="USB",
                )
            )
        return _dedupe_usb_devices(devices)

    def list_usb_devices(self) -> list[DeviceInfo]:
        return self.list_device_infos(usb_only=True)

    def list_devices(self) -> list[str]:
        return [device.label for device in self.list_usb_devices()]

    def install_ipa(
        self,
        ipa_path: Path,
        on_progress: Callable[[float, str], None] | None = None,
        *,
        expected_bundle_id: str | None = None,
        udid: str | None = None,
    ) -> str:
        if self._cancel.is_set():
            raise DeviceInstallCancelled("Операция отменена.")

        if not ipa_path.exists():
            raise DeviceInstallerError(f"Файл не найден: {ipa_path}")

        if not is_valid_ipa(ipa_path, expected_bundle_id=expected_bundle_id):
            bundle_id = read_ipa_bundle_id(ipa_path)
            details = f" ({bundle_id})" if bundle_id else ""
            raise DeviceInstallerError(
                f"Файл IPA повреждён или скачан не полностью: {ipa_path.name}{details}\n"
                "Удалите его из папки downloads и скачайте приложение заново."
            )

        devices = self.list_usb_devices()
        if not devices:
            raise DeviceInstallerError(
                "iPhone по USB не найден.\n"
                "Подключите кабель, разблокируйте iPhone и нажмите «Доверять компьютеру»."
            )

        if not udid:
            if len(devices) > 1:
                raise DeviceInstallerError(
                    "Подключено несколько iPhone по USB.\nВыберите устройство перед установкой."
                )
            udid = devices[0].udid
        elif not any(device.udid == udid for device in devices):
            raise DeviceInstallerError(
                "Выбранный iPhone больше не подключён по USB.\n"
                "Подключите кабель и выберите устройство снова."
            )

        if on_progress:
            on_progress(0.72, "Подготовка файла для установки...")
        install_path = self._stage_ipa(ipa_path)
        try:
            if self._cancel.is_set():
                raise DeviceInstallCancelled("Операция отменена.")
            if not is_valid_ipa(install_path, expected_bundle_id=expected_bundle_id):
                raise DeviceInstallerError(
                    "Не удалось подготовить IPA для установки — файл повреждён.\n"
                    "Скачайте приложение заново."
                )
            log_path = data_dir() / "install.log"

            if self.go_ios_path:
                command = [
                    self.go_ios_path,
                    "install",
                    "--path",
                    str(install_path),
                    f"--udid={udid}",
                    "--verbose",
                ]
                install_step = 0.72
                target = next((d for d in devices if d.udid == udid), None)
                target_label = (target.name if target else None) or "iPhone"

                def report(step: float, text: str) -> None:
                    nonlocal install_step
                    install_step = max(install_step, step)
                    if on_progress:
                        on_progress(install_step, text)

                if on_progress:
                    report(0.75, f"Передача на {target_label} (USB)...")

                stop_watch = threading.Event()

                def _usb_watchdog() -> None:
                    """Abort hang if the chosen USB device disappears mid-install."""
                    while not stop_watch.wait(4.0):
                        if self._cancel.is_set():
                            return
                        try:
                            live = self.list_usb_devices()
                        except DeviceInstallerError:
                            live = []
                        if any(d.udid == udid for d in live):
                            continue
                        self.request_cancel()
                        return

                watcher = threading.Thread(target=_usb_watchdog, daemon=True)
                watcher.start()
                with self._proc_lock:
                    proc = popen_hidden(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    self._active_proc = proc
                output_lines: list[str] = []
                assert proc.stdout is not None
                try:
                    for line in proc.stdout:
                        if self._cancel.is_set():
                            try:
                                proc.terminate()
                            except OSError:
                                pass
                            # Distinguish user cancel vs unplug.
                            still_there = False
                            try:
                                still_there = any(d.udid == udid for d in self.list_usb_devices())
                            except DeviceInstallerError:
                                still_there = False
                            if not still_there:
                                raise DeviceInstallerError(
                                    "iPhone отключён во время установки.\n"
                                    "Подключите кабель USB и повторите."
                                )
                            raise DeviceInstallCancelled("Операция отменена.")
                        output_lines.append(line)
                        lower = line.lower()
                        if "%" in line or "install" in lower or "upload" in lower:
                            report(min(0.94, install_step + 0.01), f"Передача на {target_label} (USB)...")
                    completed = subprocess.CompletedProcess(
                        command, proc.wait(), stdout="".join(output_lines), stderr=""
                    )
                finally:
                    stop_watch.set()
                    with self._proc_lock:
                        self._active_proc = None

                output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
                try:
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            f"\n--- install {install_path.name} udid={udid} ---\n"
                            f"exit={completed.returncode}\n{output}\n"
                        )
                except OSError:
                    pass

                if on_progress:
                    report(0.98, "Завершение установки...")

                if completed.returncode != 0:
                    lower_out = output.lower()
                    if any(
                        token in lower_out
                        for token in (
                            "not found",
                            "no device",
                            "device not connected",
                            "could not connect",
                            "unable to connect",
                            "locked",
                            "pair",
                        )
                    ):
                        raise DeviceInstallerError(
                            "Не удалось установить на выбранный iPhone.\n"
                            "Проверьте USB-кабель, разблокируйте телефон и нажмите «Доверять»."
                        )
                    raise DeviceInstallerError(
                        "Установка на iPhone не удалась.\n"
                        "Проверьте кабель, «Доверять компьютеру» и повторите."
                    )
                return (
                    f"Приложение установлено на {target_label}. "
                    "На iPhone откройте его и войдите в Apple ID, "
                    "с которого скачивали (пароль при первом запуске — норма)."
                )

            if self.pymobiledevice3_available:
                if not udid or udid.lower() == "pymobiledevice3":
                    raise DeviceInstallerError(
                        "Не удалось определить UDID iPhone для установки.\n"
                        "Подключите устройство по USB и повторите."
                    )
                target = next((d for d in devices if d.udid == udid), None)
                target_label = (target.name if target else None) or "iPhone"
                command = [
                    sys.executable,
                    "-m",
                    "pymobiledevice3",
                    "apps",
                    "install",
                    str(install_path),
                    "--udid",
                    udid,
                ]
                if on_progress:
                    on_progress(0.80, f"Передача на {target_label} (USB)...")
                completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if completed.returncode != 0:
                    raise DeviceInstallerError(
                        "Не удалось установить приложение.\n"
                        "Проверьте USB и «Доверять компьютеру»."
                    )
                return (
                    f"Приложение установлено на {target_label}. "
                    "На iPhone откройте его и войдите в Apple ID, "
                    "с которого скачивали (пароль при первом запуске — норма)."
                )

            raise DeviceInstallerError(
                "Нет инструмента для установки. Переустановите приложение из официального Setup."
            )
        finally:
            self._cleanup_staged(install_path)
