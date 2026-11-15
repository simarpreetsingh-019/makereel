"""Turn one input (a link or a local file) into reels. Used by the CLI, the job queue and the watcher."""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, env
from ..core import pipeline, sources
from ..core.live import LiveSession
from . import library

log = logging.getLogger(__name__)


def run_link(url: str, settings: Settings, section: str | None = None) -> LiveSession | list[dict]:
    """Auto-detects the link type.

    Live now -> returns a LiveSession (not started; call .run()).
    Anything else -> downloads, clips, returns the reels made.
    """
    info = sources.probe(url, settings["max_height"])
    log.info("▶ %s  [%s, %s]", info.title, info.live_status, info.channel or "unknown channel")
    if info.live_status == "is_live":
        return live_session(info, settings)
    if info.live_status == "is_upcoming":
        log.info("  not started yet; turn on the channel watcher to catch it when it goes live")
        return []
    work = env().work_dir
    dl = sources.download(url, work, section, chat=info.live_status in ("was_live", "post_live"),
                          max_height=settings["max_height"])
    try:
        folder = library.folder_for(dl.info.title, dl.info.id)
        return pipeline.process(dl.video, dl.info.to_meta(), folder, settings.clip, chat=dl.chat)
    finally:
        if not settings["keep_source"]:
            for f in work.glob(f"{dl.info.id}.*"):
                f.unlink(missing_ok=True)


def live_session(info: sources.SourceInfo, settings: Settings) -> LiveSession:
    return LiveSession(info, library.folder_for(info.title, info.id), env().work_dir, settings.clip,
                       settings["buffer_minutes"], settings["clips_per_hour"], settings["max_height"])


def run_file(video: Path, settings: Settings, title: str | None = None, credit: str | None = None,
             credit_url: str | None = None, delete_after: bool = False) -> list[dict]:
    """Clip a file you already have. Credits come from the arguments since there's no link to read."""
    title = title or video.stem
    meta = {"id": video.stem, "title": title, "channel": credit or "", "channel_url": credit_url,
            "url": credit_url or "", "tags": [], "offset": 0.0, "live_status": "not_live"}
    try:
        return pipeline.process(video, meta, library.folder_for(title, video.stem), settings.clip)
    finally:
        if delete_after:
            video.unlink(missing_ok=True)
