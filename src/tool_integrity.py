"""Verify bundled tools against pinned SHA-256 hashes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app_paths import resource_dir, tools_dir

_CHUNK = 1024 * 1024


class ToolIntegrityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_tools_lock() -> dict[str, dict]:
    path = resource_dir() / "config" / "tools_lock.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def verify_bundled_tools(*, strict: bool = True) -> list[str]:
    """Return list of human-readable problems. Raises if strict and critical tools missing/mismatched."""
    lock = load_tools_lock()
    problems: list[str] = []
    root = tools_dir()
    for name, meta in lock.items():
        expected = str((meta or {}).get("sha256") or "").strip().lower()
        path = root / name
        if not path.is_file():
            problems.append(f"Отсутствует {name}")
            continue
        if not expected:
            continue
        actual = _sha256(path)
        if actual != expected:
            problems.append(f"Контрольная сумма не совпала: {name}")
    if strict and problems:
        raise ToolIntegrityError(
            "Проверка инструментов не пройдена:\n- "
            + "\n- ".join(problems)
            + "\n\nПереустановите приложение из официального Setup."
        )
    return problems
