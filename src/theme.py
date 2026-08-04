from __future__ import annotations

from typing import Any

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Dark only — commercial graphite Liquid Glass + Apple system blue.
# Depth via layered surfaces (bg → outer mist → inner glass → elevated),
# soft luminous borders, accent glow. Never flat identical gray bricks.
# ---------------------------------------------------------------------------
DARK_THEME: dict[str, Any] = {
    # Atmosphere — deep graphite with cool blue undertone (never pure #000)
    "bg": "#07090E",
    "bg_soft": "#0C1018",
    "bg_gradient_top": "#121822",
    "bg_gradient_bottom": "#07090E",
    "surface": "#121820",
    "surface_elevated": "#1A2230",
    # Type
    "silver": "#F5F5F7",
    "text": "#F5F5F7",
    "text_secondary": "#A8ADB8",
    "muted": "#7E8594",
    # Accent — Apple blue; soft indigo only as glow companion
    "accent": "#0A84FF",
    "accent_hover": "#409CFF",
    "accent_pressed": "#0066CC",
    "accent_end": "#5E5CE6",
    "accent_soft": "#0A1F38",
    "accent_glow": "#1E5A96",
    "accent_text": "#FFFFFF",
    # Status
    "success": "#30D158",
    "success_soft": "#0A1F14",
    "warning": "#FFD60A",
    "warning_soft": "#2A2208",
    "error": "#FF453A",
    "error_soft": "#2A1210",
    # Glass layers (simulated translucency / depth — no fake blur loops)
    "glass": "#141A24",
    "glass_outer": "#0A0E16",
    "glass_inner": "#1A2230",
    "glass_hover": "#243044",
    "glass_selected": "#0C2748",
    "glass_border": "#2A3348",
    "glass_border_bright": "#44516A",
    "glass_highlight": "#2E3C54",
    "glass_edge": "#1E2636",
    "glass_rim": "#161C28",
    # Inputs / chips
    "input": "#0A0E16",
    "input_focus": "#121A28",
    "log": "#080C12",
    "skeleton": "#1E2636",
    "skeleton_shine": "#2A3448",
    "shadow": "#000000",
    "chip": "#1E2636",
    "chip_active": "#0A84FF",
    "chip_active_text": "#FFFFFF",
    "promo": "#0E1420",
    "promo_border": "#243048",
    "promo_hover": "#162030",
    "disabled": "#3A4050",
    "disabled_text": "#6B7280",
    # Install-card state fills
    "card_idle": "#161E2C",
    "card_ready": "#0C2748",
    "card_installing": "#0C2748",
    "card_done": "#0A1F14",
    "card_error": "#2A1210",
}

THEME: dict[str, Any] = dict(DARK_THEME)
_THEME_PREFERENCE = "dark"
_THEME_MODE = "dark"

# Composition scale — usable density (catalog-first, not empty air)
CORNER_RADIUS = 20
CARD_PADX = 16
CARD_PADY = 12
RADIUS_PILL = 999
RADIUS_BUTTON = 14
RADIUS_SEARCH = 18
RADIUS_SHELL = 20
RADIUS_CARD = 16
ICON_CARD = 44
ICON_INSTALL = 48
SIDEBAR_WIDTH = 268

# Typography hierarchy (px)
TYPE_BRAND = 26
TYPE_TITLE = 16
TYPE_SECTION = 11
TYPE_BODY = 14
TYPE_META = 12
TYPE_CAPTION = 11
TYPE_CARD_TITLE = 15


def detect_system_appearance() -> str:
    """Dark-only product — always dark (kept for API compatibility)."""
    return "dark"


def normalize_theme_mode(mode: str | None = None) -> str:
    """Migrate any legacy light/system preference to dark."""
    _ = mode
    return "dark"


def resolve_appearance(mode: str | None = None) -> str:
    _ = mode
    return "dark"


def apply_theme(mode: str | None = None) -> str:
    """Force dark palette. Ignores mode; always returns \"dark\"."""
    global _THEME_MODE, _THEME_PREFERENCE
    _ = mode
    _THEME_PREFERENCE = "dark"
    _THEME_MODE = "dark"
    THEME.clear()
    THEME.update(DARK_THEME)
    return "dark"


