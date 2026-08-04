"""Windows DPAPI helpers for local secret storage."""
from __future__ import annotations

import sys
from pathlib import Path


class SecretStoreError(OSError):
    """DPAPI protect/unprotect failed — caller should force re-auth."""


def _crypt_protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("DPAPI доступен только на Windows.")
    import ctypes
    import ctypes.wintypes as w

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "GROMOV Restore+",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise SecretStoreError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("DPAPI доступен только на Windows.")
    import ctypes
    import ctypes.wintypes as w

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise SecretStoreError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def save_secret(path: Path, value: str) -> None:
    """Encrypt with DPAPI. Never writes plaintext (Wave C)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.encode("utf-8")
    blob = _crypt_protect(payload)
    path.write_bytes(blob)
    from security_utils import protect_sensitive_file

    protect_sensitive_file(path)


def load_secret(path: Path) -> str | None:
    """Load DPAPI secret. Deletes legacy/plaintext files and returns None."""
    if not path.exists():
        return None
    raw = path.read_bytes()
    # Legacy plaintext markers — wipe and force re-auth (no plaintext fallback).
    if raw.startswith(b"plain:"):
        delete_secret(path)
        return None
    try:
        return _crypt_unprotect(raw).decode("utf-8", errors="replace").strip() or None
    except (OSError, SecretStoreError, ValueError):
        # Unreadable / legacy raw UTF-8: do not return plaintext; wipe.
        delete_secret(path)
        return None


def delete_secret(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
