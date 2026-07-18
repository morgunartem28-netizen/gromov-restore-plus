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
            f"UDID: {self.udid}",
        ]
        if self.battery:
            lines.append(f"Заряд: {self.battery}")
        if self.connection:
            lines.append(f"Подключение: {self.connection}")
        return "\n".join(lines)


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

    def list_device_infos(self) -> list[DeviceInfo]:
        if self.go_ios_path:
            completed = run_hidden(
                [self.go_ios_path, "list", "--details"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                # Fallback to plain list
                plain = run_hidden(
                    [self.go_ios_path, "list"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
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
                        )
                    )
                return devices

            try:
                payload = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise DeviceInstallerError("Не удалось прочитать список устройств.") from exc

            devices = []
            for item in payload.get("deviceList") or []:
                if isinstance(item, str):
                    udid = item
                    devices.append(
                        DeviceInfo(udid=udid, name=self._device_name(udid), model="", ios_version="")
                    )
                    continue
                if not isinstance(item, dict):
                    continue
                udid = str(item.get("Udid") or item.get("udid") or "").strip()
                if not udid:
                    continue
                model = str(item.get("ProductType") or item.get("productType") or "")
                ios_version = str(item.get("ProductVersion") or item.get("productVersion") or "")
                connection = str(item.get("ConnectionType") or item.get("connectionType") or "USB")
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
                        connection=connection,
                    )
                )
            return devices

        if self.pymobiledevice3_available:
            command = [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"]
            completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                raise DeviceInstallerError((completed.stderr or completed.stdout).strip())
            # Best-effort: one synthetic device if any output
            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if not lines:
                return []
            return [DeviceInfo(udid="pymobiledevice3", name="iPhone", model="", ios_version="")]

        raise DeviceInstallerError(
            "Не настроена установка на iPhone.\n"
            "Переустановите приложение из официального Setup (нужен tools\\ios.exe)."
        )

    def list_devices(self) -> list[str]:
        return [device.label for device in self.list_device_infos()]

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

        devices = self.list_device_infos()
        if not devices:
            raise DeviceInstallerError("iPhone не найден. Подключите USB и нажмите «Доверять компьютеру».")

        if not udid:
            if len(devices) > 1:
                raise DeviceInstallerError(
                    "Подключено несколько iPhone.\nВыберите устройство в боковой панели перед установкой."
                )
            udid = devices[0].udid
        elif not any(device.udid == udid for device in devices):
            raise DeviceInstallerError("Выбранный iPhone больше не подключён. Обновите список устройств.")

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

                def report(step: float, text: str) -> None:
                    nonlocal install_step
                    install_step = max(install_step, step)
                    if on_progress:
                        on_progress(install_step, text)

                if on_progress:
                    report(0.75, "Передача на iPhone...")
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
                for line in proc.stdout:
                    if self._cancel.is_set():
                        try:
                            proc.terminate()
                        except OSError:
                            pass
                        raise DeviceInstallCancelled("Операция отменена.")
                    output_lines.append(line)
                    if "%" in line or "install" in line.lower() or "upload" in line.lower():
                        report(min(0.94, install_step + 0.01), "Передача на iPhone...")
                completed = subprocess.CompletedProcess(command, proc.wait(), stdout="".join(output_lines), stderr="")
                with self._proc_lock:
                    self._active_proc = None

                output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
                try:
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write(f"\n--- install {install_path.name} udid={udid} ---\nexit={completed.returncode}\n{output}\n")
                except OSError:
                    pass

                if on_progress:
                    report(0.98, "Завершение установки...")

                if completed.returncode != 0:
                    raise DeviceInstallerError(
                        "Установка на iPhone не удалась.\n"
                        "Проверьте кабель, «Доверять компьютеру» и повторите."
                    )
                return "Приложение установлено на iPhone. Проверьте домашний экран."

            if self.pymobiledevice3_available:
                command = [sys.executable, "-m", "pymobiledevice3", "apps", "install", str(install_path)]
                completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if completed.returncode != 0:
                    raise DeviceInstallerError(
                        "Не удалось установить приложение.\n"
                        "Проверьте USB и «Доверять компьютеру»."
                    )
                return "Установка завершена."

            raise DeviceInstallerError(
                "Нет инструмента для установки. Переустановите приложение из официального Setup."
            )
        finally:
            self._cleanup_staged(install_path)