def get_theme() -> dict[str, Any]:
    return THEME


def get_theme_mode() -> str:
    """User preference — always dark."""
    return _THEME_PREFERENCE


def get_appearance() -> str:
    """Resolved palette — always dark."""
    return _THEME_MODE


def is_dark_theme() -> bool:
    return True


def theme_pair(key: str) -> tuple[str, str]:
    """(dark, dark) pair — CTK appearance-aware widgets stay dark."""
    color = str(DARK_THEME.get(key, DARK_THEME["accent"]))
    return (color, color)


def accent_fg() -> tuple[str, str] | str:
    """Primary fill — dark accent for both CTK appearance slots."""
    accent = str(DARK_THEME["accent"])
    return (accent, accent)


def accent_gradient_fg() -> tuple[str, str]:
    """
    CTK tuple is (light-mode, dark-mode) — not a CSS gradient.
    Both slots stay Apple blue so Dark appearance never flips to indigo.
    """
    accent = str(DARK_THEME["accent"])
    return (accent, accent)


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    for family in ("Segoe UI Variable", "Segoe UI", "SF Pro Display", "SF Pro Text"):
        try:
            return ctk.CTkFont(family=family, size=size, weight=weight)
        except Exception:
            continue
    return ctk.CTkFont(size=size, weight=weight)


def glass_frame(
    parent: ctk.CTkBaseClass,
    *,
    highlight: bool = False,
    elevated: bool = False,
    **kwargs: Any,
) -> ctk.CTkFrame:
    """Simulated Liquid Glass: graphite fill + soft hairline border."""
    if elevated:
        defaults: dict[str, Any] = {
            "fg_color": THEME["glass_inner"],
            "corner_radius": CORNER_RADIUS,
            "border_width": 1,
            "border_color": THEME["glass_border"],
        }
    else:
        defaults = {
            "fg_color": THEME["glass_selected"] if highlight else THEME["glass"],
            "corner_radius": CORNER_RADIUS,
            "border_width": 1,
            "border_color": THEME["accent"] if highlight else THEME["glass_border"],
        }
    defaults.update(kwargs)
    return ctk.CTkFrame(parent, **defaults)


def glass_shell(
    parent: ctk.CTkBaseClass,
    *,
    elevated: bool = True,
    corner_radius: int | None = None,
    rim: bool = True,
    **kwargs: Any,
) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    """
    Multi-layer glass: outer mist → optional rim hairline → inner graphite.
    Depth via layered fills and highlight edge — no Gaussian blur.
    """
    radius = corner_radius if corner_radius is not None else RADIUS_SHELL
    outer_kwargs = {
        k: v for k, v in kwargs.items() if k not in ("fg_color", "border_color", "border_width")
    }
    outer = ctk.CTkFrame(
        parent,
        fg_color=THEME["glass_outer"],
        corner_radius=radius,
        border_width=1,
        border_color=THEME["glass_border"],
        **outer_kwargs,
    )
    host: ctk.CTkBaseClass = outer
    pad = 3
    if rim:
        rim_frame = ctk.CTkFrame(
            outer,
            fg_color=THEME["glass_rim"],
            corner_radius=max(14, radius - 2),
            border_width=1,
            border_color=THEME["glass_edge"],
        )
        rim_frame.pack(fill="both", expand=True, padx=2, pady=2)
        host = rim_frame
        pad = 2
    inner = ctk.CTkFrame(
        host,
        fg_color=THEME["glass_inner"] if elevated else THEME["glass"],
        corner_radius=max(12, radius - 6),
        border_width=1,
        border_color=THEME["glass_highlight"] if elevated else THEME["glass_edge"],
    )
    inner.pack(fill="both", expand=True, padx=pad, pady=pad)
    return outer, inner


