"""24/7 mode: watch channels for live streams and new uploads, work through inbox.txt, clean up old reels.

Between streams it uses almost no CPU: a live check is one small request per channel every
`poll_minutes`. Settings are re-read on every loop, so edits apply without a restart.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path

from .. import logs
from ..config import env, load_settings, since_cutoff
from ..core import sources, transcribe
from ..errors import MakereelError
from . import library, runner
from .jobs import JobManager, Status

log = logging.getLogger(__name__)
SEEN_KEEP = 100  # upload ids remembered per channel (only the newest few are ever listed)
def channel_and_language(line: str, default: str = "") -> tuple[str, str | None]:
    """'@name | hi' -> ('@name', 'hi'). Without '| xx' the watched-channels default (or auto) applies."""
    name, _, lang = line.partition("|")
    lang = lang.strip().lower() or default
    return name.strip(), (lang or None)


def _default_language(settings) -> str:
    try:
        return settings["watch_language"] or ""
    except KeyError:
        return ""


RANDOM_EVERY = (4, 30)   # "random": each wait between uploads checks is anything in this range (minutes)


def uploads_wait(every: str) -> float:
    """Seconds until the next uploads check."""
    if every == "random":
        return random.uniform(*RANDOM_EVERY) * 60
    return int(every) * 60


class Watcher:
    def __init__(self, jobs: JobManager, settings_path: Path | None = None):
        self.jobs, self.settings_path = jobs, settings_path
        self._stop: threading.Event | None = None
        self._job = None
        self._watching: dict[str, str] = {}   # video id -> job id
        self._next_live = 0.0                 # when the next live check / uploads check is due
        self._next_uploads = 0.0

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
                    try:
                        self.tick()
                    except Exception:  # noqa: BLE001 - one bad pass must never stop 24/7 watching
                        log.exception("watcher pass failed; trying again on the next check")
                    stop.wait(self.wait_seconds())
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

    def wait_seconds(self) -> float:
        """Sleep until whichever check is due next (live every poll_minutes, uploads on their own clock)."""
        settings = load_settings(self.settings_path)
        due = [self._next_live] + ([self._next_uploads] if settings["watch_uploads"] else [])
        return min(max(min(due) - time.time(), 5.0), settings["poll_minutes"] * 60)

    def tick(self) -> None:
        """One pass: inbox links, then each channel (live and uploads, when due), then cleanup."""
        settings = load_settings(self.settings_path)
        for url in self._take_inbox(Path(settings["inbox"])):
            self.jobs.submit_link(url, {})
            log.info("inbox: queued %s", url)

        now = time.time()
        key = (settings["uploads_since"], settings["uploads_every"])
        if key != getattr(self, "_uploads_key", key):       # window or interval changed: check now
            self._next_uploads = 0.0
        self._uploads_key = key
        if settings["watch_uploads"] and now >= self._next_uploads:
            self._check_uploads(settings)
            self._next_uploads = time.time() + uploads_wait(settings["uploads_every"])
            log.info("next uploads check in %.0f min", (self._next_uploads - time.time()) / 60)
        if now < self._next_live:
            return
        self._next_live = now + settings["poll_minutes"] * 60

        active = {j["id"] for j in self.jobs.list() if j["status"] == Status.LIVE.value}
        self._watching = {vid: jid for vid, jid in self._watching.items() if jid in active}
        for line in settings["channels"]:
            channel, lang = channel_and_language(line, _default_language(settings))
            if self.jobs.live_count() >= settings["max_parallel_live"]:
                break
            try:
                info = sources.probe(sources.channel_live_url(channel), settings["max_height"])
            except MakereelError:
                continue  # offline / not live: yt-dlp raises, that's normal
            if info.live_status != "is_live" or info.id in self._watching:
                continue
            already = self.jobs.recording(info.id)
            if already is not None:                         # e.g. its link was pasted by hand
                self._watching[info.id] = already.id
                continue
            log.info("%s is live: %s", channel, info.title)
            try:
                job = self.jobs.adopt_live(runner.live_session(info, settings.with_clip(language=lang)))
                self._watching[info.id] = job.id
            except MakereelError as e:
                log.warning("could not start recording %s: %s", channel, e.message)

        library.cleanup(settings["keep_days"])
        if not self._watching:
            transcribe.release_if_idle(300)  # give the speech model's RAM back between streams

    # ------------------------------------------------------------------ new uploads
    def _seen_path(self) -> Path:
        return (self.settings_path or env().config_file).with_name("seen_uploads.json")

    def _check_uploads(self, settings) -> None:
        """Queue each channel's uploads inside the chosen window that we haven't clipped yet.

        uploads_since "new": the first check only notes a channel's existing videos; what's posted
        after that is clipped. "24h" / "48h" / a date: videos posted since then are clipped too, so
        the first check can catch up on the last day or two. Changing the window re-checks videos
        that were skipped before.
        """
        path = self._seen_path()
        try:
            seen: dict = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        since, now, changed = settings["uploads_since"], time.time(), False
        for line in settings["channels"]:
            channel, lang = channel_and_language(line, _default_language(settings))
            try:
                uploads = sources.recent_uploads(channel)
            except MakereelError as e:
                log.debug("uploads check failed for %s: %s", channel, e.message)
                continue
            if not uploads:
                continue
            state = seen.get(channel)
            if isinstance(state, list):                     # older format: a plain list of seen ids
                state = {"done": [], "skipped": state, "added": now, "since": since}
            first = state is None
            if first:
                state = {"done": [], "skipped": [], "added": now, "since": since}
            if state.get("since") != since:                 # new window: look at skipped videos again
                state["skipped"], state["since"] = [], since
            cutoff = since_cutoff(since, now)
            picked = self._pick_uploads(uploads, state, first, cutoff)
            for up in reversed(picked):                     # oldest first
                self.jobs.submit_link(up.url, {"language": lang} if lang else {})
                state["done"].append(up.id)
                log.info("%s uploaded: %s", channel, up.title)
            if first:
                log.info("%s: watching for uploads (%d to clip now)", channel, len(picked))
            state["done"], state["skipped"] = state["done"][-SEEN_KEEP:], state["skipped"][-SEEN_KEEP:]
            seen[channel] = state
            changed = True
        if changed:
            path.write_text(json.dumps(seen, indent=1), encoding="utf-8")

    def _pick_uploads(self, uploads, state: dict, first: bool, cutoff: float | None) -> list:
        """Uploads (newest first) to clip now; the rest are noted as skipped."""
        known = set(state["done"]) | set(state["skipped"]) | set(self._watching)
        fresh = [u for u in uploads if u.id not in known]
        if cutoff is None:                                  # "new": everything unseen is new, except on the first look
            if first:
                state["skipped"] += [u.id for u in fresh]
                return []
            return fresh
        picked = []
        for i, up in enumerate(fresh):                      # newest first: stop at the first one before the cutoff
            try:
                when = sources.probe(up.url).published
            except MakereelError:
                continue                                    # try again on the next check
            if when is not None and when < cutoff:
                state["skipped"] += [u.id for u in fresh[i:]]
                break
            if when is None and first:
                state["skipped"].append(up.id)
                continue
            picked.append(up)
        return picked

    @staticmethod
    def _take_inbox(path: Path) -> list[str]:
        if not path.exists():
            return []
        urls = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        path.write_text("# paste links here, one per line\n", encoding="utf-8")
        return urls
