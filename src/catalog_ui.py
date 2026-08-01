"""Reusable catalog widgets for GROMOV Restore+ 1.3.1 redesign."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk
import tkinter as tk

from config_manager import AppEntry
from theme import (
    CARD_PADX,
    CARD_PADY,
    CORNER_RADIUS,
    THEME,
    glass_frame,
    primary_button,
    secondary_button,
    ui_font,
)
from ui_animations import fade_in_window
from window_effects import apply_glass_window


def section_header(
    parent: ctk.CTkBaseClass,
    *,
    title: str,
    subtitle: str = "",
) -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(fill="x", padx=4, pady=(14, 6))
    ctk.CTkLabel(
        wrap,
        text=title,
        font=ui_font(15, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
    ).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            wrap,
            text=subtitle,
            font=ui_font(11),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
    return wrap


def letter_header(parent: ctk.CTkBaseClass, letter: str) -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(fill="x", padx=6, pady=(12, 2))
    ctk.CTkLabel(
        wrap,
        text=letter,
        font=ui_font(13, weight="bold"),
        text_color=THEME["accent"],
        anchor="w",
    ).pack(anchor="w")
    rule = ctk.CTkFrame(wrap, fg_color=THEME["glass_border"], height=1)
    rule.pack(fill="x", pady=(4, 0))
    return wrap


def bind_card_click(widget: tk.Misc, callback: Callable[[], None]) -> None:
    widget.bind("<Button-1>", lambda _e: callback())
    if hasattr(widget, "winfo_children"):
        for child in widget.winfo_children():
            bind_card_click(child, callback)


def catalog_app_card(
    parent: ctk.CTkBaseClass,
    *,
    title: str,
    subtitle: str,
    icon: ctk.CTkImage | None,
    on_click: Callable[[], None],
    badge: str = "",
    icon_refs: list[object] | None = None,
    compact: bool = False,
) -> ctk.CTkFrame:
    card = glass_frame(parent)
    card.pack(fill="x", padx=(0, 8), pady=5)
    card.grid_columnconfigure(1, weight=1)

    pad_y = 12 if compact else CARD_PADY
    icon_size = 40 if compact else 52
    if icon is not None:
        if icon_refs is not None:
            icon_refs.append(icon)
        icon_label = ctk.CTkLabel(card, text="", image=icon)
        icon_label.grid(row=0, column=0, padx=(CARD_PADX, 12), pady=pad_y)
    else:
        icon_label = ctk.CTkLabel(
            card,
            text="",
            width=icon_size,
            height=icon_size,
            fg_color=THEME["chip"],
            corner_radius=14,
        )
        icon_label.grid(row=0, column=0, padx=(CARD_PADX, 12), pady=pad_y)
    card.icon_label = icon_label  # type: ignore[attr-defined]

    text_wrap = ctk.CTkFrame(card, fg_color="transparent")
    text_wrap.grid(row=0, column=1, sticky="ew", pady=pad_y, padx=(0, 8))

    title_row = ctk.CTkFrame(text_wrap, fg_color="transparent")
    title_row.pack(anchor="w", fill="x")

    ctk.CTkLabel(
        title_row,
        text=title,
        font=ui_font(14 if not compact else 13, weight="bold"),
        anchor="w",
        text_color=THEME["silver"],
    ).pack(side="left")

    if badge:
        ctk.CTkLabel(
            title_row,
            text=badge,
            height=20,
            corner_radius=8,
            fg_color=THEME["accent_soft"],
            text_color=THEME["accent"],
            font=ui_font(10, weight="bold"),
            padx=8,
        ).pack(side="left", padx=(8, 0))

    if subtitle:
        ctk.CTkLabel(
            text_wrap,
            text=subtitle,
            font=ui_font(12),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    secondary_button(
        card,
        text="Выбрать",
        width=88,
        height=32,
        command=on_click,
        font=ui_font(12),
    ).grid(row=0, column=2, padx=(0, CARD_PADX), pady=12)

    bind_card_click(card, on_click)
    return card


def catalog_tab_bar(
    parent: ctk.CTkBaseClass,
    *,
    values: list[str],
    command: Callable[[str], None],
    selected: str,
) -> ctk.CTkSegmentedButton:
    """Segmented tabs for catalog sections (only one content pane is built)."""
    bar = ctk.CTkSegmentedButton(
        parent,
        values=values,
        command=command,
        height=34,
        font=ui_font(12, weight="bold"),
        fg_color=THEME["chip"],
        selected_color=THEME["accent"],
        selected_hover_color=THEME["accent_hover"],
        unselected_color=THEME["chip"],
        unselected_hover_color=THEME["glass_hover"],
        text_color=THEME["text"],
        text_color_disabled=THEME["muted"],
    )
    bar.set(selected)
    bar.pack(fill="x", padx=0, pady=(0, 4))
    return bar


def popular_chip(
    parent: ctk.CTkBaseClass,
    *,
    title: str,
    subtitle: str = "",
    icon: ctk.CTkImage | None,
    on_click: Callable[[], None],
    icon_refs: list[object] | None = None,
    accent: str | None = None,
) -> ctk.CTkFrame:
    card = ctk.CTkFrame(
        parent,
        fg_color=THEME["surface_elevated"],
        corner_radius=16,
        border_width=1,
        border_color=THEME["glass_border"],
        width=148,
        height=108,
    )
    card.pack(side="left", padx=(0, 8), pady=2)
    card.pack_propagate(False)

    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=12, pady=10)

    top = ctk.CTkFrame(inner, fg_color="transparent")
    top.pack(fill="x")

    if icon is not None:
        if icon_refs is not None:
            icon_refs.append(icon)
        ctk.CTkLabel(top, text="", image=icon).pack(side="left")
    elif accent:
        badge = ctk.CTkFrame(top, fg_color=accent, corner_radius=12, width=40, height=40)
        badge.pack(side="left")
        badge.pack_propagate(False)
        letter = (title[:1] or "?").upper()
        ctk.CTkLabel(
            badge,
            text=letter,
            font=ui_font(16, weight="bold"),
            text_color="#0A0A0A" if accent.upper() == "#FFDD2D" else "#FFFFFF",
        ).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(
        inner,
        text=title,
        font=ui_font(13, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
    ).pack(anchor="w", pady=(8, 0))
    if subtitle:
        ctk.CTkLabel(
            inner,
            text=subtitle,
            font=ui_font(10),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w")

    bind_card_click(card, on_click)

    def on_enter(_e: object = None) -> None:
        card.configure(fg_color=THEME["glass_hover"], border_color=THEME["glass_border_bright"])

    def on_leave(_e: object = None) -> None:
        card.configure(fg_color=THEME["surface_elevated"], border_color=THEME["glass_border"])

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)
    return card


def horizontal_row(parent: ctk.CTkBaseClass) -> ctk.CTkScrollableFrame:
    row = ctk.CTkScrollableFrame(
        parent,
        fg_color="transparent",
        height=120,
        orientation="horizontal",
        scrollbar_button_color=THEME["glass_border"],
        scrollbar_button_hover_color=THEME["muted"],
    )
    row.pack(fill="x", padx=2, pady=(0, 4))
    return row


class VersionPickerOption:
    __slots__ = ("label", "hint", "app", "icon")

    def __init__(self, label: str, hint: str, app: AppEntry, icon: ctk.CTkImage | None) -> None:
        self.label = label
        self.hint = hint
        self.app = app
        self.icon = icon


def open_version_picker(
    master: ctk.CTk,
    *,
    title: str,
    options: list[VersionPickerOption],
    on_select: Callable[[AppEntry], None],
    icon_refs: list[object],
) -> ctk.CTkToplevel:
    dialog = ctk.CTkToplevel(master)
    dialog.title(title)
    height = 180 + max(len(options), 1) * 72
    dialog.geometry(f"420x{min(height, 420)}")
    dialog.minsize(380, 260)
    dialog.resizable(False, False)
    dialog.transient(master)
    dialog.grab_set()
    dialog.configure(fg_color=THEME["bg"])
    dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
    fade_in_window(dialog)

    card = glass_frame(dialog, elevated=True)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    ctk.CTkLabel(
        card,
        text=title,
        font=ui_font(18, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
    ).pack(anchor="w", padx=18, pady=(16, 4))

    ctk.CTkLabel(
        card,
        text="Выберите версию для установки",
        font=ui_font(12),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w", padx=18, pady=(0, 12))

    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    def choose(app: AppEntry) -> None:
        dialog.destroy()
        on_select(app)

    for option in options:
        row = ctk.CTkFrame(
            body,
            fg_color=THEME["surface"],
            corner_radius=CORNER_RADIUS - 4,
            border_width=1,
            border_color=THEME["glass_border"],
        )
        row.pack(fill="x", pady=5, padx=4)
        row.grid_columnconfigure(1, weight=1)

        if option.icon is not None:
            icon_refs.append(option.icon)
            ctk.CTkLabel(row, text="", image=option.icon).grid(row=0, column=0, padx=(14, 12), pady=12)

        text = ctk.CTkFrame(row, fg_color="transparent")
        text.grid(row=0, column=1, sticky="ew", pady=12)
        ctk.CTkLabel(
            text,
            text=option.label,
            font=ui_font(14, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        ).pack(anchor="w")
        if option.hint:
            ctk.CTkLabel(
                text,
                text=option.hint,
                font=ui_font(11),
                text_color=THEME["muted"],
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))

        primary_button(
            row,
            text="Выбрать",
            width=96,
            height=34,
            command=lambda app=option.app: choose(app),
            font=ui_font(12, weight="bold"),
        ).grid(row=0, column=2, padx=(8, 14), pady=12)

        bind_card_click(row, lambda app=option.app: choose(app))

        def _enter(_e: object = None, target: ctk.CTkFrame = row) -> None:
            target.configure(fg_color=THEME["glass_hover"], border_color=THEME["glass_border_bright"])

        def _leave(_e: object = None, target: ctk.CTkFrame = row) -> None:
            target.configure(fg_color=THEME["surface"], border_color=THEME["glass_border"])

        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)

    secondary_button(card, text="Отмена", width=110, command=dialog.destroy).pack(
        anchor="e", padx=18, pady=(4, 16)
    )
    return dialog
