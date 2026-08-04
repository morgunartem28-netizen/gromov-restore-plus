"""Reusable catalog widgets for GROMOV Restore+ — dark liquid-glass heroes."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk
import tkinter as tk

from config_manager import AppEntry
from theme import (
    CARD_PADX,
    CARD_PADY,
    ICON_CARD,
    RADIUS_CARD,
    THEME,
    TYPE_BODY,
    TYPE_CAPTION,
    TYPE_CARD_TITLE,
    TYPE_META,
    TYPE_SECTION,
    TYPE_TITLE,
    glass_frame,
    primary_button,
    secondary_button,
    ui_font,
)
from ui_animations import (
    AnimationRunner,
    DURATION_FAST,
    bind_smooth_hover,
    fade_in_window,
)
from window_effects import apply_glass_window


def section_header(
    parent: ctk.CTkBaseClass,
    *,
    title: str,
    subtitle: str = "",
) -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    pad_bottom = 8 if subtitle else 4
    wrap.pack(fill="x", padx=4, pady=(10, pad_bottom))
    ctk.CTkLabel(
        wrap,
        text=title.upper() if len(title) < 28 else title,
        font=ui_font(TYPE_SECTION, weight="bold"),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            wrap,
            text=subtitle,
            font=ui_font(TYPE_META),
            text_color=THEME["text_secondary"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
    return wrap


def letter_header(parent: ctk.CTkBaseClass, letter: str) -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(fill="x", padx=6, pady=(10, 4))
    ctk.CTkLabel(
        wrap,
        text=letter,
        font=ui_font(TYPE_SECTION, weight="bold"),
        text_color=THEME["accent"],
        anchor="w",
    ).pack(anchor="w")
    rule = ctk.CTkFrame(wrap, fg_color=THEME["glass_border"], height=1)
    rule.pack(fill="x", pady=(6, 0))
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
    category: str = "",
    version: str = "",
    updated: str = "",
    status: str = "",
    action_text: str = "Выбрать",
    anim: AnimationRunner | None = None,
    card_key: str = "",
    is_selected: Callable[[], bool] | None = None,
) -> ctk.CTkFrame:
    """
    Dense app row — readable title / muted meta, Raycast-like packing,
    soft hover / select via AnimationRunner. Catalog height is sacred.
    """
    card = glass_frame(parent, elevated=True)
    card.pack(fill="x", padx=(2, 8), pady=3)
    card.grid_columnconfigure(1, weight=1)
    try:
        card.configure(
            border_width=1,
            border_color=THEME["glass_border"],
            fg_color=THEME["glass_inner"],
            corner_radius=RADIUS_CARD,
        )
    except tk.TclError:
        pass

    pad_y = 8 if compact else CARD_PADY
    icon_size = 36 if compact else ICON_CARD
    icon_radius = 10 if compact else 12

    # Icon well — elevated chip behind glyph / image
    icon_well = ctk.CTkFrame(
        card,
        fg_color=THEME["chip"],
        corner_radius=icon_radius,
        width=icon_size + 8,
        height=icon_size + 8,
    )
    icon_well.grid(row=0, column=0, rowspan=2, padx=(CARD_PADX, 12), pady=pad_y)
    icon_well.grid_propagate(False)
    icon_well.pack_propagate(False)

    if icon is not None:
        if icon_refs is not None:
            icon_refs.append(icon)
        icon_label = ctk.CTkLabel(icon_well, text="", image=icon)
        icon_label.place(relx=0.5, rely=0.5, anchor="center")
    else:
        icon_label = ctk.CTkLabel(
            icon_well,
            text="",
            width=icon_size,
            height=icon_size,
            fg_color=THEME["glass_edge"],
            corner_radius=icon_radius - 4,
        )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")
    card.icon_label = icon_label  # type: ignore[attr-defined]
    card.icon_well = icon_well  # type: ignore[attr-defined]

    text_wrap = ctk.CTkFrame(card, fg_color="transparent")
    text_wrap.grid(row=0, column=1, sticky="ew", pady=(pad_y, 4), padx=(0, 8))

    title_row = ctk.CTkFrame(text_wrap, fg_color="transparent")
    title_row.pack(anchor="w", fill="x")

    ctk.CTkLabel(
        title_row,
        text=title,
        font=ui_font(TYPE_CARD_TITLE if not compact else 14, weight="bold"),
        anchor="w",
        text_color=THEME["silver"],
    ).pack(side="left")

    if badge:
        ctk.CTkLabel(
            title_row,
            text=badge,
            height=22,
            corner_radius=10,
            fg_color=THEME["accent_soft"],
            text_color=THEME["accent"],
            font=ui_font(TYPE_CAPTION, weight="bold"),
            padx=10,
        ).pack(side="left", padx=(10, 0))

    meta_parts = [p for p in (category, version, updated) if p]
    if meta_parts:
        ctk.CTkLabel(
            text_wrap,
            text=" · ".join(meta_parts),
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
    elif subtitle:
        ctk.CTkLabel(
            text_wrap,
            text=subtitle,
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

    if status:
        status_color = THEME["muted"]
        if "✓" in status or "Установлено" in status:
            status_color = THEME.get("success", THEME["accent"])
        elif "ошиб" in status.lower() or "Не удалось" in status:
            status_color = THEME.get("error", "#FF453A")
        elif "обновлен" in status.lower() or "Готово" in status:
            status_color = THEME["accent"]
        ctk.CTkLabel(
            text_wrap,
            text=status,
            font=ui_font(TYPE_CAPTION, weight="bold"),
            text_color=status_color,
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
    elif subtitle and meta_parts:
        ctk.CTkLabel(
            text_wrap,
            text=subtitle,
            font=ui_font(TYPE_CAPTION),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    action_btn = secondary_button(
        card,
        text=action_text,
        width=100 if len(action_text) > 8 else 88,
        height=34,
        command=on_click,
        font=ui_font(12, weight="bold"),
        corner_radius=12,
    )
    action_btn.grid(row=0, column=2, rowspan=2, padx=(0, CARD_PADX), pady=pad_y)

    bind_card_click(card, on_click)

    if anim is not None and card_key:
        selected_fn = is_selected or (lambda: False)
        bind_smooth_hover(
            anim,
            card,
            card_key,
            normal_fg=THEME["glass_inner"],
            hover_fg=THEME["glass_hover"],
            normal_border=THEME["glass_border"],
            hover_border=THEME["glass_border_bright"],
            is_selected=selected_fn,
            duration_ms=DURATION_FAST,
        )

    return card


class CatalogTabBar(ctk.CTkFrame):
    """Dark glass category pills — active uses Apple blue + soft glow edge."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        *,
        values: list[str],
        command: Callable[[str], None],
        selected: str,
        anim: AnimationRunner | None = None,
    ) -> None:
        super().__init__(
            parent,
            fg_color=THEME["glass_outer"],
            corner_radius=16,
            border_width=1,
            border_color=THEME["glass_border"],
        )
        self._command = command
        self._values = list(values)
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._selected = selected if selected in values else (values[0] if values else "")
        self._enabled = True
        self._anim = anim

        self._inner = ctk.CTkFrame(
            self,
            fg_color=THEME["glass_inner"],
            corner_radius=12,
            border_width=1,
            border_color=THEME["glass_edge"],
        )
        self._inner.pack(fill="x", padx=4, pady=4)

        for label in self._values:
            btn = ctk.CTkButton(
                self._inner,
                text=label,
                height=32,
                corner_radius=10,
                border_width=0,
                font=ui_font(12, weight="bold"),
                command=lambda value=label: self._on_click(value),
            )
            btn.pack(side="left", padx=2, pady=3, fill="x", expand=True)
            self._buttons[label] = btn
        self._apply_styles()

    def _on_click(self, value: str) -> None:
        if not self._enabled:
            return
        self.set(value)
        self._command(value)

    def get(self) -> str:
        return self._selected

    def set(self, value: str) -> None:
        if value in self._buttons:
            prev = self._selected
            self._selected = value
            if self._anim is not None and prev != value:
                self._animate_tab_switch(prev, value)
            else:
                self._apply_styles()

    def configure(self, **kwargs: object) -> None:  # type: ignore[override]
        if "state" in kwargs:
            state = str(kwargs.pop("state"))
            self._enabled = state != "disabled"
            self._apply_styles()
        if kwargs:
            super().configure(**kwargs)

    def refresh_theme(self) -> None:
        try:
            self.configure(
                fg_color=THEME["glass_outer"],
                border_color=THEME["glass_border"],
            )
            self._inner.configure(
                fg_color=THEME["glass_inner"],
                border_color=THEME["glass_edge"],
            )
        except tk.TclError:
            pass
        self._apply_styles()

    def _animate_tab_switch(self, prev: str, nxt: str) -> None:
        assert self._anim is not None
        prev_btn = self._buttons.get(prev)
        next_btn = self._buttons.get(nxt)
        self._apply_styles()
        if prev_btn is None or next_btn is None:
            return
        # Soft settle: briefly tween next into accent (from hover/chip)
        self._anim.tween_colors(
            next_btn,
            f"tab:{nxt}",
            from_fg=THEME["glass_hover"],
            to_fg=THEME["accent"],
            from_border=THEME["glass_border"],
            to_border=THEME["accent_glow"],
            duration_ms=DURATION_FAST,
        )

    def _apply_styles(self) -> None:
        for label, btn in self._buttons.items():
            active = label == self._selected
            if not self._enabled:
                btn.configure(
                    state="disabled",
                    fg_color=THEME["chip"],
                    hover_color=THEME["chip"],
                    text_color=THEME["disabled_text"],
                    border_width=0,
                )
                continue
            if active:
                btn.configure(
                    state="normal",
                    fg_color=THEME["accent"],
                    hover_color=THEME["accent_hover"],
                    text_color=THEME["accent_text"],
                    border_width=1,
                    border_color=THEME["accent_glow"],
                )
            else:
                btn.configure(
                    state="normal",
                    fg_color="transparent",
                    hover_color=THEME["glass_hover"],
                    text_color=THEME["text_secondary"],
                    border_width=0,
                )


