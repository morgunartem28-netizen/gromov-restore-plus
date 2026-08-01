from __future__ import annotations

import customtkinter as ctk

# Graphite + Apple Blue — dark-only premium palette (2026 refresh).
DARK_THEME: dict[str, str] = {
    "bg": "#0C0E12",
    "bg_soft": "#141820",
    "surface": "#1A1E27",
    "surface_elevated": "#222833",
    "silver": "#F5F5F7",
    "text": "#F5F5F7",
    "text_secondary": "#AEAEB2",
    "muted": "#8E8E93",
    "accent": "#0A84FF",
    "accent_hover": "#409CFF",
    "accent_pressed": "#0066CC",
    "accent_soft": "#0A2540",
    "accent_glow": "#0A84FF",
    "accent_text": "#FFFFFF",
    "success": "#30D158",
    "success_soft": "#0F2A1A",
    "warning": "#FFD60A",
    "warning_soft": "#2A2208",
    "error": "#FF453A",
    "error_soft": "#2A1210",
    "glass": "#1A1E27",
    "glass_hover": "#252B38",
    "glass_selected": "#0A2540",
    "glass_border": "#2E3544",
    "glass_border_bright": "#4A5568",
    "glass_highlight": "#0A2540",
    "input": "#12151C",
    "input_focus": "#1E2430",
    "log": "#10131A",
    "skeleton": "#252B38",
    "skeleton_shine": "#323A4A",
    "shadow": "#000000",
    "chip": "#252B38",
    "chip_active": "#0A84FF",
    "chip_active_text": "#FFFFFF",
    "promo": "#151A24",
    "promo_border": "#2A3344",
    "promo_hover": "#1C2433",
    "disabled": "#3A3F4A",
    "disabled_text": "#6B7080",
}

THEME: dict[str, str] = dict(DARK_THEME)
_THEME_MODE = "dark"

CORNER_RADIUS = 20
CARD_PADX = 18
CARD_PADY = 16
RADIUS_PILL = 999


def normalize_theme_mode(_mode: str | None = None) -> str:
    """Always dark — light mode removed; arg kept for settings migration."""
    return "dark"


def apply_theme(_mode: str | None = None) -> str:
    """Ensure THEME is the dark palette. Mode arg ignored (migration-safe)."""
    global _THEME_MODE
    _THEME_MODE = "dark"
    THEME.clear()
    THEME.update(DARK_THEME)
    return "dark"


def get_theme() -> dict[str, str]:
    return THEME


def get_theme_mode() -> str:
    return "dark"


def is_dark_theme() -> bool:
    return True


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    for family in ("Segoe UI Variable", "Segoe UI", "SF Pro Display"):
        try:
            return ctk.CTkFont(family=family, size=size, weight=weight)
        except Exception:
            continue
    return ctk.CTkFont(size=size, weight=weight)


def glass_frame(parent: ctk.CTkBaseClass, *, highlight: bool = False, elevated: bool = False, **kwargs) -> ctk.CTkFrame:
    if elevated:
        defaults = {
            "fg_color": THEME["surface_elevated"],
            "corner_radius": CORNER_RADIUS,
            "border_width": 1,
            "border_color": THEME["glass_border_bright"],
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


def primary_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": THEME["accent"],
        "hover_color": THEME["accent_hover"],
        "text_color": THEME["accent_text"],
        "corner_radius": 14,
        "font": ui_font(14, weight="bold"),
        "height": 42,
        "border_width": 0,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def secondary_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": THEME["chip"],
        "hover_color": THEME["glass_hover"],
        "text_color": THEME["text"],
        "border_width": 1,
        "border_color": THEME["glass_border"],
        "corner_radius": 14,
        "font": ui_font(13),
        "height": 40,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def ghost_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": "transparent",
        "hover_color": THEME["chip"],
        "text_color": THEME["accent"],
        "corner_radius": 12,
        "font": ui_font(13, weight="bold"),
        "height": 36,
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
        corner_radius=10,
        font=ui_font(11, weight="bold"),
        height=24,
        padx=10,
    )


def skeleton_card(parent: ctk.CTkBaseClass, *, row: int, col: int) -> ctk.CTkFrame:
    card = ctk.CTkFrame(
        parent,
        fg_color=THEME["surface"],
        corner_radius=CORNER_RADIUS,
        border_width=1,
        border_color=THEME["glass_border"],
    )
    card.grid(
        row=row,
        column=col,
        sticky="nsew",
        padx=(0 if col == 0 else 8, 8 if col == 0 else 0),
        pady=8,
    )
    icon = ctk.CTkFrame(card, fg_color=THEME["skeleton"], corner_radius=14, width=52, height=52)
    icon.grid(row=0, column=0, rowspan=2, padx=(CARD_PADX, 12), pady=CARD_PADY)
    icon.grid_propagate(False)

    lines = ctk.CTkFrame(card, fg_color="transparent")
    lines.grid(row=0, column=1, sticky="ew", pady=(CARD_PADY, 4), padx=(0, CARD_PADX))
    ctk.CTkFrame(lines, fg_color=THEME["skeleton_shine"], corner_radius=6, height=14, width=150).pack(
        anchor="w", pady=(6, 8)
    )
    ctk.CTkFrame(lines, fg_color=THEME["skeleton"], corner_radius=6, height=10, width=96).pack(anchor="w")
    return card


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
    wrap.pack(fill="x", padx=24, pady=48)

    badge = ctk.CTkFrame(wrap, fg_color=THEME["accent_soft"], corner_radius=28, width=64, height=64)
    badge.pack(anchor="w")
    badge.pack_propagate(False)
    ctk.CTkLabel(
        badge,
        text=icon,
        font=ui_font(22, weight="bold"),
        text_color=THEME["accent"],
    ).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(
        wrap,
        text=title,
        font=ui_font(20, weight="bold"),
        text_color=THEME["text"],
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(18, 0))
    if hint:
        ctk.CTkLabel(
            wrap,
            text=hint,
            font=ui_font(14),
            text_color=THEME["muted"],
            anchor="w",
            justify="left",
            wraplength=480,
        ).pack(anchor="w", pady=(8, 0))
    if action_text and callable(action):
        primary_button(wrap, text=action_text, command=action, width=180).pack(anchor="w", pady=(18, 0))
    return wrap


def icon_badge(parent: ctk.CTkBaseClass, glyph: str, *, size: int = 48, tone: str = "accent") -> ctk.CTkFrame:
    tones = {
        "accent": (THEME["accent_soft"], THEME["accent"]),
        "neutral": (THEME["chip"], THEME["text_secondary"]),
        "success": (THEME["success_soft"], THEME["success"]),
    }
    bg, fg = tones.get(tone, tones["accent"])
    frame = ctk.CTkFrame(parent, fg_color=bg, corner_radius=14, width=size, height=size)
    frame.pack_propagate(False)
    frame.grid_propagate(False)
    ctk.CTkLabel(frame, text=glyph, font=ui_font(int(size * 0.38), weight="bold"), text_color=fg).place(
        relx=0.5, rely=0.5, anchor="center"
    )
    return frame
