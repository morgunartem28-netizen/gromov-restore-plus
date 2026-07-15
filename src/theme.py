from __future__ import annotations

import customtkinter as ctk

# Тёплая, воздушная палитра с мягким зелёным акцентом.
THEME = {
    "bg": "#0C0E14",
    "silver": "#F4F6FA",
    "accent": "#3DDB7A",
    "accent_hover": "#34C96E",
    "accent_text": "#0A0F0C",
    "muted": "#9AA3B5",
    "glass": "#181D27",
    "glass_hover": "#222833",
    "glass_selected": "#1E2D24",
    "glass_border": "#2E3848",
    "glass_border_bright": "#465468",
    "glass_highlight": "#2A4532",
    "input": "#121720",
    "log": "#10141C",
    "skeleton": "#1A2030",
    "skeleton_shine": "#242C3C",
}

CORNER_RADIUS = 18
CARD_PADX = 16
CARD_PADY = 14


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


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
        "height": 40,
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)


def secondary_button(parent: ctk.CTkBaseClass, **kwargs) -> ctk.CTkButton:
    defaults = {
        "fg_color": THEME["glass"],
        "hover_color": THEME["glass_hover"],
        "text_color": THEME["silver"],
        "border_width": 1,
        "border_color": THEME["glass_border"],
        "corner_radius": 14,
        "font": ui_font(13),
        "height": 38,
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
        padx=(0 if col == 0 else 6, 6 if col == 0 else 0),
        pady=6,
    )
    icon = ctk.CTkFrame(card, fg_color=THEME["skeleton_shine"], corner_radius=12, width=48, height=48)
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
    wrap.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=28)

    ctk.CTkLabel(wrap, text=emoji, font=ui_font(32)).pack(anchor="w", pady=(0, 8))
    ctk.CTkLabel(
        wrap,
        text=title,
        font=ui_font(16, weight="bold"),
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
        ).pack(anchor="w", pady=(6, 0))
    return wrap
