from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_FOLDER_NAME = "GROMOV Restore+"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", install_dir()))
    return install_dir()


def data_dir() -> Path:
    """User data always lives in LocalAppData when frozen.

    Independent of install folder (Program Files, D:\\Apps, portable path, etc.),
    so IPA cache / logs / updates never break if the user moves the .exe.
    """
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GROMOV" / "RestorePlus"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return install_dir() / "data"


def tools_dir() -> Path:
    return install_dir() / "tools"


def drivers_dir() -> Path:
    return install_dir() / "drivers"


def ensure_app_dirs() -> None:
    data = data_dir()
    for name in ("downloads", "icons"):
        (data / name).mkdir(parents=True, exist_ok=True)

    user_apps = data / "user_apps.json"
    legacy = install_dir() / "config" / "user_apps.json"
    default_apps = resource_dir() / "config" / "apps.json"
    if not user_apps.exists():
        if legacy.exists():
            shutil.copy(legacy, user_apps)
        elif default_apps.exists():
            shutil.copy(default_apps, user_apps)
