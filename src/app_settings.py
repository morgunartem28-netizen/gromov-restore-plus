"""Persisted user settings (cache retention, recent installs, history)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_dir

DEFAULT_IPA_CACHE_DAYS = 7
ALLOWED_CACHE_DAYS = (3, 7, 30)
DEFAULT_THEME_MODE = "dark"
ALLOWED_THEME_MODES = ("dark",)
RECENT_INSTALL_LIMIT = 10
INSTALL_HISTORY_LIMIT = 30


class AppSettings:
    def __init__(self) -> None:
        self.path = data_dir() / "settings.json"
        self._data = self._load()
        self._lock = threading.RLock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        """Persist settings. Safe to call from UI or bg — serialized by lock."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

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

    @property
    def recent_installs(self) -> list[str]:
        return [item["id"] for item in self.recent_install_records]

    @property
    def recent_install_records(self) -> list[dict[str, str]]:
        """Normalized recent installs: [{id, at}, ...] newest first."""
        raw = self._data.get("recent_installs") or []
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            app_id = ""
            at = ""
            if isinstance(item, str):
                app_id = item.strip()
            elif isinstance(item, dict):
                app_id = str(item.get("id") or "").strip()
                at = str(item.get("at") or "").strip()
            if not app_id or app_id in seen:
                continue
            seen.add(app_id)
            out.append({"id": app_id, "at": at})
        return out[:RECENT_INSTALL_LIMIT]

    def remember_install(self, app_id: str) -> None:
        aid = app_id.strip()
        if not aid:
            return
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        items = [{"id": aid, "at": now}] + [
            rec for rec in self.recent_install_records if rec["id"] != aid
        ]
        self._data["recent_installs"] = items[:RECENT_INSTALL_LIMIT]
        self.save()

    def clear_recent_installs(self) -> None:
        self._data["recent_installs"] = []
        self.save()

    @property
    def install_history(self) -> list[dict]:
        raw = self._data.get("install_history") or []
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            app_id = str(item.get("id") or "").strip()
            if not app_id:
                continue
            out.append(
                {
                    "id": app_id,
                    "at": str(item.get("at") or ""),
                    "result": str(item.get("result") or ""),
                    "error": str(item.get("error") or ""),
                    "title": str(item.get("title") or ""),
                }
            )
        return out[:INSTALL_HISTORY_LIMIT]

    def record_install_result(
        self,
        app_id: str,
        *,
        title: str = "",
        result: str = "ok",
        error: str = "",
    ) -> None:
        aid = app_id.strip()
        if not aid:
            return
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        entry = {
            "id": aid,
            "title": title,
            "at": now,
            "result": result,
            "error": (error or "")[:400],
        }
        items = [entry] + [h for h in self.install_history if h.get("id") != aid or h.get("at") != now]
        self._data["install_history"] = items[:INSTALL_HISTORY_LIMIT]
        if result == "ok":
            self.remember_install(aid)
        else:
            self.save()

    @property
    def theme_mode(self) -> str:
        """Always dark — legacy light/system values migrate on read."""
        value = str(self._data.get("theme_mode", DEFAULT_THEME_MODE) or DEFAULT_THEME_MODE).strip().lower()
        if value != "dark":
            # One-shot migrate stale prefs so settings.json stays coherent.
            self._data["theme_mode"] = "dark"
            try:
                self.save()
            except OSError:
                pass
        return "dark"

    @theme_mode.setter
    def theme_mode(self, mode: str) -> None:
        _ = mode
        self._data["theme_mode"] = "dark"
        self.save()
