"""Persisted user settings (cache retention, etc.)."""
from __future__ import annotations

import json
from pathlib import Path

from app_paths import data_dir

DEFAULT_IPA_CACHE_DAYS = 7
ALLOWED_CACHE_DAYS = (3, 7, 30)


class AppSettings:
    def __init__(self) -> None:
        self.path = data_dir() / "settings.json"
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def ipa_cache_days(self) -> int:
        value = int(self._data.get("ipa_cache_days", DEFAULT_IPA_CACHE_DAYS) or DEFAULT_IPA_CACHE_DAYS)
        return value if value in ALLOWED_CACHE_DAYS else DEFAULT_IPA_CACHE_DAYS

    @ipa_cache_days.setter
    def ipa_cache_days(self, days: int) -> None:
        if days not in ALLOWED_CACHE_DAYS:
            days = DEFAULT_IPA_CACHE_DAYS
        self._data["ipa_cache_days"] = days
        self.save()

    @property
    def selected_udid(self) -> str | None:
        value = str(self._data.get("selected_udid") or "").strip()
        return value or None

    @selected_udid.setter
    def selected_udid(self, udid: str | None) -> None:
        if udid:
            self._data["selected_udid"] = udid
        else:
            self._data.pop("selected_udid", None)
        self.save()

    @property
    def recent_searches(self) -> list[str]:
        raw = self._data.get("recent_searches") or []
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()][:8]

    def remember_search(self, query: str) -> None:
        q = query.strip()
        if len(q) < 2:
            return
        items = [q] + [item for item in self.recent_searches if item.lower() != q.lower()]
        self._data["recent_searches"] = items[:8]
        self.save()
