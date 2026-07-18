from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

# Длительности анимаций (мс)
DURATION_FAST = 150
DURATION_NORMAL = 220
DURATION_SLOW = 300
STAGGER_DELAY = 45


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
    """Отменяемые after()-анимации для одного виджета."""

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
        interval_ms: int = 24,
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
    ) -> None:
        def on_frame(t: float) -> None:
            fg = lerp_color(from_fg, to_fg, t)
            kwargs: dict[str, object] = {"fg_color": fg}
            if from_border is not None and to_border is not None:
                kwargs["border_color"] = lerp_color(from_border, to_border, t)
            widget.configure(**kwargs)

        self.tween(key, duration_ms=duration_ms, on_frame=on_frame)


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
    def on_enter(_event: object) -> None:
        if is_selected():
            return
        runner.tween_colors(
            card,
            f"hover:{card_key}",
            from_fg=card.cget("fg_color") if isinstance(card.cget("fg_color"), str) else normal_fg,
            to_fg=hover_fg,
            from_border=card.cget("border_color") if isinstance(card.cget("border_color"), str) else normal_border,
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
            from_fg=card.cget("fg_color") if isinstance(card.cget("fg_color"), str) else hover_fg,
            to_fg=normal_fg,
            from_border=card.cget("border_color") if isinstance(card.cget("border_color"), str) else hover_border,
            to_border=normal_border,
            duration_ms=duration_ms,
        )

    card.bind("<Enter>", on_enter)
    card.bind("<Leave>", on_leave)


def bind_press_feedback(runner: AnimationRunner, button: ctk.CTkButton, *, pressed_scale: float = 0.96) -> None:
    normal_height = button.cget("height")
    if not isinstance(normal_height, (int, float)) or normal_height <= 0:
        normal_height = 36
    pressed_height = max(28, int(normal_height * pressed_scale))
    key = f"press:{id(button)}"

    def press(_event: object) -> None:
        runner.cancel(key)
        button.configure(height=pressed_height)

    def release(_event: object) -> None:
        button.configure(height=normal_height)

    button.bind("<ButtonPress-1>", press)
    button.bind("<ButtonRelease-1>", release)


def reveal_card(
    runner: AnimationRunner,
    card: ctk.CTkFrame,
    *,
    target_fg: str,
    target_border: str,
    bg_color: str,
    duration_ms: int = DURATION_NORMAL,
) -> None:
    card.configure(fg_color=bg_color, border_color=bg_color)
    runner.tween_colors(
        card,
        f"reveal:{id(card)}",
        from_fg=bg_color,
        to_fg=target_fg,
        from_border=bg_color,
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
