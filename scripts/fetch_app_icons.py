"""Download official App Store icons for all catalog apps."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "assets" / "icons"
COUNTRIES = ("us", "ru", "kz", "by", "de", "jp")


def load_apps() -> list[dict]:
    apps: list[dict] = []
    for name in ("apps.json", "banking_apps.json"):
        path = ROOT / "config" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        apps.extend(payload.get("apps", []))
    return apps


def lookup_artwork(app_id: int) -> str | None:
    for country in COUNTRIES:
        try:
            url = f"https://itunes.apple.com/lookup?id={app_id}&country={country}"
            data = json.loads(urllib.request.urlopen(url, timeout=15).read())
            results = data.get("results") or []
            if results:
                artwork = results[0].get("artworkUrl512") or results[0].get("artworkUrl100")
                if artwork:
                    return str(artwork)
        except Exception:
            continue
    return None


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[int] = set()
    ok = 0
    fail: list[str] = []

    for app in load_apps():
        app_id = int(app["appId"])
        icon_file = str(app.get("iconFile") or f"{app['id']}.png")
        if not icon_file.endswith(".png"):
            icon_file += ".png"
        target = ICONS_DIR / icon_file

        if app_id in seen and target.exists():
            continue
        seen.add(app_id)

        if target.exists() and target.stat().st_size > 500:
            print(f"SKIP {app['id']} -> {icon_file} (exists)")
            ok += 1
            continue

        artwork = lookup_artwork(app_id)
        if not artwork:
            fail.append(f"{app['id']} ({app_id})")
            print(f"FAIL {app['id']} id={app_id}")
            continue

        try:
            data = urllib.request.urlopen(artwork, timeout=20).read()
            target.write_bytes(data)
            print(f"OK   {app['id']} -> {icon_file} ({len(data)} bytes)")
            ok += 1
        except Exception as exc:
            fail.append(f"{app['id']} ({app_id}): {exc}")
            print(f"FAIL {app['id']} download: {exc}")

    print(f"\nDone: {ok} icons, {len(fail)} failed")
    if fail:
        print("Failed:", ", ".join(fail[:20]))


if __name__ == "__main__":
    main()
