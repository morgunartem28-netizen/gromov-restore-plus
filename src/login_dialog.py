from __future__ import annotations



import threading

from typing import TYPE_CHECKING



import customtkinter as ctk



from ipatool_client import IpatoolClient, IpatoolError, IpatoolTwoFactorRequired

from theme import THEME, glass_frame, primary_button, secondary_button

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



        self.title("Вход в Apple ID — GROMOV Restore+")

        self.geometry("480x500")

        self.resizable(False, False)

        self.transient(parent)

        self.grab_set()

        self.configure(fg_color=THEME["bg"])

        self.after(50, lambda: apply_glass_window(self))



        header = glass_frame(self)

        header.pack(fill="x", padx=20, pady=(20, 12))



        if icon_loader:

            logo = icon_loader.get_logo(40)

            if logo:

                self._logo_ref = logo

                ctk.CTkLabel(header, text="", image=logo).pack(side="left", padx=(14, 8), pady=12)



        title_wrap = ctk.CTkFrame(header, fg_color="transparent")

        title_wrap.pack(side="left", fill="x", expand=True, pady=12)



        ctk.CTkLabel(

            title_wrap,

            text="Вход в Apple ID",

            font=ctk.CTkFont(size=20, weight="bold"),

            text_color=THEME["silver"],

        ).pack(anchor="w")



        ctk.CTkLabel(

            title_wrap,

            text="Нужен Apple ID, с которого вы раньше устанавливали приложения.",

            wraplength=340,

            justify="left",

            text_color=THEME["muted"],

            font=ctk.CTkFont(size=12),

        ).pack(anchor="w", pady=(4, 0))



        self.email_entry = ctk.CTkEntry(

            self,

            placeholder_text="Email Apple ID",

            height=36,

            fg_color=THEME["input"],

            border_color=THEME["glass_border"],

            text_color=THEME["silver"],

        )

        self.email_entry.pack(fill="x", padx=20, pady=4)



        self.password_entry = ctk.CTkEntry(

            self,

            placeholder_text="Пароль",

            show="*",

            height=36,

            fg_color=THEME["input"],

            border_color=THEME["glass_border"],

            text_color=THEME["silver"],

        )

        self.password_entry.pack(fill="x", padx=20, pady=4)



        ctk.CTkLabel(

            self,

            text="Код подтверждения (2FA)",

            font=ctk.CTkFont(weight="bold"),

            text_color=THEME["silver"],

        ).pack(anchor="w", padx=20, pady=(14, 4))



        self.code_entry = ctk.CTkEntry(

            self,

            placeholder_text="6 цифр с iPhone или Mac",

            height=36,

            fg_color=THEME["input"],

            border_color=THEME["glass_border"],

            text_color=THEME["silver"],

        )

        self.code_entry.pack(fill="x", padx=20, pady=4)



        self.hint_label = ctk.CTkLabel(

            self,

            text="1. Введите email и пароль, нажмите «Войти».\n"

            "2. Код придёт на iPhone или Mac.\n"

            "3. Введите код сразу — он действует ~30 секунд.\n"

            "4. Снова нажмите «Войти» (email и пароль остаются).",

            wraplength=420,

            justify="left",

            text_color=THEME["muted"],

        )

        self.hint_label.pack(anchor="w", padx=20, pady=(8, 12))



        self.status_label = ctk.CTkLabel(self, text="", wraplength=420, justify="left")

        self.status_label.pack(anchor="w", padx=20, pady=(0, 8))



        buttons = ctk.CTkFrame(self, fg_color="transparent")

        buttons.pack(fill="x", padx=20, pady=(0, 20))



        self.login_button = primary_button(

            buttons,

            text="Войти",

            command=self._submit,

            width=120,

        )

        self.login_button.pack(side="right")

        secondary_button(buttons, text="Отмена", command=self.destroy).pack(side="right", padx=(0, 8))



        self.bind("<Return>", lambda _event: self._submit())

        self.email_entry.focus_set()



    def _set_status(self, text: str, *, error: bool = False) -> None:

        self.status_label.configure(text=text, text_color=("#CC3333", "#FF6B6B") if error else THEME["muted"])



    def _submit(self) -> None:

        email = self.email_entry.get().strip()

        password = self.password_entry.get()

        code = self.code_entry.get().replace(" ", "").strip()



        if not email or not password:

            self._set_status("Введите email и пароль.", error=True)

            return



        self.login_button.configure(state="disabled")

        self._set_status("Подключение к App Store...")



        def worker() -> None:

            try:

                result = self.ipatool.auth_login(email, password, auth_code=code or None)

            except IpatoolTwoFactorRequired as exc:

                self.after(0, lambda m=str(exc): self._set_status(m, error=False))

                self.after(0, lambda: self.code_entry.focus_set())

                self.after(0, lambda: self.login_button.configure(state="normal"))

                return

            except IpatoolError as exc:

                message = IpatoolClient.format_error(str(exc))

                if IpatoolClient.needs_two_factor(message) and not code:

                    self.after(

                        0,

                        lambda: self._set_status(

                            "Код отправлен на iPhone или Mac.\n"

                            "Введите 6 цифр в поле выше и снова нажмите «Войти».",

                            error=False,

                        ),

                    )

                    self.after(0, lambda: self.code_entry.focus_set())

                else:

                    self.after(0, lambda m=message: self._set_status(m, error=True))

                self.after(0, lambda: self.login_button.configure(state="normal"))

                return



            self.after(0, lambda: self._set_status("Вход выполнен."))

            self.after(0, lambda: self.on_success(result, email))

            self.after(0, self.destroy)



        threading.Thread(target=worker, daemon=True).start()


