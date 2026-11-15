"""Logging setup plus per-job log capture.

Core modules log with `logging.getLogger(__name__)`. When a job runs, its id is stored in a
context variable; `JobLogHandler` sends every record logged under that id to the job's own
log, so the web app can show it. Threads that should inherit the job (live-stream helpers)
are started with `spawn()`, which copies the context.
"""
from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable

current_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_job", default=None)

_sinks: dict[str, Callable[[str], None]] = {}
_lock = threading.Lock()


class JobLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        job_id = current_job.get()
        if job_id is None:
            return
        sink = _sinks.get(job_id)
        if sink:
            try:
                sink(self.format(record))
            except Exception:  # a log sink must never break the job
                pass


def register_sink(job_id: str, sink: Callable[[str], None]) -> None:
    with _lock:
        _sinks[job_id] = sink


def unregister_sink(job_id: str) -> None:
    with _lock:
        _sinks.pop(job_id, None)


def spawn(target: Callable[[], None], name: str | None = None) -> threading.Thread:
    """Start a daemon thread that keeps the caller's job context (so its logs land in the job)."""
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(target,), name=name, daemon=True)
    t.start()
    return t


def setup(level: str = "INFO") -> None:
    root = logging.getLogger("makereel")
    if getattr(root, "_configured", False):
        return
    root.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    job = JobLogHandler()
    job.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    root.addHandler(console)
    root.addHandler(job)
    root.propagate = False
    root._configured = True  # type: ignore[attr-defined]
