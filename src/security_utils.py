"""Security helpers for credential hygiene and safe logging."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def redact_secrets(text: str) -> str:
    """Mask passwords/tokens in log output while keeping structure readable."""
    if not text:
        return text
    redacted = text
    redacted = re.sub(
        r'(?i)("?(?:password|passwd|token|accessToken|refreshToken|access_token|refresh_token|authCode|auth_code|keychainPassphrase|keychain_passphrase)"?\s*[:=]\s*")([^"]*)(")',
        r"\1***\3",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(--(?:password|auth-code|keychain-passphrase)\s+)\S+",
        r"\1***",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(Bearer\s+)[A-Za-z0-9\-._~+/]+=*",
        r"\1***",
        redacted,
    )
    return redacted


def mask_email(email: str) -> str:
    text = (email or "").strip()
    if "@" not in text:
        return text[:1] + "***" if text else ""
    local, _, domain = text.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def sanitize_auth_result_for_log(result: dict | None) -> str:
    if not result:
        return "сессия активна"
    email = result.get("email") or result.get("appleId")
    if isinstance(email, str) and "@" in email:
        return f"сессия активна ({mask_email(email)})"
    if result.get("success") is True:
        return "сессия активна"
    return "сессия активна"


def protect_sensitive_file(path: Path) -> None:
    """Restrict file ACL to the current user on Windows; best-effort elsewhere."""
    try:
        if not path.exists():
            return
        if sys.platform != "win32":
            os.chmod(path, 0o600)
            return
        user = os.environ.get("USERNAME") or os.getlogin()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            check=False,
            capture_output=True,
            creationflags=flags,
        )
    except OSError:
        pass


def protect_sensitive_tree(path: Path) -> None:
    """Restrict a directory (and common secret children) to the current user."""
    try:
        if not path.exists():
            return
        protect_sensitive_file(path)
        if path.is_dir():
            for child_name in ("cookies", "account", "keychain"):
                child = path / child_name
                if child.exists():
                    protect_sensitive_file(child)
    except OSError:
        pass


def is_https_url(url: str) -> bool:
    return url.strip().lower().startswith("https://")


def is_trusted_update_url(url: str) -> bool:
    """Allow only HTTPS URLs on known GitHub release/raw hosts and CDN mirrors."""
    lower = url.strip().lower()
    if not lower.startswith("https://"):
        return False
    allowed_hosts = (
        "https://github.com/",
        "https://raw.githubusercontent.com/",
        "https://objects.githubusercontent.com/",
        "https://release-assets.githubusercontent.com/",
        # jsDelivr mirrors for version.json when raw.githubusercontent.com is blocked
        "https://cdn.jsdelivr.net/gh/morgunartem28-netizen/gromov-restore-plus",
        "https://fastly.jsdelivr.net/gh/morgunartem28-netizen/gromov-restore-plus",
        "https://gcore.jsdelivr.net/gh/morgunartem28-netizen/gromov-restore-plus",
    )
    return any(lower.startswith(host) for host in allowed_hosts)
