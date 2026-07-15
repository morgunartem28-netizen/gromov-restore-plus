from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "assets" / "icons"

BRAND_URLS: dict[str, str] = {
    "rutube": "https://static.rtbcdn.ru/static/img/favicon-icons/v3/icon_180x180_square.png",
    "vk-music": "https://play-lh.googleusercontent.com/d2SNAmaPXj15ki1N6GGo5RI9iHnUA1A5cWtAJXRsjYHfKWR_OB3dT7qeEKv7kuN5C0oQ=w512-h512-rw",
    "vk-video": "https://play-lh.googleusercontent.com/GntsGclzheXXASOhjSF1lCOPOznM_OARDObiTW_NQZtpYVwPQr_0ARyRyiXB0_OocmI=w512-h512-rw",
    "mts-bank": "https://play-lh.googleusercontent.com/8QZQZQZQZQZQZQZQZQZQZQZQZQZQ=w512-h512-rw",
}

COUNTRIES = ("us", "ru", "kz", "by", "de", "gb", "jp")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def load_apps() -> list[dict]:
    apps: list[dict] = []
    for name in ("apps.json", "banking_apps.json"):
        apps.extend(json.loads((ROOT / "config" / name).read_text(encoding="utf-8")).get("apps", []))
    return apps


def itunes_artwork(app_id: int) -> str | None:
    for country in COUNTRIES:
        try:
            url = f"https://itunes.apple.com/lookup?id={app_id}&country={country}"
            data = json.loads(urllib.request.urlopen(url, timeout=15).read())
            row = (data.get("results") or [{}])[0]
            art = row.get("artworkUrl512") or row.get("artworkUrl100")
            if art:
                return str(art)
        except Exception:
            pass
    return None


def store_page_artwork(app_id: int) -> str | None:
    for country in ("us", "ru", "gb"):
        try:
            page = f"https://apps.apple.com/{country}/app/id{app_id}"
            html = urllib.request.urlopen(urllib.request.Request(page, headers=HEADERS), timeout=20).read().decode(
                "utf-8", "replace"
            )
            match = re.search(r'"artworkUrl512"\s*:\s*"([^"]+)"', html)
            if match:
                return match.group(1).replace("\\u0026", "&")
            match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            if match:
                return match.group(1)
        except Exception:
            pass
    return None


def download(url: str, target: Path) -> bool:
    try:
        data = urllib.request.urlopen(url, timeout=25).read()
        if len(data) < 200:
            return False
        target.write_bytes(data)
        return True
    except Exception:
        return False


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    for app in load_apps():
        app_id = str(app["id"])
        icon_file = str(app.get("iconFile") or f"{app_id}.png")
        target = ICONS / icon_file
        if target.exists() and target.stat().st_size > 800:
            print(f"SKIP {app_id}")
            continue

        sources = []
        if app_id in BRAND_URLS:
            sources.append(BRAND_URLS[app_id])
        if app.get("iconUrl"):
            sources.append(str(app["iconUrl"]))
        art = itunes_artwork(int(app["appId"]))
        if art:
            sources.append(art)
        page_art = store_page_artwork(int(app["appId"]))
        if page_art:
            sources.append(page_art)

        ok = False
        for url in sources:
            if download(url, target):
                print(f"OK   {app_id} <- {url[:70]}")
                ok = True
                break
        if not ok:
            print(f"FAIL {app_id} ({app['appId']})")


if __name__ == "__main__":
    main()
