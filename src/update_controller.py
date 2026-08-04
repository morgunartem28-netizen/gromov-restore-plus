"""Update check/download façade — keeps UI dialogs out of business entry points."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from security_utils import verify_setup_authenticode
from update_checker import (
    UpdateCancelled,
    UpdateCheckError,
    UpdateCheckResult,
    check_for_updates,
    download_verified_installer,
)
from version import APP_VERSION


class UpdateController:
    """Business entry points for in-app updates (1.4)."""

    def __init__(self) -> None:
        self.busy = False
        self.cancel_event: threading.Event | None = None

    def begin(self, cancel_event: threading.Event | None = None) -> None:
        self.busy = True
        self.cancel_event = cancel_event

    def end(self) -> None:
        self.busy = False
        self.cancel_event = None

    def check(self) -> UpdateCheckResult:
        return check_for_updates(current_version=APP_VERSION)

    def download(
        self,
        result: UpdateCheckResult,
        *,
        on_progress: Callable[[float], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if not result.setup_url:
            raise UpdateCheckError("В манифесте нет ссылки на установщик.")
        if not result.sha256:
            raise UpdateCheckError("В манифесте нет SHA256 установщика.")
        self.cancel_event = cancel_event
        return download_verified_installer(
            setup_url=result.setup_url,
            expected_sha256=result.sha256,
            version=result.latest_version,
            on_progress=on_progress,
            setup_urls=result.setup_urls,
            cancel_event=cancel_event,
            on_status=on_status,
        )

    def verify_installer(self, installer: Path) -> tuple[bool, str]:
        return verify_setup_authenticode(installer)


__all__ = [
    "UpdateController",
    "UpdateCancelled",
    "UpdateCheckError",
    "UpdateCheckResult",
]
