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


# Public GitHub release proxies (verified HEAD 200 for Setup.exe assets).
# Integrity is enforced by SHA256 — mirrors may only wrap a trusted inner URL.
_GITHUB_PROXY_PREFIXES = (
    "https://gh-proxy.com/",
    "https://edgeone.gh-proxy.com/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
)

_REPO_SLUG = "morgunartem28-netizen/gromov-restore-plus"


def unwrap_github_proxy_url(url: str) -> str:
    """If URL is ``https://proxy/https://github.com/...``, return the inner URL."""
    text = (url or "").strip()
    lower = text.lower()
    for prefix in _GITHUB_PROXY_PREFIXES:
        if lower.startswith(prefix):
            inner = text[len(prefix) :]
            if inner.lower().startswith("https://"):
                return inner
    return text


def is_trusted_update_url(url: str) -> bool:
    """Allow only HTTPS URLs on known GitHub release/raw hosts and CDN mirrors.

    Third-party GitHub proxies are allowed only when they wrap a trusted
    ``github.com`` / ``raw.githubusercontent.com`` URL for this repository.
    """
    text = (url or "").strip()
    lower = text.lower()
    if not lower.startswith("https://"):
        return False

    allowed_hosts = (
        "https://github.com/",
        "https://raw.githubusercontent.com/",
        "https://objects.githubusercontent.com/",
        "https://release-assets.githubusercontent.com/",
        # Contents API (uncached) for version.json when raw/CDN lag behind main
        f"https://api.github.com/repos/{_REPO_SLUG}/contents/",
        # jsDelivr mirrors for version.json / static pages (not release .exe assets)
        f"https://cdn.jsdelivr.net/gh/{_REPO_SLUG}",
        f"https://fastly.jsdelivr.net/gh/{_REPO_SLUG}",
        f"https://gcore.jsdelivr.net/gh/{_REPO_SLUG}",
    )
    if any(lower.startswith(host) for host in allowed_hosts):
        return True

    inner = unwrap_github_proxy_url(text)
    if inner == text:
        return False
    inner_lower = inner.lower()
    # Proxies may only forward our GitHub HTTPS assets (releases / raw / objects).
    trusted_inner_prefixes = (
        f"https://github.com/{_REPO_SLUG}/",
        f"https://raw.githubusercontent.com/{_REPO_SLUG}/",
        "https://objects.githubusercontent.com/",
        "https://release-assets.githubusercontent.com/",
    )
    return any(inner_lower.startswith(prefix) for prefix in trusted_inner_prefixes)


def github_release_proxy_prefixes() -> tuple[str, ...]:
    """Prefixes used to build Setup.exe download mirrors (after official GitHub)."""
    return _GITHUB_PROXY_PREFIXES


def repo_slug() -> str:
    return _REPO_SLUG