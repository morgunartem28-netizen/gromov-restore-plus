"""Relative date helpers for recent installs UI."""
from __future__ import annotations

from datetime import datetime, timezone


def format_relative_install(iso: str, *, now: datetime | None = None) -> str:
    """'Установлено сегодня' / 'вчера' / 'N дней назад' / 'DD.MM.YYYY'."""
    if not iso:
        return "Установлено недавно"
    try:
        raw = iso.replace("Z", "+00:00")
        when = datetime.fromisoformat(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        return f"Установлено · {iso[:10]}"

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = (now.date() - when.astimezone(timezone.utc).date()).days
    if days <= 0:
        return "Установлено сегодня"
    if days == 1:
        return "Установлено вчера"
    if days < 7:
        return f"Установлено {days} дн. назад"
    if days < 30:
        weeks = max(1, days // 7)
        return f"Установлено {weeks} нед. назад"
    return f"Установлено {when.astimezone(timezone.utc).strftime('%d.%m.%Y')}"
