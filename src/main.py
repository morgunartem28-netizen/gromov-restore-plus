from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from app_paths import data_dir, ensure_app_dirs, install_dir, resource_dir
from app_settings import AppSettings
from config_manager import BANKS_FOLDER_TITLE, BANK_GROUPS, AppEntry, BankGroup, ConfigManager
from device_installer import DeviceInfo, DeviceInstaller, DeviceInstallerError
from disk_utils import DiskSpaceError, ensure_download_space
from driver_installer import DriverInstallerError, apple_drivers_installed, install_apple_drivers
from icon_loader import IconLoader
from install_queue import InstallJob, InstallQueue, JobStatus
from install_service import run_install_job
from ipa_utils import purge_stale_ipa_cache, purge_stale_staging
from ipatool_client import IpatoolCancelled, IpatoolClient, IpatoolError
from login_dialog import AppleLoginDialog
from security_utils import mask_email, sanitize_auth_result_for_log
from support_report import build_support_report
from theme import (
    CARD_PADX,
    CARD_PADY,
    THEME,
    apply_theme,
    empty_state,
    ghost_button,
    glass_frame,
    primary_button,
    secondary_button,
    skeleton_card,
    ui_font,
)
from toast import ToastHost
from tool_integrity import verify_bundled_tools
from ui_animations import (
    AnimationRunner,
    DURATION_FAST,
    SearchDebouncer,
    animate_progress_to,
    bind_press_feedback,
    bind_smooth_hover,
    fade_in_window,
    reveal_card,
)
from update_checker import (
    GITHUB_RELEASES_LATEST,
    UpdateCheckError,
    UpdateCheckResult,
    check_for_updates,
    download_verified_installer,
    resolve_browser_download_url,
    update_debug_log_path,
)
from user_errors import friendly_error
from version import APP_VERSION
from window_effects import apply_glass_window

_INSTALL_PHASES = (
    ("prepare", "Подготовка"),
    ("download", "Скачивание"),
    ("verify", "Проверка"),
    ("transfer", "Передача"),
    ("install", "Установка"),
    ("done", "Готово"),
)


