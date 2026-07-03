from __future__ import annotations

import urllib.request
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from app_paths import data_dir, install_dir, resource_dir


from config_manager import AppEntry


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

    def _resolve_icon_path(self, app: AppEntry) -> Path:
        if app.iconFile:
            bundled = self.icons_dir / app.iconFile
            if bundled.exists():
                return bundled

        cached = self.cache_dir / f"{app.id}.png"
        if cached.exists():
            return cached

        if app.iconUrl:
            try:
                data = urllib.request.urlopen(app.iconUrl, timeout=15).read()
                cached.write_bytes(data)
                return cached
            except OSError:
                pass

        if app.iconFile:
            bundled = self.icons_dir / app.iconFile
            if bundled.exists():
                return bundled

        return self._generate_placeholder(app, cached)

    def _generate_placeholder(self, app: AppEntry, target: Path) -> Path:
        colors = {
            "vk": "#2787F5",
            "max": "#5B4BFF",
            "avito": "#00AAFF",
            "mailru": "#FF9E00",
            "sber-family-online": "#21A038",
            "tbank-toastmas": "#FFDD2D",
            "tbank-drive-transit": "#FFDD2D",
            "vtb-sirius": "#002882",
            "alfa-apgreyd": "#EF3124",
            "alfa-holder": "#EF3124",
            "sovcom-skb": "#003791",
            "sovcom-omp": "#003791",
            "gpb-digital-safe": "#2355D7",
        }
        color = colors.get(app.id)
        if not color and app.bankGroup:
            bank_colors = {
                "sber": "#21A038",
                "tbank": "#FFDD2D",
                "vtb": "#002882",
                "alfa": "#EF3124",
                "sovcom": "#003791",
                "gazprom": "#2355D7",
            }
            color = bank_colors.get(app.bankGroup, "#1E4D8C")
        if not color:
            color = "#1E4D8C"
        letter = app.title[:1].upper() if app.title else "?"

        image = Image.new("RGBA", (256, 256), color)
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arialbd.ttf", 110)
        except OSError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), letter, font=font)
        x = (256 - (bbox[2] - bbox[0])) // 2
        y = (256 - (bbox[3] - bbox[1])) // 2 - 8
        draw.text((x, y), letter, fill="white", font=font)
        image.save(target)
        return target
