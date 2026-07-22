"""USB-only iPhone picker dialog."""
from __future__ import annotations

import customtkinter as ctk

from device_installer import DeviceInfo
from theme import THEME, glass_frame, primary_button, secondary_button, ui_font
from ui_animations import fade_in_window
from window_effects import apply_glass_window


def _short_udid(udid: str) -> str:
    clean = udid.strip()
    if len(clean) <= 14:
        return clean
    return f"{clean[:8]}…{clean[-4:]}"


def _model_title(device: DeviceInfo) -> str:
    name = (device.name or "").strip() or "iPhone"
    return name


def _model_subtitle(device: DeviceInfo) -> str:
    parts: list[str] = []
    if device.model:
        parts.append(device.model)
    if device.ios_version:
        parts.append(f"iOS {device.ios_version}")
    return " · ".join(parts) if parts else "iPhone"


class DevicePickerDialog(ctk.CTkToplevel):
    """Modal picker for multiple USB-connected iPhones. Returns selected DeviceInfo or None."""

    def __init__(self, parent: ctk.CTk, devices: list[DeviceInfo]) -> None:
        super().__init__(parent)
        self.title("Выберите iPhone для установки")
        self.geometry("520x560")
        self.minsize(480, 420)
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=THEME["bg"])
        self.result: DeviceInfo | None = None
        self._devices = list(devices)

        self.after(40, lambda: apply_glass_window(self, dark=True))
        fade_in_window(self)

        header = glass_frame(self)
        header.pack(fill="x", padx=20, pady=(20, 12))

        ctk.CTkLabel(
            header,
            text="Выберите iPhone для установки",
            font=ui_font(20, weight="bold"),
            text_color=THEME["text"],
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(16, 4))

        ctk.CTkLabel(
            header,
            text="Показаны только устройства, подключённые по USB-кабелю.",
            font=ui_font(13),
            text_color=THEME["muted"],
            anchor="w",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 16))

        self._list = ctk.CTkScrollableFrame(
            self,
            fg_color=THEME["bg"],
            scrollbar_button_color=THEME["chip"],
            scrollbar_button_hover_color=THEME["glass_hover"],
        )
        self._list.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        for device in self._devices:
            self._add_card(device)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=(4, 20))
        secondary_button(footer, text="Отмена", command=self._cancel, width=120).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.focus_force()

    def _add_card(self, device: DeviceInfo) -> None:
        card = glass_frame(self._list)
        card.pack(fill="x", pady=8)
        card.grid_columnconfigure(0, weight=1)

        text = ctk.CTkFrame(card, fg_color="transparent")
        text.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=14)

        title = _model_title(device)
        ctk.CTkLabel(
            text,
            text=title,
            font=ui_font(16, weight="bold"),
            text_color=THEME["text"],
            anchor="w",
        ).pack(anchor="w")

        meta = _model_subtitle(device)
        ctk.CTkLabel(
            text,
            text=meta,
            font=ui_font(13),
            text_color=THEME["text_secondary"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(
            text,
            text="Подключён через USB",
            font=ui_font(12),
            text_color=THEME["success"],
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        ctk.CTkLabel(
            text,
            text=f"ID: {_short_udid(device.udid)}",
            font=ui_font(11),
            text_color=THEME["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        primary_button(
            card,
            text="Установить на этот iPhone",
            width=200,
            height=40,
            command=lambda d=device: self._choose(d),
        ).grid(row=0, column=1, padx=(8, 16), pady=14)

    def _choose(self, device: DeviceInfo) -> None:
        self.result = device
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def pick_usb_device(parent: ctk.CTk, devices: list[DeviceInfo]) -> DeviceInfo | None:
    if not devices:
        return None
    if len(devices) == 1:
        return devices[0]
    dialog = DevicePickerDialog(parent, devices)
    parent.wait_window(dialog)
    return dialog.result
