"""Modern toast notifications for CustomTkinter."""
from __future__ import annotations

import tkinter as tk
from typing import Literal

import customtkinter as ctk

from theme import THEME, ui_font
from ui_animations import AnimationRunner, DURATION_FAST, ease_out_cubic

ToastKind = Literal["success", "warning", "error", "info"]


class ToastHost:
    def __init__(self, root: ctk.CTk) -> None:
        self._root = root
        self._stack: list[ctk.CTkFrame] = []
        self._anim = AnimationRunner(root)

    def show(self, message: str, *, kind: ToastKind = "info", duration_ms: int = 3200) -> None:
        tones = {
            "success": (THEME["success_soft"], THEME["success"], "✓"),
            "warning": (THEME["warning_soft"], THEME["warning"], "!"),
            "error": (THEME["error_soft"], THEME["error"], "×"),
            "info": (THEME["accent_soft"], THEME["accent"], "i"),
        }
        bg, accent, glyph = tones.get(kind, tones["info"])

        toast = ctk.CTkFrame(
            self._root,
            fg_color=THEME["surface"],
            corner_radius=16,
            border_width=1,
            border_color=THEME["glass_border"],
        )
        toast.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")

        inner = ctk.CTkFrame(toast, fg_color="transparent")
        inner.pack(padx=14, pady=12)

        badge = ctk.CTkFrame(inner, fg_color=bg, corner_radius=12, width=32, height=32)
        badge.pack(side="left")
        badge.pack_propagate(False)
        ctk.CTkLabel(
            badge,
            text=glyph,
            font=ui_font(14, weight="bold"),
            text_color=accent,
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            inner,
            text=message,
            font=ui_font(13),
            text_color=THEME["text"],
            justify="left",
            wraplength=320,
            anchor="w",
        ).pack(side="left", padx=(12, 4))

        self._stack.append(toast)
        self._reposition()

        try:
            toast.attributes("-alpha", 0.0)  # type: ignore[attr-defined]
        except (tk.TclError, AttributeError):
            pass

        def on_frame(t: float) -> None:
            try:
                toast.attributes("-alpha", 0.2 + 0.8 * t)  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                pass

        self._anim.tween(f"toast-in:{id(toast)}", duration_ms=DURATION_FAST, on_frame=on_frame, easing=ease_out_cubic)
        self._root.after(duration_ms, lambda: self._dismiss(toast))

    def _dismiss(self, toast: ctk.CTkFrame) -> None:
        if toast not in self._stack:
            return

        def finish() -> None:
            try:
                toast.destroy()
            except tk.TclError:
                pass
            if toast in self._stack:
                self._stack.remove(toast)
            self._reposition()

        def on_frame(t: float) -> None:
            try:
                toast.attributes("-alpha", max(0.0, 1.0 - t))  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                pass

        self._anim.tween(
            f"toast-out:{id(toast)}",
            duration_ms=DURATION_FAST,
            on_frame=on_frame,
            on_complete=finish,
        )

    def _reposition(self) -> None:
        offset = 24
        for toast in reversed(self._stack):
            try:
                toast.place(relx=1.0, rely=1.0, x=-24, y=-offset, anchor="se")
                toast.update_idletasks()
                offset += toast.winfo_reqheight() + 10
            except tk.TclError:
                continue
