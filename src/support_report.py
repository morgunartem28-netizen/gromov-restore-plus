"""Build a support diagnostics report for users."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app_paths import data_dir, tools_dir
from version import APP_VERSION


def _tail(path: Path, lines: int = 80) -> str:
    if not path.is_file():
        return "(нет файла)"
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:])
    except OSError as exc:
        return f"(ошибка чтения: {exc})"


def _tool_version(exe: Path, *args: str) -> str:
    if not exe.is_file():
        return "не найден"
    try:
        completed = subprocess.run(
            [str(exe), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        return text.splitlines()[0][:200] if text else f"exit={completed.returncode}"
    except Exception as exc:  # noqa: BLE001
        return f"ошибка: {exc}"


def build_support_report(
    *,
    device_summary: str = "",
    driver_status: str = "",
    apple_id_masked: str = "",
) -> Path:
    tools = tools_dir()
    data = data_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = data / f"support_report_{stamp}.txt"

    sections = [
        "GROMOV Restore+ — отчёт для поддержки",
        f"Время: {datetime.now().isoformat(timespec='seconds')}",
        f"Версия приложения: {APP_VERSION}",
        f"Python: {sys.version.split()[0]}",
        f"Windows: {platform.platform()}",
        f"Архитектура: {platform.machine()}",
        f"Пользователь: {os.environ.get('USERNAME', '')}",
        f"Data dir: {data}",
        f"Tools dir: {tools}",
        "",
        f"Apple ID (masked): {apple_id_masked or '—'}",
        f"Драйверы: {driver_status or '—'}",
        f"Устройство: {device_summary or '—'}",
        "",
        f"ipatool: {_tool_version(tools / 'ipatool.exe', '--version')}",
        f"go-ios: {_tool_version(tools / 'ios.exe', 'version')}",
        "",
        "=== ipatool.log (хвост) ===",
        _tail(data / "ipatool.log"),
        "",
        "=== install.log (хвост) ===",
        _tail(data / "install.log"),
    ]
    out.write_text("\n".join(sections), encoding="utf-8")
    return out
