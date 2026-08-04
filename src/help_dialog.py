"""Help dialog for GROMOV Restore+ — dark liquid-glass."""
from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from theme import (
    THEME,
    TYPE_META,
    TYPE_SECTION,
    TYPE_TITLE,
    glass_shell,
    primary_button,
    secondary_button,
    ui_font,
)
from ui_animations import fade_in_window
from version import APP_VERSION
from window_effects import apply_glass_window


def open_help_dialog(
    master: ctk.CTk,
    *,
    support_url: str,
    support_handle: str,
    on_support: Callable[[], None],
    on_report: Callable[[], None] | None = None,
) -> ctk.CTkToplevel:
    dialog = ctk.CTkToplevel(master)
    dialog.title("Помощь — GROMOV Restore+")
    dialog.geometry("540x680")
    dialog.minsize(500, 580)
    dialog.resizable(False, True)
    dialog.transient(master)
    dialog.grab_set()
    dialog.configure(fg_color=THEME["bg"])
    dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
    fade_in_window(dialog)

    outer, card = glass_shell(dialog, elevated=True, corner_radius=26)
    outer.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(
        card,
        text="Помощь",
        font=ui_font(TYPE_TITLE + 2, weight="bold"),
        text_color=THEME["silver"],
        anchor="w",
    ).pack(anchor="w", padx=22, pady=(20, 4))
    ctk.CTkLabel(
        card,
        text=f"GROMOV Restore+ · версия {APP_VERSION}",
        font=ui_font(TYPE_META),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w", padx=22, pady=(0, 12))

    body = ctk.CTkScrollableFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    ctk.CTkLabel(
        body,
        text="Установка через свой Apple ID",
        font=ui_font(15, weight="bold"),
        text_color=THEME["text"],
        anchor="w",
        justify="left",
        wraplength=460,
    ).pack(anchor="w", padx=8, pady=(10, 8))

    ctk.CTkLabel(
        body,
        text=(
            "Чтобы приложения из GROMOV Restore открывались, на iPhone должна быть "
            "ваша учётная запись в разделе «Контент и покупки», и её необходимо "
            "активировать через App Store."
        ),
        font=ui_font(TYPE_META),
        text_color=THEME["text_secondary"],
        anchor="w",
        justify="left",
        wraplength=460,
    ).pack(anchor="w", padx=8, pady=(0, 14))

    ctk.CTkLabel(
        body,
        text="ЧТО НУЖНО СДЕЛАТЬ",
        font=ui_font(TYPE_SECTION, weight="bold"),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w", padx=8, pady=(6, 10))

    steps = [
        "На iPhone откройте: Настройки → [Ваше имя] → Контент и покупки → Выйти",
        "Снова откройте «Контент и покупки» и войдите под своим Apple ID, а не под учётной записью владельца устройства.",
        "Откройте App Store и скачайте любое бесплатное приложение. Это активирует лицензию для вашего Apple ID.",
        "Войдите в GROMOV Restore под тем же Apple ID и установите необходимые приложения.",
        "После завершения установки откройте приложения на iPhone.",
        "При необходимости снова откройте «Контент и покупки» и выйдите из своего Apple ID, чтобы вернуть учётную запись владельца устройства.",
    ]
    for index, step in enumerate(steps, start=1):
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 10))
        badge = ctk.CTkLabel(
            row,
            text=str(index),
            width=28,
            height=28,
            corner_radius=14,
            fg_color=THEME["accent_soft"],
            text_color=THEME["accent"],
            font=ui_font(TYPE_META, weight="bold"),
        )
        badge.pack(side="left", padx=(0, 12), anchor="n")
        ctk.CTkLabel(
            row,
            text=step,
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(side="left", fill="x", expand=True)

    important = ctk.CTkFrame(
        body,
        fg_color=THEME["warning_soft"],
        corner_radius=18,
        border_width=1,
        border_color=THEME["warning"],
    )
    important.pack(fill="x", padx=8, pady=(14, 12))
    ctk.CTkLabel(
        important,
        text="Важно",
        font=ui_font(14, weight="bold"),
        text_color=THEME["warning"],
        anchor="w",
    ).pack(anchor="w", padx=16, pady=(14, 6))
    ctk.CTkLabel(
        important,
        text=(
            "Сначала войдите в «Контент и покупки» и скачайте любое приложение "
            "из App Store.\n\n"
            "Только после этого устанавливайте приложения через GROMOV Restore.\n\n"
            "Иначе приложения могут сразу закрываться после запуска."
        ),
        font=ui_font(TYPE_META),
        text_color=THEME["text_secondary"],
        anchor="w",
        justify="left",
        wraplength=440,
    ).pack(anchor="w", padx=16, pady=(0, 16))

    ctk.CTkLabel(
        body,
        text="ПОДДЕРЖКА",
        font=ui_font(TYPE_SECTION, weight="bold"),
        text_color=THEME["muted"],
        anchor="w",
    ).pack(anchor="w", padx=8, pady=(10, 4))
    ctk.CTkLabel(
        body,
        text=f"Telegram: {support_handle}\n{support_url}",
        font=ui_font(TYPE_META),
        text_color=THEME["muted"],
        anchor="w",
        justify="left",
        wraplength=460,
    ).pack(anchor="w", padx=8, pady=(0, 10))

    buttons = ctk.CTkFrame(card, fg_color="transparent")
    buttons.pack(fill="x", padx=18, pady=(6, 18))
    primary_button(buttons, text="Написать", command=on_support, width=128, height=40).pack(
        side="right"
    )
    if on_report is not None:
        secondary_button(
            buttons, text="Отчёт", command=on_report, width=108, height=40
        ).pack(side="right", padx=(0, 10))
    secondary_button(buttons, text="Закрыть", command=dialog.destroy, width=108, height=40).pack(
        side="left"
    )
    return dialog
