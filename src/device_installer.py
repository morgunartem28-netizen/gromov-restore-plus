from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from app_paths import data_dir, tools_dir
from ipa_utils import is_valid_ipa, read_ipa_bundle_id
from subprocess_utils import popen_hidden, run_hidden


class DeviceInstallerError(RuntimeError):
    pass


class DeviceInstaller:
    def __init__(self) -> None:
        self.go_ios_path = self._resolve_go_ios()
        self.pymobiledevice3_available = self._has_pymobiledevice3()
        self.staging_dir = Path(tempfile.gettempdir()) / "restore-ios-apps"
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_go_ios(self) -> str | None:
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
        """go-ios on Windows ломается на путях с кириллицей — копируем во временную ASCII-папку."""
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

    def list_devices(self) -> list[str]:
        if self.go_ios_path:
            completed = run_hidden(
                [self.go_ios_path, "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                raise DeviceInstallerError((completed.stderr or completed.stdout).strip())
            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            return lines or ["Устройство найдено (go-ios)"]

        if self.pymobiledevice3_available:
            command = [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"]
            completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                raise DeviceInstallerError((completed.stderr or completed.stdout).strip())
            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            return lines

        raise DeviceInstallerError(
            "Не настроена установка на iPhone.\n"
            "Скачайте go-ios (ios.exe) с https://github.com/danielpaulus/go-ios/releases "
            "и положите в tools/ios.exe\n"
            "Или установите pymobiledevice3: pip install -r requirements-device.txt "
            "(нужен Python 3.11–3.12 или Microsoft C++ Build Tools)."
        )

    def install_ipa(
        self,
        ipa_path: Path,
        on_progress: Callable[[float, str], None] | None = None,
        *,
        expected_bundle_id: str | None = None,
    ) -> str:
        if not ipa_path.exists():
            raise DeviceInstallerError(f"Файл не найден: {ipa_path}")

        if not is_valid_ipa(ipa_path, expected_bundle_id=expected_bundle_id):
            bundle_id = read_ipa_bundle_id(ipa_path)
            details = f" ({bundle_id})" if bundle_id else ""
            raise DeviceInstallerError(
                f"Файл IPA повреждён или скачан не полностью: {ipa_path.name}{details}\n"
                "Удалите его из папки downloads и скачайте приложение заново."
            )

        devices = self.list_devices()
        if not devices:
            raise DeviceInstallerError("iPhone не найден. Подключите USB и нажмите «Доверять компьютеру».")

        if on_progress:
            on_progress(0.72, "Подготовка файла для установки...")
        install_path = self._stage_ipa(ipa_path)
        try:
            if not is_valid_ipa(install_path, expected_bundle_id=expected_bundle_id):
                raise DeviceInstallerError(
                    "Не удалось подготовить IPA для установки — файл повреждён.\n"
                    "Скачайте приложение заново."
                )
            log_path = data_dir() / "install.log"

            if self.go_ios_path:
                command = [self.go_ios_path, "install", "--path", str(install_path), "--verbose"]
                install_step = 0.72

                def report(step: float, text: str) -> None:
                    nonlocal install_step
                    install_step = max(install_step, step)
                    if on_progress:
                        on_progress(install_step, text)

                if on_progress:
                    report(0.75, "Установка на iPhone...")
                    proc = popen_hidden(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    output_lines: list[str] = []
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        output_lines.append(line)
                        if "%" in line or "install" in line.lower() or "upload" in line.lower():
                            report(min(0.94, install_step + 0.01), "Передача на iPhone...")
                    completed = subprocess.CompletedProcess(
                        command, proc.wait(), stdout="".join(output_lines), stderr=""
                    )
                else:
                    completed = run_hidden(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n--- install {install_path.name} ---\nexit={completed.returncode}\n{output}\n")

                if on_progress:
                    report(0.98, "Завершение установки...")

                if completed.returncode != 0:
                    hint = (
                        "\n\nЧто проверить на iPhone:\n"
                        "1. Кабель USB надёжно подключён\n"
                        "2. Нажато «Доверять этому компьютеру»\n"
                        "3. iOS 17+: Настройки → Конфиденциальность → Режим разработчика (включить)\n"
                        "4. Установлены Apple Devices или iTunes на ПК"
                    )
                    if "tunnel" in output.lower() or "agent is not running" in output.lower():
                        hint += (
                            "\n5. Для iOS 17+ откройте отдельный терминал и выполните:\n"
                            "   tools\\ios.exe tunnel start\n"
                            "   затем снова нажмите «Скачать и установить»"
                        )
                    if "No such file or directory" in output or "PublicStaging" in output:
                        hint += "\n\nПуть к IPA исправлен — попробуйте установку ещё раз."
                    if "EOF" in output:
                        hint += (
                            "\n\nСоединение оборвалось при передаче файла (~400 МБ).\n"
                            "Используйте оригинальный кабель, не отключайте iPhone 2–3 минуты."
                        )
                    if "zip not a valid" in output.lower() or "not a valid zip" in output.lower():
                        hint += (
                            "\n\nФайл IPA повреждён. Приложение скачает его заново при следующей попытке."
                        )
                    raise DeviceInstallerError(
                        "Установка на iPhone не удалась."
                        + hint
                        + "\n\nТехнические детали:\n"
                        + output.strip()
                    )
                return "Приложение установлено на iPhone. Проверьте домашний экран."

            if self.pymobiledevice3_available:
                command = [sys.executable, "-m", "pymobiledevice3", "apps", "install", str(install_path)]
                completed = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
                output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
                if completed.returncode != 0:
                    raise DeviceInstallerError(
                        "pymobiledevice3 не смог установить IPA.\n"
                        "Проверьте USB, «Доверять компьютеру» и Apple Devices/iTunes.\n\n"
                        + output.strip()
                    )
                return output.strip() or "Установка завершена."

            raise DeviceInstallerError(
                "Нет инструмента для установки. Положите tools/ios.exe (go-ios) или установите pymobiledevice3."
            )
        finally:
            self._cleanup_staged(install_path)
