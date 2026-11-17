"""24/7 mode: watch channels for live streams and new uploads, work through inbox.txt, clean up old reels.

Between streams it uses almost no CPU: a live check is one small request per channel every
`poll_minutes`. Settings are re-read on every loop, so edits apply without a restart.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .. import logs
from ..config import env, load_settings
from ..core import sources, transcribe
from ..errors import MakereelError
from . import library, runner
from .jobs import JobManager, Status

log = logging.getLogger(__name__)
SEEN_KEEP = 50   # upload ids remembered per channel (only the newest few are ever listed)


class Watcher:
    def __init__(self, jobs: JobManager, settings_path: Path | None = None):
        self.jobs, self.settings_path = jobs, settings_path
        self._stop: threading.Event | None = None
        self._job = None
        self._watching: dict[str, str] = {}   # video id -> job id

    @property
    def running(self) -> bool:
        return self._stop is not None and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()
        self._job = self.jobs.add_running("watcher", "Watching channels")
        stop, job_id = self._stop, self._job.id

        def loop() -> None:
            logs.current_job.set(job_id)
            log.info("watcher started")
            try:
                while not stop.is_set():
                    self.tick()
                    stop.wait(load_settings(self.settings_path)["poll_minutes"] * 60)
            finally:
                if self._job is not None:
                    self._job.status = Status.STOPPED
                log.info("watcher stopped")

        threading.Thread(target=loop, name="watcher", daemon=True).start()

    def stop(self, stop_live: bool = True) -> None:
        if self._stop:
            self._stop.set()
        if stop_live:
            for job_id in self._watching.values():
                try:
                    self.jobs.stop(job_id)
                except MakereelError:
                    pass
            self._watching.clear()

    def tick(self) -> None:
        """One pass: inbox links, then each channel, then cleanup."""
        settings = load_settings(self.settings_path)
        for url in self._take_inbox(Path(settings["inbox"])):
            self.jobs.submit_link(url, {})
            log.info("inbox: queued %s", url)

        active = {j["id"] for j in self.jobs.list() if j["status"] == Status.LIVE.value}
        self._watching = {vid: jid for vid, jid in self._watching.items() if jid in active}
        for channel in settings["channels"]:
            if self.jobs.live_count() >= settings["max_parallel_live"]:
                break
            try:
                info = sources.probe(sources.channel_live_url(channel), settings["max_height"])
            except MakereelError:
                continue  # offline / not live: yt-dlp raises, that's normal
            if info.live_status != "is_live" or info.id in self._watching:
                continue
            log.info("%s is live: %s", channel, info.title)
            try:
                job = self.jobs.adopt_live(runner.live_session(info, settings))
                self._watching[info.id] = job.id
            except MakereelError as e:
                log.warning("could not start recording %s: %s", channel, e.message)

        if settings["watch_uploads"]:
            self._check_uploads(settings)

        library.cleanup(settings["keep_days"])
        if not self._watching:
            transcribe.release_if_idle(300)  # give the speech model's RAM back between streams

    # ------------------------------------------------------------------ new uploads
    def _seen_path(self) -> Path:
        return (self.settings_path or env().config_file).with_name("seen_uploads.json")

    def _check_uploads(self, settings) -> None:
        """Queue each channel's uploads we haven't seen (new videos, premieres once they've aired).

        The first time a channel is checked, its current videos are only remembered, not clipped:
        adding a channel shouldn't turn its back catalogue into reels.
        """
        path = self._seen_path()
        try:
            seen: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        changed = False
        for channel in settings["channels"]:
            try:
                uploads = sources.recent_uploads(channel)
            except MakereelError as e:
                log.debug("uploads check failed for %s: %s", channel, e.message)
                continue
            if not uploads:
                continue
            known = seen.get(channel)
            ids = [u.id for u in uploads]
            if known is None:                               # first look: remember, don't clip
                seen[channel] = ids
                changed = True
                log.info("%s: watching for new uploads (%d existing ones skipped)", channel, len(ids))
                continue
            for up in reversed(uploads):                    # oldest new one first
                if up.id in known or up.id in self._watching:
                    continue
                self.jobs.submit_link(up.url, {})
                log.info("%s uploaded: %s", channel, up.title)
                known.append(up.id)
                changed = True
            seen[channel] = known[-SEEN_KEEP:]
        if changed:
            path.write_text(json.dumps(seen, indent=1), encoding="utf-8")

    @staticmethod
    def _take_inbox(path: Path) -> list[str]:
        if not path.exists():
            return []
        urls = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        path.write_text("# paste links here, one per line\n", encoding="utf-8")
        return urls
