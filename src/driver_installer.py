from __future__ import annotations

import subprocess
from pathlib import Path

from app_paths import drivers_dir
from subprocess_utils import run_hidden


class DriverInstallerError(RuntimeError):
    pass


def apple_drivers_installed() -> bool:
    service = run_hidden(
        ["sc", "query", "Apple Mobile Device Service"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if service.returncode == 0 and "RUNNING" in (service.stdout or "").upper():
        return True

    common = Path(r"C:\Program Files\Common Files\Apple\Mobile Device Support")
    return common.exists() and any(common.iterdir())


def install_apple_drivers() -> str:
    if apple_drivers_installed():
        return "Драйверы Apple уже установлены."

    drivers = drivers_dir()
    batch = drivers / "install_drivers.bat"
    if batch.exists():
        completed = run_hidden(
            ["cmd", "/c", str(batch)],
            cwd=str(drivers),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if apple_drivers_installed():
            return "Драйверы Apple установлены.\n" + output
        if completed.returncode != 0:
            raise DriverInstallerError(
                "Не удалось установить драйверы Apple.\n"
                + (output or "Запустите установщик от имени администратора.")
            )

    msi_order = [
        "AppleApplicationSupport64.msi",
        "AppleMobileDeviceSupport64.msi",
    ]
    installed_any = False
    messages: list[str] = []
    for name in msi_order:
        msi = drivers / name
        if not msi.exists():
            continue
        completed = run_hidden(
            ["msiexec", "/i", str(msi), "/passive", "/norestart"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        installed_any = True
        messages.append(f"{name}: код {completed.returncode}")

    if installed_any and apple_drivers_installed():
        return "Драйверы Apple установлены.\n" + "\n".join(messages)

    if installed_any:
        return (
            "Установка драйверов запущена. Перезагрузите ПК при запросе Windows.\n"
            + "\n".join(messages)
        )

    raise DriverInstallerError(
        "Файлы драйверов Apple не найдены в папке drivers.\n"
        "Установите «Apple Devices» из Microsoft Store:\n"
        "https://apps.microsoft.com/detail/9pb2mz1zmb1s"
    )
