"""Fetch icons via App Store page og:image when iTunes lookup fails."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "assets" / "icons"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def load_apps() -> list[dict]:
    apps: list[dict] = []
    for name in ("apps.json", "banking_apps.json"):
        payload = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        apps.extend(payload.get("apps", []))
    return apps


def fetch_og_image(app_id: int) -> str | None:
    for country in ("us", "ru", "gb", "de"):
        url = f"https://apps.apple.com/{country}/app/id{app_id}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        except Exception:
            continue
        match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'"artworkUrl512"\s*:\s*"([^"]+)"', html)
        if match:
            return match.group(1).replace("\\u0026", "&")
    return None


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for app in load_apps():
        icon_file = str(app.get("iconFile") or f"{app['id']}.png")
        target = ICONS_DIR / icon_file
        if target.exists() and target.stat().st_size > 500:
            print(f"SKIP {app['id']}")
            continue
        app_id = int(app["appId"])
        url = fetch_og_image(app_id)
        if not url:
            print(f"FAIL {app['id']} {app_id}")
            continue
        data = urllib.request.urlopen(url, timeout=20).read()
        target.write_bytes(data)
        print(f"OK   {app['id']} {len(data)} bytes")


if __name__ == "__main__":
    main()
