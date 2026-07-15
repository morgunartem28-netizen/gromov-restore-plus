from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from app_paths import data_dir, install_dir, resource_dir

from config_manager import AppEntry, BankGroup

ITUNES_COUNTRIES = ("us", "ru", "kz", "by", "de", "jp")

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


class IconLoader:
    def __init__(self) -> None:
        self.base_dir = install_dir()
        self.assets_dir = resource_dir() / "assets"
        self.icons_dir = self.assets_dir / "icons"
        self.cache_dir = data_dir() / "icons"
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, ctk.CTkImage] = {}

    def _to_ctk_image(self, image: Image.Image, size: int) -> ctk.CTkImage:
        return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))

    def get_logo(self, size: int = 48) -> ctk.CTkImage | None:
        logo_path = self.assets_dir / "logo.png"
        if not logo_path.exists():
            return None
        key = f"logo:{size}"
        if key not in self._cache:
            image = Image.open(logo_path).convert("RGBA")
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            self._cache[key] = self._to_ctk_image(image, size)
        return self._cache[key]

    def get_bank_group_icon(self, group: BankGroup, size: int = 52) -> ctk.CTkImage:
        key = f"bank:{group.id}:{size}"
        if key in self._cache:
            return self._cache[key]

        path = self.cache_dir / f"bank_{group.id}.png"
        if not path.exists():
            image = Image.new("RGBA", (256, 256), group.color)
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("arialbd.ttf", 110)
            except OSError:
                font = ImageFont.load_default()
            letter = group.letter
            bbox = draw.textbbox((0, 0), letter, font=font)
            x = (256 - (bbox[2] - bbox[0])) // 2
            y = (256 - (bbox[3] - bbox[1])) // 2 - 8
            text_color = "#0A0A0A" if group.id == "tbank" else "white"
            draw.text((x, y), letter, fill=text_color, font=font)
            image.save(path)

        image = Image.open(path).convert("RGBA")
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        photo = self._to_ctk_image(image, size)
        self._cache[key] = photo
        return photo

    def get_app_icon(self, app: AppEntry, size: int = 52) -> ctk.CTkImage:
        key = f"{app.id}:{size}"
        if key in self._cache:
            return self._cache[key]

        path = self._resolve_icon_path(app)
        image = Image.open(path).convert("RGBA")
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        photo = self._to_ctk_image(image, size)
        self._cache[key] = photo
        return photo

    def _bundled_path(self, app: AppEntry) -> Path | None:
        if not app.iconFile:
            return None
        bundled = self.icons_dir / app.iconFile
        if bundled.exists() and bundled.stat().st_size > 200:
            return bundled
        return None

    def _lookup_itunes_artwork(self, app_id: int) -> str | None:
        for country in ITUNES_COUNTRIES:
            try:
                url = f"https://itunes.apple.com/lookup?id={app_id}&country={country}"
                payload = json.loads(urllib.request.urlopen(url, timeout=15).read())
                results = payload.get("results") or []
                if results:
                    artwork = results[0].get("artworkUrl512") or results[0].get("artworkUrl100")
                    if artwork:
                        return str(artwork)
            except OSError:
                continue
        return None

    def _download_to(self, url: str, target: Path) -> bool:
        try:
            data = urllib.request.urlopen(url, timeout=20).read()
            if len(data) < 200:
                return False
            target.write_bytes(data)
            return True
        except OSError:
            return False

    def _resolve_icon_path(self, app: AppEntry) -> Path:
        cached = self.cache_dir / f"{app.id}.png"

        bundled = self._bundled_path(app)
        if bundled is not None:
            return bundled

        if cached.exists() and cached.stat().st_size > 200:
            return cached

        artwork = self._lookup_itunes_artwork(app.appId)
        if artwork and self._download_to(artwork, cached):
            return cached

        if app.iconUrl and self._download_to(app.iconUrl, cached):
            return cached

        bundled = self._bundled_path(app)
        if bundled is not None:
            return bundled

        return self._generate_placeholder(app, cached)

    @staticmethod
    def _palette_for(app: AppEntry) -> tuple[str, str]:
        digest = hashlib.sha256(f"{app.id}:{app.appId}".encode("utf-8")).hexdigest()
        index = int(digest[:2], 16) % len(PALETTES)
        return PALETTES[index]

    @staticmethod
    def _initials(app: AppEntry) -> str:
        label = (app.maskTitle or app.title or "?").strip()
        parts = [part for part in label.replace("—", " ").replace("-", " ").split() if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            word = parts[0]
            return (word[:2] if len(word) >= 2 else word[:1]).upper()
        return (parts[0][0] + parts[1][0]).upper()

    @staticmethod
    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

    def _generate_placeholder(self, app: AppEntry, target: Path) -> Path:
        top, _bottom = self._palette_for(app)
        size = 512
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        radius = 112
        draw.rounded_rectangle((32, 32, size - 32, size - 32), radius=radius, fill=self._hex_to_rgb(top))
        draw.rounded_rectangle(
            (32, 32, size - 32, size - 32),
            radius=radius,
            outline=(255, 255, 255, 40),
            width=3,
        )

        try:
            font = ImageFont.truetype("segoeuib.ttf", 160)
        except OSError:
            try:
                font = ImageFont.truetype("arialbd.ttf", 160)
            except OSError:
                font = ImageFont.load_default()

        text = self._initials(app)
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (size - (bbox[2] - bbox[0])) // 2
        y = (size - (bbox[3] - bbox[1])) // 2 - 12
        draw.text((x, y), text, fill="white", font=font)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG")
        return target
