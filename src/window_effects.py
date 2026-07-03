from __future__ import annotations

import ctypes
import sys
import tkinter as tk


def apply_glass_window(window: tk.Misc, *, alpha: float = 0.97) -> None:
    """Windows 11: acrylic/mica за окном + лёгкая прозрачность. На других ОС — только alpha."""
    try:
        window.attributes("-alpha", alpha)
    except tk.TclError:
        pass

    if sys.platform != "win32":
        return

    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return

        dwm = ctypes.windll.dwmapi
        dark_mode = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))

        # DWMSBT_TRANSIENTWINDOW — эффект «жидкого стекла» (Windows 11)
        backdrop = ctypes.c_int(3)
        dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
    except (AttributeError, OSError, ValueError):
        pass
