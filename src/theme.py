from __future__ import annotations

import customtkinter as ctk

# Fluent / Windows 11 light — премиальный светлый UI, акцент Apple Blue.
LIGHT_THEME: dict[str, str] = {
    "bg": "#F2F4F8",
    "bg_soft": "#E8ECF2",
    "surface": "#FFFFFF",
    "surface_elevated": "#FFFFFF",
    "silver": "#1C1C1E",  # primary text (legacy key)
    "text": "#1C1C1E",
    "text_secondary": "#636366",
    "muted": "#8E8E93",
    "accent": "#007AFF",
    "accent_hover": "#0066D6",
    "accent_soft": "#E8F2FF",
    "accent_text": "#FFFFFF",
    "success": "#34C759",
    "success_soft": "#E8F8ED",
    "warning": "#FF9F0A",
    "warning_soft": "#FFF6E5",
    "error": "#FF3B30",
    "error_soft": "#FFECEB",
    "glass": "#FFFFFF",
    "glass_hover": "#F5F7FA",
    "glass_selected": "#E8F2FF",
    "glass_border": "#E1E4EA",
    "glass_border_bright": "#B8C0CC",
    "glass_highlight": "#E8F2FF",
    "input": "#F5F6F8",
    "input_focus": "#FFFFFF",
    "log": "#F5F6F8",
    "skeleton": "#EEF0F4",
    "skeleton_shine": "#E0E3EA",
    "shadow": "#D0D5DE",
    "chip": "#EEF1F6",
    "chip_active": "#007AFF",
    "chip_active_text": "#FFFFFF",
}

# Graphite + Apple Blue — согласован с светлой брендовой палитрой.
DARK_THEME: dict[str, str] = {
    "bg": "#0F1115",
    "bg_soft": "#171A21",
    "surface": "#1C1F26",
    "surface_elevated": "#242833",
    "silver": "#F5F5F7",
    "text": "#F5F5F7",
    "text_secondary": "#AEAEB2",
    "muted": "#8E8E93",
    "accent": "#0A84FF",
    "accent_hover": "#409CFF",
    "accent_soft": "#0A2540",
    "accent_text": "#FFFFFF",
    "success": "#30D158",
    "success_soft": "#0F2A1A",
    "warning": "#FFD60A",
    "warning_soft": "#2A2208",
    "error": "#FF453A",
    "error_soft": "#2A1210",
    "glass": "#1C1F26",
    "glass_hover": "#242833",
    "glass_selected": "#0A2540",
    "glass_border": "#2C313C",
    "glass_border_bright": "#3A4050",
    "glass_highlight": "#0A2540",
    "input": "#171A21",
    "input_focus": "#242833",
    "log": "#14161C",
    "skeleton": "#242833",
    "skeleton_shine": "#2C313C",
    "shadow": "#000000",
    "chip": "#242833",
    "chip_active": "#0A84FF",
    "chip_active_text": "#FFFFFF",
}

THEME: dict[str, str] = dict(LIGHT_THEME)
_THEME_MODE = "light"

CORNER_RADIUS = 18
CARD_PADX = 16
CARD_PADY = 14
RADIUS_PILL = 999


def normalize_theme_mode(mode: str | None) -> str:
    return "dark" if str(mode or "").strip().lower() == "dark" else "light"


def apply_theme(mode: str | None) -> str:
    """Switch active palette in-place so all THEME readers see new colors."""
    global _THEME_MODE
    normalized = normalize_theme_mode(mode)
    _THEME_MODE = normalized
    palette = DARK_THEME if normalized == "dark" else LIGHT_THEME
    THEME.clear()
    THEME.update(palette)
    return normalized


def get_theme() -> dict[str, str]:
    return THEME


def get_theme_mode() -> str:
    return _THEME_MODE


def is_dark_theme() -> bool:
    return _THEME_MODE == "dark"


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    for family in ("Segoe UI Variable", "Segoe UI", "SF Pro Display"):
        try:
            return ctk.CTkFont(family=family, size=size, weight=weight)
        except Exception:
            continue
    return ctk.CTkFont(size=size, weight=weight)


def glass_frame(parent: ctk.CTkBaseClass, *, highlight: bool = False, **kwargs) -> ctk.CTkFrame:
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
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def secondary_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": THEME["chip"],
        "hover_color": THEME["bg_soft"],
        "text_color": THEME["text"],
        "border_width": 0,
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
    wrap.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=48)

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
