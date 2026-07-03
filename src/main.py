from __future__ import annotations

import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from app_paths import ensure_app_dirs, install_dir, resource_dir
from config_manager import BANKING_CATEGORY, AppEntry, ConfigManager
from device_installer import DeviceInstaller, DeviceInstallerError
from disk_utils import DiskSpaceError, ensure_download_space
from driver_installer import DriverInstallerError, apple_drivers_installed, install_apple_drivers
from icon_loader import IconLoader
from ipatool_client import IpatoolClient, IpatoolError
from login_dialog import AppleLoginDialog
from theme import THEME, glass_frame, primary_button, secondary_button, ui_font
from update_checker import UpdateCheckError, check_for_updates
from version import APP_VERSION
from window_effects import apply_glass_window


class RestoreIosApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("GROMOV Restore+")
        self.geometry("1040x740")
        self.minsize(900, 660)
        self._set_window_icon()

        self.config_manager = ConfigManager()
        self.icon_loader = IconLoader()
        self.ipatool: IpatoolClient | None = None
        self.device_installer = DeviceInstaller()
        self.selected_app: AppEntry | None = None
        self._worker: threading.Thread | None = None
        self._icon_refs: list[object] = []
        self._app_rows: dict[str, ctk.CTkFrame] = {}
        self._catalog_view = "root"
        self._progress_active = False
        self._progress_anim_id: str | None = None
        self._progress_value = 0.0

        self._build_layout()
        self._refresh_app_list()
        self.after(50, lambda: apply_glass_window(self))
        self.after(200, self._startup_checks)

    def _set_window_icon(self) -> None:
        icon_path = resource_dir() / "assets" / "icon.ico"
        if not icon_path.exists():
            icon_path = install_dir() / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

    def _build_layout(self) -> None:
        self.configure(fg_color=THEME["bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = glass_frame(self, corner_radius=0, fg_color=THEME["glass"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(1, weight=1)

        logo = self.icon_loader.get_logo(52)
        if logo:
            self._icon_refs.append(logo)
            logo_label = ctk.CTkLabel(header, text="", image=logo)
            logo_label.grid(row=0, column=0, rowspan=2, padx=(20, 12), pady=16)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=1, rowspan=2, sticky="w", pady=16)

        title_row = ctk.CTkFrame(title_wrap, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row,
            text="GROMOV ",
            font=ui_font(26, weight="bold"),
            text_color=THEME["silver"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text="Restore+",
            font=ui_font(26, weight="bold"),
            text_color=THEME["accent"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_wrap,
            text="Восстановление приложений App Store на iPhone",
            font=ui_font(13),
            text_color=THEME["muted"],
        ).pack(anchor="w", pady=(4, 0))

        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.grid(row=0, column=2, rowspan=2, padx=(0, 20), pady=16, sticky="e")

        ctk.CTkLabel(
            header_actions,
            text=f"v{APP_VERSION}",
            font=ui_font(12),
            text_color=THEME["muted"],
        ).pack(side="left", padx=(0, 10))

        secondary_button(
            header_actions,
            text="Обновить",
            width=108,
            height=42,
            font=ui_font(13, weight="bold"),
            command=self._check_updates,
        ).pack(side="left", padx=(0, 8))

        primary_button(
            header_actions,
            text="?",
            width=42,
            height=42,
            corner_radius=21,
            font=ui_font(20, weight="bold"),
            command=self._show_help,
        ).pack(side="left")

        sidebar = glass_frame(self, width=290)
        sidebar.grid(row=1, column=0, sticky="nsw", padx=(16, 8), pady=12)
        sidebar.grid_propagate(False)

        self._section_label(sidebar, "Apple ID")
        self.auth_status_label = ctk.CTkLabel(
            sidebar,
            text="Статус: не проверен",
            wraplength=250,
            justify="left",
            text_color=THEME["muted"],
        )
        self.auth_status_label.pack(anchor="w", padx=16, pady=(0, 10))

        self._action_button(sidebar, "Войти в Apple ID", self._login_dialog).pack(fill="x", padx=14, pady=4)
        self._action_button(sidebar, "Проверить вход", self._update_auth_status, secondary=True).pack(
            fill="x", padx=14, pady=4
        )
        self._action_button(sidebar, "Выйти из Apple ID", self._logout, secondary=True).pack(
            fill="x", padx=14, pady=4
        )

        self._section_label(sidebar, "Устройство", top_pad=20)
        self.readiness_label = ctk.CTkLabel(
            sidebar,
            text="Проверка системы...",
            wraplength=250,
            justify="left",
            text_color=THEME["muted"],
        )
        self.readiness_label.pack(anchor="w", padx=16, pady=(0, 10))

        self._action_button(sidebar, "Проверить iPhone", self._check_device).pack(fill="x", padx=14, pady=4)
        self._action_button(sidebar, "Установить драйверы Apple", self._install_drivers, secondary=True).pack(
            fill="x", padx=14, pady=4
        )

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        top_bar = glass_frame(main)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top_bar.grid_columnconfigure(1, weight=1)

        self.selected_icon_label = ctk.CTkLabel(top_bar, text="")
        self.selected_icon_label.grid(row=0, column=0, padx=(16, 10), pady=14)

        info_wrap = ctk.CTkFrame(top_bar, fg_color="transparent")
        info_wrap.grid(row=0, column=1, sticky="w", pady=14)

        self.selected_label = ctk.CTkLabel(
            info_wrap,
            text="Выберите приложение",
            font=ui_font(19, weight="bold"),
            text_color=THEME["silver"],
        )
        self.selected_label.pack(anchor="w")

        self.selected_meta_label = ctk.CTkLabel(
            info_wrap,
            text="Нажмите на карточку в списке ниже",
            text_color=THEME["muted"],
        )
        self.selected_meta_label.pack(anchor="w", pady=(2, 0))

        self.install_button = primary_button(
            top_bar,
            text="Скачать и установить",
            command=self._install_selected,
            width=200,
            height=42,
            font=ui_font(13, weight="bold"),
        )
        self.install_button.grid(row=0, column=2, padx=16, pady=14)

        catalog_nav = ctk.CTkFrame(main, fg_color="transparent")
        catalog_nav.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        catalog_nav.grid_columnconfigure(1, weight=1)

        self.catalog_back_button = secondary_button(
            catalog_nav,
            text="← Назад",
            command=self._open_root_catalog,
            width=110,
            height=32,
        )
        self.catalog_back_button.grid(row=0, column=0, sticky="w")

        self.catalog_path_label = ctk.CTkLabel(
            catalog_nav,
            text="Каталог",
            font=ui_font(15, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        )
        self.catalog_path_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.app_list = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.app_list.grid(row=2, column=0, sticky="nsew")
        self.app_list.grid_columnconfigure(0, weight=1)
        self.app_list.grid_columnconfigure(1, weight=1)

        log_frame = glass_frame(main)
        log_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_frame,
            text="Журнал",
            font=ui_font(13, weight="bold"),
            text_color=THEME["silver"],
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.progress_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        self.progress_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_frame.grid_remove()

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            anchor="w",
            text_color=THEME["muted"],
        )
        self.progress_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            height=14,
            progress_color=THEME["accent"],
            fg_color=THEME["glass_border"],
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew")
        self.progress_bar.set(0)

        self.log_box = ctk.CTkTextbox(
            log_frame,
            height=72,
            fg_color=THEME["log"],
            border_width=1,
            border_color=THEME["glass_border"],
            text_color=THEME["silver"],
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_box.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.log_box.configure(state="disabled")

    def _section_label(self, parent: ctk.CTkFrame, text: str, *, top_pad: int = 12) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            font=ui_font(14, weight="bold"),
            text_color=THEME["silver"],
        ).pack(anchor="w", padx=16, pady=(top_pad, 8))

    def _action_button(
        self,
        parent: ctk.CTkFrame,
        text: str,
        command: Callable[[], None],
        *,
        secondary: bool = False,
    ) -> ctk.CTkButton:
        if secondary:
            return secondary_button(parent, text=text, command=command)
        return primary_button(parent, text=text, command=command)

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _reset_progress(self) -> None:
        self._stop_progress_creep()
        self._progress_value = 0.0
        self.progress_bar.set(0)

    def _set_progress(self, text: str, value: float) -> None:
        self.progress_frame.grid()
        self.progress_label.configure(text=text)
        self._progress_value = max(self._progress_value, min(1.0, value))
        self.progress_bar.set(self._progress_value)

    def _start_progress_creep(self, text: str, *, cap: float = 0.6, step: float = 0.003) -> None:
        self._stop_progress_creep()
        self._progress_active = True
        self.progress_frame.grid()
        self.progress_label.configure(text=text)

        def tick() -> None:
            if not self._progress_active:
                return
            if self._progress_value < cap:
                self._set_progress(text, self._progress_value + step)
            self._progress_anim_id = self.after(300, tick)

        tick()

    def _stop_progress_creep(self) -> None:
        self._progress_active = False
        if self._progress_anim_id is not None:
            self.after_cancel(self._progress_anim_id)
            self._progress_anim_id = None

    def _hide_progress(self) -> None:
        self._stop_progress_creep()
        self._progress_value = 0.0
        self.progress_bar.set(0)
        self.progress_label.configure(text="")
        self.progress_frame.grid_remove()

    def _progress_callback(self) -> Callable[[float, str], None]:
        def callback(value: float, text: str) -> None:
            self.after(0, lambda v=value, t=text: self._set_progress(t, v))

        return callback

    def _collect_readiness(self) -> tuple[str, str, str]:
        driver_line = (
            "Драйверы Apple: установлены"
            if apple_drivers_installed()
            else "Драйверы Apple: не установлены"
        )
        try:
            devices = self.device_installer.list_devices()
            if devices:
                device_name = devices[0]
                if len(device_name) > 42:
                    device_name = device_name[:39] + "..."
                device_line = f"iPhone: {device_name}"
            else:
                device_line = "iPhone: не найден"
        except DeviceInstallerError:
            device_line = "iPhone: не найден"
        return driver_line, device_line, f"{driver_line}\n{device_line}"

    def _refresh_readiness(self, *, log: bool = False) -> None:
        driver_line, device_line, combined = self._collect_readiness()
        self.readiness_label.configure(text=combined)
        if log:
            self._log("--- Проверка системы ---")
            self._log(driver_line)
            self._log(device_line)

    def _startup_checks(self) -> None:
        def task() -> None:
            driver_line, device_line, combined = self._collect_readiness()
            self.after(0, lambda: self.readiness_label.configure(text=combined))
            self.after(0, lambda: self._log("--- Проверка при запуске ---"))
            self.after(0, lambda: self._log(driver_line))
            self.after(0, lambda: self._log(device_line))

            self._try_init_ipatool(show_errors=False)
            if not self.ipatool:
                self.after(0, lambda: self.auth_status_label.configure(text="ipatool не найден"))
                self.after(0, lambda: self._log("Apple ID: ipatool не найден"))
                return

            try:
                info = self.ipatool.auth_info()
                email = info.get("email") or info.get("appleId") or "выполнен вход"
                if isinstance(email, str) and "@" in email:
                    self.config_manager.set_apple_account(email)
                self.after(0, lambda e=email: self.auth_status_label.configure(text=f"Авторизован\n{e}"))
                self.after(0, lambda e=email: self._log(f"Apple ID: {e}"))
            except IpatoolError:
                self.config_manager.set_apple_account(None)
                self.after(0, lambda: self.auth_status_label.configure(text="Не авторизован"))
                self.after(0, lambda: self._log("Apple ID: не авторизован"))

        threading.Thread(target=task, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.install_button.configure(state=state)

    def _run_async(self, task: Callable[[], None]) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Подождите", "Операция уже выполняется.")
            return

        def runner() -> None:
            self._set_busy(True)
            try:
                task()
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(0, self._hide_progress)

        self._worker = threading.Thread(target=runner, daemon=True)
        self._worker.start()

    def _try_init_ipatool(self, show_errors: bool = True) -> None:
        try:
            self.ipatool = IpatoolClient()
        except IpatoolError as exc:
            self.ipatool = None
            if show_errors:
                messagebox.showerror("ipatool", str(exc))

    def _resolve_apple_account_email(self) -> str | None:
        if self.config_manager.apple_account_email:
            return self.config_manager.apple_account_email
        if not self.ipatool:
            return None
        try:
            info = self.ipatool.auth_info()
            email = str(info.get("email") or info.get("appleId") or "").strip()
            if email and "@" in email:
                self.config_manager.set_apple_account(email)
                return email
        except IpatoolError:
            pass
        return None

    def _update_auth_status(self) -> None:
        self._try_init_ipatool(show_errors=False)
        if not self.ipatool:
            self.auth_status_label.configure(text="Статус: ipatool не найден")
            return

        def task() -> None:
            try:
                info = self.ipatool.auth_info()
                email = info.get("email") or info.get("appleId") or "выполнен вход"
                if isinstance(email, str) and "@" in email:
                    self.config_manager.set_apple_account(email)
                self.after(0, lambda e=email: self.auth_status_label.configure(text=f"Авторизован\n{e}"))
                self.after(0, lambda e=email: self._log(f"Apple ID: {e}"))
            except IpatoolError as exc:
                self.config_manager.set_apple_account(None)
                message = str(exc)
                self.after(0, lambda: self.auth_status_label.configure(text="Не авторизован"))
                self.after(0, lambda m=message: self._log(m))

        self._run_async(task)

    def _login_dialog(self) -> None:
        self._try_init_ipatool()
        if not self.ipatool:
            return

        def on_success(result: dict, email: str) -> None:
            self.config_manager.set_apple_account(email)
            self._log(f"Вход выполнен: {email}")
            self.auth_status_label.configure(text=f"Авторизован\n{email}")
            if result:
                self._log(str(result))

        AppleLoginDialog(self, self.ipatool, on_success, icon_loader=self.icon_loader)

    def _logout(self) -> None:
        self._try_init_ipatool()
        if not self.ipatool:
            return

        if not messagebox.askyesno(
            "Выход",
            "Выйти из текущего Apple ID?\n\nПосле выхода можно войти под другим аккаунтом.",
        ):
            return

        def task() -> None:
            try:
                self.ipatool.auth_logout()
                self.config_manager.set_apple_account(None)
                self.after(0, lambda: self.auth_status_label.configure(text="Не авторизован"))
                self.after(0, lambda: self._log("Выход из Apple ID выполнен."))
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Выход",
                        "Вы вышли из Apple ID.\nНажмите «Войти в Apple ID» для входа под другим аккаунтом.",
                    ),
                )
            except IpatoolError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Выход", m))

        self._run_async(task)

    def _check_updates(self) -> None:
        def task() -> None:
            self.after(0, lambda: self._log("Проверка обновлений..."))
            try:
                result = check_for_updates()
            except UpdateCheckError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(f"Обновление: {m}"))
                self.after(0, lambda m=message: messagebox.showwarning("Обновление", m))
                return

            if result.is_up_to_date:
                text = f"У вас актуальная версия ({result.current_version})."
                self.after(0, lambda: self._log(text))
                self.after(0, lambda: messagebox.showinfo("Обновление", text))
                return

            notes = f"\n\n{result.notes}" if result.notes else ""
            prompt = (
                f"Доступна новая версия {result.latest_version}.\n"
                f"Текущая версия: {result.current_version}.{notes}\n\n"
                "Открыть страницу загрузки?"
            )
            self.after(0, lambda: self._log(f"Доступна версия {result.latest_version}."))

            def ask_download() -> None:
                if messagebox.askyesno("Доступно обновление", prompt):
                    if result.setup_url:
                        webbrowser.open(result.setup_url)
                        self._log("Открыта ссылка на установщик.")
                    else:
                        messagebox.showwarning(
                            "Обновление",
                            "Ссылка на установщик не указана в манифесте обновлений.",
                        )

            self.after(0, ask_download)

        self._run_async(task)

    def _open_root_catalog(self) -> None:
        self._catalog_view = "root"
        if self.selected_app and self.selected_app.is_banking:
            self.selected_app = None
            self.selected_label.configure(text="Выберите приложение")
            self.selected_meta_label.configure(text="Нажмите на карточку в списке ниже")
            self.selected_icon_label.configure(image="")
        self._refresh_app_list()

    def _open_banking_folder(self) -> None:
        self._catalog_view = "banking"
        self._refresh_app_list()

    def _bind_click(self, widget: tk.Misc, callback: Callable[[], None]) -> None:
        widget.bind("<Button-1>", lambda _e: callback())
        if hasattr(widget, "winfo_children"):
            for child in widget.winfo_children():
                self._bind_click(child, callback)

    def _bind_card_hover(self, card: ctk.CTkFrame, card_id: str) -> None:
        def on_enter(_event: object) -> None:
            if self.selected_app and self.selected_app.id == card_id:
                return
            card.configure(fg_color=THEME["glass_hover"], border_color=THEME["glass_border_bright"])

        def on_leave(_event: object) -> None:
            if self.selected_app and self.selected_app.id == card_id:
                return
            card.configure(fg_color=THEME["glass"], border_color=THEME["glass_border"])

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

    def _refresh_app_list(self) -> None:
        for child in self.app_list.winfo_children():
            child.destroy()
        self._app_rows.clear()

        if self._catalog_view == "banking":
            self.catalog_back_button.grid()
            self.catalog_path_label.configure(text=BANKING_CATEGORY)
            items = self.config_manager.list_banking_apps()
            index = 0
            for app in items:
                row, col = divmod(index, 2)
                self._create_app_card(app, row, col)
                index += 1
        else:
            self.catalog_back_button.grid_remove()
            self.catalog_path_label.configure(text="Каталог")
            items = sorted(
                self.config_manager.list_general_apps(),
                key=lambda item: item.title.lower(),
            )
            index = 0
            for app in items:
                row, col = divmod(index, 2)
                self._create_app_card(app, row, col)
                index += 1
            row, col = divmod(index, 2)
            self._create_folder_card(BANKING_CATEGORY, row, col)

        if self.selected_app and self.selected_app.id in self._app_rows:
            self._highlight_card(self.selected_app.id)

    def _create_folder_card(self, title: str, row: int, col: int) -> None:
        card = glass_frame(self.app_list)
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 5 if col == 0 else 0), pady=4)
        card.grid_columnconfigure(1, weight=1)
        self._app_rows["__banking_folder__"] = card

        icon_wrap = ctk.CTkFrame(card, fg_color=THEME["accent"], corner_radius=12, width=44, height=44)
        icon_wrap.grid(row=0, column=0, padx=(12, 10), pady=12)
        icon_wrap.grid_propagate(False)
        ctk.CTkLabel(
            icon_wrap,
            text="₽",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=THEME["bg"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        text_wrap = ctk.CTkFrame(card, fg_color="transparent")
        text_wrap.grid(row=0, column=1, sticky="ew", pady=12, padx=(0, 12))

        ctk.CTkLabel(
            text_wrap,
            text=title,
            font=ui_font(15, weight="bold"),
            anchor="w",
            text_color=THEME["silver"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            text_wrap,
            text="Сбер, Т-Банк, ВТБ и другие",
            font=ui_font(12),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self._bind_click(card, self._open_banking_folder)
        self._bind_card_hover(card, "__banking_folder__")

    def _install_drivers(self) -> None:
        if apple_drivers_installed():
            messagebox.showinfo("Драйверы", "Драйверы Apple для iPhone уже установлены.")
            return

        if not messagebox.askyesno(
            "Драйверы Apple",
            "Установить драйверы для подключения iPhone по USB?\n\n"
            "Может потребоваться подтверждение администратора Windows.",
        ):
            return

        def task() -> None:
            try:
                message = install_apple_drivers()
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda: self._refresh_readiness())
                self.after(0, lambda m=message: messagebox.showinfo("Драйверы", m))
            except DriverInstallerError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Драйверы", m))

        self._run_async(task)

    def _create_app_card(self, app: AppEntry, row: int, col: int) -> None:
        card = glass_frame(self.app_list)
        card.grid(
            row=row,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 5, 5 if col == 0 else 0),
            pady=4,
        )
        card.grid_columnconfigure(1, weight=1)
        self._app_rows[app.id] = card

        icon = self.icon_loader.get_app_icon(app, size=44)
        self._icon_refs.append(icon)
        icon_label = ctk.CTkLabel(card, text="", image=icon)
        icon_label.grid(row=0, column=0, padx=(12, 8), pady=10)

        text_wrap = ctk.CTkFrame(card, fg_color="transparent")
        text_wrap.grid(row=0, column=1, sticky="ew", pady=10, padx=(0, 10))

        if app.maskTitle:
            title_line = app.maskTitle
            subtitle = app.description or app.title
        else:
            title_line = app.title
            subtitle = app.description or ""

        ctk.CTkLabel(
            text_wrap,
            text=title_line,
            font=ui_font(14, weight="bold"),
            anchor="w",
            text_color=THEME["silver"],
        ).pack(anchor="w")

        if subtitle and subtitle != title_line:
            ctk.CTkLabel(
                text_wrap,
                text=subtitle,
                font=ui_font(12),
                text_color=THEME["muted"],
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))

        self._bind_click(card, lambda: self._select_app(app))
        self._bind_card_hover(card, app.id)

    def _highlight_card(self, app_id: str) -> None:
        for card_id, row in self._app_rows.items():
            if card_id == app_id:
                row.configure(
                    fg_color=THEME["glass_selected"],
                    border_color=THEME["accent"],
                    border_width=2,
                )
            else:
                row.configure(
                    fg_color=THEME["glass"],
                    border_color=THEME["glass_border"],
                    border_width=1,
                )

    def _select_app(self, app: AppEntry) -> None:
        self.selected_app = app
        if app.maskTitle:
            self.selected_label.configure(text=app.maskTitle)
            self.selected_meta_label.configure(text=app.description or app.title)
        else:
            self.selected_label.configure(text=app.title)
            self.selected_meta_label.configure(text=app.description or "")

        icon = self.icon_loader.get_app_icon(app, size=48)
        self._icon_refs.append(icon)
        self.selected_icon_label.configure(image=icon)

        self._highlight_card(app.id)
        label = app.maskTitle or app.title
        self._log(f"Выбрано: {label}")

    def _show_help(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Помощь — GROMOV Restore+")
        dialog.geometry("420x240")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=THEME["bg"])
        dialog.after(50, lambda: apply_glass_window(dialog))

        if logo := self.icon_loader.get_logo(36):
            self._icon_refs.append(logo)
            ctk.CTkLabel(dialog, text="", image=logo).pack(anchor="w", padx=20, pady=(20, 8))

        ctk.CTkLabel(
            dialog,
            text="По вопросам работы приложения:",
            font=ui_font(15, weight="bold"),
            text_color=THEME["silver"],
        ).pack(anchor="w", padx=20, pady=(0, 8))

        ctk.CTkLabel(
            dialog,
            text="Telegram: @art_gromov",
            font=ui_font(16),
            text_color=THEME["accent"],
        ).pack(anchor="w", padx=20, pady=(0, 16))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=(0, 20))

        primary_button(
            buttons,
            text="Написать в Telegram",
            command=lambda: webbrowser.open("https://t.me/art_gromov"),
        ).pack(side="right")
        secondary_button(buttons, text="Закрыть", command=dialog.destroy).pack(side="right", padx=(0, 8))

    def _check_device(self) -> None:
        def task() -> None:
            try:
                devices = self.device_installer.list_devices()
                if devices:
                    self.after(0, lambda: self._log("Найденные устройства:\n" + "\n".join(devices)))
                else:
                    self.after(0, lambda: self._log("iPhone не найден. Подключите USB и нажмите «Доверять»."))
            except DeviceInstallerError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(m))
            finally:
                self.after(0, lambda: self._refresh_readiness())

        self._run_async(task)

    def _install_selected(self) -> None:
        if not self.selected_app:
            messagebox.showinfo("Установка", "Сначала выберите приложение из списка.")
            return

        self._try_init_ipatool()
        if not self.ipatool:
            return

        app = self.selected_app

        def task() -> None:
            if not self._resolve_apple_account_email():
                self.after(0, lambda: messagebox.showerror("Apple ID", "Сначала войдите в Apple ID."))
                return

            downloads_dir = self.config_manager.account_downloads_dir()
            if downloads_dir is None:
                self.after(0, lambda: messagebox.showerror("Apple ID", "Сначала войдите в Apple ID."))
                return

            progress = self._progress_callback()
            cached = self.config_manager.find_cached_ipa(app.appId, expected_bundle_id=app.bundleId)
            try:
                self.after(0, self._reset_progress)
                self.after(0, lambda: self._set_progress("Подготовка...", 0.05))

                if cached:
                    ipa_path = cached
                    self.after(0, lambda: self._log(f"IPA уже скачан: {ipa_path.name} — пропускаю загрузку"))
                    self.after(0, lambda: self._set_progress("IPA уже скачан, подготовка к установке...", 0.55))
                else:
                    ensure_download_space(downloads_dir)
                    self.after(0, lambda: self._log(f"Скачивание {app.title}..."))
                    self.after(0, lambda: self._start_progress_creep(f"Скачивание {app.title}...", cap=0.25))

                    stop_poll = threading.Event()
                    max_bytes = [0]

                    def poll_download() -> None:
                        while not stop_poll.is_set():
                            candidates = sorted(
                                downloads_dir.glob(f"{app.appId}_*.ipa"),
                                key=lambda path: path.stat().st_mtime,
                                reverse=True,
                            )
                            if candidates:
                                size = candidates[0].stat().st_size
                                max_bytes[0] = max(max_bytes[0], size)
                                size_mb = max_bytes[0] / (1024 * 1024)
                                value = min(0.65, 0.25 + (max_bytes[0] / (850 * 1024 * 1024)) * 0.4)
                                text = f"Скачивание {app.title}... ({size_mb:.0f} МБ)"
                                self.after(0, lambda v=value, t=text: self._set_progress(t, v))
                            time.sleep(0.5)

                    poll_thread = threading.Thread(target=poll_download, daemon=True)
                    poll_thread.start()
                    try:
                        ipa_path = self.ipatool.download(
                            app_id=app.appId,
                            bundle_id=app.bundleId,
                            output_dir=downloads_dir,
                            purchase=True,
                        )
                    finally:
                        stop_poll.set()
                        self.after(0, self._stop_progress_creep)
                        poll_thread.join(timeout=1)

                    self.after(0, lambda p=ipa_path: self._log(f"IPA сохранён: {p}"))
                    self.after(0, lambda: self._set_progress("Скачивание завершено", 0.68))

                self.after(0, lambda: self._log("Установка на iPhone..."))
                message = self.device_installer.install_ipa(
                    ipa_path,
                    on_progress=progress,
                    expected_bundle_id=app.bundleId,
                )
                self.after(0, lambda: self._set_progress("Готово!", 1.0))
                self.after(0, lambda: self._log(message))
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Готово",
                        f"Приложение «{app.title}» установлено.\n\n"
                        "Проверьте домашний экран iPhone.\n"
                        "Если иконки нет — поищите в библиотеке приложений (свайп влево).",
                    ),
                )
                self.after(0, lambda: self._refresh_readiness())
            except DiskSpaceError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Ошибка", m))
            except IpatoolError as exc:
                message = str(exc)
                if "zip not a valid" in message.lower() or "failed to open zip reader" in message.lower() or "повреждён" in message.lower():
                    removed = self.config_manager.remove_cached_ipa(app.appId)
                    if removed:
                        self.after(0, lambda: self._log("Повреждённые файлы скачивания удалены — попробуйте ещё раз."))
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Ошибка", m))
            except DeviceInstallerError as exc:
                message = str(exc)
                if "zip not a valid" in message.lower() or "failed to open zip reader" in message.lower() or "повреждён" in message.lower():
                    removed = self.config_manager.remove_cached_ipa(app.appId)
                    if removed:
                        self.after(0, lambda: self._log("Повреждённый IPA удалён — при следующей попытке скачается заново."))
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Ошибка", m))

        self._run_async(task)


def main() -> None:
    ensure_app_dirs()
    app = RestoreIosApp()
    app.mainloop()


if __name__ == "__main__":
    main()
