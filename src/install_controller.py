"""Install façade — unified UI state machine over InstallQueue."""
from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING

from install_queue import InstallJob, InstallQueue, JobStatus, ProgressCb

if TYPE_CHECKING:
    from config_manager import AppEntry


BUSY_OTHER_APP_MSG = (
    "Идёт установка другого приложения. Дождитесь окончания или нажмите «Отмена»."
)


class InstallUiState(str, Enum):
    """Coarse install lifecycle exposed to the UI (UI-thread only)."""

    IDLE = "idle"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (
            InstallUiState.PREPARING,
            InstallUiState.DOWNLOADING,
            InstallUiState.VERIFYING,
            InstallUiState.INSTALLING,
        )


_PHASE_TO_STATE: dict[str, InstallUiState] = {
    "prepare": InstallUiState.PREPARING,
    "download": InstallUiState.DOWNLOADING,
    "verify": InstallUiState.VERIFYING,
    "transfer": InstallUiState.INSTALLING,
    "install": InstallUiState.INSTALLING,
    "done": InstallUiState.COMPLETED,
}


def map_phase_to_state(phase: str) -> InstallUiState | None:
    return _PHASE_TO_STATE.get((phase or "").strip().lower())


class InstallController:
    """Wraps InstallQueue; UI binds via on_changed / progress_hook.

    State transitions must be applied on the UI thread (via ``set_ui_state`` /
    ``apply_phase``). Worker threads only report phases through the progress hook.
    """

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
            allow_pending_queue=False,
        )
        self.last_failed_app: AppEntry | None = None
        self.last_installed_title = ""
        self._ui_state = InstallUiState.IDLE
        self._state_lock = threading.Lock()
        # Re-entry guard for the UI path before the queue worker is alive
        # (USB picker / Apple ID checks).
        self._preparing = False
        self.active_app_id: str | None = None
        self.active_app_title: str = ""

    @property
    def ui_state(self) -> InstallUiState:
        with self._state_lock:
            return self._ui_state

    @property
    def is_busy(self) -> bool:
        return self._preparing or self.queue.is_busy or self.queue.has_active_job

    @property
    def is_preparing(self) -> bool:
        return self._preparing

    @property
    def jobs(self) -> list[InstallJob]:
        return self.queue.jobs

    @property
    def current(self) -> InstallJob | None:
        return self.queue.current

    @property
    def cancel_event(self):
        return self.queue.cancel_event

    @property
    def worker_start_count(self) -> int:
        return self.queue.worker_start_count

    @property
    def max_concurrent_workers_seen(self) -> int:
        return self.queue.max_concurrent_workers_seen

    def set_progress_hook(self, hook: ProgressCb | None) -> None:
        self.queue.progress_hook = hook

    def set_ui_state(self, state: InstallUiState) -> None:
        """UI-thread only — assign lifecycle state."""
        with self._state_lock:
            self._ui_state = state

    def apply_phase(self, phase: str) -> InstallUiState | None:
        """Map a worker phase name → UI state. Call from UI thread only."""
        mapped = map_phase_to_state(phase)
        if mapped is None:
            return None
        self.set_ui_state(mapped)
        return mapped

    def begin_preparing(self, app: AppEntry | None = None) -> bool:
        """Mark install entry path as busy before the queue worker starts.

        Returns False if another install is already in progress.
        """
        with self._state_lock:
            if self._preparing or self.queue.is_busy or self.queue.has_active_job:
                return False
            self._preparing = True
            if app is not None:
                self.active_app_id = app.id
                self.active_app_title = app.maskTitle or app.title
            self._ui_state = InstallUiState.PREPARING
        return True

    def end_preparing(self, *, keep_active: bool = False) -> None:
        """Clear preparing flag (abort before enqueue, or hand-off to queue)."""
        with self._state_lock:
            self._preparing = False
            if not keep_active:
                if not self.queue.is_busy:
                    self.active_app_id = None
                    self.active_app_title = ""
                    if self._ui_state == InstallUiState.PREPARING:
                        self._ui_state = InstallUiState.IDLE

    def enqueue(self, apps: list, *, udid: str | None = None) -> int:
        if apps and not self.active_app_id:
            app = apps[0]
            self.active_app_id = app.id
            self.active_app_title = app.maskTitle or app.title
        added = self.queue.enqueue(apps, udid=udid)
        if added:
            # Hand-off: queue worker owns busy from here.
            self._preparing = False
        return added

    def try_enqueue(self, apps: list, *, udid: str | None = None) -> int:
        """Enqueue only when idle (or mid-prepare); 0 = rejected."""
        if self.queue.is_busy or self.queue.has_active_job:
            return 0
        return self.enqueue(apps, udid=udid)

    def cancel_all(self) -> None:
        self._preparing = False
        self.active_app_id = None
        self.active_app_title = ""
        self.queue.cancel_all()
        self.set_ui_state(InstallUiState.CANCELLED)

    def retry_failed(self) -> int:
        if self.is_busy:
            return 0
        count = self.queue.retry_failed()
        if count:
            self.set_ui_state(InstallUiState.PREPARING)
        return count

    def note_success(self, title: str) -> None:
        self.last_installed_title = title
        self.last_failed_app = None
        self.active_app_id = None
        self.active_app_title = ""
        self._preparing = False
        self.set_ui_state(InstallUiState.COMPLETED)

    def note_failure(self, app: AppEntry) -> None:
        self.last_failed_app = app
        self.last_installed_title = ""
        self.active_app_id = None
        self.active_app_title = ""
        self._preparing = False
        self.set_ui_state(InstallUiState.FAILED)

    def note_cancelled(self) -> None:
        self.active_app_id = None
        self.active_app_title = ""
        self._preparing = False
        self.set_ui_state(InstallUiState.CANCELLED)

    def clear_success(self) -> None:
        self.last_installed_title = ""

    def clear_failure(self) -> None:
        self.last_failed_app = None

    def clear_outcome(self) -> None:
        self.last_installed_title = ""
        self.last_failed_app = None
        if not self.is_busy:
            self.set_ui_state(InstallUiState.IDLE)

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

    def installing_title(self, selected_fallback: str = "") -> str:
        """Title for the in-progress card — prefer active job over selection."""
        if self.active_app_title:
            return self.active_app_title
        current = self.current
        if current is not None:
            return current.app.maskTitle or current.app.title
        return selected_fallback
