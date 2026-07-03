from __future__ import annotations

import customtkinter as ctk

# Обновлённая палитра: мягкий тёмный UI + более спокойный зелёный акцент.
THEME = {
    "bg": "#0B0D12",
    "silver": "#F2F4F8",
    "accent": "#32D86B",
    "accent_hover": "#28C45F",
    "accent_text": "#0A0A0A",
    "muted": "#8A94A6",
    "glass": "#171C24",
    "glass_hover": "#202734",
    "glass_selected": "#1D2B22",
    "glass_border": "#2C3645",
    "glass_border_bright": "#415063",
    "glass_highlight": "#243A29",
    "input": "#11161E",
    "log": "#0F131A",
}


def ui_font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def glass_frame(parent: ctk.CTkBaseClass, *, highlight: bool = False, **kwargs) -> ctk.CTkFrame:
    defaults = {
        "fg_color": THEME["glass_selected"] if highlight else THEME["glass"],
        "corner_radius": 16,
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
        "corner_radius": 12,
        "font": ui_font(13, weight="bold"),
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
        "corner_radius": 12,
        "font": ui_font(12),
    }
    defaults.update(kwargs)
    return ctk.CTkButton(parent, **defaults)
