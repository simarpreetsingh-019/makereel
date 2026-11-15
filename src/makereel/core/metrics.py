"""Stage timers for benchmarks. `with stage("render"): ...` adds the time to the active recorder, if any.

Costs nothing when no benchmark is running.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
from collections import defaultdict

_recorder: contextvars.ContextVar[dict | None] = contextvars.ContextVar("metrics_recorder", default=None)


@contextlib.contextmanager
def stage(name: str):
    rec = _recorder.get()
    if rec is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        rec[name] += time.perf_counter() - t0


@contextlib.contextmanager
def record():
    """Collect stage times for everything run inside this block (same thread / spawned with logs.spawn)."""
    rec: dict[str, float] = defaultdict(float)
    token = _recorder.set(rec)
    try:
        yield rec
    finally:
        _recorder.reset(token)