def primary_button(parent: ctk.CTkBaseClass, **kwargs: Any) -> ctk.CTkButton:
    """Premium CTA — solid Apple blue + soft glow edge (CTK has no CSS gradient)."""
    defaults: dict[str, Any] = {
        "fg_color": THEME["accent"],
        "hover_color": THEME["accent_hover"],
        "text_color": THEME["accent_text"],
        "corner_radius": RADIUS_BUTTON,
        "font": ui_font(14, weight="bold"),
        "height": 40,
        "border_width": 1,
        "border_color": THEME["accent_glow"],
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def secondary_button(parent: ctk.CTkBaseClass, **kwargs: Any) -> ctk.CTkButton:
    """Elevated chip — soft border, hover lifts surface."""
    defaults: dict[str, Any] = {
        "fg_color": THEME["chip"],
        "hover_color": THEME["glass_hover"],
        "text_color": THEME["text"],
        "border_width": 1,
        "border_color": THEME["glass_border"],
        "corner_radius": RADIUS_BUTTON,
        "font": ui_font(13, weight="bold"),
        "height": 38,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def ghost_button(parent: ctk.CTkBaseClass, **kwargs: Any) -> ctk.CTkButton:
    """Transparent accent text — soft accent wash on hover."""
    defaults: dict[str, Any] = {
        "fg_color": "transparent",
        "hover_color": THEME["accent_soft"],
        "text_color": THEME["accent"],
        "corner_radius": 14,
        "font": ui_font(13, weight="bold"),
        "height": 38,
        "border_width": 0,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def status_pill(
    parent: ctk.CTkBaseClass,
    text: str,
    *,
    tone: str = "neutral",
) -> ctk.CTkLabel:
    tones = {
        "neutral": (THEME["chip"], THEME["text_secondary"]),
        "ok": (THEME["success_soft"], THEME["success"]),
        "warn": (THEME["warning_soft"], THEME["warning"]),
        "error": (THEME["error_soft"], THEME["error"]),
        "info": (THEME["accent_soft"], THEME["accent"]),
    }
    bg, fg = tones.get(tone, tones["neutral"])
    return ctk.CTkLabel(
        parent,
        text=text,
        fg_color=bg,
        text_color=fg,
        corner_radius=12,
        font=ui_font(TYPE_CAPTION, weight="bold"),
        height=28,
        padx=14,
    )


def empty_state(
    parent: ctk.CTkBaseClass,
    *,
    icon: str = "○",
    title: str,
    hint: str = "",
    action_text: str = "",
    action: object | None = None,
) -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(fill="x", padx=32, pady=64)

    badge = ctk.CTkFrame(wrap, fg_color=THEME["accent_soft"], corner_radius=36, width=72, height=72)
    badge.pack(anchor="w")
    badge.pack_propagate(False)
    ctk.CTkLabel(
        badge,
        text=icon,
        font=ui_font(26, weight="bold"),
        text_color=THEME["accent"],
    ).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(
        wrap,
        text=title,
        font=ui_font(22, weight="bold"),
        text_color=THEME["text"],
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(22, 0))
    if hint:
        ctk.CTkLabel(
            wrap,
            text=hint,
            font=ui_font(TYPE_BODY),
            text_color=THEME["muted"],
            anchor="w",
            justify="left",
            wraplength=480,
        ).pack(anchor="w", pady=(10, 0))
    if action_text and callable(action):
        primary_button(wrap, text=action_text, command=action, width=188).pack(
            anchor="w", pady=(22, 0)
        )
    return wrap


def icon_badge(
    parent: ctk.CTkBaseClass, glyph: str, *, size: int = 52, tone: str = "accent"
) -> ctk.CTkFrame:
    tones = {
        "accent": (THEME["accent_soft"], THEME["accent"]),
        "neutral": (THEME["chip"], THEME["text_secondary"]),
        "success": (THEME["success_soft"], THEME["success"]),
    }
    bg, fg = tones.get(tone, tones["accent"])
    frame = ctk.CTkFrame(parent, fg_color=bg, corner_radius=18, width=size, height=size)
    frame.pack_propagate(False)
    frame.grid_propagate(False)
    ctk.CTkLabel(frame, text=glyph, font=ui_font(int(size * 0.38), weight="bold"), text_color=fg).place(
        relx=0.5, rely=0.5, anchor="center"
    )
    return frame


def theme_mode_label(preference: str | None = None) -> str:
    _ = preference
    return "Тёмная"


def theme_mode_from_label(label: str) -> str:
    _ = label
    return "dark"
