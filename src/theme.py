from __future__ import annotations

import customtkinter as ctk

# 2026: спокойный тёмный UI, много воздуха, один акцент, без «дашборд-шума».
THEME = {
    "bg": "#090A0C",
    "silver": "#F5F6F7",
    "accent": "#3DDC84",
    "accent_hover": "#32C574",
    "accent_text": "#06140C",
    "muted": "#8B93A1",
    "glass": "#12151A",
    "glass_hover": "#1A1E26",
    "glass_selected": "#15231B",
    "glass_border": "#242A33",
    "glass_border_bright": "#3A4350",
    "glass_highlight": "#1B2E22",
    "input": "#0E1116",
    "log": "#0E1116",
    "skeleton": "#15181E",
    "skeleton_shine": "#1E232C",
}

CORNER_RADIUS = 20
CARD_PADX = 18
CARD_PADY = 16


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    # Prefer Windows 11 variable font; fall back cleanly on older systems.
    for family in ("Segoe UI Variable", "Segoe UI"):
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
        "corner_radius": 16,
        "font": ui_font(14, weight="bold"),
        "height": 44,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def secondary_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": "transparent",
        "hover_color": THEME["glass_hover"],
        "text_color": THEME["silver"],
        "border_width": 1,
        "border_color": THEME["glass_border"],
        "corner_radius": 16,
        "font": ui_font(13),
        "height": 40,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def skeleton_card(parent: ctk.CTkBaseClass, *, row: int, col: int) -> ctk.CTkFrame:
    card = ctk.CTkFrame(
        parent,
        fg_color=THEME["skeleton"],
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
    icon = ctk.CTkFrame(card, fg_color=THEME["skeleton_shine"], corner_radius=14, width=48, height=48)
    icon.grid(row=0, column=0, padx=(CARD_PADX, 12), pady=CARD_PADY)
    icon.grid_propagate(False)

    lines = ctk.CTkFrame(card, fg_color="transparent")
    lines.grid(row=0, column=1, sticky="ew", pady=CARD_PADY, padx=(0, CARD_PADX))
    ctk.CTkFrame(lines, fg_color=THEME["skeleton_shine"], corner_radius=6, height=14, width=140).pack(
        anchor="w", pady=(4, 8)
    )
    ctk.CTkFrame(lines, fg_color=THEME["skeleton_shine"], corner_radius=6, height=10, width=100).pack(anchor="w")
    return card


def empty_state(parent: ctk.CTkBaseClass, *, emoji: str, title: str, hint: str = "") -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=36)

    ctk.CTkLabel(wrap, text=emoji, font=ui_font(28)).pack(anchor="w", pady=(0, 10))
    ctk.CTkLabel(
        wrap,
        text=title,
        font=ui_font(18, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
        justify="left",
    ).pack(anchor="w")
    if hint:
        ctk.CTkLabel(
            wrap,
            text=hint,
            font=ui_font(13),
            text_color=THEME["muted"],
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(anchor="w", pady=(8, 0))
    return wrap
