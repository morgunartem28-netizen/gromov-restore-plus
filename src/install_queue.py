"""Sequential install queue with pause / cancel / retry."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_manager import AppEntry


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class InstallJob:
    app: AppEntry
    status: JobStatus = JobStatus.PENDING
    error: str = ""
    id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"{self.app.id}-{int(time.time() * 1000)}"


ProgressCb = Callable[[str, float, str], None]
WorkerCb = Callable[[InstallJob, ProgressCb], None]


class InstallQueue:
    def __init__(
        self,
        *,
        worker: WorkerCb,
        on_changed: Callable[[], None] | None = None,
        on_cancel_request: Callable[[], None] | None = None,
    ) -> None:
        self._jobs: list[InstallJob] = []
        self._lock = threading.Lock()
        self._worker = worker
        self._on_changed = on_changed
        self._on_cancel_request = on_cancel_request
        self._thread: threading.Thread | None = None
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._current: InstallJob | None = None

    def _notify(self) -> None:
        if self._on_changed:
            self._on_changed()

    @property
    def jobs(self) -> list[InstallJob]:
        with self._lock:
            return list(self._jobs)

    @property
    def current(self) -> InstallJob | None:
        return self._current

    @property
    def is_busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def enqueue(self, apps: list) -> int:
        added = 0
        with self._lock:
            existing = {
                job.app.id
                for job in self._jobs
                if job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            }
            for app in apps:
                if app.id in existing:
                    continue
                self._jobs.append(InstallJob(app=app))
                existing.add(app.id)
                added += 1
        self._notify()
        if added:
            self.start()
        return added

    def start(self) -> None:
        self._stop.clear()
        self._pause.clear()
        if self.is_busy:
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._pause.set()
        self._notify()

    def resume(self) -> None:
        self._pause.clear()
        self.start()
        self._notify()

    def cancel_all(self) -> None:
        self._stop.set()
        self._pause.clear()
        if self._on_cancel_request:
            self._on_cancel_request()
        with self._lock:
            for job in self._jobs:
                if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                    job.status = JobStatus.CANCELLED
                    job.error = "Отменено"
        self._notify()

    def retry_failed(self) -> int:
        count = 0
        with self._lock:
            for job in self._jobs:
                if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                    job.status = JobStatus.PENDING
                    job.error = ""
                    count += 1
        if count:
            self.start()
            self._notify()
        return count

    def clear_finished(self) -> None:
        with self._lock:
            self._jobs = [
                job for job in self._jobs if job.status not in (JobStatus.DONE, JobStatus.CANCELLED)
            ]
        self._notify()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.15)

            job: InstallJob | None = None
            with self._lock:
                for item in self._jobs:
                    if item.status == JobStatus.PENDING:
                        job = item
                        item.status = JobStatus.RUNNING
                        break
            if job is None:
                break

            self._current = job
            self._notify()

            def progress(phase: str, value: float, text: str) -> None:
                _ = (phase, value, text)
                # UI listens via external progress hook set by app.
                hook = getattr(self, "progress_hook", None)
                if callable(hook):
                    hook(phase, value, text)

            try:
                if self._stop.is_set():
                    job.status = JobStatus.CANCELLED
                    job.error = "Отменено"
                else:
                    self._worker(job, progress)
                    if self._stop.is_set():
                        job.status = JobStatus.CANCELLED
                        job.error = "Отменено"
                    elif job.status == JobStatus.RUNNING:
                        job.status = JobStatus.DONE
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if self._stop.is_set() or "отмен" in msg.lower() or "cancel" in msg.lower():
                    job.status = JobStatus.CANCELLED
                    job.error = "Отменено"
                else:
                    job.status = JobStatus.FAILED
                    job.error = msg

            self._current = None
            self._notify()

        self._current = None
        self._notify()
