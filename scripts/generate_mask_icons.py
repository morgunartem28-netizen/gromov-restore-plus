"""Generate iOS-style icons for masked apps when App Store artwork is unavailable."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "assets" / "icons"

PALETTES = [
    ("#4F46E5", "#7C3AED"),
    ("#0EA5E9", "#0369A1"),
    ("#10B981", "#047857"),
    ("#F59E0B", "#D97706"),
    ("#EF4444", "#B91C1C"),
    ("#EC4899", "#BE185D"),
    ("#14B8A6", "#0F766E"),
    ("#8B5CF6", "#6D28D9"),
    ("#F97316", "#C2410C"),
    ("#6366F1", "#4338CA"),
]


def load_apps() -> list[dict]:
    apps: list[dict] = []
    for name in ("apps.json", "banking_apps.json"):
        apps.extend(json.loads((ROOT / "config" / name).read_text(encoding="utf-8")).get("apps", []))
    return apps


def palette_for(key: str) -> tuple[str, str]:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    index = int(digest[:2], 16) % len(PALETTES)
    return PALETTES[index]


def initials(app: dict) -> str:
    label = str(app.get("maskTitle") or app.get("title") or "?").strip()
    parts = [part for part in label.replace("—", " ").replace("-", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        word = parts[0]
        return (word[:2] if len(word) >= 2 else word[:1]).upper()
    return (parts[0][0] + parts[1][0]).upper()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def draw_icon(app: dict, target: Path) -> None:
    top, bottom = palette_for(f"{app['id']}:{app['appId']}")
    size = 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = 112
    draw.rounded_rectangle((32, 32, size - 32, size - 32), radius=radius, fill=hex_to_rgb(top))
    draw.rounded_rectangle((32, 32, size - 32, size - 32), radius=radius, outline=(255, 255, 255, 40), width=3)

    try:
        font = ImageFont.truetype("segoeuib.ttf", 160)
    except OSError:
        try:
            font = ImageFont.truetype("arialbd.ttf", 160)
        except OSError:
            font = ImageFont.load_default()

    text = initials(app)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (size - (bbox[2] - bbox[0])) // 2
    y = (size - (bbox[3] - bbox[1])) // 2 - 12
    draw.text((x, y), text, fill="white", font=font)

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")


def main() -> None:
    for app in load_apps():
        icon_file = str(app.get("iconFile") or f"{app['id']}.png")
        target = ICONS / icon_file
        if target.exists() and target.stat().st_size > 800:
            continue
        draw_icon(app, target)
        print(f"GEN {app['id']} -> {icon_file} ({initials(app)})")


if __name__ == "__main__":
    main()
