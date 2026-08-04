from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Callable

# --- Startup crash diagnostics (stdlib only; must stay before heavy imports) ---


def _startup_crash_log_path() -> Path:
    """Always LocalAppData — works even if install dir is read-only / broken."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GROMOV" / "RestorePlus"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "GROMOV-RestorePlus"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path(tempfile.gettempdir()) / "gromov_restoreplus_startup_crash.log"
    return base / "startup_crash.log"


def _write_startup_crash(exc: BaseException) -> Path:
    path = _startup_crash_log_path()
    version = "unknown"
    try:
        from version import APP_VERSION as _ver  # local import — may itself be failing

        version = str(_ver)
    except Exception:
        pass
    lines = [
        f"time={time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"version={version}",
        f"frozen={bool(getattr(sys, 'frozen', False))}",
        f"executable={sys.executable}",
        f"argv={sys.argv!r}",
        f"cwd={os.getcwd()}",
        f"exception={type(exc).__name__}: {exc}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
    return path


def _show_startup_crash_dialog(path: Path, exc: BaseException) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "GROMOV Restore+",
            "Не удалось запустить приложение.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Подробности сохранены в:\n{path}\n\n"
            "Отправьте этот файл в Telegram @gromov_restore.",
        )
        root.destroy()
    except Exception:
        pass


def _install_startup_excepthook() -> None:
    """PyInstaller console=False hides stderr — persist uncaught errors to disk."""

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]
            return
        path = _write_startup_crash(exc)
        _show_startup_crash_dialog(path, exc)
        sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]

    sys.excepthook = _hook


_install_startup_excepthook()

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from app_paths import data_dir, ensure_app_dirs, install_dir, resource_dir
from app_settings import AppSettings
from catalog_controller import CatalogController
from date_format import format_relative_install
from help_dialog import open_help_dialog
from catalog_tabs import tab_by_id, tab_by_label, tab_labels
from catalog_ui import (
    VersionPickerOption,
    catalog_app_card,
    catalog_tab_bar,
    letter_header,
    open_version_picker,
    section_header,
)
from config_manager import (
    AppEntry,
    BankGroup,
    ConfigManager,
    VersionGroup,
)
from device_installer import DeviceInfo, DeviceInstaller, DeviceInstallerError
from device_picker import pick_usb_device
from disk_utils import DiskSpaceError, ensure_download_space
from driver_installer import DriverInstallerError, apple_drivers_installed, install_apple_drivers
from icon_loader import IconLoader
from install_controller import InstallController
from install_queue import InstallJob, JobStatus
from install_service import run_install_job
from ipa_utils import purge_stale_ipa_cache, purge_stale_staging
from ipatool_client import IpatoolCancelled, IpatoolClient, IpatoolError
from login_dialog import AppleLoginDialog
from security_utils import mask_email, sanitize_auth_result_for_log
from support_report import build_support_report
from theme import (
    ICON_CARD,
    ICON_INSTALL,
    SIDEBAR_WIDTH,
    THEME,
    TYPE_BRAND,
    TYPE_CAPTION,
    TYPE_META,
    TYPE_SECTION,
    TYPE_TITLE,
    apply_theme,
    empty_state,
    glass_frame,
    glass_shell,
    primary_button,
    secondary_button,
    status_pill,
    ui_font,
)
from toast import ToastHost
from tool_integrity import verify_bundled_tools
from ui_animations import (
    AnimationRunner,
    SearchDebouncer,
    animate_card_select,
    animate_progress_to,
    bind_press_feedback,
    fade_in_window,
)
from update_controller import UpdateController
from update_checker import (
    UpdateCancelled,
    UpdateCheckError,
    UpdateCheckResult,
    sanitize_update_message,
    update_debug_log_path,
)
from user_errors import friendly_error
from virtual_list import BatchCatalogList, DEFAULT_BATCH
from version import APP_VERSION
from window_effects import apply_glass_window

_SUPPORT_TELEGRAM = "https://t.me/gromov_restore"
_SUPPORT_TELEGRAM_APP = "tg://resolve?domain=gromov_restore"
_IFI_VPN_URL = "https://my.ifivpn.biz/auth?lang=ru"
_IFI_PROMO_CODE = "GROMOV"

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
        if settings.theme_mode != "dark":
            settings.theme_mode = "dark"

        super().__init__()
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("GROMOV Restore+")
        self.geometry("1180x780")
        self.minsize(1020, 700)
        self._set_window_icon()

        self.settings = settings
        self.config_manager = ConfigManager()
        self.catalog = CatalogController(self.config_manager, self.settings)
        self.updates = UpdateController()
        self.icon_loader = IconLoader()
        self.ipatool: IpatoolClient | None = None
        self.device_installer = DeviceInstaller()
        self.selected_app: AppEntry | None = None
        self._devices: list[DeviceInfo] = []
        self._selected_udid: str | None = self.settings.selected_udid
        self._worker: threading.Thread | None = None
        self._async_busy = False
        self._icon_refs: list[object] = []
        self._selected_icon_ref: object | None = None
        self._app_rows: dict[str, ctk.CTkFrame] = {}
        self._catalog_panels: dict[str, ctk.CTkFrame] = {}
        self._catalog_panel_rows: dict[str, dict[str, ctk.CTkFrame]] = {}
        self._catalog_panel_complete: dict[str, bool] = {}
        self._catalog_parent: ctk.CTkFrame | None = None
        self._catalog_view = "root"  # root | bank (drill-down from Banks tab)
        self._catalog_tab = "popular"
        self._catalog_bank_group: str | None = None
        self._bank_search_query = ""
        self._global_search_query = ""
        self._batch_list: BatchCatalogList | None = None
        self._catalog_state_path = data_dir() / "catalog_state.json"
        self._catalog_ready = False
        self._catalog_anim_token = 0
        self._catalog_tabs = None
        self._tabs_wrap: ctk.CTkFrame | None = None
        self._cancel_install_btn: ctk.CTkButton | None = None
        self._retry_install_btn: ctk.CTkButton | None = None
        self._install_card_state = "idle"
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
        self._update_cancel: threading.Event | None = None
        self._update_busy = False
        self._install = InstallController(
            worker=self._queue_worker,
            on_changed=lambda: self.after(0, self._refresh_queue_ui),
            on_cancel_request=self._cancel_tools,
        )
        self._install.set_progress_hook(self._queue_progress_hook)
        self._install_queue = self._install.queue  # compat for existing call sites
        self._queue_seen: dict[str, str] = {}
        self._fairplay_checklist_pending = False

        self._build_layout()
        self._toasts = ToastHost(self)
        self._restore_catalog_state()
        # First paint: only active tab (Популярные) — no skeleton / no full catalog.
        self.after(0, self._refresh_app_list)
        self._render_recent_searches()
        self.after(50, lambda: apply_glass_window(self, dark=True))
        self.after(200, self._startup_checks)
        self.after(300, self._warm_icon_cache)
        self.after(2500, self._purge_stale_caches)
        self.after(800, self._first_run_driver_nudge)
        self.after(5000, self._poll_usb_devices)

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

        # Compact header — brand visible, minimal vertical tax on catalog
        header_outer, header = glass_shell(self, elevated=True, corner_radius=18, rim=False)
        header_outer.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 0))
        header.grid_columnconfigure(1, weight=1)
        self._header = header
        self._header_outer = header_outer

        logo = self.icon_loader.get_logo(44)
        if logo:
            self._icon_refs.append(logo)
            logo_label = ctk.CTkLabel(header, text="", image=logo)
            logo_label.grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=10)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=1, rowspan=2, sticky="w", pady=10)

        title_row = ctk.CTkFrame(title_wrap, fg_color="transparent")
        title_row.pack(anchor="w")

        brand = ctk.CTkLabel(
            title_row,
            text="GROMOV ",
            font=ui_font(TYPE_BRAND, weight="bold"),
            text_color=THEME["silver"],
        )
        brand.pack(side="left")

        product = ctk.CTkLabel(
            title_row,
            text="Restore+",
            font=ui_font(TYPE_BRAND, weight="bold"),
            text_color=THEME["accent"],
        )
        product.pack(side="left")

        tagline = ctk.CTkLabel(
            title_wrap,
            text="Приложения из вашего Apple ID — снова на iPhone",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
        )
        tagline.pack(anchor="w", pady=(2, 0))

        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.grid(row=0, column=2, rowspan=2, padx=(0, 14), pady=10, sticky="e")

        self.version_label = ctk.CTkLabel(
            header_actions,
            text=f"v{APP_VERSION}",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            cursor="hand2",
        )
        self.version_label.pack(side="left", padx=(0, 10))
        self.version_label.bind("<Button-1>", self._on_version_click)

        self.update_button = secondary_button(
            header_actions,
            text="Обновить",
            width=108,
            height=36,
            font=ui_font(12, weight="bold"),
            command=self._check_updates,
        )
        self.update_button.pack(side="left", padx=(0, 8))
        bind_press_feedback(self._anim, self.update_button)

        self.help_button = primary_button(
            header_actions,
            text="?",
            width=36,
            height=36,
            corner_radius=18,
            font=ui_font(18, weight="bold"),
            command=self._show_help,
        )
        self.help_button.pack(side="left")
        bind_press_feedback(self._anim, self.help_button)

        # Sidebar — narrow utility column; catalog owns the window
        sidebar_shell, sidebar_inner = glass_shell(
            self, elevated=True, corner_radius=18, rim=False, width=SIDEBAR_WIDTH
        )
        sidebar_shell.grid(row=1, column=0, sticky="nsw", padx=(14, 8), pady=10)
        sidebar_shell.grid_propagate(False)
        sidebar_shell.configure(width=SIDEBAR_WIDTH)
        sidebar_inner.grid_rowconfigure(0, weight=1)
        sidebar_inner.grid_columnconfigure(0, weight=1)
        self._sidebar = sidebar_shell

        sidebar = ctk.CTkScrollableFrame(
            sidebar_inner,
            fg_color="transparent",
            width=SIDEBAR_WIDTH - 28,
            scrollbar_button_color=THEME["glass_border"],
            scrollbar_button_hover_color=THEME["muted"],
        )
        sidebar.grid(row=0, column=0, sticky="nsew", padx=4, pady=6)
        self._sidebar_scroll = sidebar

        self._section_label(sidebar, "Apple ID")
        self.auth_status_label = ctk.CTkLabel(
            sidebar,
            text="Статус: не проверен",
            wraplength=220,
            justify="left",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
        )
        self.auth_status_label.pack(anchor="w", padx=14, pady=(0, 8))

        login_btn = self._action_button(sidebar, "Войти в Apple ID", self._login_dialog)
        login_btn.pack(fill="x", padx=12, pady=3)
        bind_press_feedback(self._anim, login_btn)
        self._action_button(sidebar, "Обновить статус", self._update_auth_status, secondary=True).pack(
            fill="x", padx=12, pady=3
        )
        self._action_button(sidebar, "Выйти из Apple ID", self._logout, secondary=True).pack(
            fill="x", padx=12, pady=3
        )

        self._section_label(sidebar, "Устройства", top_pad=18)
        device_card = glass_frame(sidebar, elevated=True, corner_radius=14)
        device_card.pack(fill="x", padx=10, pady=(0, 8))

        self.device_name_label = ctk.CTkLabel(
            device_card,
            text="iPhone не подключён",
            font=ui_font(14, weight="bold"),
            text_color=THEME["text"],
            anchor="w",
            wraplength=210,
            justify="left",
        )
        self.device_name_label.pack(anchor="w", padx=12, pady=(10, 4))

        status_row = ctk.CTkFrame(device_card, fg_color="transparent")
        status_row.pack(anchor="w", fill="x", padx=12, pady=(0, 4))
        self.device_status_pill = status_pill(status_row, "Нет связи", tone="neutral")
        self.device_status_pill.pack(side="left")

        self.device_connection_label = ctk.CTkLabel(
            device_card,
            text="Подключение: —",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
        )
        self.device_connection_label.pack(anchor="w", padx=12, pady=(0, 2))

        self.readiness_label = ctk.CTkLabel(
            device_card,
            text="Проверка системы...",
            wraplength=210,
            justify="left",
            font=ui_font(TYPE_META),
            text_color=THEME["text_secondary"],
        )
        self.readiness_label.pack(anchor="w", padx=12, pady=(0, 10))

        check_dev_btn = self._action_button(sidebar, "Проверить iPhone", self._check_device)
        check_dev_btn.pack(fill="x", padx=12, pady=3)
        bind_press_feedback(self._anim, check_dev_btn)
        self._action_button(sidebar, "Установить драйверы Apple", self._install_drivers, secondary=True).pack(
            fill="x", padx=12, pady=3
        )

        self._build_ifi_promo(sidebar)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=1, sticky="nsew", padx=(4, 14), pady=10)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(5, weight=1)

        # Install strip — compact; must not steal catalog viewport
        install_outer, install_inner = glass_shell(main, elevated=True, corner_radius=16, rim=False)
        install_outer.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        install_outer.configure(height=128)
        install_outer.grid_propagate(False)
        self._top_bar = install_outer
        self._install_card = install_inner
        self._install_card_outer = install_outer
        self._install_card_state = "idle"

        card_inner = ctk.CTkFrame(install_inner, fg_color="transparent")
        card_inner.pack(fill="both", expand=True, padx=12, pady=8)

        head = ctk.CTkFrame(card_inner, fg_color="transparent", height=52)
        head.pack(fill="x")
        head.pack_propagate(False)

        self.selected_icon_label = ctk.CTkLabel(
            head,
            text="",
            width=ICON_INSTALL,
            height=ICON_INSTALL,
            fg_color=THEME["chip"],
            corner_radius=12,
        )
        self.selected_icon_label.pack(side="left", padx=(0, 12))

        info_wrap = ctk.CTkFrame(head, fg_color="transparent")
        info_wrap.pack(side="left", fill="both", expand=True)

        self.selected_label = ctk.CTkLabel(
            info_wrap,
            text="Выберите приложение",
            font=ui_font(TYPE_TITLE, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        )
        self.selected_label.pack(anchor="w")

        self.selected_meta_label = ctk.CTkLabel(
            info_wrap,
            text="Чтобы начать установку, выберите приложение из каталога",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
            wraplength=520,
            justify="left",
        )
        self.selected_meta_label.pack(anchor="w", pady=(2, 0))

        divider = ctk.CTkFrame(card_inner, fg_color=THEME["glass_border"], height=1)
        divider.pack(fill="x", pady=(6, 6))
        self._install_divider = divider

        self._install_progress_wrap = ctk.CTkFrame(card_inner, fg_color="transparent", height=24)
        self._install_progress_wrap.pack(fill="x")
        self._install_progress_wrap.pack_propagate(False)
        self._install_progress_wrap.pack_forget()

        self._install_progress_bar = ctk.CTkProgressBar(
            self._install_progress_wrap,
            height=8,
            progress_color=THEME["accent"],
            fg_color=THEME["chip"],
            corner_radius=4,
        )
        self._install_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._install_progress_bar.set(0)
        self._install_progress_pct = ctk.CTkLabel(
            self._install_progress_wrap,
            text="0%",
            width=44,
            font=ui_font(TYPE_META, weight="bold"),
            text_color=THEME["text_secondary"],
            anchor="e",
        )
        self._install_progress_pct.pack(side="right")

        actions = ctk.CTkFrame(card_inner, fg_color="transparent", height=38)
        actions.pack(fill="x", pady=(0, 0))
        actions.pack_propagate(False)
        self._install_actions = actions

        self.install_button = primary_button(
            actions,
            text="Установить приложение",
            command=self._install_selected,
            width=220,
            height=36,
            font=ui_font(13, weight="bold"),
            corner_radius=12,
        )
        self.install_button.pack(side="left")
        self.install_button.configure(state="disabled")
        bind_press_feedback(self._anim, self.install_button)

        self._cancel_install_btn = secondary_button(
            actions,
            text="Отмена",
            command=self._cancel_install_queue,
            width=100,
            height=36,
            corner_radius=12,
        )
        self._retry_install_btn = secondary_button(
            actions,
            text="Повторить",
            command=self._retry_install_queue,
            width=112,
            height=36,
            corner_radius=12,
        )
        # Kept packed/unpacked by state sync — start hidden.
        self._cancel_install_btn.pack_forget()
        self._retry_install_btn.pack_forget()

        catalog_nav = ctk.CTkFrame(main, fg_color="transparent")
        catalog_nav.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        catalog_nav.grid_columnconfigure(1, weight=1)

        self.catalog_back_button = secondary_button(
            catalog_nav,
            text="← Назад",
            command=self._catalog_back,
            width=100,
            height=30,
        )
        self.catalog_back_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.catalog_back_button.grid_remove()

        self.catalog_path_label = ctk.CTkLabel(
            catalog_nav,
            text="Каталог",
            font=ui_font(TYPE_TITLE, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        )
        self.catalog_path_label.grid(row=0, column=1, sticky="w")

        # Search — compact Spotlight strip
        search_outer, search_inner = glass_shell(main, elevated=False, corner_radius=16, rim=False)
        search_outer.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        search_outer.configure(height=46)
        search_outer.grid_propagate(False)
        self._search_wrap = search_outer
        self._search_inner = search_inner

        search_row = ctk.CTkFrame(search_inner, fg_color="transparent")
        search_row.pack(fill="both", expand=True, padx=8, pady=4)
        search_row.grid_columnconfigure(1, weight=1)

        search_icon = ctk.CTkLabel(
            search_row,
            text="⌕",
            width=26,
            font=ui_font(18),
            text_color=THEME["muted"],
            anchor="center",
        )
        search_icon.grid(row=0, column=0, padx=(6, 4), pady=0)
        self._search_icon = search_icon

        self.bank_search_var = tk.StringVar()
        self.bank_search_entry = ctk.CTkEntry(
            search_row,
            textvariable=self.bank_search_var,
            placeholder_text="Поиск приложений",
            height=34,
            corner_radius=10,
            border_width=0,
            fg_color=THEME["input"],
            text_color=THEME["text"],
            placeholder_text_color=THEME["muted"],
            font=ui_font(14),
        )
        self.bank_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=1)
        self.bank_search_var.trace_add("write", lambda *_: self._on_search_text_changed())
        self.bank_search_entry.bind("<Return>", lambda _e: self._commit_search())
        self.bank_search_entry.bind("<FocusIn>", lambda _e: self._on_search_focus(True))
        self.bank_search_entry.bind("<FocusOut>", lambda _e: self._on_search_focus(False))

        self._search_hint = ctk.CTkLabel(
            search_row,
            text="Поиск",
            font=ui_font(TYPE_CAPTION, weight="bold"),
            text_color=THEME["muted"],
            width=48,
            anchor="e",
        )
        self._search_hint.grid(row=0, column=2, padx=(0, 8))
        self._update_search_chrome()

        tabs_wrap = ctk.CTkFrame(main, fg_color="transparent")
        tabs_wrap.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        tab_titles = tab_labels(self.catalog.tabs)
        selected_tab = tab_by_id(self.catalog.tabs, self._catalog_tab)
        self._catalog_tabs = catalog_tab_bar(
            tabs_wrap,
            values=tab_titles,
            command=self._on_catalog_tab,
            selected=(selected_tab.title if selected_tab else tab_titles[0]),
            anim=self._anim,
        )
        self._tabs_wrap = tabs_wrap

        self.recent_searches_frame = ctk.CTkFrame(main, fg_color="transparent")
        self.recent_searches_frame.grid(row=4, column=0, sticky="ew", pady=(0, 4))

        # Catalog plane — single-layer tray so the list gets max height
        list_outer, list_inner = glass_shell(main, elevated=False, corner_radius=16, rim=False)
        list_outer.grid(row=5, column=0, sticky="nsew")
        list_inner.grid_rowconfigure(0, weight=1)
        list_inner.grid_columnconfigure(0, weight=1)
        self._catalog_shell = list_outer

        self.app_list = ctk.CTkScrollableFrame(
            list_inner,
            fg_color=THEME["bg_soft"],
            corner_radius=12,
            border_width=0,
            scrollbar_button_color=THEME["glass_border"],
            scrollbar_button_hover_color=THEME["muted"],
        )
        self.app_list.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self._style_app_list()

        log_outer, log_inner = glass_shell(main, elevated=True, corner_radius=16, rim=False)
        log_outer.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        log_inner.grid_columnconfigure(0, weight=1)
        self._log_frame = log_outer
        self._log_inner = log_inner
        log_outer.grid_remove()

        self.log_title = ctk.CTkLabel(
            log_inner,
            text="Журнал",
            font=ui_font(13, weight="bold"),
            text_color=THEME["text"],
        )
        self.log_title.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self.progress_frame = ctk.CTkFrame(log_inner, fg_color="transparent")
        self.progress_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 8))
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
                font=ui_font(TYPE_CAPTION),
                height=26,
                padx=10,
            )
            pill.pack(side="left", padx=(0 if index == 0 else 5, 0))
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
            log_inner,
            height=72,
            fg_color=THEME["log"],
            border_width=1,
            border_color=THEME["glass_border"],
            text_color=THEME["silver"],
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_box.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.log_box.configure(state="disabled")
        # Hidden for normal users — progress bar stays; unlock via 5 clicks on version.
        self.log_title.grid_remove()
        self.log_box.grid_remove()

    def _section_label(self, parent: ctk.CTkFrame, text: str, *, top_pad: int = 12) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text.upper(),
            font=ui_font(TYPE_SECTION, weight="bold"),
            text_color=THEME["muted"],
        )
        label.pack(anchor="w", padx=14, pady=(top_pad, 6))
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

    def _build_ifi_promo(self, parent: ctk.CTkBaseClass) -> None:
        """IFI.VPN promo card — left sidebar, under Devices."""
        card = ctk.CTkFrame(
            parent,
            fg_color=THEME["promo"],
            corner_radius=22,
            border_width=1,
            border_color=THEME["promo_border"],
        )
        card.pack(fill="x", padx=10, pady=(14, 12))

        def open_ifi(_event: object = None) -> None:
            webbrowser.open(_IFI_VPN_URL)

        def on_enter(_event: object = None) -> None:
            card.configure(fg_color=THEME["promo_hover"], border_color=THEME["glass_border_bright"])

        def on_leave(_event: object = None) -> None:
            card.configure(fg_color=THEME["promo"], border_color=THEME["promo_border"])

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        card.bind("<Button-1>", open_ifi)
        card.configure(cursor="hand2")

        ctk.CTkLabel(
            card,
            text="IFI.VPN",
            font=ui_font(16, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(12, 2))

        ctk.CTkLabel(
            card,
            text="VPN для безопасного и стабильного подключения",
            font=ui_font(12),
            text_color=THEME["muted"],
            wraplength=240,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Stacked promo block: code chip → discount → full-width Copy
        # (side-by-side clipped «Копировать» in the narrow sidebar)
        promo_block = ctk.CTkFrame(card, fg_color="transparent")
        promo_block.pack(fill="x", padx=14, pady=(0, 6))

        code_chip = ctk.CTkFrame(
            promo_block,
            fg_color=THEME["chip"],
            corner_radius=10,
            border_width=1,
            border_color=THEME["glass_border"],
        )
        code_chip.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            code_chip,
            text=_IFI_PROMO_CODE,
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=THEME["accent"],
            anchor="center",
        ).pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(
            promo_block,
            text="Скидка 20%",
            font=ui_font(14, weight="bold"),
            text_color=THEME["silver"],
            anchor="center",
        ).pack(fill="x", pady=(2, 8))

        def copy_promo() -> None:
            try:
                self.clipboard_clear()
                self.clipboard_append(_IFI_PROMO_CODE)
                self._toast("Промокод скопирован", kind="success")
            except tk.TclError:
                self._toast("Не удалось скопировать промокод", kind="warning")

        copy_btn = secondary_button(
            promo_block,
            text="Копировать",
            command=copy_promo,
            height=30,
            font=ui_font(12, weight="bold"),
        )
        copy_btn.pack(fill="x")
        # Don't bubble click to card open
        copy_btn.bind("<Button-1>", lambda e: "break")

        cta = primary_button(
            card,
            text="Открыть IFI.VPN",
            command=open_ifi,
            height=34,
            font=ui_font(12, weight="bold"),
        )
        cta.pack(fill="x", padx=14, pady=(4, 12))
        bind_press_feedback(self._anim, cta)

    def _open_telegram_support(self) -> None:
        """Open support chat in Telegram app if possible, else browser."""
        try:
            os.startfile(_SUPPORT_TELEGRAM_APP)  # noqa: S606
            return
        except OSError:
            pass
        webbrowser.open(_SUPPORT_TELEGRAM)

    def _style_app_list(self) -> None:
        """Keep CTkScrollableFrame canvas/scrollbar in sync with soft catalog tray."""
        app_list = getattr(self, "app_list", None)
        if app_list is None:
            return
        try:
            app_list.configure(
                fg_color=THEME["bg_soft"],
                scrollbar_button_color=THEME["glass_border"],
                scrollbar_button_hover_color=THEME["muted"],
            )
        except tk.TclError:
            return
        # Defensive: some CTK builds leave the raw tk canvas on the previous mode.
        try:
            canvas = getattr(app_list, "_parent_canvas", None)
            if canvas is not None:
                canvas.configure(bg=THEME["bg_soft"])
            tk.Frame.configure(app_list, bg=THEME["bg_soft"])
        except tk.TclError:
            pass

    def _scroll_catalog_to_top(self) -> None:
        """Reset catalog list scroll so tab/bank/search switches always start at top."""
        app_list = getattr(self, "app_list", None)
        if app_list is None:
            return
        try:
            canvas = getattr(app_list, "_parent_canvas", None)
            if canvas is not None:
                canvas.yview_moveto(0)
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

    def _log_exception(self, where: str, exc: BaseException) -> None:
        """Surface unexpected errors instead of silent pass."""
        message = f"[ошибка] {where}: {type(exc).__name__}: {exc}"
        try:
            self._log(message)
        except Exception:
            pass
        try:
            path = data_dir() / "runtime_errors.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
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
        # Prefer UDID frozen at enqueue time — never retarget mid-queue.
        udid = (job.udid or self._selected_udid or "").strip() or None
        if not udid:
            devices = self.device_installer.list_usb_devices()
            if len(devices) == 1:
                udid = devices[0].udid
            elif len(devices) > 1:
                raise DeviceInstallerError(
                    "Подключено несколько iPhone по USB.\nВыберите устройство перед установкой."
                )
            else:
                raise DeviceInstallerError(
                    "iPhone по USB не найден.\nПодключите кабель и нажмите «Доверять»."
                )

        def on_phase(phase: str, value: float, text: str) -> None:
            if text.startswith("FairPlay:") or text.startswith("Предупреждение:"):
                self.after(0, lambda t=text: self._log(t))
            progress(phase, value, text)

        # Never clear cancel flags if the queue already requested cancel.
        if self._install_queue.cancel_event.is_set():
            raise IpatoolCancelled("Операция отменена.")
        self.ipatool.clear_cancel()
        self.device_installer.clear_cancel()
        run_install_job(
            app=job.app,
            ipatool=self.ipatool,
            device_installer=self.device_installer,
            config_manager=self.config_manager,
            udid=udid,
            on_phase=on_phase,
            cancel_event=self._install_queue.cancel_event,
        )

    def _refresh_queue_ui(self) -> None:
        jobs = self._install_queue.jobs
        busy = self._install_queue.is_busy

        if not busy and not any(job.status == JobStatus.RUNNING for job in jobs):
            try:
                self._hide_progress()
            except Exception as exc:
                self._log_exception("hide_progress", exc)

        for job in jobs:
            prev = self._queue_seen.get(job.id)
            status = job.status.value
            if prev == status:
                continue
            self._queue_seen[job.id] = status
            title = job.app.maskTitle or job.app.title
            if job.status == JobStatus.DONE and prev == JobStatus.RUNNING.value:
                self._log(f"Установлено: {title}")
                try:
                    self.settings.record_install_result(
                        job.app.id, title=title, result="ok"
                    )
                except Exception as exc:
                    self._log_exception("record_install_result", exc)
                target_udid = job.udid or self._selected_udid
                target = next((d for d in self._devices if d.udid == target_udid), None)
                target_name = (target.name if target else None) or "iPhone"
                self._toast(f"Установлено на {target_name}: {title}", kind="success")
                self._install.note_success(title)
                account = self.config_manager.apple_account_email or ""
                if account:
                    self._log(
                        f"Подсказка: до установки на iPhone уже должен быть {mask_email(account)} "
                        f"в «Медиаматериалы и покупки»; смена аккаунта после установки часто не помогает."
                    )
                self._fairplay_checklist_pending = True
            elif job.status == JobStatus.FAILED and prev == JobStatus.RUNNING.value:
                self._install.note_failure(job.app)
                try:
                    self.settings.record_install_result(
                        job.app.id,
                        title=title,
                        result="error",
                        error=str(job.error or ""),
                    )
                except Exception as exc:
                    self._log_exception("record_install_result", exc)
                title_e, message = friendly_error(job.error or "Ошибка", domain="Установка")
                self._toast(f"Ошибка: {title}", kind="error")
                messagebox.showerror(title_e, f"«{title}»\n\n{message}")
            elif job.status == JobStatus.CANCELLED and prev in (
                JobStatus.RUNNING.value,
                JobStatus.PENDING.value,
                None,
            ):
                self._toast(f"Отменено: {title}", kind="info")
                self._log(f"Отменено: {title}")

        if (
            self._fairplay_checklist_pending
            and not busy
            and not any(job.status == JobStatus.RUNNING for job in jobs)
        ):
            self._fairplay_checklist_pending = False
            self.after(200, self._show_fairplay_launch_checklist)

        self._sync_install_card()

    def _show_fairplay_launch_checklist(self) -> None:
        account = self.config_manager.apple_account_email or ""
        masked = mask_email(account) if account else "тот же, что в GROMOV"
        messagebox.showinfo(
            "Чтобы приложение открылось",
            "Установка прошла. Открытие на iPhone проверяет лицензию FairPlay.\n\n"
            f"Важно: аккаунт на телефоне должен совпадать с GROMOV ({masked}) "
            "ДО установки. Смена «Медиа и покупки» после установки часто не помогает.\n\n"
            f"1. Настройки → [имя] → Медиаматериалы и покупки → {masked}\n"
            "2. iPhone онлайн (Wi‑Fi / LTE)\n"
            "3. Удалите ярлык со старой установки и поставьте снова уже под этим ID\n"
            "4. Откройте приложение; если спросит пароль Apple ID — введите\n"
            "5. Если снова вылет: в App Store скачайте любое приложение этим ID, затем повторите",
        )

    def _cancel_install_queue(self) -> None:
        if not self._install.is_busy:
            return
        self._install.cancel_all()
        self._toast("Отмена установки…", kind="info")
        self._log("Очередь установки: отмена")

    def _retry_install_queue(self) -> None:
        count = self._install.retry_failed()
        if count:
            self._toast(f"Повтор: {count}", kind="info")
            self._log(f"Повтор установки: {count}")
            return
        if self._install.last_failed_app is not None:
            self._enqueue_apps([self._install.last_failed_app])
            return
        messagebox.showinfo("Очередь", "Нет заданий для повтора.")

    def _remember_devices(self, devices: list[DeviceInfo]) -> None:
        self._devices = devices
        busy = self._install_queue.is_busy
        if self._selected_udid and not any(d.udid == self._selected_udid for d in devices):
            # Previously chosen phone was unplugged — never silently switch to another.
            self._selected_udid = None
            self.settings.selected_udid = None
        elif not devices:
            self._selected_udid = None
            self.settings.selected_udid = None
        elif len(devices) == 1 and not busy:
            # Auto-bind only when idle; mid-queue target stays on job.udid.
            self._selected_udid = devices[0].udid
            self.settings.selected_udid = devices[0].udid
        self._apply_device_ui(devices)

    def _poll_usb_devices(self) -> None:
        """Refresh USB readiness periodically so plug/unplug is reflected without restart."""

        def task() -> None:
            try:
                devices = self.device_installer.list_usb_devices()
            except Exception:
                devices = []

            def apply() -> None:
                prev = {d.udid for d in self._devices}
                now = {d.udid for d in devices}
                self._remember_devices(devices)
                if prev != now and not self._install_queue.is_busy:
                    self._refresh_readiness()
                # Reschedule on UI thread only (tkinter is not thread-safe).
                self.after(8000, self._poll_usb_devices)

            self.after(0, apply)

        threading.Thread(target=task, daemon=True).start()

    def _usb_not_connected_message(self) -> str:
        return (
            "Подключите iPhone к компьютеру через USB-кабель\n\n"
            "1. Подключите iPhone к ПК через USB.\n"
            "2. Разблокируйте iPhone.\n"
            "3. Нажмите «Доверять этому компьютеру», если появится запрос.\n"
            "4. После обнаружения устройства можно начинать установку.\n\n"
            "Устройства в той же Wi‑Fi сети не используются — только кабель."
        )

    def _confirm_device_for_install(self) -> str | None:
        try:
            devices = self.device_installer.list_usb_devices()
            self._remember_devices(devices)
        except DeviceInstallerError as exc:
            title, message = friendly_error(exc, domain="iPhone")
            messagebox.showerror(title, message)
            return None
        if not devices:
            messagebox.showwarning("iPhone", self._usb_not_connected_message())
            self._apply_device_ui([])
            return None
        if len(devices) == 1:
            device = devices[0]
            self._toast(f"Установка на {device.name or 'iPhone'} (USB)", kind="info")
        else:
            device = pick_usb_device(self, devices)
            if device is None:
                return None
            # Re-validate after picker (user might unplug while choosing).
            try:
                live = self.device_installer.list_usb_devices()
            except DeviceInstallerError as exc:
                title, message = friendly_error(exc, domain="iPhone")
                messagebox.showerror(title, message)
                return None
            if not any(d.udid == device.udid for d in live):
                messagebox.showwarning(
                    "iPhone",
                    "Выбранный iPhone отключён.\nПодключите его по USB и повторите.",
                )
                return None
            devices = live
        self._selected_udid = device.udid
        self.settings.selected_udid = device.udid
        self._remember_devices(devices)
        self._refresh_readiness()
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
        added = self._install.enqueue(apps, udid=udid)
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
                        f"Отчёт сохранён:\n{path}\n\nОтправьте файл в Telegram @gromov_restore",
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
            devices = self.device_installer.list_usb_devices()
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
        # Mirror into install card (stable UX).
        try:
            self._install_progress_wrap.pack(fill="x", before=self._install_actions)
            self._install_progress_bar.set(self._progress_value)
            self._install_progress_pct.configure(text=f"{int(self._progress_value * 100)}%")
            if self.selected_app:
                name = self.selected_app.maskTitle or self.selected_app.title
                self.selected_label.configure(text=f"Установка «{name}»…")
                self.selected_meta_label.configure(text=text or "Идёт установка")
        except Exception:
            pass

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
        try:
            self._install_progress_bar.set(0)
            self._install_progress_pct.configure(text="0%")
            self._install_progress_wrap.pack_forget()
        except Exception:
            pass

    def _progress_callback(self) -> Callable[[float, str], None]:
        def callback(value: float, text: str) -> None:
            self.after(0, lambda v=value, t=text: self._set_progress(t, v))

        return callback

    def _collect_readiness(self) -> tuple[str, str, str]:
        driver_ok = apple_drivers_installed()
        driver_line = (
            "Драйверы Apple: установлены" if driver_ok else "Драйверы Apple: не установлены"
        )
        try:
            devices = self.device_installer.list_usb_devices()
            if len(devices) == 1:
                device = devices[0]
                device_name = device.name or "iPhone"
                if len(device_name) > 36:
                    device_name = device_name[:33] + "..."
                device_line = f"USB: {device.label}"
            elif len(devices) > 1:
                device_line = f"USB: подключено {len(devices)} iPhone — выберите при установке"
            else:
                device_line = "USB: iPhone не найден"
        except DeviceInstallerError:
            devices = []
            device_line = "USB: iPhone не найден"
        return driver_line, device_line, f"{driver_line}\n{device_line}"

    def _apply_device_ui(self, devices: list[DeviceInfo] | None = None) -> None:
        """Refresh Devices card: name, status pill, connection, driver hint."""
        if devices is None:
            try:
                devices = self.device_installer.list_usb_devices()
            except DeviceInstallerError:
                devices = []

        driver_ok = apple_drivers_installed()
        driver_hint = (
            "Драйверы Apple установлены" if driver_ok else "Нужны драйверы Apple"
        )

        name_label = getattr(self, "device_name_label", None)
        status_widget = getattr(self, "device_status_pill", None)
        conn_label = getattr(self, "device_connection_label", None)
        ready_label = getattr(self, "readiness_label", None)
        if name_label is None:
            return

        if len(devices) == 1:
            device = devices[0]
            name = device.name or "iPhone"
            meta = " · ".join(p for p in (device.model, f"iOS {device.ios_version}" if device.ios_version else "") if p)
            name_label.configure(text=name if not meta else f"{name}\n{meta}")
            if status_widget is not None:
                status_widget.configure(
                    text="Подключён",
                    fg_color=THEME["success_soft"],
                    text_color=THEME["success"],
                )
            if conn_label is not None:
                conn_label.configure(text="Подключение: USB")
            if ready_label is not None:
                ready_label.configure(text=driver_hint)
        elif len(devices) > 1:
            name_label.configure(text=f"{len(devices)} iPhone по USB")
            if status_widget is not None:
                status_widget.configure(
                    text="Несколько устройств",
                    fg_color=THEME["accent_soft"],
                    text_color=THEME["accent"],
                )
            if conn_label is not None:
                conn_label.configure(text="Подключение: USB — выберите при установке")
            if ready_label is not None:
                ready_label.configure(text=driver_hint)
        else:
            name_label.configure(text="iPhone не подключён")
            if status_widget is not None:
                status_widget.configure(
                    text="Нет связи",
                    fg_color=THEME["chip"],
                    text_color=THEME["text_secondary"],
                )
            if conn_label is not None:
                conn_label.configure(text="Подключение: —")
            if ready_label is not None:
                ready_label.configure(
                    text=f"{driver_hint}\nПодключите iPhone кабелем USB"
                )

    def _refresh_readiness(self, *, log: bool = False) -> None:
        driver_line, device_line, combined = self._collect_readiness()
        try:
            devices = self.device_installer.list_usb_devices()
        except DeviceInstallerError:
            devices = []
        self._apply_device_ui(devices)
        if log:
            self._log("--- Проверка системы ---")
            self._log(driver_line)
            self._log(device_line)

    def _warm_icon_cache(self) -> None:
        """Warm PIL disk cache for Popular only — never create CTkImage off UI thread."""

        def task() -> None:
            try:
                apps: list[AppEntry] = []
                groups: list[BankGroup] = []
                for item_id in self.config_manager.popular_item_ids():
                    if item_id.startswith("@bank:"):
                        group = self.config_manager.get_bank_group(item_id.split(":", 1)[1])
                        if group:
                            groups.append(group)
                    elif item_id.startswith("@version:"):
                        group = self.config_manager.get_version_group(item_id.split(":", 1)[1])
                        if group:
                            app = self.config_manager.get_app(group.icon_app_id)
                            if app:
                                apps.append(app)
                    else:
                        app = self.config_manager.get_app(item_id)
                        if app:
                            apps.append(app)
                self.icon_loader.warm_apps(apps, size=ICON_CARD)
                self.icon_loader.warm_bank_groups(groups, size=ICON_CARD)
            except Exception as exc:
                self.after(0, lambda e=exc: self._log_exception("warm_icon_cache", e))

        threading.Thread(target=task, daemon=True).start()

    def _startup_checks(self) -> None:
        def task() -> None:
            try:
                strict = bool(getattr(sys, "frozen", False))
                problems = verify_bundled_tools(strict=strict)
                if problems:
                    self.after(0, lambda p=problems: self._log("Проверка tools: " + "; ".join(p)))
            except Exception as exc:
                self.after(0, lambda e=exc: self._log_exception("verify_bundled_tools", e))
                if getattr(sys, "frozen", False):
                    self.after(
                        0,
                        lambda e=exc: messagebox.showerror(
                            "Целостность",
                            "Проверка встроенных инструментов не пройдена.\n"
                            f"{e}\n\nПереустановите GROMOV Restore+.",
                        ),
                    )

            driver_line, device_line, _combined = self._collect_readiness()
            self.after(0, self._refresh_readiness)
            self.after(0, lambda: self._log("--- Проверка при запуске ---"))
            self.after(0, lambda: self._log(driver_line))
            self.after(0, lambda: self._log(device_line))

            try:
                devices = self.device_installer.list_usb_devices()
                self.after(0, lambda d=devices: self._remember_devices(d))
            except Exception as exc:
                self.after(0, lambda e=exc: self._log_exception("startup_list_usb", e))

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

    def _on_search_text_changed(self) -> None:
        self._update_search_chrome()
        self._search_debouncer.trigger()

    def _update_search_chrome(self) -> None:
        """Keep search affordance visible: icon always on; 'Поиск' label when empty."""
        hint = getattr(self, "_search_hint", None)
        if hint is None:
            return
        has_text = bool(self.bank_search_var.get().strip())
        try:
            if has_text:
                hint.grid_remove()
            else:
                hint.grid()
        except tk.TclError:
            pass

    def _on_search_focus(self, focused: bool) -> None:
        outer = getattr(self, "_search_wrap", None)
        inner = getattr(self, "_search_inner", None)
        if outer is None:
            return
        try:
            outer.configure(
                border_color=THEME["accent"] if focused else THEME["glass_border"],
                fg_color=THEME["accent_soft"] if focused else THEME["glass_outer"],
            )
            if inner is not None:
                inner.configure(
                    fg_color=THEME["input_focus"] if focused else THEME["glass_inner"],
                    border_color=THEME["accent_glow"] if focused else THEME["glass_edge"],
                )
            self.bank_search_entry.configure(
                fg_color=THEME["input_focus"] if focused else THEME["input"],
            )
            if getattr(self, "_search_icon", None) is not None:
                self._search_icon.configure(
                    text_color=THEME["accent"] if focused else THEME["text_secondary"],
                )
            if getattr(self, "_search_hint", None) is not None and not self.bank_search_var.get().strip():
                self._search_hint.configure(
                    text_color=THEME["accent"] if focused else THEME["muted"],
                )
        except tk.TclError:
            pass

    def _clear_app_selection(self) -> None:
        self.selected_app = None
        self._selected_icon_ref = None
        self._install.clear_success()
        try:
            self.selected_icon_label.configure(image="")
        except tk.TclError:
            pass
        self._sync_install_card()

    def _install_another(self) -> None:
        """Reset card to idle after successful install."""
        self._install.clear_outcome()
        self._clear_app_selection()

    def _sync_install_card(self) -> None:
        """Drive install-card UI states without changing layout geometry."""
        if not getattr(self, "install_button", None):
            return

        busy = self._async_busy or self._install.is_busy or self._update_busy or self.updates.busy
        has_failed = bool(self._install.last_failed_app) and not busy
        just_done = bool(self._install.last_installed_title) and not busy and not has_failed

        # Reset action buttons packing (fixed slots via pack order).
        for btn in (self.install_button, self._cancel_install_btn, self._retry_install_btn):
            try:
                btn.pack_forget()
            except tk.TclError:
                pass

        if busy:
            self._install_card_state = "installing"
            name = ""
            if self.selected_app:
                name = self.selected_app.maskTitle or self.selected_app.title
            elif self._install.current:
                app = self._install.current.app
                name = app.maskTitle or app.title
            self.selected_label.configure(text=f"Установка «{name or 'приложения'}»…")
            phase = str(self.progress_label.cget("text") or "").strip()
            self.selected_meta_label.configure(text=phase or "Идёт установка на iPhone")
            try:
                self._install_progress_wrap.pack(fill="x", before=self._install_actions)
            except tk.TclError:
                self._install_progress_wrap.pack(fill="x")
            self._cancel_install_btn.pack(side="left")
            self.install_button.configure(state="disabled")
            self._paint_install_card()
            return

        try:
            self._install_progress_wrap.pack_forget()
        except tk.TclError:
            pass

        if has_failed and self._install.last_failed_app is not None:
            self._install_card_state = "error"
            app = self._install.last_failed_app
            title = app.maskTitle or app.title
            self.selected_label.configure(text=title)
            self.selected_meta_label.configure(text="Не удалось установить — можно повторить")
            icon = self.icon_loader.get_app_icon(app, size=ICON_INSTALL)
            self._selected_icon_ref = icon
            self.selected_icon_label.configure(image=icon)
            self._retry_install_btn.pack(side="left")
            self.install_button.configure(
                text="Установить приложение",
                command=self._install_selected,
                state="disabled",
            )
            self._paint_install_card()
            return

        if just_done:
            self._install_card_state = "done"
            title = self._install.last_installed_title
            self.selected_label.configure(text="✓ Установлено")
            self.selected_meta_label.configure(text=f"«{title}» успешно установлено")
            self.install_button.configure(
                text="Установить другое",
                command=self._install_another,
                state="normal",
            )
            self.install_button.pack(side="left")
            self._paint_install_card()
            return

        if self.selected_app is not None:
            self._install_card_state = "ready"
            app = self.selected_app
            title = app.maskTitle or app.title
            self.selected_label.configure(text=title)
            self.selected_meta_label.configure(text="Готово к установке")
            self.install_button.configure(
                text="Установить приложение",
                command=self._install_selected,
                state="normal",
            )
            self.install_button.pack(side="left")
            self._paint_install_card()
            return

        self._install_card_state = "idle"
        self.selected_label.configure(text="Выберите приложение")
        self.selected_meta_label.configure(
            text="Чтобы начать установку, выберите приложение из каталога"
        )
        try:
            self.selected_icon_label.configure(image="")
        except tk.TclError:
            pass
        self.install_button.configure(
            text="Установить приложение",
            command=self._install_selected,
            state="disabled",
        )
        self.install_button.pack(side="left")
        self._paint_install_card()

    def _paint_install_card(self) -> None:
        """Apply Liquid Glass state fill to the install card (inner + outer shell)."""
        card = getattr(self, "_install_card", None)
        outer = getattr(self, "_install_card_outer", None)
        if card is None:
            return
        fills = {
            "idle": THEME.get("card_idle", THEME["glass_inner"]),
            "ready": THEME.get("card_ready", THEME["accent_soft"]),
            "installing": THEME.get("card_installing", THEME["accent_soft"]),
            "done": THEME.get("card_done", THEME["success_soft"]),
            "error": THEME.get("card_error", THEME["error_soft"]),
        }
        borders = {
            "idle": THEME["glass_border"],
            "ready": THEME["accent"],
            "installing": THEME["accent_hover"],
            "done": THEME["success"],
            "error": THEME["error"],
        }
        state = getattr(self, "_install_card_state", "idle")
        try:
            card.configure(
                fg_color=fills.get(state, fills["idle"]),
                border_color=borders.get(state, borders["idle"]),
                border_width=1,
            )
            if outer is not None:
                outer.configure(
                    fg_color=THEME["glass_outer"],
                    border_color=borders.get(state, borders["idle"]) if state != "idle" else THEME["glass_border"],
                )
        except tk.TclError:
            pass

    def _update_selection_bar(self) -> None:
        # Card is always visible — state is driven by _sync_install_card.
        self._sync_install_card()

    def _update_install_button_state(self) -> None:
        self._sync_install_card()

    def _set_busy(self, busy: bool) -> None:
        self._async_busy = busy
        self._sync_install_card()

    def _run_async(self, task: Callable[[], None]) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Подождите", "Операция уже выполняется.")
            return

        def runner() -> None:
            self.after(0, lambda: self._set_busy(True))
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
        """Refresh Apple ID session status from ipatool (does not open login)."""
        self._try_init_ipatool(show_errors=False)
        if not self.ipatool:
            self.auth_status_label.configure(text="Статус: ipatool не найден")
            self._toast("ipatool не найден", kind="error")
            return

        self.auth_status_label.configure(text="Проверка сессии…")

        def task() -> None:
            try:
                info = self.ipatool.auth_info()
                email = info.get("email") or info.get("appleId") or "выполнен вход"
                if isinstance(email, str) and "@" in email:
                    self.config_manager.set_apple_account(email)
                masked = mask_email(str(email)) if isinstance(email, str) else "…"

                def ok() -> None:
                    self.auth_status_label.configure(text=f"Авторизован\n{masked}")
                    self._log(f"Apple ID: {masked}")
                    self._toast(f"Сессия активна: {masked}", kind="success")

                self.after(0, ok)
            except IpatoolError as exc:
                self.config_manager.set_apple_account(None)
                message = str(exc)

                def fail() -> None:
                    self.auth_status_label.configure(text="Не авторизован")
                    self._log(message)
                    self._toast("Сессия не активна — войдите в Apple ID", kind="error")

                self.after(0, fail)

        self._run_async(task)

    def _login_dialog(self) -> None:
        self._try_init_ipatool()
        if not self.ipatool:
            return
        # A previous «Отмена» установки оставляла cancel-флаг и ломала вход.
        self.ipatool.clear_cancel()

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
    ) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("520x400")
        dialog.minsize(460, 300)
        dialog.resizable(False, True)
        dialog.transient(self)
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
        bind_press_feedback(self._anim, primary_btn)

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

    def _launch_verified_setup(self, installer: Path) -> None:
        """Start silent Inno Setup after SHA256 + Authenticode checks, then quit."""
        ok, detail = self.updates.verify_installer(installer)
        self._log(f"Authenticode: {detail}")
        if not ok:
            raise UpdateCheckError(
                "Цифровая подпись установщика не прошла проверку.\n"
                f"{detail}\n"
                "Обновление прервано для вашей безопасности."
            )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(  # noqa: S603 — local SHA256+Authenticode verified Setup.exe
                [str(installer), "/VERYSILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],
                close_fds=True,
                creationflags=flags,
            )
            self._log("Запущен проверенный установщик обновления.")
        except OSError as exc:
            raise UpdateCheckError(
                f"Файл проверен, но не удалось запустить установщик:\n{exc}"
            ) from exc

    def _download_update(self, result: UpdateCheckResult) -> None:
        if self._update_busy:
            messagebox.showwarning("Обновление", "Обновление уже выполняется.")
            return
        if not result.setup_url:
            self._show_update_action_dialog(
                title="GROMOV Restore+",
                message=(
                    "В манифесте обновлений нет ссылки на установщик.\n"
                    "Повторите проверку позже или напишите в поддержку."
                ),
                primary_text="Повторить",
                on_primary=self._check_updates,
                secondary_text="",
                tertiary_text="Закрыть",
            )
            return
        if not result.sha256:
            self._show_update_action_dialog(
                title="GROMOV Restore+",
                message=(
                    "В манифесте нет SHA256 установщика.\n"
                    "Загрузка отменена — так безопаснее.\n"
                    "Повторите проверку позже."
                ),
                primary_text="Повторить",
                on_primary=self._check_updates,
                secondary_text="",
                tertiary_text="Закрыть",
            )
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Обновление GROMOV Restore+")
        dialog.geometry("460x280")
        dialog.minsize(420, 260)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=THEME["bg"])
        dialog.after(50, lambda: apply_glass_window(dialog, dark=True))
        fade_in_window(dialog)

        card = glass_frame(dialog, elevated=True)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card,
            text="Обновление",
            font=ui_font(18, weight="bold"),
            text_color=THEME["text"],
        ).pack(anchor="w", padx=18, pady=(14, 4))

        status_label = ctk.CTkLabel(
            card,
            text="Проверяем обновление...",
            font=ui_font(13),
            text_color=THEME["text_secondary"],
            anchor="w",
        )
        status_label.pack(anchor="w", fill="x", padx=18, pady=(4, 8))

        percent_label = ctk.CTkLabel(
            card,
            text="",
            font=ui_font(12, weight="bold"),
            text_color=THEME["accent"],
            anchor="e",
        )
        percent_label.pack(anchor="e", padx=18)

        bar = ctk.CTkProgressBar(
            card,
            height=10,
            corner_radius=8,
            progress_color=THEME["accent"],
            fg_color=THEME["glass_border"],
        )
        bar.pack(fill="x", padx=18, pady=(4, 12))
        bar.set(0.02)

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(8, 14))

        cancel_event = threading.Event()
        self._update_cancel = cancel_event
        self._update_busy = True
        self.updates.begin(cancel_event)
        finished = {"done": False}

        def set_ui(status: str, ratio: float | None = None, percent: str = "") -> None:
            if not dialog.winfo_exists():
                return
            status_label.configure(text=status)
            if percent:
                percent_label.configure(text=percent)
            if ratio is not None:
                bar.set(max(0.0, min(1.0, ratio)))

        def show_error(message: str) -> None:
            if not dialog.winfo_exists():
                return
            self._update_busy = False
            self.updates.end()
            set_ui("Не удалось скачать обновление", 0.0, "")
            status_label.configure(text=sanitize_update_message(message), text_color=THEME["error"])
            for child in buttons.winfo_children():
                child.destroy()

            def retry() -> None:
                dialog.destroy()
                self._download_update(result)

            primary_button(buttons, text="Повторить", command=retry, width=120, height=36).pack(
                side="right"
            )
            secondary_button(buttons, text="Отмена", command=dialog.destroy, width=100, height=36).pack(
                side="right", padx=(0, 8)
            )

        def on_cancel() -> None:
            cancel_event.set()
            if not finished["done"]:
                set_ui("Отмена...", None)

        cancel_btn = secondary_button(buttons, text="Отмена", command=on_cancel, width=100, height=36)
        cancel_btn.pack(side="left")
        # Same as «Отмена»: closing via title-bar X must abort download (not leave _update_busy stuck).
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        def download_task() -> None:
            self.after(0, lambda: set_ui("Проверяем обновление...", 0.05))

            def on_progress(ratio: float) -> None:
                pct = int(ratio * 100)
                self.after(
                    0,
                    lambda r=ratio, p=pct: set_ui(
                        f"Загрузка обновления {p}%",
                        0.05 + r * 0.75,
                        f"{p}%",
                    ),
                )

            def on_status(text: str) -> None:
                if text.startswith("Загрузка"):
                    return
                self.after(0, lambda t=text: set_ui(t, None))

            try:
                installer = self.updates.download(
                    result,
                    on_progress=on_progress,
                    cancel_event=cancel_event,
                    on_status=on_status,
                )
            except UpdateCancelled:
                finished["done"] = True
                self._update_busy = False
                self.updates.end()
                self.after(0, lambda: dialog.destroy() if dialog.winfo_exists() else None)
                self.after(0, lambda: self._log("Обновление отменено."))
                return
            except UpdateCheckError as exc:
                message = sanitize_update_message(str(exc))
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(m))
                self.after(0, lambda p=debug_path: self._log(f"Диагностика обновления (файл): {p}"))
                self.after(0, lambda m=message: show_error(m))
                return
            except Exception as exc:  # noqa: BLE001
                message = f"Не удалось скачать обновление.\n{type(exc).__name__}: {exc}"
                self.after(0, lambda m=message: show_error(sanitize_update_message(m)))
                return

            self.after(0, lambda: set_ui("Подготовка обновления...", 0.92, "100%"))
            try:
                self._launch_verified_setup(installer)
            except UpdateCheckError as exc:
                self.after(0, lambda m=str(exc): show_error(m))
                return

            finished["done"] = True
            self._update_busy = False
            self.updates.end()
            self.after(0, lambda: set_ui("Обновление готово", 1.0, "100%"))
            self.after(0, lambda: self._log(f"Установщик проверен: {installer.name}"))
            self.after(0, lambda: self._toast("Обновление готово — перезапуск…", kind="success"))

            def restart() -> None:
                try:
                    if dialog.winfo_exists():
                        dialog.destroy()
                except tk.TclError:
                    pass
                self.quit()

            self.after(1200, restart)

        threading.Thread(target=download_task, daemon=True).start()

    def _present_update_available(self, result: UpdateCheckResult) -> None:
        notes = f"\n\n{result.notes}" if result.notes else ""
        message = (
            f"Версия {result.latest_version}\n"
            f"Текущая: {result.current_version}.{notes}\n\n"
            "Обновление установится внутри приложения "
            "(загрузка, проверка SHA256, перезапуск)."
        )

        def start_download() -> None:
            self._download_update(result)

        if self._toasts is not None:
            try:
                self._toasts.show_action(
                    f"Доступно обновление {result.latest_version}",
                    primary_text="Обновить",
                    on_primary=start_download,
                    secondary_text="Позже",
                )
            except Exception:
                pass

        self._show_update_action_dialog(
            title="Доступно новое обновление",
            message=message,
            primary_text="Обновить",
            on_primary=start_download,
            secondary_text="",
            tertiary_text="Позже",
        )

    def _present_update_check_failure(self, message: str) -> None:
        safe = sanitize_update_message(message)
        self._toast("Не удалось проверить обновления", kind="warning")
        self._show_update_action_dialog(
            title="GROMOV Restore+",
            message=(
                f"{safe}\n\n"
                "Проверьте интернет, VPN или другую сеть, затем повторите."
            ),
            primary_text="Повторить",
            on_primary=self._check_updates,
            secondary_text="",
            tertiary_text="Закрыть",
        )

    def _check_updates(self) -> None:
        if self._update_busy:
            messagebox.showwarning("Обновление", "Обновление уже выполняется.")
            return

        def task() -> None:
            self.after(0, lambda: self._log("Проверка обновлений..."))
            self.after(
                0,
                lambda: self.update_button.configure(state="disabled", text="…"),
            )
            try:
                result = self.updates.check()
            except UpdateCheckError as exc:
                message = sanitize_update_message(str(exc))
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(f"Обновление: {m}"))
                self.after(0, lambda p=debug_path: self._log(f"Диагностика обновления (файл): {p}"))
                self.after(0, lambda m=message: self._present_update_check_failure(m))
                return
            except Exception as exc:  # noqa: BLE001
                message = (
                    "Не удалось проверить обновления из-за внутренней ошибки.\n"
                    f"{type(exc).__name__}: {exc}"
                )
                debug_path = update_debug_log_path()
                self.after(0, lambda m=message: self._log(f"Обновление: {m}"))
                self.after(0, lambda p=debug_path: self._log(f"Диагностика обновления (файл): {p}"))
                self.after(
                    0,
                    lambda m=sanitize_update_message(message): self._present_update_check_failure(m),
                )
                return
            finally:
                self.after(
                    0,
                    lambda: self.update_button.configure(state="normal", text="Обновить"),
                )

            if result.is_up_to_date:
                text = f"У вас установлена последняя версия ({result.current_version})."
                self.after(0, lambda: self._log(text))
                self.after(0, lambda: self._toast(text, kind="success"))
                self.after(0, lambda: messagebox.showinfo("GROMOV Restore+", text))
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
                    "tab": str(payload.get("tab", "popular")),
                    "view": str(payload.get("view", "root")),
                    "bankGroup": str(payload.get("bankGroup", "")),
                }
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_catalog_state(self) -> None:
        payload = {
            "tab": self._catalog_tab,
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
        """Restore tab only — skip bank drill-down on cold start for faster first paint."""
        state = self._load_catalog_state()
        tab = state.get("tab", "popular")
        if tab_by_id(self.catalog.tabs, tab) is None:
            tab = self.catalog.tabs[0].id
        self._catalog_tab = tab
        self.catalog.set_tab(tab)
        self._catalog_view = "root"
        self._catalog_bank_group = None

    def _on_catalog_tab(self, label: str) -> None:
        found = tab_by_label(self.catalog.tabs, label)
        key = found.id if found else "popular"
        if (
            key == self._catalog_tab
            and self._catalog_view == "root"
            and not self._global_search_query
        ):
            return
        self._catalog_tab = key
        self.catalog.set_tab(key)
        self._catalog_view = "root"
        self._catalog_bank_group = None
        self._save_catalog_state()
        self._refresh_app_list()

    def _catalog_back(self) -> None:
        if self._catalog_view != "bank":
            return
        self._catalog_view = "root"
        self._catalog_bank_group = None
        self._catalog_tab = "banks"
        self.catalog.set_tab("banks")
        banks = tab_by_id(self.catalog.tabs, "banks")
        if self._catalog_tabs is not None and banks is not None:
            self._catalog_tabs.set(banks.title)
        self._bank_search_query = ""
        self.bank_search_var.set("")
        self._save_catalog_state()
        self._refresh_app_list()

    def _open_root_catalog(self) -> None:
        self._catalog_view = "root"
        self._catalog_bank_group = None
        self._bank_search_query = ""
        self.bank_search_var.set("")
        if self.selected_app and self.selected_app.is_banking:
            self._clear_app_selection()
        self._save_catalog_state()
        self._refresh_app_list()

    def _open_banks_folder(self) -> None:
        self._catalog_tab = "banks"
        self.catalog.set_tab("banks")
        self._catalog_view = "root"
        self._catalog_bank_group = None
        banks = tab_by_id(self.catalog.tabs, "banks")
        if self._catalog_tabs is not None and banks is not None:
            self._catalog_tabs.set(banks.title)
        self._bank_search_query = ""
        self.bank_search_var.set("")
        self._save_catalog_state()
        self._refresh_app_list()

    def _open_bank_group(self, bank_group_id: str) -> None:
        if not self.config_manager.get_bank_group(bank_group_id):
            return
        self._catalog_tab = "banks"
        self._catalog_view = "bank"
        self._catalog_bank_group = bank_group_id
        self._bank_search_query = ""
        self.bank_search_var.set("")
        self._save_catalog_state()
        self._refresh_app_list()

    def _apply_bank_search(self) -> None:
        query = self.config_manager.normalize_search_text(self.bank_search_var.get())
        if query == self._bank_search_query:
            return
        self._bank_search_query = query
        self._global_search_query = query
        self.catalog.set_search(query, scope="section")
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
            font=ui_font(TYPE_CAPTION),
            text_color=THEME["muted"],
        ).pack(side="left", padx=(0, 8))
        for item in recent[:5]:
            chip = ctk.CTkButton(
                frame,
                text=item,
                height=28,
                width=1,
                corner_radius=14,
                fg_color=THEME["chip"],
                hover_color=THEME["accent_soft"],
                text_color=THEME["text_secondary"],
                border_width=1,
                border_color=THEME["glass_border"],
                font=ui_font(TYPE_CAPTION),
                command=lambda q=item: self._use_recent_search(q),
            )
            chip.pack(side="left", padx=(0, 6))

    def _use_recent_search(self, query: str) -> None:
        self.bank_search_var.set(query)
        self._commit_search()

    def _update_catalog_header(self) -> None:
        if self._catalog_view == "bank" and self._catalog_bank_group:
            self.catalog_back_button.grid()
            if self._tabs_wrap is not None:
                self._tabs_wrap.grid_remove()
            group = self.config_manager.get_bank_group(self._catalog_bank_group)
            bank_title = group.title if group else "Банк"
            self.catalog_path_label.configure(text=f"Банки / {bank_title}")
            return

        self.catalog_back_button.grid_remove()
        if self._tabs_wrap is not None:
            self._tabs_wrap.grid()
        if self._catalog_tabs is not None:
            tab = tab_by_id(self.catalog.tabs, self._catalog_tab)
            label = tab.title if tab else "Популярные"
            try:
                self._catalog_tabs.set(label)
            except Exception:
                pass
        count = self.config_manager.catalog_app_count()
        self.catalog_path_label.configure(text=f"Каталог · {count}")

    def _filter_bank_apps(self, apps: list[AppEntry]) -> list[AppEntry]:
        query = self._bank_search_query.strip().lower()
        if not query:
            return apps
        return [app for app in apps if self.config_manager.app_matches_query(app, query)]

    def _catalog_host(self) -> ctk.CTkBaseClass:
        return self._catalog_parent if self._catalog_parent is not None else self.app_list

    def _catalog_panel_key(self) -> str:
        query = self._global_search_query.strip().lower()
        if self._catalog_view == "bank" and self._catalog_bank_group:
            return f"bank:{self._catalog_bank_group}:{query}"
        if query:
            return f"search:{self._catalog_tab}:{query}"
        return f"tab:{self._catalog_tab}"

    def _hide_catalog_panels(self) -> None:
        for frame in self._catalog_panels.values():
            try:
                frame.pack_forget()
            except tk.TclError:
                pass

    def _evict_search_panels(self) -> None:
        doomed = [key for key in self._catalog_panels if key.startswith("search:")]
        for key in doomed:
            self._destroy_catalog_panel(key)

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        self.after(0, callback)

    def _bind_async_app_icon(
        self,
        card: ctk.CTkFrame,
        app: AppEntry,
        *,
        size: int = ICON_CARD,
        token: int | None = None,
    ) -> None:
        _ = token  # kept for call-site compatibility; card existence is the gate
        cached = self.icon_loader.peek_app_icon(app, size)
        if cached is not None:
            self._icon_refs.append(cached)
            try:
                card.icon_label.configure(image=cached)  # type: ignore[attr-defined]
            except Exception:
                pass
            return

        def on_ready(photo: ctk.CTkImage) -> None:
            self._icon_refs.append(photo)
            try:
                if card.winfo_exists():
                    card.icon_label.configure(image=photo)  # type: ignore[attr-defined]
            except Exception:
                pass

        self.icon_loader.schedule_app_icon(
            app,
            size=size,
            on_ready=on_ready,
            schedule=self._schedule_ui,
        )

    def _cancel_batch_list(self) -> None:
        if self._batch_list is not None:
            try:
                self._batch_list.cancel()
            except Exception:
                pass
            self._batch_list = None

    def _destroy_catalog_panel(self, key: str) -> None:
        frame = self._catalog_panels.pop(key, None)
        self._catalog_panel_rows.pop(key, None)
        self._catalog_panel_complete.pop(key, None)
        if frame is None:
            return
        try:
            frame.destroy()
        except tk.TclError:
            pass

    def _purge_incomplete_catalog_panels(self) -> None:
        for key in list(self._catalog_panels):
            if not self._catalog_panel_complete.get(key, False):
                self._destroy_catalog_panel(key)

    def _mark_catalog_panel_complete(self, key: str, token: int) -> None:
        if token != self._catalog_anim_token:
            return
        if key not in self._catalog_panels:
            return
        self._catalog_panel_complete[key] = True
        self._catalog_panel_rows[key] = dict(self._app_rows)

    def _refresh_app_list(self) -> None:
        self._catalog_anim_token += 1
        token = self._catalog_anim_token
        self._anim.cancel_all()
        self._cancel_batch_list()
        self._purge_incomplete_catalog_panels()
        self._update_catalog_header()

        key = self._catalog_panel_key()
        self._hide_catalog_panels()

        # Reuse only fully built tab panels (never half-filled batch caches).
        reusable = (
            key in self._catalog_panels
            and self._catalog_panel_complete.get(key, False)
            and not key.startswith("search:")
        )
        if reusable:
            panel = self._catalog_panels[key]
            panel.pack(fill="both", expand=True)
            self._catalog_parent = panel
            self._app_rows = dict(self._catalog_panel_rows.get(key, {}))
            self._icon_refs = [ref for ref in self._icon_refs if ref is self._selected_icon_ref]
            if self.selected_app and self.selected_app.id in self._app_rows:
                self._highlight_card(self.selected_app.id)
            self._catalog_ready = True
            self._scroll_catalog_to_top()
            self.after(0, self._scroll_catalog_to_top)
            return

        if key.startswith("search:"):
            self._evict_search_panels()

        # Cap cached panels to avoid unbounded widget growth.
        while len(self._catalog_panels) >= 8:
            oldest = next(iter(self._catalog_panels))
            self._destroy_catalog_panel(oldest)

        panel = ctk.CTkFrame(self.app_list, fg_color="transparent")
        panel.pack(fill="both", expand=True)
        self._catalog_panels[key] = panel
        self._catalog_panel_complete[key] = False
        self._catalog_parent = panel
        self._app_rows = {}
        # Keep selected icon; drop only catalog card refs from previous live panel.
        self._icon_refs = [ref for ref in self._icon_refs if ref is self._selected_icon_ref]
        self._populate_catalog_cards(token)
        # Sync populate paths mark complete immediately; batch paths use on_complete.
        if self._batch_list is None or self._batch_list.is_complete:
            self._mark_catalog_panel_complete(key, token)
        self._catalog_ready = True
        self._scroll_catalog_to_top()
        self.after(0, self._scroll_catalog_to_top)

    def _populate_catalog_cards(self, token: int) -> None:
        query = self._global_search_query.strip().lower()

        # Drill-down: one bank's apps (pack cards — never grid).
        if self._catalog_view == "bank" and self._catalog_bank_group:
            apps = self._filter_bank_apps(
                self.config_manager.list_banking_apps_for_group(self._catalog_bank_group)
            )
            apps = self.catalog.sort_apps(apps)
            if not apps:
                empty_state(
                    self._catalog_host(),
                    icon="○" if not query else "?",
                    title="Ничего не найдено" if query else "В этом банке пока нет приложений",
                    hint="Попробуйте другой запрос." if query else "Загляните позже — каталог пополняется.",
                    action_text="Очистить поиск" if query else "",
                    action=(lambda: self.bank_search_var.set("")) if query else None,
                )
                return
            self._render_app_cards(apps, token, badge_new=False)
            return

        if query:
            self._populate_tab_search(query, token)
            return

        tab = self.catalog.current_tab()
        if tab.kind == "popular":
            self._populate_tab_popular(token)
            return
        if tab.kind == "all":
            self._populate_tab_all(token)
            return
        if tab.kind == "recent":
            self._populate_tab_recent(token)
            return

        result = self.catalog.list_for_tab(tab)
        if result is None:
            self._populate_tab_all(token)
            return
        if not result.apps:
            empty_state(
                self._catalog_host(),
                icon="○",
                title=result.empty_title or "Пусто",
                hint=result.empty_hint,
            )
            return
        section_header(self._catalog_host(), title=result.title, subtitle=result.subtitle)
        self._render_app_cards(
            result.apps,
            token,
            badge_new=result.badge_new,
            collapse_versions=result.collapse_versions,
        )

    def _populate_tab_search(self, query: str, token: int) -> None:
        """Filter active tab content by search query."""
        self.catalog.set_search(query, scope="section")
        matches = self.catalog.search(query, scope="section")
        tab = self.catalog.current_tab()

        if not matches:
            empty_state(
                self._catalog_host(),
                icon="?",
                title="Ничего не найдено",
                hint="Попробуйте другое название или очистите поиск.",
                action_text="Очистить поиск",
                action=lambda: self.bank_search_var.set(""),
            )
            return

        section_header(
            self._catalog_host(),
            title="Результаты поиска",
            subtitle=f"В разделе «{tab.title}» · {len(matches)}",
        )
        self._render_app_cards(matches, token, badge_new=True, collapse_versions=True)

    def _populate_tab_popular(self, token: int) -> None:
        popular_ids = self.config_manager.popular_item_ids()
        if not popular_ids:
            empty_state(self._catalog_host(), icon="○", title="Популярные пока пусты", hint="")
            return
        for item_id in popular_ids:
            if token != self._catalog_anim_token:
                return
            self._add_popular_list_card(item_id)

    def _add_popular_list_card(self, item_id: str) -> None:
        """Vertical list cards for popular tab (faster / clearer than horizontal chips)."""
        if item_id.startswith("@bank:"):
            group = self.config_manager.get_bank_group(item_id.split(":", 1)[1])
            if not group:
                return
            count = self.config_manager.banking_app_counts().get(group.id, 0)
            icon = self.icon_loader.peek_bank_group_icon(group, ICON_CARD)
            card = catalog_app_card(
                self._catalog_host(),
                title=group.title,
                subtitle=f"{count} приложений банка",
                icon=icon,
                on_click=lambda gid=group.id: self._open_bank_group(gid),
                icon_refs=self._icon_refs,
                anim=self._anim,
                card_key=f"bank:{group.id}",
            )
            if icon is None:

                def on_ready(photo: ctk.CTkImage, c=card) -> None:
                    self._icon_refs.append(photo)
                    try:
                        if c.winfo_exists():
                            c.icon_label.configure(image=photo)  # type: ignore[attr-defined]
                    except Exception:
                        pass

                self.icon_loader.schedule_bank_group_icon(
                    group,
                    size=ICON_CARD,
                    on_ready=on_ready,
                    schedule=self._schedule_ui,
                )
            return
        if item_id.startswith("@version:"):
            group = self.config_manager.get_version_group(item_id.split(":", 1)[1])
            if not group:
                return
            icon_app = self.config_manager.get_app(group.icon_app_id)
            icon = self.icon_loader.peek_app_icon(icon_app, ICON_CARD) if icon_app else None
            card = catalog_app_card(
                self._catalog_host(),
                title=group.title,
                subtitle="Старая и новая версия",
                icon=icon,
                on_click=lambda g=group: self._open_version_group(g),
                icon_refs=self._icon_refs,
                anim=self._anim,
                card_key=f"vg:{group.id}",
            )
            if icon_app is not None:
                self._bind_async_app_icon(card, icon_app, size=ICON_CARD)
            return
        app = self.config_manager.get_app(item_id)
        if app is None:
            return
        icon = self.icon_loader.peek_app_icon(app, ICON_CARD)
        card = catalog_app_card(
            self._catalog_host(),
            title=app.display_title(),
            subtitle=app.description or "",
            icon=icon,
            on_click=lambda aid=app.id: self._activate_catalog_item(aid),
            icon_refs=self._icon_refs,
            anim=self._anim,
            card_key=app.id,
            is_selected=lambda aid=app.id: bool(self.selected_app and self.selected_app.id == aid),
        )
        self._app_rows[app.id] = card
        self._bind_async_app_icon(card, app, size=ICON_CARD)

    def _populate_tab_recent(self, token: int) -> None:
        apps = self.catalog.list_recent_apps()
        if not apps:
            empty_state(
                self._catalog_host(),
                icon="○",
                title="Пока пусто",
                hint="Здесь появятся приложения после первой установки.",
            )
            return
        head = ctk.CTkFrame(self._catalog_host(), fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(14, 6))
        ctk.CTkLabel(
            head,
            text="Недавние",
            font=ui_font(TYPE_TITLE, weight="bold"),
            text_color=THEME["silver"],
            anchor="w",
        ).pack(side="left")
        secondary_button(
            head,
            text="Очистить",
            width=96,
            height=32,
            command=self._clear_recent_installs,
            font=ui_font(TYPE_CAPTION),
        ).pack(side="right", padx=(0, 10))
        ctk.CTkLabel(
            self._catalog_host(),
            text=f"Последние установки · {len(apps)}",
            font=ui_font(TYPE_META),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        for app in apps:
            if token != self._catalog_anim_token:
                return
            at = self.catalog.recent_install_at(app.id)
            status = format_relative_install(at)
            category = app.category or ("Банки" if app.is_banking else "")
            version = app.version_label() if app.maskTitle else ""
            updated = ""
            if app.freshness_date():
                updated = f"Обновлено {app.freshness_date()[:10]}"
            icon = self.icon_loader.peek_app_icon(app, ICON_CARD)
            card = catalog_app_card(
                self._catalog_host(),
                title=app.display_title(),
                subtitle=app.description or "",
                icon=icon,
                badge="",
                category=category,
                version=version,
                updated=updated,
                status=f"✓ {status}",
                action_text="Повторить",
                on_click=lambda a=app: self._reinstall_recent(a),
                icon_refs=self._icon_refs,
                anim=self._anim,
                card_key=app.id,
                is_selected=lambda aid=app.id: bool(self.selected_app and self.selected_app.id == aid),
            )
            self._app_rows[app.id] = card
            self._bind_async_app_icon(card, app, size=ICON_CARD, token=token)

    def _clear_recent_installs(self) -> None:
        if not messagebox.askyesno("Недавние", "Очистить историю установок?"):
            return
        self.settings.clear_recent_installs()
        self._refresh_app_list()
        self._toast("История очищена", kind="info")

    def _reinstall_recent(self, app: AppEntry) -> None:
        self._select_app(app)
        self._install_selected()

    @staticmethod
    def _format_install_date(iso: str) -> str:
        return format_relative_install(iso)

    def _populate_tab_all(self, token: int) -> None:
        entries = self.config_manager.list_root_all_entries()
        if not entries:
            empty_state(self._catalog_host(), icon="○", title="Каталог пуст", hint="")
            return
        items: list[tuple[str, str, object]] = []
        for entry in entries:
            if isinstance(entry, VersionGroup):
                items.append((entry.title, "version", entry))
            elif isinstance(entry, AppEntry):
                items.append((entry.display_title(), "app", entry))
        items.sort(key=lambda item: ConfigManager.sort_key_ru_first(item[0]))

        section_header(
            self._catalog_host(),
            title="Все приложения",
        )

        letter_state = {"current": ""}
        panel_key = self._catalog_panel_key()

        def render_row(item: tuple[str, str, object], _index: int) -> None:
            if token != self._catalog_anim_token:
                return
            title, kind, payload = item
            letter = ConfigManager.first_letter_ru(title)
            if letter != letter_state["current"]:
                letter_state["current"] = letter
                letter_header(self._catalog_host(), letter)
            if kind == "version":
                group = payload
                assert isinstance(group, VersionGroup)
                icon_app = self.config_manager.get_app(group.icon_app_id)
                icon = self.icon_loader.peek_app_icon(icon_app, ICON_CARD) if icon_app else None
                card = catalog_app_card(
                    self._catalog_host(),
                    title=group.title,
                    subtitle="Старая и новая версия",
                    category="Версии",
                    status="Выберите версию",
                    icon=icon,
                    on_click=lambda g=group: self._open_version_group(g),
                    icon_refs=self._icon_refs,
                    anim=self._anim,
                    card_key=f"vg:{group.id}",
                )
                if icon_app is not None:
                    self._bind_async_app_icon(card, icon_app, size=ICON_CARD, token=token)
                return
            app = payload
            assert isinstance(app, AppEntry)
            icon = self.icon_loader.peek_app_icon(app, ICON_CARD)
            badge = "Новинка" if self.config_manager.is_new_app(app) else ""
            subtitle = app.description or ""
            if app.is_banking and app.maskTitle:
                subtitle = f"{app.title} · {app.description}".strip(" ·")
            category = app.category or ("Банки" if app.is_banking else "")
            version = app.version_label() if (app.maskTitle or app.appId) else ""
            fresh = app.freshness_date()
            updated = f"Обновлено {fresh[:10]}" if fresh else ""
            status = "Готово к установке"
            if app.id in self.settings.recent_installs:
                status = "✓ Установлено"
            card = catalog_app_card(
                self._catalog_host(),
                title=app.display_title(),
                subtitle=subtitle,
                icon=icon,
                badge=badge,
                category=category,
                version=version,
                updated=updated,
                status=status,
                on_click=lambda a=app: self._activate_catalog_item(a.id),
                icon_refs=self._icon_refs,
                anim=self._anim,
                card_key=app.id,
                is_selected=lambda aid=app.id: bool(self.selected_app and self.selected_app.id == aid),
            )
            self._app_rows[app.id] = card
            self._bind_async_app_icon(card, app, size=ICON_CARD, token=token)

        # Small catalogs: render fully. Large: batch on scroll.
        if len(items) <= DEFAULT_BATCH:
            for index, item in enumerate(items):
                if token != self._catalog_anim_token:
                    return
                render_row(item, index)
            return

        self._batch_list = BatchCatalogList(
            self.app_list,
            render_item=render_row,
            batch_size=DEFAULT_BATCH,
            on_complete=lambda: self._mark_catalog_panel_complete(panel_key, token),
        )
        self._batch_list.reset(items, token=token)

    def _render_app_cards(
        self,
        apps: list[AppEntry],
        token: int,
        *,
        badge_new: bool,
        collapse_versions: bool = False,
    ) -> None:
        groups = self.config_manager.version_groups() if collapse_versions else {}
        seen_groups: set[str] = set()
        flat: list[AppEntry | VersionGroup] = []
        for app in apps:
            if collapse_versions and app.versionGroup:
                if app.versionGroup in seen_groups:
                    continue
                seen_groups.add(app.versionGroup)
                group = groups.get(app.versionGroup)
                if group:
                    flat.append(group)
                    continue
            flat.append(app)

        def render_one(item: AppEntry | VersionGroup, _index: int) -> None:
            if token != self._catalog_anim_token:
                return
            if isinstance(item, VersionGroup):
                group = item
                icon_app = self.config_manager.get_app(group.icon_app_id)
                icon = self.icon_loader.peek_app_icon(icon_app, ICON_CARD) if icon_app else None
                card = catalog_app_card(
                    self._catalog_host(),
                    title=group.title,
                    subtitle="Несколько версий — выберите при установке",
                    category="Версии",
                    status="Выберите версию",
                    icon=icon,
                    badge="",
                    on_click=lambda g=group: self._open_version_group(g),
                    icon_refs=self._icon_refs,
                    anim=self._anim,
                    card_key=f"vg:{group.id}",
                )
                if icon_app is not None:
                    self._bind_async_app_icon(card, icon_app, size=ICON_CARD, token=token)
                return
            app = item
            icon = self.icon_loader.peek_app_icon(app, ICON_CARD)
            badge = ""
            if badge_new and self.config_manager.is_new_app(app):
                badge = "Новинка"
            subtitle = app.description or ""
            if app.is_banking and app.maskTitle:
                subtitle = f"{app.title} · {app.description}".strip(" ·")
            category = app.category or ("Банки" if app.is_banking else "")
            version = app.version_label() if (app.maskTitle or app.appId) else ""
            fresh = app.freshness_date()
            updated = f"Обновлено {fresh[:10]}" if fresh else ""
            status = "Готово к установке"
            if self._install.last_failed_app and self._install.last_failed_app.id == app.id:
                status = "Не удалось установить"
            elif app.id in self.settings.recent_installs:
                status = "✓ Установлено"
            card = catalog_app_card(
                self._catalog_host(),
                title=app.display_title(),
                subtitle=subtitle,
                icon=icon,
                badge=badge,
                category=category,
                version=version,
                updated=updated,
                status=status,
                on_click=lambda a=app: self._activate_catalog_item(a.id),
                icon_refs=self._icon_refs,
                anim=self._anim,
                card_key=app.id,
                is_selected=lambda aid=app.id: bool(
                    self.selected_app and self.selected_app.id == aid
                ),
            )
            self._app_rows[app.id] = card
            self._bind_async_app_icon(card, app, size=ICON_CARD, token=token)

        if len(flat) <= DEFAULT_BATCH:
            for index, item in enumerate(flat):
                if token != self._catalog_anim_token:
                    return
                render_one(item, index)
        else:
            panel_key = self._catalog_panel_key()
            self._batch_list = BatchCatalogList(
                self.app_list,
                render_item=render_one,
                batch_size=DEFAULT_BATCH,
                on_complete=lambda: self._mark_catalog_panel_complete(panel_key, token),
            )
            self._batch_list.reset(flat, token=token)
        if self.selected_app and self.selected_app.id in self._app_rows:
            self._highlight_card(self.selected_app.id)

    def _open_version_group(self, group: VersionGroup) -> None:
        options: list[VersionPickerOption] = []
        for option in group.options:
            app = self.config_manager.get_app(option.app_id)
            if app is None:
                continue
            icon = self.icon_loader.get_app_icon(app, size=40)
            options.append(
                VersionPickerOption(
                    label=option.label,
                    hint=option.hint or app.description,
                    app=app,
                    icon=icon,
                )
            )
        if not options:
            return
        if len(options) == 1:
            self._select_app(options[0].app)
            return
        open_version_picker(
            self,
            title=group.title,
            options=options,
            on_select=self._select_app,
            icon_refs=self._icon_refs,
        )

    def _activate_catalog_item(self, item_id: str) -> None:
        if item_id.startswith("@bank:"):
            self._open_bank_group(item_id.split(":", 1)[1])
            return
        if item_id.startswith("@version:"):
            group = self.config_manager.get_version_group(item_id.split(":", 1)[1])
            if group:
                self._open_version_group(group)
            return
        app = self.config_manager.get_app(item_id)
        if app is None:
            return
        if app.versionGroup:
            group = self.config_manager.get_version_group(app.versionGroup)
            if group:
                self._open_version_group(group)
                return
        self._select_app(app)

    def _highlight_card(self, app_id: str) -> None:
        for card_id, row in self._app_rows.items():
            selected = card_id == app_id
            animate_card_select(
                self._anim,
                row,
                card_id,
                selected=selected,
            )

    def _select_app(self, app: AppEntry) -> None:
        self.selected_app = app
        self._install.clear_success()
        if self._install.last_failed_app and self._install.last_failed_app.id != app.id:
            self._install.clear_failure()

        icon = self.icon_loader.get_app_icon(app, size=ICON_INSTALL)
        self._selected_icon_ref = icon
        if icon not in self._icon_refs:
            self._icon_refs.append(icon)
        self.selected_icon_label.configure(image=icon)

        self._highlight_card(app.id)
        self._sync_install_card()
        label = app.maskTitle or app.title
        self._log(f"Выбрано: {label}")

    def _show_help(self) -> None:
        open_help_dialog(
            self,
            support_url=_SUPPORT_TELEGRAM,
            support_handle="@gromov_restore",
            on_support=self._open_telegram_support,
            on_report=self._create_support_report,
        )

    def _check_device(self) -> None:
        if getattr(self, "device_connection_label", None) is not None:
            self.device_connection_label.configure(text="Подключение: проверка…")
        self.readiness_label.configure(text="Проверка USB...")

        def task() -> None:
            try:
                devices = self.device_installer.list_usb_devices()

                def done() -> None:
                    self._remember_devices(devices)
                    if devices:
                        if len(devices) == 1:
                            body = (
                                "Подключён по USB и готов к установке:\n\n"
                                + devices[0].detail_lines
                            )
                        else:
                            body = (
                                "Подключено несколько iPhone по USB.\n"
                                "При установке нужно будет выбрать устройство.\n\n"
                                + "\n\n".join(d.detail_lines for d in devices)
                            )
                        lines = "\n".join(f"• {d.label} (USB)" for d in devices)
                        self._log("USB-устройства:\n" + lines)
                        messagebox.showinfo("iPhone (USB)", body)
                    else:
                        self._log("iPhone по USB не найден.")
                        messagebox.showwarning("iPhone", self._usb_not_connected_message())

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

    perf_probe = os.environ.get("GROMOV_PERF_PROBE", "").strip().lower() in {"1", "true", "yes"}
    t_boot = time.perf_counter()

    if not acquire_single_instance_lock():
        try:
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
    if perf_probe:
        construct_ms = (time.perf_counter() - t_boot) * 1000

        def _perf_after_first_paint() -> None:
            try:
                app.update_idletasks()
            except tk.TclError:
                pass
            ready_ms = (time.perf_counter() - t_boot) * 1000
            tab = getattr(app, "_catalog_tab", "?")
            print(
                f"[perf] construct_ms={construct_ms:.1f} "
                f"first_paint_ms={ready_ms:.1f} tab={tab}",
                flush=True,
            )
            try:
                app.destroy()
            except tk.TclError:
                pass

        app.after(0, app._refresh_app_list)
        app.after(150, _perf_after_first_paint)
    app.mainloop()


if __name__ == "__main__":
    # Windowed PyInstaller (console=False) hides stderr; excepthook + this guard persist crashes.
    try:
        main()
    except BaseException as exc:  # noqa: BLE001 — must never die silently on Windows GUI
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            raise
        path = _write_startup_crash(exc)
        _show_startup_crash_dialog(path, exc)
        raise SystemExit(1) from exc
