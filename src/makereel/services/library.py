"""The reel library on disk: one folder per source video, reels inside.

    output/
      Me at the zoo/
        folder.json          source video: title, channel, link
        reel_01.mp4          the reel (9:16), captions burned in
        reel_01.src.mp4      the moment in its original shape: master for every export format
        reel_01.raw.mp4      9:16 without captions (for fast re-renders)
        reel_01.4x5.mp4      exports in other formats, made on demand
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

from ..config import env, load_settings
from ..core import branding, captions, render, transcribe
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
    d = video.parent
    exports = {}
    for fmt, item in (post.get("exports") or {}).items():
        f = d / item["file"]
        if f.is_file():
            url = _media_url(folder, f.name, f)
            exports[fmt] = {"fit": item.get("fit"), "video": url, "download": url + "&download=1"}
    return {"folder": folder, "name": name, "video": _media_url(folder, video.name, video),
            "download": _media_url(folder, video.name, video) + "&download=1",
            "raw": _media_url(folder, post["raw"], d / post["raw"]) if (d / post.get("raw", "-")).is_file() else None,
            "can_export": (d / post.get("source_clip", "-")).is_file(),
            "logo": post.get("logo", True), "exports": exports,
            **{k: post.get(k) for k in ("hook", "caption", "creator", "creator_url", "source",
                                        "score", "why", "start", "end", "fit")}}


def get_reel(folder: str, name: str) -> dict:
    meta_file, post = _reel_paths(folder, name)
    ass_text = (meta_file.parent / post["captions"]).read_text(encoding="utf-8")
    words = captions.parse_words(ass_text)
    return {**_summary(folder, name, post, meta_file.parent / post["file"]),
            "transcript": " ".join(w["word"] for w in words), "words": words, "ass": ass_text}


# --------------------------------------------------------------------------- editing
def update_reel(folder: str, name: str, *, hook: str | None = None, caption: str | None = None,
                transcript: str | None = None, words: list[dict] | None = None, offset: float | None = None,
                ass: str | None = None, logo: bool | None = None, restyle: bool = False) -> dict:
    """Apply edits and re-render the reel (and any exports).

    - `transcript`: the caption words as a paragraph. Unchanged words keep their timing; edited,
      added or removed words are fitted around them (captions.align).
    - `words`: exact timings from the timing editor [{start, end, word}].
    - `offset`: move every caption earlier (negative seconds) or later (positive).
    - `hook`: on-screen title; the post text's first line follows it.
    - `caption`: the post text (credits etc.).
    - `ass`: the whole caption file, for advanced edits (wins over the options above).
    - `logo`: show the brand logo on this reel or not.
    - `restyle`: re-apply the current brand kit's caption style.
    """
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    ass_file = d / post["captions"]
    current = ass_file.read_text(encoding="utf-8")
    new_hook = hook.strip() if hook is not None and hook.strip() else post.get("hook")
    brand = load_settings().brand

    if ass is not None and ass.strip() and ass != current:
        text = ass
    else:
        timed = captions.parse_words(current)
        changed = False
        if words is not None:
            try:
                timed = captions.clean_timings(words)
            except ValueError as e:
                raise InvalidInput(str(e)) from e
            changed = True
        if transcript is not None and " ".join(transcript.split()) != " ".join(w["word"] for w in timed):
            if not transcript.split():
                raise InvalidInput("the transcript is empty")
            timed = captions.align(transcript, timed)
            changed = True
        if offset:
            if abs(offset) > 10:
                raise InvalidInput("shift captions by at most 10 seconds")
            timed = captions.shift(timed, offset)
            changed = True
        style = branding.style_for(render.MAIN_FORMAT, brand) if restyle else None
        if changed or restyle:
            text = captions.rebuild(current, timed, new_hook, style)
        elif new_hook != post.get("hook"):
            text = captions.set_hook(current, new_hook or "")
        else:
            text = current

    if caption is not None:
        post["caption"] = caption
    old_hook = post.get("hook") or ""
    if new_hook != old_hook:
        if old_hook and post.get("caption", "").startswith(old_hook):
            post["caption"] = new_hook + post["caption"][len(old_hook):]
        post["hook"] = new_hook
    if logo is not None:
        post["logo"] = bool(logo)

    ass_file.write_text(text, encoding="utf-8")
    render.burn(d / post["raw"], ass_file, d / post["file"], branding.logo_for(brand, post.get("logo", True)),
                branding.fonts_dir())
    meta_file.write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    for fmt, item in list((post.get("exports") or {}).items()):   # keep exports in step with edits
        if (d / item["file"]).exists():
            export_reel(folder, name, fmt, item.get("fit") or post.get("fit") or "blur")
    return get_reel(folder, name)


def autosync(folder: str, name: str) -> dict:
    """Re-time the captions from the reel's own audio, keeping the user's corrected words."""
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    audio = d / post.get("source_clip", "-")
    if not audio.is_file():
        audio = d / post["raw"]
    clip = load_settings().clip
    fresh = transcribe.words_in_file(audio, clip["model"], clip["language"])
    if not fresh:
        raise InvalidInput("no speech found in this reel, so there's nothing to sync to")
    current = captions.parse_words((d / post["captions"]).read_text(encoding="utf-8"))
    text = " ".join(w["word"] for w in current) or " ".join(w["word"] for w in fresh)
    return update_reel(folder, name, words=captions.align(text, fresh))


def export_reel(folder: str, name: str, fmt: str, fit: str | None = None) -> dict:
    """Make this reel in another shape (4x5, 1x1, 16x9 or 9x16 with a different fit)."""
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    fit = fit or post.get("fit") or "blur"
    if fmt not in render.FORMATS or fit not in render.FITS:
        raise InvalidInput(f"format must be one of {', '.join(render.FORMATS)}; fit one of {', '.join(render.FITS)}")
    source = d / post.get("source_clip", "-")
    if not source.is_file():
        raise InvalidInput("this reel was made before exports existed",
                           "Run its link again to get reels that can be exported in any format.")
    brand = load_settings().brand
    main_ass = (d / post["captions"]).read_text(encoding="utf-8")
    words, hook = captions.parse_words(main_ass), captions.parse_hook(main_ass)
    ass = d / f"{name}.{fmt}.ass"
    ass.write_text(captions.rebuild(main_ass, words, hook, branding.style_for(fmt, brand)), encoding="utf-8")
    out = d / f"{name}.{fmt}.mp4"
    render.export(source, ass, out, fmt, fit, branding.logo_for(brand, post.get("logo", True)),
                  branding.fonts_dir())
    post.setdefault("exports", {})[fmt] = {"file": out.name, "fit": fit, "captions": ass.name}
    meta_file.write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    return get_reel(folder, name)


def delete_reel(folder: str, name: str) -> None:
    meta_file, post = _reel_paths(folder, name)
    for key in ("file", "raw", "captions", "source_clip"):
        if post.get(key):
            (meta_file.parent / post[key]).unlink(missing_ok=True)
    for item in (post.get("exports") or {}).values():
        for key in ("file", "captions"):
            (meta_file.parent / item[key]).unlink(missing_ok=True)
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
