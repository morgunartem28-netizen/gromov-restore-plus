from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import customtkinter as ctk

from ipatool_client import IpatoolClient, IpatoolError, IpatoolTwoFactorRequired
from theme import CARD_PADX, THEME, glass_frame, primary_button, secondary_button, ui_font
from ui_animations import AnimationRunner, bind_press_feedback, fade_in_window
from window_effects import apply_glass_window

if TYPE_CHECKING:
    from icon_loader import IconLoader


class AppleLoginDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        ipatool: IpatoolClient,
        on_success,
        *,
        icon_loader: IconLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self.ipatool = ipatool
        self.on_success = on_success
        self._anim = AnimationRunner(self)

        self.title("Вход в Apple ID — GROMOV Restore+")
        self.geometry("500x560")
        self.minsize(460, 420)
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=THEME["bg"])
        self.after(50, lambda: apply_glass_window(self, dark=True))
        fade_in_window(self)

        header = glass_frame(self)
        header.pack(fill="x", padx=24, pady=(24, 12))

        if icon_loader:
            logo = icon_loader.get_logo(44)
            if logo:
                self._logo_ref = logo
                ctk.CTkLabel(header, text="", image=logo).pack(side="left", padx=(CARD_PADX, 10), pady=14)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.pack(side="left", fill="x", expand=True, pady=14)

        ctk.CTkLabel(
            title_wrap,
            text="Вход в Apple ID",
            font=ui_font(22, weight="bold"),
            text_color=THEME["silver"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_wrap,
            text="Нужен Apple ID, с которого вы раньше устанавливали приложения.",
            wraplength=360,
            justify="left",
            text_color=THEME["muted"],
            font=ui_font(13),
        ).pack(anchor="w", pady=(6, 0))

        # Scrollable body so fields + long 2FA hints stay reachable on short screens.
        # Solid fg_color — transparent CTkScrollableFrame canvas often mismatches theme.
        body = ctk.CTkScrollableFrame(
            self,
            fg_color=THEME["bg"],
            scrollbar_button_color=THEME["chip"],
            scrollbar_button_hover_color=THEME["glass_hover"],
        )
        body.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        self.email_entry = ctk.CTkEntry(
            body,
            placeholder_text="Email Apple ID",
            height=40,
            corner_radius=12,
            fg_color=THEME["input"],
            border_color=THEME["glass_border"],
            text_color=THEME["silver"],
            font=ui_font(13),
        )
        self.email_entry.pack(fill="x", pady=6)

        self.password_entry = ctk.CTkEntry(
            body,
            placeholder_text="Пароль",
            show="*",
            height=40,
            corner_radius=12,
            fg_color=THEME["input"],
            border_color=THEME["glass_border"],
            text_color=THEME["silver"],
            font=ui_font(13),
        )
        self.password_entry.pack(fill="x", pady=6)

        ctk.CTkLabel(
            body,
            text="Код подтверждения (2FA)",
            font=ui_font(14, weight="bold"),
            text_color=THEME["silver"],
        ).pack(anchor="w", pady=(16, 6))

        self.code_entry = ctk.CTkEntry(
            body,
            placeholder_text="Появится после первого «Войти»",
            height=40,
            corner_radius=12,
            fg_color=THEME["input"],
            border_color=THEME["glass_border"],
            text_color=THEME["silver"],
            font=ui_font(13),
        )
        self.code_entry.pack(fill="x", pady=6)

        self.hint_label = ctk.CTkLabel(
            body,
            text="Введите email и пароль → «Войти». Если нужен код — он придёт на "
            "доверенный iPhone/Mac (или Настройки → Apple ID → Получить код). "
            "При опечатке в пароле код не приходит. Введите 6 цифр сразу и снова «Войти».",
            wraplength=420,
            justify="left",
            text_color=THEME["muted"],
            font=ui_font(12),
        )
        self.hint_label.pack(anchor="w", pady=(10, 10))

        self.status_label = ctk.CTkLabel(
            body,
            text="",
            wraplength=420,
            justify="left",
            font=ui_font(12),
        )
        self.status_label.pack(anchor="w", pady=(0, 8))

        # Pinned footer — primary actions stay reachable without scrolling.
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(4, 20))

        self.login_button = primary_button(
            buttons,
            text="Войти",
            command=self._submit,
            width=130,
            height=42,
        )
        self.login_button.pack(side="right")
        bind_press_feedback(self._anim, self.login_button)

        cancel_btn = secondary_button(buttons, text="Отмена", command=self.destroy, width=110, height=42)
        cancel_btn.pack(side="right", padx=(0, 10))
        bind_press_feedback(self._anim, cancel_btn)

        self.bind("<Return>", lambda _event: self._submit())
        self.email_entry.focus_set()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.configure(text=text, text_color=THEME["error"] if error else THEME["muted"])

    def _submit(self) -> None:
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        code = self.code_entry.get().replace(" ", "").strip()

        if not email or not password:
            self._set_status("Введите email и пароль.", error=True)
            return

        self.login_button.configure(state="disabled")
        self._set_status("Подключение к App Store...")
        # Clear password from the widget immediately; keep a local copy for this attempt / 2FA retry.
        self.password_entry.delete(0, "end")
        self.code_entry.delete(0, "end")

        def worker() -> None:
            nonlocal password
            try:
                result = self.ipatool.auth_login(email, password, auth_code=code or None)
            except IpatoolTwoFactorRequired as exc:
                # Restore password into the field only for the immediate 2FA retry.
                self.after(0, lambda: self.password_entry.insert(0, password))
                self.after(0, lambda m=str(exc): self._set_status(m, error=False))
                self.after(0, lambda: self.code_entry.focus_set())
                self.after(0, lambda: self.login_button.configure(state="normal"))
                return
            except IpatoolError as exc:
                # auth_login already formats most errors; do not re-classify as 2FA.
                message = str(exc).strip() or "Не удалось войти в Apple ID."
                password = ""
                self.after(0, lambda m=message: self._set_status(m, error=True))
                self.after(0, lambda: self.login_button.configure(state="normal"))
                return

            password = ""
            self.after(0, lambda: self._set_status("Вход выполнен."))
            self.after(0, lambda: self.on_success(result, email))
            self.after(0, self.destroy)

        threading.Thread(target=worker, daemon=True).start()
