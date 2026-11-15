"""The reel library on disk: one folder per source video, reels inside.

    output/
      Me at the zoo/
        folder.json          source video: title, channel, link
        reel_01.mp4          the reel, captions burned in
        reel_01.raw.mp4      same moment without captions (for fast re-renders)
        reel_01.ass          editable captions
        reel_01.json         post text with credits, hook, score, timing

Every path coming from outside goes through `_folder()` / `_reel_paths()`, which refuse
anything that escapes the output directory.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..config import env
from ..core import captions, render
from ..core.pipeline import FOLDER_FILE
from ..errors import Forbidden, InvalidInput, NotFound

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
REEL_NAME = re.compile(r"reel_\d+")


def root() -> Path:
    path = env().output_dir.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- folder naming
def safe_name(title: str, limit: int = 80) -> str:
    """A folder name that works on Windows, macOS and Linux."""
    name = _UNSAFE.sub(" ", title or "").strip(" .")
    name = re.sub(r"\s+", " ", name)[:limit].strip(" .")
    return name or "untitled"


def folder_for(title: str, video_id: str) -> Path:
    """Folder named after the video. Two different videos with the same title get the id appended."""
    base = root() / safe_name(title)
    info = base / FOLDER_FILE
    if base.exists() and info.exists():
        try:
            if json.loads(info.read_text(encoding="utf-8")).get("id") != video_id:
                return root() / f"{safe_name(title, 66)} ({video_id})"
        except ValueError:
            pass
    return base


# --------------------------------------------------------------------------- safe paths
def _folder(folder: str) -> Path:
    path = (root() / folder).resolve()
    if path.parent != root():
        raise Forbidden("that folder is outside the library")
    if not path.is_dir():
        raise NotFound(f"no folder named {folder!r}")
    return path


def _reel_paths(folder: str, name: str) -> tuple[Path, dict]:
    if not REEL_NAME.fullmatch(name):
        raise InvalidInput("reel names look like reel_01")
    meta_file = _folder(folder) / f"{name}.json"
    if not meta_file.exists():
        raise NotFound(f"no reel {folder}/{name}")
    return meta_file, json.loads(meta_file.read_text(encoding="utf-8"))


def media_file(rel: str) -> Path:
    """A file inside the library, for streaming to the browser."""
    path = (root() / rel).resolve()
    if root() not in path.parents:
        raise Forbidden("that file is outside the library")
    if not path.is_file():
        raise NotFound("file not found")
    return path


def _media_url(folder: str, file: str, path: Path) -> str:
    from urllib.parse import quote
    return f"/media/{quote(folder)}/{quote(file)}?v={int(path.stat().st_mtime)}"


# --------------------------------------------------------------------------- reading
def list_folders() -> list[dict]:
    out = []
    for d in root().iterdir():
        if not d.is_dir():
            continue
        reels = sorted(d.glob("reel_*.json"))
        info = {}
        if (d / FOLDER_FILE).exists():
            try:
                info = json.loads((d / FOLDER_FILE).read_text(encoding="utf-8"))
            except ValueError:
                pass
        if not reels and not info:
            continue
        cover = next((d / r.stem for r in reels if (d / f"{r.stem}.mp4").exists()), None)
        out.append({
            "folder": d.name, "title": info.get("title") or d.name, "channel": info.get("channel"),
            "url": info.get("url"), "live": info.get("live_status") == "is_live", "count": len(reels),
            "updated": max([p.stat().st_mtime for p in reels] + [d.stat().st_mtime]),
            "cover": _media_url(d.name, cover.name + ".mp4", cover.with_suffix(".mp4")) if cover else None,
        })
    return sorted(out, key=lambda f: f["updated"], reverse=True)


def list_reels(folder: str) -> dict:
    d = _folder(folder)
    info = {}
    if (d / FOLDER_FILE).exists():
        info = json.loads((d / FOLDER_FILE).read_text(encoding="utf-8"))
    reels = []
    for meta_file in sorted(d.glob("reel_*.json")):
        try:
            post = json.loads(meta_file.read_text(encoding="utf-8"))
        except ValueError:
            continue
        video = d / post.get("file", "")
        if video.is_file():
            reels.append(_summary(folder, meta_file.stem, post, video))
    return {"folder": folder, "info": info, "reels": reels}


def _summary(folder: str, name: str, post: dict, video: Path) -> dict:
    return {"folder": folder, "name": name, "video": _media_url(folder, video.name, video),
            "download": _media_url(folder, video.name, video) + "&download=1",
            **{k: post.get(k) for k in ("hook", "caption", "creator", "creator_url", "source",
                                        "score", "why", "start", "end")}}


def get_reel(folder: str, name: str) -> dict:
    meta_file, post = _reel_paths(folder, name)
    ass_text = (meta_file.parent / post["captions"]).read_text(encoding="utf-8")
    return {**_summary(folder, name, post, meta_file.parent / post["file"]),
            "transcript": " ".join(w["word"] for w in captions.parse_words(ass_text)),
            "ass": ass_text}


# --------------------------------------------------------------------------- editing
def update_reel(folder: str, name: str, *, hook: str | None = None, caption: str | None = None,
                transcript: str | None = None, ass: str | None = None) -> dict:
    """Apply edits and re-render.

    - `transcript`: the caption words as one paragraph; timings are kept (see captions.retime).
    - `hook`: on-screen title; the post text's first line follows it.
    - `caption`: the post text (credits etc.).
    - `ass`: the whole caption file, for advanced edits (wins over transcript/hook).
    """
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    ass_file = d / post["captions"]
    current = ass_file.read_text(encoding="utf-8")
    new_hook = hook.strip() if hook is not None and hook.strip() else post.get("hook")

    if ass is not None and ass.strip() and ass != current:
        text = ass
    else:
        text = current
        old_words = " ".join(w["word"] for w in captions.parse_words(current))
        if transcript is not None and " ".join(transcript.split()) != old_words:
            if not transcript.split():
                raise InvalidInput("the transcript is empty")
            text = captions.rebuild(current, transcript, new_hook)
        elif new_hook != post.get("hook"):
            text = captions.set_hook(current, new_hook or "")

    if caption is not None:
        post["caption"] = caption
    old_hook = post.get("hook") or ""
    if new_hook != old_hook:
        if old_hook and post.get("caption", "").startswith(old_hook):
            post["caption"] = new_hook + post["caption"][len(old_hook):]
        post["hook"] = new_hook

    ass_file.write_text(text, encoding="utf-8")
    render.burn(d / post["raw"], ass_file, d / post["file"])
    meta_file.write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    return get_reel(folder, name)


def delete_reel(folder: str, name: str) -> None:
    meta_file, post = _reel_paths(folder, name)
    for key in ("file", "raw", "captions"):
        if post.get(key):
            (meta_file.parent / post[key]).unlink(missing_ok=True)
    meta_file.unlink(missing_ok=True)


def delete_folder(folder: str) -> None:
    shutil.rmtree(_folder(folder))


def cleanup(keep_days: int) -> None:
    """Remove folders untouched for `keep_days` (24/7 mode keeps disk use bounded)."""
    import time
    cutoff = time.time() - keep_days * 86400
    for d in root().iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
