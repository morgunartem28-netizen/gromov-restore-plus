from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from theme import THEME

# Durations — snappy premium (100–200ms)
DURATION_FAST = 120
DURATION_NORMAL = 160
DURATION_SLOW = 200
DURATION_THEME = 160
STAGGER_DELAY = 40
THEME_FADE_FLOOR = 0.08
THEME_FADE_TARGET = 0.99


def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def lerp_color(from_color: str, to_color: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(from_color)
    r2, g2, b2 = _hex_to_rgb(to_color)
    return f"#{int(r1 + (r2 - r1) * t):02x}{int(g1 + (g2 - g1) * t):02x}{int(b1 + (b2 - b1) * t):02x}"


class AnimationRunner:
    """Cancelable after()-animations for one widget."""

    def __init__(self, widget: ctk.CTkBaseClass) -> None:
        self._widget = widget
        self._jobs: dict[str, str | None] = {}
        self._tokens: dict[str, int] = {}
        self._token_counter = 0

    def cancel(self, key: str) -> None:
        job = self._jobs.pop(key, None)
        if job is not None:
            try:
                self._widget.after_cancel(job)
            except (ValueError, AttributeError):
                pass
        self._tokens.pop(key, None)

    def cancel_all(self) -> None:
        for key in list(self._jobs.keys()):
            self.cancel(key)

    def _next_token(self, key: str) -> int:
        self._token_counter += 1
        token = self._token_counter
        self._tokens[key] = token
        return token

    def tween(
        self,
        key: str,
        *,
        duration_ms: int = DURATION_NORMAL,
        on_frame: Callable[[float], None],
        on_complete: Callable[[], None] | None = None,
        easing: Callable[[float], float] = ease_out_cubic,
        interval_ms: int = 20,
    ) -> None:
        self.cancel(key)
        token = self._next_token(key)
        steps = max(1, duration_ms // interval_ms)
        step = [0]

        def tick() -> None:
            if self._tokens.get(key) != token:
                return
            step[0] += 1
            progress = min(1.0, step[0] / steps)
            on_frame(easing(progress))
            if progress >= 1.0:
                self._jobs.pop(key, None)
                self._tokens.pop(key, None)
                if on_complete:
                    on_complete()
                return
            self._jobs[key] = self._widget.after(interval_ms, tick)

        tick()

    def tween_colors(
        self,
        widget: ctk.CTkBaseClass,
        key: str,
        *,
        from_fg: str,
        to_fg: str,
        from_border: str | None = None,
        to_border: str | None = None,
        duration_ms: int = DURATION_FAST,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        def on_frame(t: float) -> None:
            fg = lerp_color(from_fg, to_fg, t)
            kwargs: dict[str, object] = {"fg_color": fg}
            if from_border is not None and to_border is not None:
                kwargs["border_color"] = lerp_color(from_border, to_border, t)
            try:
                widget.configure(**kwargs)
            except tk.TclError:
                pass

        self.tween(key, duration_ms=duration_ms, on_frame=on_frame, on_complete=on_complete)


def fade_in_window(window: ctk.CTkToplevel | ctk.CTk, *, duration_ms: int = DURATION_NORMAL) -> None:
    runner = AnimationRunner(window)
    try:
        window.attributes("-alpha", 0.0)
    except tk.TclError:
        return

    def on_frame(t: float) -> None:
        try:
            window.attributes("-alpha", t)
        except tk.TclError:
            pass

    runner.tween("fade_in", duration_ms=duration_ms, on_frame=on_frame)


def bind_smooth_hover(
    runner: AnimationRunner,
    card: ctk.CTkFrame,
    card_key: str,
    *,
    normal_fg: str,
    hover_fg: str,
    normal_border: str,
    hover_border: str,
    is_selected: Callable[[], bool],
    duration_ms: int = DURATION_FAST,
) -> None:
    """Soft lift on hover; skips when selected. Reads live colors to avoid snap."""

    def _color(attr: str, fallback: str) -> str:
        try:
            value = card.cget(attr)
        except tk.TclError:
            return fallback
        return value if isinstance(value, str) and value.startswith("#") else fallback

    def on_enter(_event: object) -> None:
        if is_selected():
            return
        runner.tween_colors(
            card,
            f"hover:{card_key}",
            from_fg=_color("fg_color", normal_fg),
            to_fg=hover_fg,
            from_border=_color("border_color", normal_border),
            to_border=hover_border,
            duration_ms=duration_ms,
        )

    def on_leave(_event: object) -> None:
        if is_selected():
            return
        runner.cancel(f"hover:{card_key}")
        runner.tween_colors(
            card,
            f"hover:{card_key}",
            from_fg=_color("fg_color", hover_fg),
            to_fg=normal_fg,
            from_border=_color("border_color", hover_border),
            to_border=normal_border,
            duration_ms=duration_ms,
        )

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)


def animate_card_select(
    runner: AnimationRunner,
    card: ctk.CTkFrame,
    card_key: str,
    *,
    selected: bool,
    duration_ms: int = DURATION_NORMAL,
) -> None:
    """Glow into selected accent state, or settle back to elevated glass."""
    runner.cancel(f"hover:{card_key}")
    key = f"select:{card_key}"
    try:
        from_fg = card.cget("fg_color")
        from_border = card.cget("border_color")
    except tk.TclError:
        from_fg = THEME["glass_inner"]
        from_border = THEME["glass_border"]
    if not isinstance(from_fg, str) or not from_fg.startswith("#"):
        from_fg = THEME["glass_inner"]
    if not isinstance(from_border, str) or not from_border.startswith("#"):
        from_border = THEME["glass_border"]

    if selected:
        to_fg = THEME["glass_selected"]
        to_border = THEME["accent"]
        try:
            card.configure(border_width=2)
        except tk.TclError:
            pass
    else:
        to_fg = THEME["glass_inner"]
        to_border = THEME["glass_border"]
        try:
            card.configure(border_width=1)
        except tk.TclError:
            pass

    runner.tween_colors(
        card,
        key,
        from_fg=from_fg,
        to_fg=to_fg,
        from_border=from_border,
        to_border=to_border,
        duration_ms=duration_ms,
    )


def fade_window_alpha(
    window: ctk.CTkToplevel | ctk.CTk,
    runner: AnimationRunner,
    *,
    to_alpha: float,
    duration_ms: int = DURATION_THEME,
    on_complete: Callable[[], None] | None = None,
    key: str = "fade_alpha",
) -> None:
    """Tween window -alpha; used to hide theme reconfigure flicker."""
    try:
        from_alpha = float(window.attributes("-alpha"))
    except (tk.TclError, TypeError, ValueError):
        from_alpha = THEME_FADE_TARGET

    def on_frame(t: float) -> None:
        try:
            window.attributes("-alpha", from_alpha + (to_alpha - from_alpha) * t)
        except tk.TclError:
            pass

    runner.tween(
        key,
        duration_ms=duration_ms,
        on_frame=on_frame,
        on_complete=on_complete,
        easing=ease_in_out_cubic,
        interval_ms=16,
    )


def bind_press_feedback(runner: AnimationRunner, button: ctk.CTkButton, *, pressed_scale: float = 0.96) -> None:
    normal_height = button.cget("height")
    if not isinstance(normal_height, (int, float)) or normal_height <= 0:
        normal_height = 40
    pressed_height = max(30, int(normal_height * pressed_scale))
    key = f"press:{id(button)}"
    try:
        normal_fg = button.cget("fg_color")
        hover_fg = button.cget("hover_color")
    except tk.TclError:
        normal_fg = THEME["accent"]
        hover_fg = THEME["accent_hover"]

    def _as_hex(value: object, fallback: str) -> str:
        if isinstance(value, str) and value.startswith("#"):
            return value
        if isinstance(value, (tuple, list)) and value:
            last = value[-1]
            if isinstance(last, str) and last.startswith("#"):
                return last
        return fallback

    normal_hex = _as_hex(normal_fg, THEME["accent"])
    pressed_hex = THEME.get("accent_pressed", THEME["accent"])
    # Secondary/ghost: darken toward chip, not accent_pressed
    if normal_hex.lower() not in (THEME["accent"].lower(), THEME["accent_hover"].lower()):
        pressed_hex = THEME["glass_edge"]

    def press(_event: object) -> None:
        runner.cancel(key)
        try:
            button.configure(height=pressed_height, fg_color=pressed_hex)
        except tk.TclError:
            pass

    def release(_event: object) -> None:
        try:
            button.configure(height=normal_height, fg_color=normal_hex)
        except tk.TclError:
            pass

    button.bind("<ButtonPress-1>", press)
    button.bind("<ButtonRelease-1>", release)
    _ = hover_fg


def reveal_card(
    runner: AnimationRunner,
    card: ctk.CTkFrame,
    *,
    target_fg: str,
    target_border: str,
    bg_color: str | None = None,
    duration_ms: int = DURATION_NORMAL,
) -> None:
    """Fade card border in; keep glass fill (no window-bg flash over scroll gaps)."""
    _ = bg_color  # optional, ignored — kept for call-site compatibility
    card.configure(fg_color=target_fg, border_color=target_fg)
    runner.tween_colors(
        card,
        f"reveal:{id(card)}",
        from_fg=target_fg,
        to_fg=target_fg,
        from_border=target_fg,
        to_border=target_border,
        duration_ms=duration_ms,
    )


class SearchDebouncer:
    def __init__(
        self,
        widget: ctk.CTkBaseClass,
        *,
        delay_ms: int = 250,
        callback: Callable[[], None],
    ) -> None:
        self._widget = widget
        self._delay_ms = delay_ms
        self._callback = callback
        self._job: str | None = None

    def trigger(self) -> None:
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except (ValueError, AttributeError):
                pass
        self._job = self._widget.after(self._delay_ms, self._fire)

    def _fire(self) -> None:
        self._job = None
        self._callback()

    def cancel(self) -> None:
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except (ValueError, AttributeError):
                pass
            self._job = None


def animate_progress_to(
    runner: AnimationRunner,
    bar: ctk.CTkProgressBar,
    target: float,
    *,
    duration_ms: int = DURATION_FAST,
) -> None:
    try:
        start = float(bar.get())
    except (ValueError, TypeError, tk.TclError):
        start = 0.0
    target = max(0.0, min(1.0, target))

    def on_frame(t: float) -> None:
        value = start + (target - start) * t
        bar.set(value)

    runner.tween("progress", duration_ms=duration_ms, on_frame=on_frame, easing=ease_in_out_cubic)
