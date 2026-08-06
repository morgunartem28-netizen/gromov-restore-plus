"""Sequential install queue — at most one worker thread; jobs wait or are rejected."""
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
    udid: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"{self.app.id}-{int(time.time() * 1000)}"


ProgressCb = Callable[[str, float, str], None]
WorkerCb = Callable[[InstallJob, ProgressCb], None]


class InstallQueue:
    """One active install at a time. New apps are rejected while a worker is alive
    (single-active UX). Retry re-queues failed/cancelled jobs only when idle or
    already running the same loop.
    """

    def __init__(
        self,
        *,
        worker: WorkerCb,
        on_changed: Callable[[], None] | None = None,
        on_cancel_request: Callable[[], None] | None = None,
        allow_pending_queue: bool = False,
    ) -> None:
        self._jobs: list[InstallJob] = []
        self._lock = threading.RLock()
        self._worker = worker
        self._on_changed = on_changed
        self._on_cancel_request = on_cancel_request
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._current: InstallJob | None = None
        self.progress_hook: ProgressCb | None = None
        # When False (default): refuse enqueue while busy — single-active UX.
        self.allow_pending_queue = allow_pending_queue
        self.worker_start_count = 0
        self.max_concurrent_workers_seen = 0
        self._alive_workers = 0

    def _notify(self) -> None:
        if self._on_changed:
            self._on_changed()

    @property
    def jobs(self) -> list[InstallJob]:
        with self._lock:
            return list(self._jobs)

    @property
    def current(self) -> InstallJob | None:
        with self._lock:
            return self._current

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def has_active_job(self) -> bool:
        """True while a worker loop is alive or a job is RUNNING/PENDING."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            return any(
                job.status in (JobStatus.PENDING, JobStatus.RUNNING) for job in self._jobs
            )

    @property
    def cancel_event(self) -> threading.Event:
        """Shared cancel flag for the active install pipeline."""
        return self._stop

    @property
    def active_worker_count(self) -> int:
        with self._lock:
            return self._alive_workers

    def enqueue(self, apps: list, *, udid: str | None = None) -> int:
        """Add apps and start worker. Returns 0 if rejected (busy / duplicate)."""
        if not apps:
            return 0
        with self._lock:
            busy = bool(self._thread and self._thread.is_alive())
            if busy and not self.allow_pending_queue:
                # Single-active: never pile up another app while one is running.
                return 0

            existing = {
                job.app.id
                for job in self._jobs
                if job.status in (JobStatus.PENDING, JobStatus.RUNNING)
            }
            added = 0
            for app in apps:
                if app.id in existing:
                    continue
                self._jobs.append(InstallJob(app=app, udid=udid))
                existing.add(app.id)
                added += 1
            should_start = added > 0
        if added:
            self._notify()
        if should_start:
            self.start()
        return added

    def start(self) -> None:
        """Start the worker loop if idle. Never clears cancel while a worker is alive."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="install-queue")
            self.worker_start_count += 1
            thread = self._thread
        thread.start()

    def cancel_all(self) -> None:
        self._stop.set()
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
            should_start = count > 0
        if count:
            self._notify()
        if should_start:
            self.start()
        return count

    def clear_finished(self) -> None:
        with self._lock:
            self._jobs = [
                job
                for job in self._jobs
                if job.status not in (JobStatus.DONE, JobStatus.CANCELLED, JobStatus.FAILED)
            ]
        self._notify()

    def _run_loop(self) -> None:
        with self._lock:
            self._alive_workers += 1
            self.max_concurrent_workers_seen = max(
                self.max_concurrent_workers_seen, self._alive_workers
            )
        try:
            while not self._stop.is_set():
                job: InstallJob | None = None
                with self._lock:
                    for item in self._jobs:
                        if item.status == JobStatus.PENDING:
                            job = item
                            item.status = JobStatus.RUNNING
                            self._current = job
                            break
                if job is None:
                    break

                self._notify()

                def progress(phase: str, value: float, text: str) -> None:
                    hook = self.progress_hook
                    if callable(hook):
                        hook(phase, value, text)

                try:
                    if self._stop.is_set():
                        with self._lock:
                            job.status = JobStatus.CANCELLED
                            job.error = "Отменено"
                    else:
                        self._worker(job, progress)
                        with self._lock:
                            if self._stop.is_set():
                                job.status = JobStatus.CANCELLED
                                job.error = "Отменено"
                            elif job.status == JobStatus.RUNNING:
                                job.status = JobStatus.DONE
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    with self._lock:
                        if self._stop.is_set() or "отмен" in msg.lower() or "cancel" in msg.lower():
                            job.status = JobStatus.CANCELLED
                            job.error = "Отменено"
                        else:
                            job.status = JobStatus.FAILED
                            job.error = msg

                with self._lock:
                    self._current = None
                self._notify()
        finally:
            with self._lock:
                self._current = None
                self._alive_workers = max(0, self._alive_workers - 1)
            self._notify()
