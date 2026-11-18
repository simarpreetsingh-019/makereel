"""Job state: the single source of truth for what is queued, running, live or finished.

- One worker thread processes downloads/files one at a time (keeps memory and power low).
- Live streams each run in their own thread, up to `max_parallel_live`.
- Every job has its own log (see logs.py) and a status the web app polls.
All state changes go through `JobManager` methods under one lock.
"""
from __future__ import annotations

import enum
import logging
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import logs
from ..config import Settings, load_settings
from ..core.live import LiveSession
from ..errors import Conflict, MakereelError, NotFound
from . import runner

log = logging.getLogger(__name__)

MAX_LOG_LINES = 3000
MAX_FINISHED_JOBS = 200


class Status(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    LIVE = "live"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


ACTIVE = {Status.QUEUED, Status.RUNNING, Status.LIVE}


@dataclass
class Job:
    kind: str                         # link | file | watcher
    target: str                       # URL or file path
    options: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: Status = Status.QUEUED
    title: str = ""
    folder: str | None = None         # library folder the reels went into
    reels: int = 0
    error: dict | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    log: list[str] = field(default_factory=list, repr=False)
    session: LiveSession | None = field(default=None, repr=False)
    result: dict | None = None        # e.g. a benchmark's result id

    def append_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > MAX_LOG_LINES:
            del self.log[: len(self.log) - MAX_LOG_LINES]

    def to_dict(self, with_log: bool = False) -> dict:
        d = {"id": self.id, "kind": self.kind, "target": self.target, "status": self.status.value,
             "title": self.title or self.target, "folder": self.folder, "reels": self.reels,
             "error": self.error, "created": self.created, "finished": self.finished, "result": self.result,
             "last_line": self.log[-1] if self.log else ""}
        if self.session is not None:
            d["live"] = self.session.stats()
            d["reels"] = max(self.reels, self.session.stats()["reels"])
        if with_log:
            d["log"] = "\n".join(self.log)
        return d


class JobManager:
    def __init__(self, settings_path: Path | None = None):
        self.settings_path = settings_path
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[Job] = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="job-worker", daemon=True)
        self._worker.start()

    # -------------------------------------------------------------- queries
    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
            return [j.to_dict() for j in jobs]

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"no job {job_id}")
        return job

    def live_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status is Status.LIVE and j.kind != "watcher")

    def recording(self, video_id: str) -> Job | None:
        """The live job already recording this stream, if any (the watcher and pasted links share it)."""
        with self._lock:
            return next((j for j in self._jobs.values() if j.session is not None and j.status is Status.LIVE
                         and j.session.info.id == video_id), None)

    def _check_not_recording(self, session: LiveSession) -> None:
        other = self.recording(session.info.id)
        if other is not None:
            raise Conflict(f"already recording this stream: '{other.title}'",
                           "Its reels go into the folder that's already open under Reels.")

    # -------------------------------------------------------------- commands
    def submit_link(self, url: str, options: dict[str, Any]) -> Job:
        return self._add(Job("link", url, options, title=url))

    def submit_bench(self, options: dict[str, Any]) -> Job:
        return self._add(Job("bench", options.get("video") or "test video", options, title="Benchmark"))

    def submit_file(self, path: Path, options: dict[str, Any]) -> Job:
        return self._add(Job("file", str(path), options, title=options.get("title") or path.stem))

    def add_running(self, kind: str, title: str) -> Job:
        """A job that runs elsewhere (the watcher) but should show up with a log."""
        job = Job(kind, title, title=title, status=Status.LIVE)
        self._add(job, enqueue=False)
        return job

    def adopt_live(self, session: LiveSession) -> Job:
        """Track and run a live session in its own thread."""
        if self.live_count() >= self._settings({})["max_parallel_live"]:
            raise Conflict("already recording the maximum number of live streams",
                           "Stop one, or raise 'Live streams at once' in the 24/7 tab.")
        job = Job("link", session.info.url, title=session.info.title)
        with self._lock:                      # check and start together, so two starts can't both pass
            self._check_not_recording(session)
            self._add(job, enqueue=False)
            self._start_live(job, session)
        return job

    def stop(self, job_id: str) -> Job:
        job = self.get(job_id)
        with self._lock:
            if job.session is not None and job.status is Status.LIVE:
                job.session.stop.set()  # pending reels finish, then ffmpeg shuts down
                self._finish(job, Status.STOPPED)
            elif job.status is Status.QUEUED:
                self._finish(job, Status.STOPPED)
            elif job.status is Status.RUNNING:
                raise Conflict("this job is processing and can't be interrupted safely",
                               "It will finish on its own; delete its reels afterwards if unwanted.")
        return job

    def stop_all_live(self) -> None:
        with self._lock:
            for job in list(self._jobs.values()):
                if job.session is not None and job.status is Status.LIVE:
                    self.stop(job.id)

    # -------------------------------------------------------------- internals
    def _add(self, job: Job, enqueue: bool = True) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        logs.register_sink(job.id, job.append_log)
        if enqueue:
            self._queue.put(job)
        return job

    def _prune(self) -> None:
        done = [j for j in self._jobs.values() if j.status not in ACTIVE]
        for j in sorted(done, key=lambda j: j.created)[: max(0, len(done) - MAX_FINISHED_JOBS)]:
            self._jobs.pop(j.id, None)
            logs.unregister_sink(j.id)

    def _finish(self, job: Job, status: Status, error: MakereelError | Exception | None = None) -> None:
        job.status, job.finished = status, time.time()
        if isinstance(error, MakereelError):
            job.error = error.to_dict()
        elif error is not None:
            job.error = {"code": "internal", "message": str(error) or error.__class__.__name__, "hint": None}

    def _settings(self, options: dict[str, Any]) -> Settings:
        clip_keys = ("profile", "max_clips", "min_len", "max_len", "model", "model_other", "language", "layout", "fps")
        return load_settings(self.settings_path).with_clip(**{k: options.get(k) for k in clip_keys})

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job.status is not Status.QUEUED:
                continue
            token = logs.current_job.set(job.id)
            job.status = Status.RUNNING
            try:
                self._run(job)
            except MakereelError as e:
                log.error("✗ %s%s", e.message, f"  ({e.hint})" if e.hint else "")
                self._finish(job, Status.FAILED, e)
            except Exception as e:  # noqa: BLE001 - never let the worker die
                log.error("✗ unexpected error: %s\n%s", e, traceback.format_exc())
                self._finish(job, Status.FAILED, e)
            finally:
                logs.current_job.reset(token)

    def _run(self, job: Job) -> None:
        if job.kind == "bench":
            from . import bench
            job.result = {"id": bench.run(job.options.get("video"), job.options.get("model"))["id"]}
            self._finish(job, Status.DONE)
            return
        settings = self._settings(job.options)
        if job.kind == "file":
            reels = runner.run_file(Path(job.target), settings, job.options.get("title"),
                                    job.options.get("credit"), job.options.get("credit_url"),
                                    delete_after=not settings["keep_source"])
        else:
            result = runner.run_link(job.target, settings, job.options.get("section") or None)
            if isinstance(result, LiveSession):
                with self._lock:
                    if self.live_count() >= settings["max_parallel_live"]:
                        raise Conflict("already recording the maximum number of live streams")
                    self._check_not_recording(result)
                    self._start_live(job, result)
                return
            reels = result
        job.reels = len(reels)
        if reels:
            job.folder = reels[0]["folder"]
        self._finish(job, Status.DONE)

    def _start_live(self, job: Job, session: LiveSession) -> None:
        job.session, job.status = session, Status.LIVE
        job.title, job.folder = session.info.title, session.out.name

        def run() -> None:
            token = logs.current_job.set(job.id)
            try:
                session.run()
                if job.status is Status.LIVE:
                    self._finish(job, Status.DONE)
            except Exception as e:  # noqa: BLE001
                log.error("✗ live session failed: %s", e)
                self._finish(job, Status.FAILED, e)
            finally:
                logs.current_job.reset(token)

        threading.Thread(target=run, name=f"live-{job.id}", daemon=True).start()
