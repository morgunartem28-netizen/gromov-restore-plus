"""Update action dialogs — extracted from main without behavior change."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from theme import THEME, glass_frame, primary_button, secondary_button, ui_font
from ui_animations import AnimationRunner, bind_press_feedback, fade_in_window
from update_checker import sanitize_update_message
from window_effects import apply_glass_window


def show_update_action_dialog(
    host: ctk.CTk,
    anim: AnimationRunner,
    *,
    title: str,
    message: str,
    primary_text: str,
    on_primary: Callable[[], None] | None = None,
    secondary_text: str = "",
    on_secondary: Callable[[], None] | None = None,
    tertiary_text: str = "Закрыть",
) -> None:
    dialog = ctk.CTkToplevel(host)
    dialog.title(title)
    dialog.geometry("520x400")
    dialog.minsize(460, 300)
    dialog.resizable(False, True)
    dialog.transient(host)
    dialog.grab_set()
    dialog.configure(fg_color=THEME["bg"])
    dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
    fade_in_window(dialog)

    card = glass_frame(dialog, elevated=True)
    card.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(
        card,
        text=title,
        font=ui_font(18, weight="bold"),
        text_color=THEME["text"],
        anchor="w",
    ).pack(anchor="w", padx=18, pady=(16, 8))

    body = ctk.CTkScrollableFrame(
        card,
        fg_color=THEME["bg_soft"],
        corner_radius=12,
        scrollbar_button_color=THEME["chip"],
        scrollbar_button_hover_color=THEME["glass_hover"],
    )
    body.pack(fill="both", expand=True, padx=14, pady=(0, 4))

    ctk.CTkLabel(
        body,
        text=sanitize_update_message(message),
        font=ui_font(13),
        text_color=THEME["text_secondary"],
        justify="left",
        anchor="nw",
        wraplength=430,
    ).pack(anchor="w", fill="x", padx=10, pady=(8, 10))

    buttons = ctk.CTkFrame(card, fg_color="transparent")
    buttons.pack(fill="x", padx=14, pady=(8, 16))

    def close_then(action: Callable[[], None] | None) -> None:
        dialog.destroy()
        if action:
            action()

    primary_btn = primary_button(
        buttons,
        text=primary_text,
        command=lambda: close_then(on_primary),
        width=160,
        height=40,
    )
    primary_btn.pack(side="right")
    bind_press_feedback(anim, primary_btn)

    if secondary_text:
        secondary_button(
            buttons,
            text=secondary_text,
            command=lambda: close_then(on_secondary),
            width=140 if len(secondary_text) <= 14 else 180,
            height=40,
            font=ui_font(12),
        ).pack(side="right", padx=(0, 8))

    if tertiary_text:
        secondary_button(
            buttons,
            text=tertiary_text,
            command=dialog.destroy,
            width=100,
            height=40,
        ).pack(side="left")
