"""Batch / virtual catalog list for large catalogs (Wave C).

CTkScrollableFrame cannot easily recycle widgets, so we load cards in batches
when the user scrolls near the bottom. Keeps first paint fast for 500+ apps.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import customtkinter as ctk


DEFAULT_BATCH = 40
SCROLL_LOAD_THRESHOLD = 0.82
_HOST_BATCH_ATTR = "_gromov_active_batch"
_HOST_BOUND_ATTR = "_gromov_batch_scroll_bound"


@dataclass
class VirtualListState:
    items: list[Any] = field(default_factory=list)
    rendered: int = 0
    batch_size: int = DEFAULT_BATCH
    loading: bool = False
    token: int = 0
    cancelled: bool = False


class BatchCatalogList:
    """Incremental renderer bound to a scrollable host frame."""

    def __init__(
        self,
        host: ctk.CTkScrollableFrame,
        *,
        render_item: Callable[[Any, int], None],
        batch_size: int = DEFAULT_BATCH,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.render_item = render_item
        self.batch_size = max(10, batch_size)
        self.on_complete = on_complete
        self.state = VirtualListState(batch_size=self.batch_size)

    def reset(self, items: list[Any], *, token: int) -> None:
        self.state = VirtualListState(
            items=list(items),
            rendered=0,
            batch_size=self.batch_size,
            token=token,
            cancelled=False,
        )
        # Only the latest batch list receives scroll events for this host.
        setattr(self.host, _HOST_BATCH_ATTR, self)
        self._ensure_scroll_bind()
        self.load_more()

    def cancel(self) -> None:
        """Stop loading; safe to call when switching tabs mid-batch."""
        self.state.cancelled = True
        self.state.loading = False
        self.state.items = []
        self.state.rendered = 0
        if getattr(self.host, _HOST_BATCH_ATTR, None) is self:
            setattr(self.host, _HOST_BATCH_ATTR, None)

    def _ensure_scroll_bind(self) -> None:
        if getattr(self.host, _HOST_BOUND_ATTR, False):
            return
        canvas = getattr(self.host, "_parent_canvas", None)
        if canvas is None:
            return

        def _dispatch(_event: object = None) -> None:
            active = getattr(self.host, _HOST_BATCH_ATTR, None)
            if isinstance(active, BatchCatalogList):
                active._on_scroll()

        canvas.bind("<MouseWheel>", _dispatch, add="+")
        canvas.bind("<Button-4>", _dispatch, add="+")
        canvas.bind("<Button-5>", _dispatch, add="+")
        canvas.bind("<Configure>", _dispatch, add="+")
        setattr(self.host, _HOST_BOUND_ATTR, True)

    def _on_scroll(self, _event: object = None) -> None:
        if self.state.cancelled:
            return
        self.host.after(16, self._maybe_load)

    def _maybe_load(self) -> None:
        if self.state.cancelled or self.state.loading or self.state.rendered >= len(self.state.items):
            return
        if getattr(self.host, _HOST_BATCH_ATTR, None) is not self:
            return
        canvas = getattr(self.host, "_parent_canvas", None)
        if canvas is None:
            self.load_more()
            return
        try:
            top, bottom = canvas.yview()
        except Exception:
            self.load_more()
            return
        if bottom >= SCROLL_LOAD_THRESHOLD or bottom >= 0.98:
            self.load_more()

    def load_more(self) -> None:
        if self.state.cancelled or self.state.loading:
            return
        if getattr(self.host, _HOST_BATCH_ATTR, None) is not self:
            return
        if self.state.rendered >= len(self.state.items):
            if self.on_complete and not self.state.cancelled:
                self.on_complete()
            return
        self.state.loading = True
        token = self.state.token
        end = min(self.state.rendered + self.state.batch_size, len(self.state.items))
        for index in range(self.state.rendered, end):
            if self.state.cancelled or token != self.state.token:
                break
            if getattr(self.host, _HOST_BATCH_ATTR, None) is not self:
                break
            self.render_item(self.state.items[index], index)
        self.state.rendered = end
        self.state.loading = False
        if self.state.cancelled:
            return
        if self.state.rendered >= len(self.state.items):
            if self.on_complete:
                self.on_complete()
            return
        # If content still doesn't fill the viewport, keep loading.
        self.host.after(50, self._maybe_load)

    @property
    def remaining(self) -> int:
        if self.state.cancelled:
            return 0
        return max(0, len(self.state.items) - self.state.rendered)

    @property
    def is_complete(self) -> bool:
        return (not self.state.cancelled) and self.state.rendered >= len(self.state.items) and len(self.state.items) >= 0
