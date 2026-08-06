"""Startup crash diagnostics — stdlib only; safe before heavy imports."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def startup_crash_log_path() -> Path:
    """Always LocalAppData — works even if install dir is read-only / broken."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GROMOV" / "RestorePlus"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "GROMOV-RestorePlus"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path(tempfile.gettempdir()) / "gromov_restoreplus_startup_crash.log"
    return base / "startup_crash.log"


def write_startup_crash(exc: BaseException) -> Path:
    path = startup_crash_log_path()
    version = "unknown"
    try:
        from version import APP_VERSION as _ver  # may itself be failing

        version = str(_ver)
    except Exception:
        pass
    lines = [
        f"time={time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"version={version}",
        f"frozen={bool(getattr(sys, 'frozen', False))}",
        f"executable={sys.executable}",
        f"argv={sys.argv!r}",
        f"cwd={os.getcwd()}",
        f"exception={type(exc).__name__}: {exc}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
    return path


def show_startup_crash_dialog(path: Path, exc: BaseException) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "GROMOV Restore+",
            "Не удалось запустить приложение.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Подробности сохранены в:\n{path}\n\n"
            "Отправьте этот файл в Telegram @gromov_restore.",
        )
        root.destroy()
    except Exception:
        pass


def install_startup_excepthook() -> None:
    """PyInstaller console=False hides stderr — persist uncaught errors to disk."""

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]
            return
        path = write_startup_crash(exc)
        show_startup_crash_dialog(path, exc)
        sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]

    sys.excepthook = _hook
