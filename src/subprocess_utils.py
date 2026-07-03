from __future__ import annotations

import subprocess
import sys


def _no_window_kwargs() -> dict:
    if sys.platform != "win32":
        return {}

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": flags, "startupinfo": startupinfo}


def run_hidden(*popenargs, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*popenargs, **{**_no_window_kwargs(), **kwargs})


def popen_hidden(*popenargs, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(*popenargs, **{**_no_window_kwargs(), **kwargs})
