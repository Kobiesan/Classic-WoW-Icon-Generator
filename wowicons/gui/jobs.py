"""Run long work off the UI thread and stream it back.

Tkinter is single threaded: touching a widget from a worker thread corrupts the
interpreter, sometimes much later and somewhere else. So workers never touch
widgets. They push events onto a queue, and the UI drains that queue from a
``after()`` tick on the main thread.

Everything here is display free, so the awkward parts - cancellation, failure,
ordering - are unit tested without a GUI.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

__all__ = ["JobStatus", "JobEvent", "JobHandle", "JobRunner", "CancelledError"]


class CancelledError(Exception):
    """Raised inside a worker when the user cancels."""


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


@dataclass(frozen=True)
class JobEvent:
    """Something a worker wants the UI to know."""

    kind: str                       # "log" | "progress" | "status" | "result"
    message: str = ""
    fraction: Optional[float] = None
    status: Optional[JobStatus] = None
    payload: Any = None


@dataclass
class JobHandle:
    """A worker's view of the job: report progress, check for cancellation."""

    name: str
    _events: "queue.Queue[JobEvent]"
    _cancel: threading.Event = field(default_factory=threading.Event)

    def log(self, message: str) -> None:
        for line in str(message).splitlines() or [""]:
            self._events.put(JobEvent("log", message=line))

    def progress(self, fraction: Optional[float], message: str = "") -> None:
        if fraction is not None:
            fraction = min(max(float(fraction), 0.0), 1.0)
        self._events.put(JobEvent("progress", message=message, fraction=fraction))

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledError(f"{self.name} was cancelled.")


class JobRunner:
    """Runs one job at a time and delivers its events to the UI thread."""

    def __init__(self) -> None:
        self._events: "queue.Queue[JobEvent]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._handle: Optional[JobHandle] = None
        self._status = JobStatus.PENDING
        self._lock = threading.Lock()

    @property
    def status(self) -> JobStatus:
        with self._lock:
            return self._status

    @property
    def is_running(self) -> bool:
        return self.status == JobStatus.RUNNING

    def start(self, name: str, work: Callable[[JobHandle], Any]) -> JobHandle:
        """Begin ``work`` on a background thread.

        Refuses to start a second job while one is running: two concurrent
        trainings or dataset builds writing the same folders is never what the
        user meant.
        """
        if self.is_running:
            raise RuntimeError(f"{name} cannot start: another job is still running.")

        handle = JobHandle(name=name, _events=self._events)
        self._handle = handle
        self._set_status(JobStatus.RUNNING)
        self._events.put(JobEvent("status", message=f"{name} started", status=JobStatus.RUNNING))

        def runner() -> None:
            try:
                result = work(handle)
            except CancelledError as exc:
                self._set_status(JobStatus.CANCELLED)
                self._events.put(
                    JobEvent("status", message=str(exc) or "Cancelled.", status=JobStatus.CANCELLED)
                )
            except Exception as exc:  # noqa: BLE001 - the UI must survive any worker error
                self._set_status(JobStatus.FAILED)
                # Full traceback to the log, one readable line to the status.
                self._events.put(JobEvent("log", message=traceback.format_exc()))
                self._events.put(
                    JobEvent("status", message=_friendly_error(exc), status=JobStatus.FAILED)
                )
            else:
                if handle.cancelled:
                    self._set_status(JobStatus.CANCELLED)
                    self._events.put(
                        JobEvent("status", message="Cancelled.", status=JobStatus.CANCELLED)
                    )
                else:
                    self._set_status(JobStatus.SUCCEEDED)
                    self._events.put(JobEvent("result", payload=result))
                    self._events.put(
                        JobEvent("status", message=f"{name} finished.", status=JobStatus.SUCCEEDED)
                    )

        thread = threading.Thread(target=runner, name=f"wowicons-{name}", daemon=True)
        self._thread = thread
        thread.start()
        return handle

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()

    def drain(self, limit: int = 200) -> List[JobEvent]:
        """Pop pending events. Called from the UI thread on a timer."""
        events: List[JobEvent] = []
        for _ in range(limit):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the worker. For tests and for shutdown, not for the UI."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _set_status(self, status: JobStatus) -> None:
        with self._lock:
            self._status = status


def _friendly_error(exc: Exception) -> str:
    """A message a non-technical user can act on."""
    if isinstance(exc, FileNotFoundError):
        return f"Could not find: {exc.filename or exc}"
    if isinstance(exc, PermissionError):
        return f"Permission denied: {exc.filename or exc}. Try a folder inside your Documents."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