class RestoreIosApp(ctk.CTk):
    def __init__(self) -> None:
        settings = AppSettings()
        apply_theme("dark")

        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("GROMOV Restore+")
        self.geometry("1120x740")
        self.minsize(980, 660)
        self._set_window_icon()

        self.settings = settings
        self.config_manager = ConfigManager()
        self.icon_loader = IconLoader()
        self.ipatool: IpatoolClient | None = None
        self.device_installer = DeviceInstaller()
        self.selected_app: AppEntry | None = None
        self._devices: list[DeviceInfo] = []
        self._selected_udid: str | None = self.settings.selected_udid
        self._last_failed_app: AppEntry | None = None
        self._worker: threading.Thread | None = None
        self._icon_refs: list[object] = []
        self._app_rows: dict[str, ctk.CTkFrame] = {}
        self._catalog_view = "root"
        self._catalog_bank_group: str | None = None
        self._bank_search_query = ""
        self._global_search_query = ""
        self._catalog_state_path = data_dir() / "catalog_state.json"
        self._catalog_ready = False
        self._catalog_anim_token = 0
        self._progress_active = False
        self._progress_anim_id: str | None = None
        self._progress_value = 0.0
        self._phase_labels: dict[str, ctk.CTkLabel] = {}
        self._phase_order = [key for key, _ in _INSTALL_PHASES]
        self._anim = AnimationRunner(self)
        self._search_debouncer = SearchDebouncer(self, delay_ms=250, callback=self._apply_bank_search)
        self._log_visible = False
        self._version_click_count = 0
        self._toasts: ToastHost | None = None
        self._last_setup_url: str | None = None
        self._install_queue = InstallQueue(
            worker=self._queue_worker,
            on_changed=lambda: self.after(0, self._refresh_queue_ui),
            on_cancel_request=self._cancel_tools,
        )
        self._install_queue.progress_hook = self._queue_progress_hook
        self._queue_seen: dict[str, str] = {}

        self._build_layout()
        self._toasts = ToastHost(self)
        self._restore_catalog_state()
        self._refresh_app_list()
        self._render_recent_searches()
        self.after(50, lambda: apply_glass_window(self, dark=True))
        self.after(200, self._startup_checks)
        self.after(300, self._warm_icon_cache)
        self.after(400, self._purge_stale_caches)
        self.after(800, self._first_run_driver_nudge)

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
        self._header = header

        logo = self.icon_loader.get_logo(52)
        if logo:
            self._icon_refs.append(logo)
            logo_label = ctk.CTkLabel(header, text="", image=logo)
            logo_label.grid(row=0, column=0, rowspan=2, padx=(20, 12), pady=16)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=1, rowspan=2, sticky="w", pady=16)

        title_row = ctk.CTkFrame(title_wrap, fg_color="transparent")
        title_row.pack(anchor="w")

        brand = ctk.CTkLabel(
            title_row,
            text="GROMOV ",
            font=ui_font(26, weight="bold"),
            text_color=THEME["silver"],
        )
        brand.pack(side="left")

        product = ctk.CTkLabel(
            title_row,
            text="Restore+",
            font=ui_font(26, weight="bold"),
            text_color=THEME["accent"],
        )
        product.pack(side="left")

        tagline = ctk.CTkLabel(
            title_wrap,
            text="Приложения из вашего Apple ID — снова на iPhone",
            font=ui_font(13),
            text_color=THEME["muted"],
        )
        tagline.pack(anchor="w", pady=(6, 0))

        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.grid(row=0, column=2, rowspan=2, padx=(0, 20), pady=16, sticky="e")

        self.version_label = ctk.CTkLabel(
            header_actions,
            text=f"v{APP_VERSION}",
            font=ui_font(12),
            text_color=THEME["muted"],
            cursor="hand2",
        )
        self.version_label.pack(side="left", padx=(0, 10))
        self.version_label.bind("<Button-1>", self._on_version_click)

        self.update_button = secondary_button(
            header_actions,
            text="Обновить",
            width=108,
            height=42,
            font=ui_font(13, weight="bold"),
            command=self._check_updates,
        )
        self.update_button.pack(side="left", padx=(0, 8))

        self.help_button = primary_button(
            header_actions,
            text="?",
            width=42,
            height=42,
            corner_radius=21,
            font=ui_font(20, weight="bold"),
            command=self._show_help,
        )
        self.help_button.pack(side="left")

        sidebar = glass_frame(self, width=290)
        sidebar.grid(row=1, column=0, sticky="nsw", padx=(16, 8), pady=12)
        sidebar.grid_propagate(False)
        self._sidebar = sidebar

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
        main.grid_rowconfigure(3, weight=1)

        top_bar = glass_frame(main)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top_bar.grid_columnconfigure(1, weight=1)
        self._top_bar = top_bar

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
            text="Установить",
            command=self._install_selected,
            width=168,
            height=44,
            font=ui_font(14, weight="bold"),
        )
        self.install_button.grid(row=0, column=2, padx=(8, 18), pady=16)
        bind_press_feedback(self._anim, self.install_button)

        catalog_nav = ctk.CTkFrame(main, fg_color="transparent")
        catalog_nav.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        catalog_nav.grid_columnconfigure(2, weight=1)

        self.catalog_back_button = secondary_button(
            catalog_nav,
            text="← Назад",
            command=self._catalog_back,
            width=110,
            height=32,
        )
        self.catalog_back_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.catalog_path_label = ctk.CTkLabel(
            catalog_nav,
            text="Каталог",
            font=ui_font(15, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        )
        self.catalog_path_label.grid(row=0, column=1, sticky="w", padx=(0, 12))

        self.bank_search_var = tk.StringVar()
        self.bank_search_entry = ctk.CTkEntry(
            catalog_nav,
            textvariable=self.bank_search_var,
            placeholder_text="Поиск по каталогу и банкам...",
            height=36,
            corner_radius=12,
            fg_color=THEME["input"],
            border_color=THEME["glass_border"],
            text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
        )
        self.bank_search_entry.grid(row=0, column=2, sticky="ew")
        self.bank_search_var.trace_add("write", lambda *_: self._search_debouncer.trigger())
        self.bank_search_entry.bind("<Return>", lambda _e: self._commit_search())

        self.recent_searches_frame = ctk.CTkFrame(main, fg_color="transparent")
        self.recent_searches_frame.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        # Explicit bg — transparent CTkScrollableFrame canvas often mismatches theme
        # (black gaps in light / white gaps in dark), especially with mica/DWM.
        self.app_list = ctk.CTkScrollableFrame(
            main,
            fg_color=THEME["bg"],
            corner_radius=0,
            border_width=0,
            scrollbar_button_color=THEME["glass_border"],
            scrollbar_button_hover_color=THEME["muted"],
        )
        self.app_list.grid(row=3, column=0, sticky="nsew")
        self.app_list.grid_columnconfigure(0, weight=1)
        self.app_list.grid_columnconfigure(1, weight=1)
        self._style_app_list()

        log_frame = glass_frame(main)
        log_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        log_frame.grid_columnconfigure(0, weight=1)
        self._log_frame = log_frame
        # Idle: hide empty glass slab under the catalog.
        log_frame.grid_remove()

        self.log_title = ctk.CTkLabel(
            log_frame,
            text="Журнал",
            font=ui_font(13, weight="bold"),
            text_color=THEME["text"],
        )
        self.log_title.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.progress_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        self.progress_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 8))
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_frame.grid_remove()

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            anchor="w",
            text_color=THEME["muted"],
            font=ui_font(13),
        )
        self.progress_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.phases_row = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.phases_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._phase_labels = {}
        for index, (key, label) in enumerate(_INSTALL_PHASES):
            pill = ctk.CTkLabel(
                self.phases_row,
                text=label,
                fg_color=THEME["chip"],
                text_color=THEME["muted"],
                corner_radius=10,
                font=ui_font(11),
                height=24,
                padx=8,
            )
            pill.pack(side="left", padx=(0 if index == 0 else 4, 0))
            self._phase_labels[key] = pill

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            height=10,
            progress_color=THEME["accent"],
            fg_color=THEME["glass_border"],
            corner_radius=8,
        )
        self.progress_bar.grid(row=2, column=0, sticky="ew")
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
        # Hidden for normal users — progress bar stays; unlock via 5 clicks on version.
        self.log_title.grid_remove()
        self.log_box.grid_remove()

    def _section_label(self, parent: ctk.CTkFrame, text: str, *, top_pad: int = 12) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=ui_font(14, weight="bold"),
            text_color=THEME["silver"],
        )
        label.pack(anchor="w", padx=16, pady=(top_pad, 8))
        return label

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

    def _style_app_list(self) -> None:
        """Keep CTkScrollableFrame canvas/scrollbar in sync with THEME["bg"]."""
        app_list = getattr(self, "app_list", None)
        if app_list is None:
            return
        try:
            app_list.configure(
                fg_color=THEME["bg"],
                scrollbar_button_color=THEME["glass_border"],
                scrollbar_button_hover_color=THEME["muted"],
            )
        except tk.TclError:
            return
        # Defensive: some CTK builds leave the raw tk canvas on the previous mode.
        try:
            canvas = getattr(app_list, "_parent_canvas", None)
            if canvas is not None:
                canvas.configure(bg=THEME["bg"])
            tk.Frame.configure(app_list, bg=THEME["bg"])
        except tk.TclError:
            pass

    def _update_log_frame_visibility(self) -> None:
        """Show bottom panel only when progress or tech log is active."""
        log_frame = getattr(self, "_log_frame", None)
        if log_frame is None:
            return
        progress_shown = bool(
            getattr(self, "progress_frame", None) and self.progress_frame.winfo_manager()
        )
        if self._log_visible or progress_shown:
            try:
                log_frame.grid()
            except tk.TclError:
                pass
            return
        try:
            log_frame.grid_remove()
        except tk.TclError:
            pass

    def _log(self, message: str) -> None:
        if not getattr(self, "log_box", None):
            return
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except tk.TclError:
            pass

    def _on_version_click(self, _event: object = None) -> None:
        self._version_click_count += 1
        if self._version_click_count < 5:
            return
        self._version_click_count = 0
        self._toggle_log_panel()

    def _toggle_log_panel(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_title.grid()
            self.log_box.grid()
            self._update_log_frame_visibility()
            self._log("Технический журнал включён (ещё 5 кликов по версии — скрыть).")
        else:
            self.log_title.grid_remove()
            self.log_box.grid_remove()
            self._update_log_frame_visibility()

    def _purge_stale_caches(self) -> None:
        """Remove old IPA cache from AppData — safe even if the app is installed elsewhere."""

        def task() -> None:
            try:
                downloads = data_dir() / "downloads"
                days = self.settings.ipa_cache_days
                removed = purge_stale_ipa_cache(downloads, max_age_days=days)
                staging = data_dir() / "staging"
                removed += purge_stale_staging(staging)
                legacy_staging = Path(tempfile.gettempdir()) / "restore-ios-apps"
                removed += purge_stale_staging(legacy_staging)
                if removed:
                    self.after(0, lambda n=removed: self._log(f"Очистка кэша: удалено файлов — {n}"))
            except Exception:
                pass

        threading.Thread(target=task, daemon=True).start()

    def _toast(self, message: str, *, kind: str = "info") -> None:
        if self._toasts is None:
            return
        try:
            self._toasts.show(message, kind=kind)  # type: ignore[arg-type]
        except Exception:
            pass

    def _reset_phases(self) -> None:
        for key, label in self._phase_labels.items():
            label.configure(
                fg_color=THEME["chip"],
                text_color=THEME["muted"],
                text=dict(_INSTALL_PHASES).get(key, key),
            )

    def _mark_phase(self, phase: str, *, active: bool = False, done: bool = False) -> None:
        if phase not in self._phase_labels and phase != "done":
            return
        try:
            active_index = self._phase_order.index(phase)
        except ValueError:
            active_index = len(self._phase_order) - 1 if phase == "done" else -1
        all_done = phase == "done" or done
        for index, key in enumerate(self._phase_order):
            label = self._phase_labels.get(key)
            if label is None:
                continue
            title = dict(_INSTALL_PHASES).get(key, key)
            if all_done or index < active_index:
                label.configure(fg_color=THEME["success_soft"], text_color=THEME["success"], text=f"✓ {title}")
            elif key == phase and active:
                label.configure(fg_color=THEME["accent_soft"], text_color=THEME["accent"], text=title)
            else:
                label.configure(fg_color=THEME["chip"], text_color=THEME["muted"], text=title)

    def _cancel_tools(self) -> None:
        if self.ipatool:
            self.ipatool.request_cancel()
        self.device_installer.request_cancel()

    def _queue_progress_hook(self, phase: str, value: float, text: str) -> None:
        self.after(0, lambda: self._set_progress(text, value))
        self.after(0, lambda: self._mark_phase(phase, active=True, done=phase == "done"))

    def _queue_worker(self, job: InstallJob, progress) -> None:
        if not self.ipatool:
            self._try_init_ipatool(show_errors=False)
        if not self.ipatool:
            raise IpatoolError("ipatool не найден")
        if not self._resolve_apple_account_email():
            raise IpatoolError("Сначала войдите в Apple ID.")
        udid = self._selected_udid
        if not udid:
            devices = self.device_installer.list_device_infos()
            if len(devices) == 1:
                udid = devices[0].udid
            elif len(devices) > 1:
                raise DeviceInstallerError(
                    "Подключено несколько iPhone.\nВыберите устройство в боковой панели."
                )
            elif not devices:
                raise DeviceInstallerError("iPhone не найден.")

        def on_phase(phase: str, value: float, text: str) -> None:
            progress(phase, value, text)

        self.ipatool.clear_cancel()
        self.device_installer.clear_cancel()
        run_install_job(
            app=job.app,
            ipatool=self.ipatool,
            device_installer=self.device_installer,
            config_manager=self.config_manager,
            udid=udid,
            on_phase=on_phase,
        )

    def _refresh_queue_ui(self) -> None:
        jobs = self._install_queue.jobs
        running = sum(1 for job in jobs if job.status == JobStatus.RUNNING)
        busy = self._install_queue.is_busy
        self.install_button.configure(state="disabled" if busy and running else "normal")

        for job in jobs:
            prev = self._queue_seen.get(job.id)
            status = job.status.value
            if prev == status:
                continue
            self._queue_seen[job.id] = status
            title = job.app.maskTitle or job.app.title
            if job.status == JobStatus.DONE and prev == JobStatus.RUNNING.value:
                self._log(f"Установлено: {title}")
                self._toast(f"Установлено: {title}", kind="success")
                messagebox.showinfo(
                    "Готово",
                    f"Приложение «{title}» установлено.\nПроверьте домашний экран iPhone.",
                )
            elif job.status == JobStatus.FAILED and prev == JobStatus.RUNNING.value:
                self._last_failed_app = job.app
                title_e, message = friendly_error(job.error or "Ошибка", domain="Установка")
                self._toast(f"Ошибка: {title}", kind="error")
                messagebox.showerror(title_e, f"«{title}»\n\n{message}")

    def _remember_devices(self, devices: list[DeviceInfo]) -> None:
        self._devices = devices
        if len(devices) == 1:
            self._selected_udid = devices[0].udid
            self.settings.selected_udid = devices[0].udid
        elif not devices:
            self._selected_udid = None

    def _confirm_device_for_install(self) -> str | None:
        try:
            devices = self.device_installer.list_device_infos()
            self._remember_devices(devices)
        except DeviceInstallerError as exc:
            title, message = friendly_error(exc, domain="iPhone")
            messagebox.showerror(title, message)
            return None
        if not devices:
            messagebox.showerror("iPhone", "iPhone не найден.\nПодключите кабель и нажмите «Доверять».")
            return None
        if len(devices) == 1:
            device = devices[0]
        else:
            # Несколько устройств — короткое подтверждение по списку имён.
            lines = "\n".join(f"• {d.name} ({d.model or 'iPhone'})" for d in devices)
            if not messagebox.askyesno(
                "Несколько iPhone",
                "Подключено несколько устройств:\n\n"
                f"{lines}\n\n"
                "Установить на первое в списке?\n"
                f"({devices[0].name})",
            ):
                return None
            device = devices[0]
        self._selected_udid = device.udid
        self.settings.selected_udid = device.udid
        return device.udid

    def _enqueue_apps(self, apps: list[AppEntry]) -> None:
        self._try_init_ipatool()
        if not self.ipatool:
            return
        if not self._resolve_apple_account_email():
            messagebox.showerror("Apple ID", "Сначала войдите в Apple ID.")
            return
        udid = self._confirm_device_for_install()
        if not udid:
            return
        self._selected_udid = udid
        self.after(0, self._reset_progress)
        self.after(0, self._reset_phases)
        self.after(0, lambda: self._set_progress("В очереди...", 0.02))
        added = self._install_queue.enqueue(apps)
        if added == 0:
            messagebox.showinfo("Очередь", "Эти приложения уже в очереди.")
        else:
            self._log(f"В очередь добавлено: {added}")

    def _create_support_report(self) -> None:
        def task() -> None:
            try:
                device_summary = ""
                if self._devices:
                    device_summary = "; ".join(
                        f"{d.name} {d.model} iOS {d.ios_version}" for d in self._devices
                    )
                driver = "установлены" if apple_drivers_installed() else "не найдены"
                email = self.config_manager.apple_account_email or ""
                path = build_support_report(
                    device_summary=device_summary,
                    driver_status=driver,
                    apple_id_masked=mask_email(email) if email else "",
                )
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Поддержка",
                        f"Отчёт сохранён:\n{path}\n\nОтправьте файл в Telegram @art_gromov",
                    ),
                )
                try:
                    os.startfile(str(path.parent))  # noqa: S606
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("Поддержка", str(exc)))

        threading.Thread(target=task, daemon=True).start()

    def _first_run_driver_nudge(self) -> None:
        try:
            if apple_drivers_installed():
                return
            devices = self.device_installer.list_device_infos()
            if devices:
                return
        except Exception:
            return
        if messagebox.askyesno(
            "Драйверы Apple",
            "iPhone не обнаружен, драйверы Apple могут быть не установлены.\n\n"
            "Установить драйверы сейчас?",
        ):
            self._install_drivers()

    def _reset_progress(self) -> None:
        self._stop_progress_creep()
        self._progress_value = 0.0
        self.progress_bar.set(0)

    def _set_progress(self, text: str, value: float) -> None:
        self.progress_frame.grid()
        self._update_log_frame_visibility()
        self.progress_label.configure(text=text)
        self._progress_value = max(self._progress_value, min(1.0, value))
        animate_progress_to(self._anim, self.progress_bar, self._progress_value)

    def _start_progress_creep(self, text: str, *, cap: float = 0.6, step: float = 0.003) -> None:
        self._stop_progress_creep()
        self._progress_active = True
        self.progress_frame.grid()
        self._update_log_frame_visibility()
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
        self._update_log_frame_visibility()

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

    def _warm_icon_cache(self) -> None:
        """Warm PIL disk/memory for bank logos and catalog icons off the critical path."""

        def task() -> None:
            try:
                groups = self.config_manager.list_bank_groups()
                self.icon_loader.warm_bank_groups(groups, size=44)
                apps = self.config_manager.list_apps()
                self.icon_loader.warm_apps(apps, size=44)
            except Exception:
                pass

        threading.Thread(target=task, daemon=True).start()

    def _startup_checks(self) -> None:
        def task() -> None:
            try:
                problems = verify_bundled_tools(strict=False)
                if problems:
                    self.after(0, lambda p=problems: self._log("Проверка tools: " + "; ".join(p)))
            except Exception:
                pass

            driver_line, device_line, combined = self._collect_readiness()
            self.after(0, lambda: self.readiness_label.configure(text=combined))
            self.after(0, lambda: self._log("--- Проверка при запуске ---"))
            self.after(0, lambda: self._log(driver_line))
            self.after(0, lambda: self._log(device_line))

            try:
                devices = self.device_installer.list_device_infos()
                self.after(0, lambda d=devices: self._remember_devices(d))
            except Exception:
                pass

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
                masked = mask_email(str(email)) if isinstance(email, str) else "…"
                self.after(0, lambda m=masked: self.auth_status_label.configure(text=f"Авторизован\n{m}"))
                self.after(0, lambda m=masked: self._log(f"Apple ID: {m}"))
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
                masked = mask_email(str(email)) if isinstance(email, str) else "…"
                self.after(0, lambda m=masked: self.auth_status_label.configure(text=f"Авторизован\n{m}"))
                self.after(0, lambda m=masked: self._log(f"Apple ID: {m}"))
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
            masked = mask_email(email)
            self._log(f"Вход выполнен: {masked}")
            self.auth_status_label.configure(text=f"Авторизован\n{masked}")
            self._log(sanitize_auth_result_for_log(result))

        AppleLoginDialog(self, self.ipatool, on_success, icon_loader=self.icon_loader)

    def _logout(self) -> None:
        self._try_init_ipatool()
        if not self.ipatool:
            return

        if not messagebox.askyesno(
            "Выход",
            "Выйти из текущего Apple ID?\n\nПосле выхода сессия на этом ПК будет полностью удалена.",
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
                        "Вы вышли из Apple ID.\n"
                        "Нажмите «Войти в Apple ID» для входа под другим аккаунтом.",
                    ),
                )
            except IpatoolError as exc:
                message = str(exc)
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda m=message: messagebox.showerror("Выход", m))

        self._run_async(task)

    def _open_update_in_browser(self, setup_url: str | None = None) -> None:
        url = resolve_browser_download_url(setup_url or self._last_setup_url)
        self._log(f"Открыта страница загрузки в браузере:\n{url}")
        webbrowser.open(url)

    def _show_update_action_dialog(
        self,
        *,
        title: str,
        message: str,
        primary_text: str,
        on_primary: Callable[[], None] | None = None,
        secondary_text: str = "",
        on_secondary: Callable[[], None] | None = None,
        tertiary_text: str = "Закрыть",
        browser_url: str | None = None,
        link_text: str | None = None,
        on_link: Callable[[], None] | None = None,
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("540x400")
        dialog.minsize(500, 360)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=THEME["bg"])
        dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
        fade_in_window(dialog)

        card = glass_frame(dialog)
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            card,
            text=title,
            font=ui_font(18, weight="bold"),
            text_color=THEME["text"],
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            card,
            text=message,
            font=ui_font(13),
            text_color=THEME["text_secondary"],
            justify="left",
            anchor="nw",
            wraplength=450,
        ).pack(anchor="w", fill="both", expand=True, padx=18, pady=(0, 8))

        if link_text:

            def _link() -> None:
                if on_link:
                    on_link()
                else:
                    self._open_update_in_browser(browser_url)

            ghost_button(card, text=link_text, command=_link, anchor="w").pack(
                anchor="w", padx=14, pady=(0, 8)
            )

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(8, 16))

        def close_then(action: Callable[[], None] | None) -> None:
            dialog.destroy()
            if action:
                action()

        primary_button(
            buttons,
            text=primary_text,
            command=lambda: close_then(on_primary),
            width=180,
            height=40,
        ).pack(side="right")

        if secondary_text:
            secondary_button(
                buttons,
                text=secondary_text,
                command=lambda: close_then(on_secondary),
                width=280 if len(secondary_text) > 12 else 120,
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

    def _download_update(self, result: UpdateCheckResult) -> None:
        if not result.setup_url:
            self._show_update_action_dialog(
                title="Обновление",
                message=(
                    "Ссылка на установщик не указана в манифесте обновлений.\n"
                    "Можно открыть страницу релизов в браузере."
                ),
                primary_text="Открыть в браузере",
                on_primary=lambda: self._open_update_in_browser(None),
                secondary_text="",
                tertiary_text="Закрыть",
            )
            return
        if not result.sha256:
            self._show_update_action_dialog(
                title="Обновление",
                message=(
                    "В манифесте нет SHA256 установщика.\n"
                    "Встроенная загрузка отменена — так безопаснее.\n\n"
                    "Скачайте установщик в браузере с официальной страницы релизов."
                ),
                primary_text="Открыть в браузере",
                on_primary=lambda: self._open_update_in_browser(result.setup_url),
                secondary_text="",
                tertiary_text="Закрыть",
                browser_url=result.setup_url,
            )
            return

        def download_task() -> None:
            self.after(0, lambda: self._set_progress("Скачивание обновления...", 0.05))

            def on_progress(ratio: float) -> None:
                self.after(
                    0,
                    lambda r=ratio: self._set_progress(
                        f"Скачивание обновления... {int(r * 100)}%",
                        0.05 + r * 0.9,
                    ),
                )

            try:
                installer = download_verified_installer(
                    setup_url=result.setup_url,
                    expected_sha256=result.sha256,
                    version=result.latest_version,
                    on_progress=on_progress,
                    setup_urls=result.setup_urls,
                )
            except UpdateCheckError as exc:
                message = str(exc)
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(m))
                self.after(
                    0,
                    lambda p=debug_path: self._log(
                        f"Диагностика обновления (файл): {p}"
                    ),
                )
                self.after(
                    0,
                    lambda m=message: self._show_update_action_dialog(
                        title="Не удалось скачать обновление",
                        message=(
                            f"{m}\n\n"
                            "Рекомендуем скачать в браузере — там обычно доступны "
                            "другие зеркала (GitHub + прокси), даже когда встроенная "
                            "загрузка не проходит."
                        ),
                        primary_text="Скачать в браузере",
                        on_primary=lambda: self._open_update_in_browser(result.setup_url),
                        secondary_text="Повторить в приложении",
                        on_secondary=lambda: self._download_update(result),
                        tertiary_text="Закрыть",
                    ),
                )
                return

            self.after(0, lambda: self._set_progress("Проверка завершена", 1.0))
            self.after(0, lambda: self._log(f"Установщик проверен: {installer.name}"))

            def launch() -> None:
                try:
                    os.startfile(str(installer))  # noqa: S606 — verified local Setup.exe
                    self._log("Запущен проверенный установщик.")
                except OSError as exc:
                    self._show_update_action_dialog(
                        title="Обновление",
                        message=(
                            f"Файл проверен, но не удалось открыть установщик:\n{exc}\n\n"
                            f"Откройте вручную:\n{installer}\n\n"
                            "Или скачайте заново в браузере."
                        ),
                        primary_text="Открыть в браузере",
                        on_primary=lambda: self._open_update_in_browser(result.setup_url),
                        secondary_text="",
                        tertiary_text="Закрыть",
                        browser_url=result.setup_url,
                    )

            self.after(0, launch)

        self._run_async(download_task)

    def _present_update_available(self, result: UpdateCheckResult) -> None:
        if result.setup_url:
            self._last_setup_url = result.setup_url
        # Browser-first: same path that worked on other PCs (system TLS/proxy).
        self._open_update_in_browser(result.setup_url)
        self._toast(
            "Скачивание обновления открыто в браузере — установите Setup",
            kind="info",
        )
        notes = f"\n\n{result.notes}" if result.notes else ""
        message = (
            f"Доступна новая версия {result.latest_version}.\n"
            f"Текущая версия: {result.current_version}.{notes}\n\n"
            "Скачивание обновления открыто в браузере — установите Setup.\n"
            "Это надёжнее на разных ПК (антивирус, прокси, блокировка GitHub).\n"
            "При желании можно скачать внутри приложения (проверка SHA256)."
        )
        self._show_update_action_dialog(
            title="Доступно обновление",
            message=message,
            primary_text="Открыть снова в браузере",
            on_primary=lambda: self._open_update_in_browser(result.setup_url),
            secondary_text="Скачать в приложении",
            on_secondary=lambda: self._download_update(result),
            tertiary_text="Позже",
            browser_url=result.setup_url,
        )

    def _present_update_check_failure(self, message: str) -> None:
        releases_url = GITHUB_RELEASES_LATEST
        self._log(f"Открыта страница релизов в браузере:\n{releases_url}")
        webbrowser.open(releases_url)
        self._toast(
            "Страница загрузки открыта в браузере",
            kind="warning",
        )
        self._show_update_action_dialog(
            title="Не удалось проверить обновления",
            message=(
                f"{message}\n\n"
                "Проверка из приложения может не пройти, даже если сайт GitHub "
                "открывается в браузере (другой путь сети, TLS, блокировка CDN).\n\n"
                "Страница релизов уже открыта в браузере — скачайте Setup оттуда."
            ),
            primary_text="Открыть релизы в браузере",
            on_primary=lambda: webbrowser.open(GITHUB_RELEASES_LATEST),
            secondary_text="Повторить проверку",
            on_secondary=self._check_updates,
            tertiary_text="Закрыть",
        )

    def _check_updates(self) -> None:
        def task() -> None:
            self.after(0, lambda: self._log("Проверка обновлений..."))
            try:
                result = check_for_updates()
            except UpdateCheckError as exc:
                message = str(exc)
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(f"Обновление: {m}"))
                self.after(
                    0,
                    lambda p=debug_path: self._log(
                        f"Диагностика обновления (файл): {p}"
                    ),
                )
                self.after(0, lambda m=message: self._present_update_check_failure(m))
                return
            except Exception as exc:  # noqa: BLE001 — surface unexpected transport bugs
                message = (
                    "Не удалось проверить обновления из-за внутренней ошибки.\n"
                    f"{type(exc).__name__}: {exc}"
                )
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(f"Обновление: {m}"))
                self.after(
                    0,
                    lambda p=debug_path: self._log(
                        f"Диагностика обновления (файл): {p}"
                    ),
                )
                self.after(0, lambda m=message: self._present_update_check_failure(m))
                return

            if result.setup_url:
                self._last_setup_url = result.setup_url

            if result.is_up_to_date:
                text = f"У вас актуальная версия ({result.current_version})."
                self.after(0, lambda: self._log(text))
                self.after(0, lambda: self._toast(text, kind="success"))
                self.after(0, lambda: messagebox.showinfo("Обновление", text))
                return

            self.after(0, lambda: self._log(f"Доступна версия {result.latest_version}."))
            self.after(0, lambda: self._present_update_available(result))

        self._run_async(task)

    def _load_catalog_state(self) -> dict[str, str]:
        if not self._catalog_state_path.exists():
            return {}
        try:
            with self._catalog_state_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                return {
                    "view": str(payload.get("view", "root")),
                    "bankGroup": str(payload.get("bankGroup", "")),
                }
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_catalog_state(self) -> None:
        payload = {
            "view": self._catalog_view,
            "bankGroup": self._catalog_bank_group or "",
        }
        try:
            self._catalog_state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._catalog_state_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _restore_catalog_state(self) -> None:
        state = self._load_catalog_state()
        view = state.get("view", "root")
        bank_group = state.get("bankGroup", "")
        if view == "bank" and bank_group and self.config_manager.get_bank_group(bank_group):
            self._catalog_view = "bank"
            self._catalog_bank_group = bank_group
        elif view == "banks":
            self._catalog_view = "banks"
            self._catalog_bank_group = None
        else:
            self._catalog_view = "root"
            self._catalog_bank_group = None

    def _catalog_back(self) -> None:
        if self._catalog_view == "bank":
            self._open_banks_folder()
            return
        if self._catalog_view == "banks":
            self._open_root_catalog()

    def _open_root_catalog(self) -> None:
        self._catalog_view = "root"
        self._catalog_bank_group = None
        self._bank_search_query = ""
        self.bank_search_var.set("")
        if self.selected_app and self.selected_app.is_banking:
            self.selected_app = None
            self.selected_label.configure(text="Выберите приложение")
            self.selected_meta_label.configure(text="Нажмите на карточку в списке ниже")
            self.selected_icon_label.configure(image="")
        self._save_catalog_state()
        self._refresh_app_list()

    def _open_banks_folder(self) -> None:
        self._catalog_view = "banks"
        self._catalog_bank_group = None
        self._bank_search_query = ""
        self.bank_search_var.set("")
        self._save_catalog_state()
        self._refresh_app_list()

    def _open_bank_group(self, bank_group_id: str) -> None:
        if not self.config_manager.get_bank_group(bank_group_id):
            return
        self._catalog_view = "bank"
        self._catalog_bank_group = bank_group_id
        self._bank_search_query = ""
        self.bank_search_var.set("")
        self._save_catalog_state()
        self._refresh_app_list()

    def _apply_bank_search(self) -> None:
        query = self.bank_search_var.get().strip().lower()
        if query == self._bank_search_query:
            return
        self._bank_search_query = query
        self._global_search_query = query
        self._refresh_app_list()

    def _commit_search(self) -> None:
        query = self.bank_search_var.get().strip()
        if len(query) >= 2:
            self.settings.remember_search(query)
            self._render_recent_searches()
        self._apply_bank_search()

    def _render_recent_searches(self) -> None:
        frame = getattr(self, "recent_searches_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        recent = self.settings.recent_searches
        if not recent:
            frame.grid_remove()
            return
        frame.grid()
        ctk.CTkLabel(
            frame,
            text="Недавние:",
            font=ui_font(11),
            text_color=THEME["muted"],
        ).pack(side="left", padx=(0, 6))
        for item in recent[:5]:
            chip = ctk.CTkButton(
                frame,
                text=item,
                height=26,
                width=1,
                corner_radius=12,
                fg_color=THEME["chip"],
                hover_color=THEME["accent_soft"],
                text_color=THEME["text_secondary"],
                font=ui_font(11),
                command=lambda q=item: self._use_recent_search(q),
            )
            chip.pack(side="left", padx=(0, 4))

    def _use_recent_search(self, query: str) -> None:
        self.bank_search_var.set(query)
        self._commit_search()

    def _update_catalog_header(self) -> None:
        self.bank_search_entry.grid()
        if self._catalog_view == "root":
            self.catalog_back_button.grid_remove()
            self.catalog_path_label.configure(text="Каталог")
            return

        self.catalog_back_button.grid()
        if self._catalog_view == "banks":
            self.catalog_path_label.configure(text=BANKS_FOLDER_TITLE)
            return

        group = self.config_manager.get_bank_group(self._catalog_bank_group or "")
        bank_title = group.title if group else "Банк"
        self.catalog_path_label.configure(text=f"{BANKS_FOLDER_TITLE} / {bank_title}")

    def _filter_bank_apps(self, apps: list[AppEntry]) -> list[AppEntry]:
        query = self._bank_search_query.strip().lower()
        if not query:
            return apps
        filtered: list[AppEntry] = []
        for app in apps:
            haystack = " ".join(
                part
                for part in (
                    app.title,
                    app.maskTitle,
                    app.description,
                    str(app.appId),
                )
                if part
            ).lower()
            if query in haystack:
                filtered.append(app)
        return filtered

    def _schedule_card_reveal(self, card: ctk.CTkFrame, index: int, token: int) -> None:
        # Subtle border fade only — avoid painting cards with window bg (gap flash).
        if index > 12:
            return
        delay = min(index, 8) * 20

        def start() -> None:
            if token != self._catalog_anim_token:
                return
            reveal_card(
                self._anim,
                card,
                target_fg=THEME["glass"],
                target_border=THEME["glass_border"],
                duration_ms=DURATION_FAST,
            )

        self.after(delay, start)

    def _bind_card_hover(self, card: ctk.CTkFrame, card_id: str) -> None:
        bind_smooth_hover(
            self._anim,
            card,
            card_id,
            normal_fg=THEME["glass"],
            hover_fg=THEME["glass_hover"],
            normal_border=THEME["glass_border"],
            hover_border=THEME["glass_border_bright"],
            is_selected=lambda cid=card_id: bool(self.selected_app and self.selected_app.id == cid),
            duration_ms=DURATION_FAST,
        )

    def _refresh_app_list(self) -> None:
        self._catalog_anim_token += 1
        token = self._catalog_anim_token
        self._anim.cancel_all()

        for child in self.app_list.winfo_children():
            child.destroy()
        self._app_rows.clear()
        self._icon_refs.clear()
        self._update_catalog_header()

        # Instant populate for Banks / bank apps — skeleton caused perceived freeze.
        # Keep a short skeleton only on cold root load with many general apps.
        use_skeleton = self._catalog_view == "root" and not getattr(self, "_catalog_ready", False)
        if use_skeleton:
            for index in range(4):
                row, col = divmod(index, 2)
                skeleton_card(self.app_list, row=row, col=col)

            def populate() -> None:
                if token != self._catalog_anim_token:
                    return
                for child in self.app_list.winfo_children():
                    child.destroy()
                self._app_rows.clear()
                self._populate_catalog_cards(token)
                self._catalog_ready = True

            self.after(80, populate)
            return

        self._populate_catalog_cards(token)
        self._catalog_ready = True

    def _populate_catalog_cards(self, token: int) -> None:
        cards: list[ctk.CTkFrame] = []

        if self._catalog_view == "banks":
            counts = self.config_manager.banking_app_counts()
            groups = [group for group in BANK_GROUPS if counts.get(group.id, 0) > 0]
            for index, group in enumerate(groups):
                count = counts.get(group.id, 0)
                row, col = divmod(index, 2)
                cards.append(self._create_bank_card(group, count, row, col))
        elif self._catalog_view == "bank" and self._catalog_bank_group:
            apps = self._filter_bank_apps(
                self.config_manager.list_banking_apps_for_group(self._catalog_bank_group)
            )
            if not apps:
                if self._bank_search_query:
                    empty_state(
                        self.app_list,
                        icon="?",
                        title="Ничего не найдено",
                        hint="Попробуйте другой запрос или очистите поле поиска.",
                        action_text="Очистить поиск",
                        action=lambda: self.bank_search_var.set(""),
                    )
                else:
                    empty_state(
                        self.app_list,
                        icon="○",
                        title="В этом банке пока нет приложений",
                        hint="Загляните позже — каталог пополняется.",
                    )
            else:
                self._populate_cards_incremental(apps, token)
                return
        else:
            query = self._global_search_query.strip().lower()
            if query:
                # Global search across general + banking apps.
                matches = [
                    app
                    for app in self.config_manager.list_apps()
                    if query
                    in " ".join(
                        [
                            app.title,
                            app.maskTitle,
                            app.description,
                            app.bundleId,
                            str(app.appId),
                            app.bankGroup,
                        ]
                    ).lower()
                ]
                if not matches:
                    empty_state(
                        self.app_list,
                        icon="?",
                        title="Ничего не найдено",
                        hint="Попробуйте другое название или очистите поиск.",
                        action_text="Очистить поиск",
                        action=lambda: self.bank_search_var.set(""),
                    )
                    return
                self._populate_cards_incremental(matches, token)
                return

            items = sorted(
                self.config_manager.list_general_apps(),
                key=lambda item: item.title.lower(),
            )
            for index, app in enumerate(items):
                row, col = divmod(index, 2)
                cards.append(self._create_app_card(app, row, col))
            row, col = divmod(len(items), 2)
            bank_count = len(self.config_manager.banking_app_counts())
            cards.append(self._create_folder_card(BANKS_FOLDER_TITLE, row, col, bank_count))

        for index, card in enumerate(cards):
            self._schedule_card_reveal(card, index, token)

        if self.selected_app and self.selected_app.id in self._app_rows:
            self._highlight_card(self.selected_app.id)

    def _populate_cards_incremental(self, apps: list[AppEntry], token: int) -> None:
        """Create app cards in batches so the UI stays responsive for large banks."""
        batch_size = 6
        total = len(apps)

        def add_batch(start: int) -> None:
            if token != self._catalog_anim_token:
                return
            end = min(start + batch_size, total)
            for index in range(start, end):
                row, col = divmod(index, 2)
                card = self._create_app_card(apps[index], row, col)
                self._schedule_card_reveal(card, index, token)
            if end < total:
                self.after(1, lambda: add_batch(end))
            elif self.selected_app and self.selected_app.id in self._app_rows:
                self._highlight_card(self.selected_app.id)

        add_batch(0)

    def _bind_click(self, widget: tk.Misc, callback: Callable[[], None]) -> None:
        widget.bind("<Button-1>", lambda _e: callback())
        if hasattr(widget, "winfo_children"):
            for child in widget.winfo_children():
                self._bind_click(child, callback)

    def _create_bank_card(self, group: BankGroup, app_count: int, row: int, col: int) -> ctk.CTkFrame:
        card = glass_frame(self.app_list)
        card.grid(
            row=row,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 6, 6 if col == 0 else 0),
            pady=6,
        )
        card.grid_columnconfigure(1, weight=1)
        card_id = f"__bank_{group.id}__"
        self._app_rows[card_id] = card

        icon = self.icon_loader.get_bank_group_icon(group, size=44)
        self._icon_refs.append(icon)
        ctk.CTkLabel(card, text="", image=icon).grid(row=0, column=0, padx=(CARD_PADX, 12), pady=CARD_PADY)

        text_wrap = ctk.CTkFrame(card, fg_color="transparent")
        text_wrap.grid(row=0, column=1, sticky="ew", pady=CARD_PADY, padx=(0, CARD_PADX))

        title_row = ctk.CTkFrame(text_wrap, fg_color="transparent")
        title_row.pack(anchor="w", fill="x")

        ctk.CTkLabel(
            title_row,
            text=group.title,
            font=ui_font(15, weight="bold"),
            anchor="w",
            text_color=THEME["silver"],
        ).pack(side="left")

        count_label = ctk.CTkLabel(
            title_row,
            text=str(app_count),
            width=28,
            height=22,
            corner_radius=11,
            fg_color=THEME["glass_border"],
            text_color=THEME["muted"],
            font=ui_font(11, weight="bold"),
        )
        count_label.pack(side="left", padx=(8, 0))

        app_word = "приложений"
        if app_count % 10 == 1 and app_count % 100 != 11:
            app_word = "приложение"
        elif app_count % 10 in {2, 3, 4} and app_count % 100 not in {12, 13, 14}:
            app_word = "приложения"
        ctk.CTkLabel(
            text_wrap,
            text=f"{app_count} {app_word}",
            font=ui_font(12),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self._bind_click(card, lambda gid=group.id: self._open_bank_group(gid))
        self._bind_card_hover(card, card_id)
        return card

    def _create_folder_card(self, title: str, row: int, col: int, bank_count: int = 0) -> ctk.CTkFrame:
        card = glass_frame(self.app_list)
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0), pady=6)
        card.grid_columnconfigure(1, weight=1)
        self._app_rows["__banking_folder__"] = card

        icon_wrap = ctk.CTkFrame(card, fg_color=THEME["accent_soft"], corner_radius=14, width=48, height=48)
        icon_wrap.grid(row=0, column=0, padx=(CARD_PADX, 12), pady=CARD_PADY)
        icon_wrap.grid_propagate(False)
        ctk.CTkLabel(
            icon_wrap,
            text="₽",
            font=ui_font(20, weight="bold"),
            text_color=THEME["accent"],
        ).place(relx=0.5, rely=0.5, anchor="center")

        text_wrap = ctk.CTkFrame(card, fg_color="transparent")
        text_wrap.grid(row=0, column=1, sticky="ew", pady=CARD_PADY, padx=(0, CARD_PADX))

        title_row = ctk.CTkFrame(text_wrap, fg_color="transparent")
        title_row.pack(anchor="w", fill="x")

        ctk.CTkLabel(
            title_row,
            text=title,
            font=ui_font(15, weight="bold"),
            anchor="w",
            text_color=THEME["silver"],
        ).pack(side="left")

        if bank_count:
            ctk.CTkLabel(
                title_row,
                text=str(bank_count),
                width=28,
                height=22,
                corner_radius=11,
                fg_color=THEME["glass_border"],
                text_color=THEME["muted"],
                font=ui_font(11, weight="bold"),
            ).pack(side="left", padx=(8, 0))

        subtitle = f"{bank_count} банков" if bank_count else "Сбер, Т-Банк, ВТБ и другие"
        ctk.CTkLabel(
            text_wrap,
            text=subtitle,
            font=ui_font(12),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self._bind_click(card, self._open_banks_folder)
        self._bind_card_hover(card, "__banking_folder__")
        return card

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

    def _create_app_card(self, app: AppEntry, row: int, col: int) -> ctk.CTkFrame:
        card = glass_frame(self.app_list)
        card.grid(
            row=row,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 6, 6 if col == 0 else 0),
            pady=6,
        )
        card.grid_columnconfigure(1, weight=1)
        self._app_rows[app.id] = card

        icon = self.icon_loader.get_app_icon(app, size=44)
        self._icon_refs.append(icon)
        icon_label = ctk.CTkLabel(card, text="", image=icon)
        icon_label.grid(row=0, column=0, padx=(CARD_PADX, 12), pady=CARD_PADY)

        text_wrap = ctk.CTkFrame(card, fg_color="transparent")
        text_wrap.grid(row=0, column=1, sticky="ew", pady=CARD_PADY, padx=(0, CARD_PADX))

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
        return card

    def _highlight_card(self, app_id: str) -> None:
        for card_id, row in self._app_rows.items():
            self._anim.cancel(f"hover:{card_id}")
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
        dialog.title("Помощь")
        dialog.geometry("400x240")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=THEME["bg"])
        dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
        fade_in_window(dialog)

        if logo := self.icon_loader.get_logo(36):
            self._icon_refs.append(logo)
            ctk.CTkLabel(dialog, text="", image=logo).pack(anchor="w", padx=24, pady=(24, 12))

        ctk.CTkLabel(
            dialog,
            text="Нужна помощь?",
            font=ui_font(18, weight="bold"),
            text_color=THEME["silver"],
        ).pack(anchor="w", padx=24, pady=(0, 6))

        ctk.CTkLabel(
            dialog,
            text="Telegram @art_gromov",
            font=ui_font(15),
            text_color=THEME["accent"],
        ).pack(anchor="w", padx=24, pady=(0, 20))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=24, pady=(0, 24))

        primary_button(
            buttons,
            text="Написать",
            command=lambda: webbrowser.open("https://t.me/art_gromov"),
            width=120,
        ).pack(side="right")
        secondary_button(buttons, text="Закрыть", command=dialog.destroy, width=100).pack(side="right", padx=(0, 8))

    def _check_device(self) -> None:
        self.readiness_label.configure(text="Проверка iPhone...")

        def task() -> None:
            try:
                devices = self.device_installer.list_device_infos()

                def done() -> None:
                    self._remember_devices(devices)
                    driver_ok = apple_drivers_installed()
                    driver_line = (
                        "Драйверы Apple: установлены" if driver_ok else "Драйверы Apple: не установлены"
                    )
                    if devices:
                        device_line = f"iPhone: {devices[0].label}"
                        if len(devices) > 1:
                            device_line += f" (+{len(devices) - 1})"
                        self.readiness_label.configure(text=f"{driver_line}\n{device_line}")
                        lines = "\n".join(f"• {d.label}" for d in devices)
                        self._log("Найденные устройства:\n" + lines)
                        messagebox.showinfo(
                            "iPhone",
                            "Найдено:\n\n" + "\n\n".join(d.detail_lines for d in devices),
                        )
                    else:
                        self.readiness_label.configure(text=f"{driver_line}\niPhone: не найден")
                        self._log("iPhone не найден. Подключите USB и нажмите «Доверять».")
                        messagebox.showwarning(
                            "iPhone",
                            "iPhone не найден.\n\n"
                            "1. Подключите кабель USB\n"
                            "2. На iPhone нажмите «Доверять»\n"
                            "3. При необходимости установите драйверы Apple",
                        )

                self.after(0, done)
            except DeviceInstallerError as exc:
                title, message = friendly_error(exc, domain="iPhone")

                def fail() -> None:
                    self._log(message)
                    self._refresh_readiness()
                    messagebox.showerror(title, message)

                self.after(0, fail)
            except Exception as exc:
                message = str(exc) or "Не удалось проверить iPhone."

                def fail_unknown() -> None:
                    self._log(message)
                    self._refresh_readiness()
                    messagebox.showerror("iPhone", message)

                self.after(0, fail_unknown)

        threading.Thread(target=task, daemon=True).start()

    def _install_selected(self) -> None:
        if not self.selected_app:
            messagebox.showinfo("Установка", "Сначала выберите приложение из списка.")
            return
        self._enqueue_apps([self.selected_app])


def main() -> None:
    ensure_app_dirs()
    from single_instance import acquire_single_instance_lock

    if not acquire_single_instance_lock():
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "GROMOV Restore+",
                "Приложение уже запущено.\nЗакройте другое окно и попробуйте снова.",
            )
            root.destroy()
        except Exception:
            pass
        return

    app = RestoreIosApp()
    app.mainloop()


if __name__ == "__main__":
    main()
