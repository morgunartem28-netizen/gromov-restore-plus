"""Install queue façade — cancel / retry / busy without owning CTk widgets."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from install_queue import InstallJob, InstallQueue, JobStatus, ProgressCb

if TYPE_CHECKING:
    from config_manager import AppEntry


class InstallController:
    """Wraps InstallQueue; UI binds via on_changed / progress_hook."""

    def __init__(
        self,
        *,
        worker: Callable[[InstallJob, ProgressCb], None],
        on_changed: Callable[[], None] | None = None,
        on_cancel_request: Callable[[], None] | None = None,
    ) -> None:
        self.queue = InstallQueue(
            worker=worker,
            on_changed=on_changed,
            on_cancel_request=on_cancel_request,
        )
        self.last_failed_app: AppEntry | None = None
        self.last_installed_title = ""

    @property
    def is_busy(self) -> bool:
        return self.queue.is_busy

    @property
    def jobs(self) -> list[InstallJob]:
        return self.queue.jobs

    @property
    def current(self) -> InstallJob | None:
        return self.queue.current

    @property
    def cancel_event(self):
        return self.queue.cancel_event

    def set_progress_hook(self, hook: ProgressCb | None) -> None:
        self.queue.progress_hook = hook

    def enqueue(self, apps: list, *, udid: str | None = None) -> int:
        return self.queue.enqueue(apps, udid=udid)

    def cancel_all(self) -> None:
        self.queue.cancel_all()

    def retry_failed(self) -> int:
        return self.queue.retry_failed()

    def note_success(self, title: str) -> None:
        self.last_installed_title = title
        self.last_failed_app = None

    def note_failure(self, app: AppEntry) -> None:
        self.last_failed_app = app
        self.last_installed_title = ""

    def clear_success(self) -> None:
        self.last_installed_title = ""

    def clear_failure(self) -> None:
        self.last_failed_app = None

    def clear_outcome(self) -> None:
        self.last_installed_title = ""
        self.last_failed_app = None

    def has_failed_jobs(self) -> bool:
        return any(job.status == JobStatus.FAILED for job in self.queue.jobs) or bool(
            self.last_failed_app
        )

    def card_state(self, *, async_busy: bool = False, update_busy: bool = False) -> str:
        """idle | ready | installing | done | error — without knowing selection."""
        busy = async_busy or self.is_busy or update_busy
        if busy:
            return "installing"
        if self.last_failed_app is not None:
            return "error"
        if self.last_installed_title:
            return "done"
        return "idle"
