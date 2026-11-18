"""Where makereel keeps files, how much space they take, and clearing what isn't needed.

- Reels folder: one folder per video, with its reels. Yours to keep; delete them in Reels or by hand.
- Work folder (cache): downloads, uploads and live-stream buffers. Only needed while a job runs, so
  "Clear cache" can empty it at any time, except the buffers of live streams being recorded right now.
- Speech models live in their own cache and are managed in System -> Speech models.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

from ..config import env, reels_dir, save_settings, work_dir
from ..errors import Forbidden, InvalidInput, NotFound

log = logging.getLogger(__name__)


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def info() -> dict:
    reels, work = reels_dir().resolve(), work_dir().resolve()
    bench = (env().data_dir / "bench").resolve()
    free = shutil.disk_usage(reels if reels.exists() else Path.home()).free
    return {"reels_folder": str(reels), "work_folder": str(work), "reels_bytes": _size(reels),
            "cache_bytes": _size(work) + _size(bench), "free_bytes": free,
            "fixed_by_env": {"reels": bool(os.environ.get("MAKEREEL_OUTPUT_DIR")),
                             "work": bool(os.environ.get("MAKEREEL_WORK_DIR"))}}


def open_folder(which: str, folder: str | None = None) -> dict:
    """Show a folder in Finder / Explorer / the file manager (makereel runs on this computer)."""
    if which == "reels":
        path = reels_dir().resolve()
        if folder:                                   # one video's folder, by its name in the library
            path = (path / folder).resolve()
            if path.parent != reels_dir().resolve():
                raise Forbidden("that folder is outside the library")
    elif which == "work":
        path = work_dir().resolve()
    else:
        raise InvalidInput("which must be reels or work")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise NotFound("folder not found")
    system = platform.system()
    cmd = (["open", str(path)] if system == "Darwin" else ["explorer", str(path)] if system == "Windows"
           else ["xdg-open", str(path)])
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise InvalidInput(f"couldn't open a file window here ({e.strerror}); the folder is {path}") from e
    return {"opened": str(path)}


def clear_cache(recording: set[str]) -> dict:
    """Delete downloads, uploads, old live buffers and the benchmark video. `recording`: video ids of
    live streams being recorded now; their buffers are kept."""
    freed, kept = 0, []
    work = work_dir().resolve()
    targets = [p for p in work.iterdir()] if work.is_dir() else []
    bench = (env().data_dir / "bench").resolve()
    targets += [p for p in bench.iterdir() if p.suffix in (".mp4", ".mkv", ".webm")] if bench.is_dir() else []
    for p in targets:
        if p.name.startswith("live_") and p.name[len("live_"):] in recording:
            kept.append(p.name)
            continue
        size = _size(p)
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            freed += size
        except OSError as e:
            log.warning("couldn't delete %s (%s)", p, e.strerror)
    log.info("cleared %.1f MB of cache", freed / 1e6)
    return {"freed_bytes": freed, "kept": kept, **info()}


def move_reels(target: str, move_existing: bool) -> dict:
    """Use a new reels folder; optionally move the existing video folders there."""
    old = reels_dir().resolve()
    settings = save_settings({"reels_folder": target})
    new = reels_dir().resolve()
    moved = 0
    if move_existing and old.is_dir() and new != old:
        for d in old.iterdir():
            if d.is_dir() and not (new / d.name).exists():
                shutil.move(str(d), str(new / d.name))
                moved += 1
    return {"moved": moved, "settings": settings.data, **info()}
