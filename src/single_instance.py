"""Single-instance guard for Windows (best-effort)."""
from __future__ import annotations

import atexit
import os
import sys

from app_paths import data_dir

_lock_handle = None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _read_lock_pid(lock_path) -> int:
    try:
        text = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
        return int(text) if text.isdigit() else 0
    except (OSError, ValueError):
        return 0


def acquire_single_instance_lock() -> bool:
    """Return False if another instance already holds the lock."""
    global _lock_handle
    lock_path = data_dir() / "app.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        try:
            import msvcrt

            for _attempt in range(2):
                handle = lock_path.open("a+b")
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    handle.close()
                    stale_pid = _read_lock_pid(lock_path)
                    if stale_pid and not _pid_alive(stale_pid):
                        try:
                            lock_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        continue
                    return False

                handle.seek(0)
                handle.truncate()
                handle.write(str(os.getpid()).encode("ascii", "replace"))
                handle.flush()
                _lock_handle = handle

                def _release() -> None:
                    global _lock_handle
                    if _lock_handle is None:
                        return
                    try:
                        _lock_handle.seek(0)
                        msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                    try:
                        _lock_handle.close()
                    except OSError:
                        pass
                    _lock_handle = None
                    try:
                        lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass

                atexit.register(_release)
                return True
            return False
        except OSError:
            # Fail closed: do not allow a second instance if locking is broken.
            return False

    if lock_path.exists():
        stale_pid = _read_lock_pid(lock_path)
        if stale_pid and _pid_alive(stale_pid):
            return False
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            return False
    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(lambda: lock_path.unlink(missing_ok=True))
    except OSError:
        return False
    return True
