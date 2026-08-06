from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from app_paths import data_dir, install_dir, resource_dir
from config_manager import AppEntry, BankGroup

logger = logging.getLogger("gromov.icons")

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

_CTK_CACHE_MAX = 128
_PIL_CACHE_MAX = 256
_EXECUTOR_WORKERS = 4


class IconLoader:
    """Loads app icons without blocking the UI thread on disk/PIL I/O.

    CTkImage objects are created on the UI thread via ``schedule`` callbacks.
    Background work uses a shared ThreadPoolExecutor (not unbounded Threads).
    """

    _executor: ThreadPoolExecutor | None = None
    _executor_lock = threading.Lock()

    def __init__(self) -> None:
        self.base_dir = install_dir()
        self.assets_dir = resource_dir() / "assets"
        self.icons_dir = self.assets_dir / "icons"
        self.cache_dir = data_dir() / "icons"
        # Bundled assets may live under Program Files (read-only for users).
        try:
            self.icons_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[str, ctk.CTkImage] = OrderedDict()
        self._pil_cache: OrderedDict[str, Image.Image] = OrderedDict()
        self._lock = threading.RLock()
        self._placeholder_pil: dict[int, Image.Image] = {}

    @classmethod
    def _pool(cls) -> ThreadPoolExecutor:
        with cls._executor_lock:
            if cls._executor is None:
                cls._executor = ThreadPoolExecutor(
                    max_workers=_EXECUTOR_WORKERS,
                    thread_name_prefix="icon-load",
                )
            return cls._executor

    def _to_ctk_image(self, image: Image.Image, size: int) -> ctk.CTkImage:
        return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))

    def _lru_put_ctk(self, key: str, photo: ctk.CTkImage) -> ctk.CTkImage:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            self._cache[key] = photo
            self._cache.move_to_end(key)
            while len(self._cache) > _CTK_CACHE_MAX:
                self._cache.popitem(last=False)
            return photo

    def _lru_put_pil(self, key: str, image: Image.Image) -> Image.Image:
        with self._lock:
            if key in self._pil_cache:
                self._pil_cache.move_to_end(key)
                return self._pil_cache[key]
            self._pil_cache[key] = image
            self._pil_cache.move_to_end(key)
            while len(self._pil_cache) > _PIL_CACHE_MAX:
                self._pil_cache.popitem(last=False)
            return image

    def get_logo(self, size: int = 48) -> ctk.CTkImage | None:
        logo_path = self.assets_dir / "logo.png"
        if not logo_path.exists():
            return None
        key = f"logo:{size}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        image = self._load_resized(logo_path, size)
        photo = self._to_ctk_image(image, size)
        return self._lru_put_ctk(key, photo)

    def get_bank_group_icon(self, group: BankGroup, size: int = 52) -> ctk.CTkImage:
        key = f"bank:{group.id}:{size}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        path = self.cache_dir / f"bank_{group.id}.png"
        if not path.exists():
            self._generate_bank_icon(group, path)

        image = self._load_resized(path, size)
        photo = self._to_ctk_image(image, size)
        return self._lru_put_ctk(key, photo)

    def get_app_icon(self, app: AppEntry, size: int = 52) -> ctk.CTkImage:
        """Sync path — prefer peek + schedule_app_icon on the UI thread."""
        key = f"{app.id}:{size}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        path = self._resolve_icon_path_local(app)
        image = self._load_resized(path, size)
        photo = self._to_ctk_image(image, size)
        return self._lru_put_ctk(key, photo)

    def peek_app_icon(self, app: AppEntry, size: int = 52) -> ctk.CTkImage | None:
        """Return cached CTkImage if already built; else None (no disk I/O)."""
        key = f"{app.id}:{size}"
        with self._lock:
            photo = self._cache.get(key)
            if photo is not None:
                self._cache.move_to_end(key)
            return photo

    def peek_bank_group_icon(self, group: BankGroup, size: int = 52) -> ctk.CTkImage | None:
        key = f"bank:{group.id}:{size}"
        with self._lock:
            photo = self._cache.get(key)
            if photo is not None:
                self._cache.move_to_end(key)
            return photo

    def placeholder_app_icon(self, size: int = 52) -> ctk.CTkImage:
        """Cheap shared placeholder for async icon swap (UI thread)."""
        key = f"placeholder:{size}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        image = self._neutral_placeholder_pil(size)
        photo = self._to_ctk_image(image, size)
        return self._lru_put_ctk(key, photo)

    def schedule_app_icon(
        self,
        app: AppEntry,
        *,
        size: int,
        on_ready: Callable[[ctk.CTkImage], None],
        schedule: Callable[[Callable[[], None]], None],
    ) -> ctk.CTkImage | None:
        """Return cached icon or start background PIL load; CTkImage on UI via schedule."""
        cached = self.peek_app_icon(app, size)
        if cached is not None:
            return cached

        app_id = app.id

        def work() -> None:
            try:
                path = self._resolve_icon_path_local(app)
                image = self._load_resized(path, size)
            except Exception:
                logger.exception("icon load failed for %s", app_id)
                return

            def apply() -> None:
                key = f"{app_id}:{size}"
                with self._lock:
                    existing = self._cache.get(key)
                    if existing is not None:
                        self._cache.move_to_end(key)
                        on_ready(existing)
                        return
                photo = self._to_ctk_image(image, size)
                self._lru_put_ctk(key, photo)
                on_ready(photo)

            schedule(apply)

        self._pool().submit(work)
        return None

    def schedule_bank_group_icon(
        self,
        group: BankGroup,
        *,
        size: int,
        on_ready: Callable[[ctk.CTkImage], None],
        schedule: Callable[[Callable[[], None]], None],
    ) -> ctk.CTkImage | None:
        cached = self.peek_bank_group_icon(group, size)
        if cached is not None:
            return cached

        group_id = group.id

        def work() -> None:
            try:
                path = self.cache_dir / f"bank_{group_id}.png"
                if not path.exists():
                    self._generate_bank_icon(group, path)
                image = self._load_resized(path, size)
            except Exception:
                logger.exception("bank icon load failed for %s", group_id)
                return

            def apply() -> None:
                key = f"bank:{group_id}:{size}"
                with self._lock:
                    existing = self._cache.get(key)
                    if existing is not None:
                        self._cache.move_to_end(key)
                        on_ready(existing)
                        return
                photo = self._to_ctk_image(image, size)
                self._lru_put_ctk(key, photo)
                on_ready(photo)

            schedule(apply)

        self._pool().submit(work)
        return None

    def warm_apps(self, apps: list[AppEntry], *, size: int = 44) -> None:
        """Preload icons into PIL cache (safe from background thread)."""
        for app in apps:
            try:
                path = self._resolve_icon_path_local(app)
                self._load_resized(path, size)
            except OSError:
                continue

    def warm_bank_groups(self, groups: list[BankGroup], *, size: int = 44) -> None:
        for group in groups:
            try:
                path = self.cache_dir / f"bank_{group.id}.png"
                if not path.exists():
                    self._generate_bank_icon(group, path)
                self._load_resized(path, size)
            except OSError:
                continue

    def _neutral_placeholder_pil(self, size: int) -> Image.Image:
        cached = self._placeholder_pil.get(size)
        if cached is not None:
            return cached
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        pad = max(2, size // 12)
        radius = max(4, size // 5)
        draw.rounded_rectangle(
            (pad, pad, size - pad, size - pad),
            radius=radius,
            fill=(60, 60, 68, 255),
        )
        self._placeholder_pil[size] = image
        return image

    def _load_resized(self, path: Path, size: int) -> Image.Image:
        try:
            mtime = path.stat().st_mtime
            resolved = str(path.resolve())
        except OSError:
            mtime = 0.0
            resolved = str(path)
        cache_key = f"{resolved}:{size}:{mtime}"
        with self._lock:
            cached = self._pil_cache.get(cache_key)
            if cached is not None:
                self._pil_cache.move_to_end(cache_key)
                return cached

        image = Image.open(path).convert("RGBA")
        if image.size != (size, size):
            image = image.resize((size, size), Image.Resampling.BILINEAR)
        return self._lru_put_pil(cache_key, image)

    def _bundled_path(self, app: AppEntry) -> Path | None:
        candidates: list[Path] = []
        if app.iconFile:
            candidates.append(self.icons_dir / app.iconFile)
        candidates.append(self.icons_dir / f"{app.id}.png")
        for path in candidates:
            try:
                if path.exists() and path.stat().st_size > 200:
                    return path
            except OSError:
                continue
        return None

    def _resolve_icon_path_local(self, app: AppEntry) -> Path:
        """Resolve icon using only local files — never blocks on network."""
        cached = self.cache_dir / f"{app.id}.png"

        bundled = self._bundled_path(app)
        if bundled is not None:
            return bundled

        try:
            if cached.exists() and cached.stat().st_size > 200:
                return cached
        except OSError:
            pass

        return self._generate_placeholder(app, cached)

    def _generate_bank_icon(self, group: BankGroup, path: Path) -> None:
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
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)

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
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    def _generate_placeholder(self, app: AppEntry, target: Path) -> Path:
        if target.exists() and target.stat().st_size > 200:
            return target

        top, _bottom = self._palette_for(app)
        size = 256
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        radius = 56
        draw.rounded_rectangle((16, 16, size - 16, size - 16), radius=radius, fill=self._hex_to_rgb(top))

        try:
            font = ImageFont.truetype("segoeuib.ttf", 80)
        except OSError:
            try:
                font = ImageFont.truetype("arialbd.ttf", 80)
            except OSError:
                font = ImageFont.load_default()

        text = self._initials(app)
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (size - (bbox[2] - bbox[0])) // 2
        y = (size - (bbox[3] - bbox[1])) // 2 - 6
        draw.text((x, y), text, fill="white", font=font)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG")
        return target