def catalog_tab_bar(
    parent: ctk.CTkBaseClass,
    *,
    values: list[str],
    command: Callable[[str], None],
    selected: str,
    anim: AnimationRunner | None = None,
) -> CatalogTabBar:
    """Fluent category pills for catalog sections."""
    bar = CatalogTabBar(parent, values=values, command=command, selected=selected, anim=anim)
    bar.pack(fill="x", padx=0, pady=(0, 4))
    return bar


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
    height = 200 + max(len(options), 1) * 80
    dialog.geometry(f"440x{min(height, 460)}")
    dialog.minsize(400, 280)
    dialog.resizable(False, False)
    dialog.transient(master)
    dialog.grab_set()
    dialog.configure(fg_color=THEME["bg"])
    dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
    fade_in_window(dialog)

    card = glass_frame(dialog, elevated=True)
    card.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(
        card,
        text=title,
        font=ui_font(TYPE_TITLE, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
    ).pack(anchor="w", padx=22, pady=(20, 4))

    ctk.CTkLabel(
        card,
        text="Выберите версию для установки",
        font=ui_font(TYPE_META),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w", padx=22, pady=(0, 14))

    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

    def choose(app: AppEntry) -> None:
        dialog.destroy()
        on_select(app)

    for option in options:
        row = ctk.CTkFrame(
            body,
            fg_color=THEME["glass_inner"],
            corner_radius=RADIUS_CARD - 4,
            border_width=1,
            border_color=THEME["glass_border"],
        )
        row.pack(fill="x", pady=6, padx=4)
        row.grid_columnconfigure(1, weight=1)

        if option.icon is not None:
            icon_refs.append(option.icon)
            ctk.CTkLabel(row, text="", image=option.icon).grid(
                row=0, column=0, padx=(16, 14), pady=14
            )

        text = ctk.CTkFrame(row, fg_color="transparent")
        text.grid(row=0, column=1, sticky="ew", pady=14)
        ctk.CTkLabel(
            text,
            text=option.label,
            font=ui_font(TYPE_BODY, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        ).pack(anchor="w")
        if option.hint:
            ctk.CTkLabel(
                text,
                text=option.hint,
                font=ui_font(TYPE_CAPTION),
                text_color=THEME["muted"],
                anchor="w",
            ).pack(anchor="w", pady=(3, 0))

        primary_button(
            row,
            text="Выбрать",
            width=100,
            height=36,
            command=lambda app=option.app: choose(app),
            font=ui_font(12, weight="bold"),
        ).grid(row=0, column=2, padx=(8, 16), pady=14)

        bind_card_click(row, lambda app=option.app: choose(app))

        def _enter(_e: object = None, target: ctk.CTkFrame = row) -> None:
            target.configure(fg_color=THEME["glass_hover"], border_color=THEME["glass_border_bright"])

        def _leave(_e: object = None, target: ctk.CTkFrame = row) -> None:
            target.configure(fg_color=THEME["glass_inner"], border_color=THEME["glass_border"])

        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)

    secondary_button(card, text="Отмена", width=120, command=dialog.destroy).pack(
        anchor="e", padx=22, pady=(6, 18)
    )
    return dialog
