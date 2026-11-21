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

from ..config import load_settings, reels_dir
from ..core import branding, captions, framing, language, render, transcribe
from ..core.pipeline import FOLDER_FILE, caption_hook, folder_language
from ..errors import Forbidden, InvalidInput, NotFound

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
REEL_NAME = re.compile(r"reel_\d+")


def root() -> Path:
    path = reels_dir().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- folder naming
def safe_name(title: str, limit: int = 80) -> str:
    """A folder name that works on Windows, macOS and Linux."""
    name = _UNSAFE.sub(" ", title or "").strip(" .")
    name = re.sub(r"\s+", " ", name)[:limit].strip(" .")
    return name or "untitled"


def folder_for(title: str, video_id: str) -> Path:
    """Folder named after the video. Two different videos with the same title get the id appended.

    The same video always lands in the same folder, even when its title changed (YouTube adds the
    current time to live-stream titles, so a restarted recording would otherwise get a new folder).
    """
    for meta in root().glob(f"*/{FOLDER_FILE}") if root().is_dir() else []:
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("id") == video_id:
                return meta.parent
        except (OSError, ValueError):
            continue
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
            "logo": post.get("logo", True), "exports": exports, "look": _look(post),
            **{k: post.get(k) for k in ("hook", "caption", "creator", "creator_url", "source",
                                        "score", "why", "start", "end", "fit", "ai")}}


def _look(post: dict) -> dict:
    """The reel's effective caption look (its overrides on top of the brand kit), for the editor."""
    b = load_settings().brand
    style = branding.style_for(render.MAIN_FORMAT, b, post.get("look"), fit=post.get("fit"))
    default_vertical = {"bottom": 0.29, "middle": 0.46, "top": 0.78}[style.position]
    return {"vertical": style.vertical if style.vertical is not None else default_vertical, "size": style.size,
            "box": style.box, "box_colour": style.box_colour, "box_opacity": style.box_opacity,
            "font": style.font, "text_colour": style.text_colour, "highlight_colour": style.highlight_colour,
            "outline_colour": style.outline_colour, "template": branding.template_for(b, post.get("look")),
            "script": branding.script_mode(b, post.get("look")), "custom": bool(post.get("look"))}


def _camera_view(folder: str, d: Path, post: dict) -> dict:
    """What the Camera editor needs: the wide master and how much of its width the 9:16 crop shows."""
    src = d / post.get("source_clip", "-")
    if post.get("fit") != "track" or not src.is_file():
        return {}
    try:
        w, h = framing._dimensions(src)
    except Exception:  # noqa: BLE001
        return {}
    out_w, out_h = render.FORMATS[render.MAIN_FORMAT]
    return {"source": _media_url(folder, src.name, src), "src_offset": post.get("src_offset", 0.0),
            "crop_share": round(min(1.0, h * out_w / out_h / w), 4)}


# --------------------------------------------------------------------------- YouTube captions after a live stream
UPGRADE_FOR = 48 * 3600      # keep looking for a finished stream's captions this long
UPGRADE_EVERY = 3600         # at most once an hour per folder


def ai_fix_words(folder: str, name: str) -> dict:
    """The AI's spelling fixes for a reel's captions, as a suggested transcript (not saved until the user does)."""
    from ..core import judge
    meta_file, post = _reel_paths(folder, name)
    words = captions.parse_words((meta_file.parent / post["captions"]).read_text(encoding="utf-8"))
    text = " ".join(w["word"] for w in words)
    fixed = judge.fix_words(text, post.get("language"), load_settings().ai)
    if fixed is None:
        raise InvalidInput("the AI couldn't fix these captions",
                           "Turn on the AI judge in Settings (local model, Claude, or an OpenAI-compatible API "
                           "such as Gemini), then try again.")
    changed = sum(x != y for x, y in zip(text.split(), fixed.split(), strict=False))
    return {"transcript": fixed, "changed": changed}


def youtube_upgrade(folder: str) -> dict:
    """Swap YouTube's captions into this folder's reels (live reels, once the stream has ended and YouTube
    has captioned it). Reels edited by hand, or already on YouTube's captions, are left alone. Each reel's
    place in the stream is fine-tuned by matching its words within ±20 s; the old words go to the
    side-by-side check."""
    import time

    from ..core import sources
    from ..core.pipeline import align
    d = _folder(folder)
    info = json.loads((d / FOLDER_FILE).read_text(encoding="utf-8")) if (d / FOLDER_FILE).exists() else {}
    info["yt_captions_tried"] = time.time()
    (d / FOLDER_FILE).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    yt = sources.youtube_captions(info.get("url") or "", info.get("language"))
    if not yt:
        return {"updated": 0, "status": "YouTube has no captions for this video yet"}
    brand, updated, skipped = load_settings().brand, 0, 0
    for meta_file in sorted(d.glob("reel_*.json")):
        try:
            post = json.loads(meta_file.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if post.get("captions_edited") or post.get("captions_source") == "youtube" or "source_start" not in post:
            skipped += 1
            continue
        current = (d / post["captions"]).read_text(encoding="utf-8")
        mine = captions.parse_words(current)
        length = float(post.get("length") or captions.length_of(current))
        best, best_score = None, 0.0
        for k in range(-40, 41):                           # ±20 s in half-second steps
            t0 = post["source_start"] + k / 2
            cand = [{"start": round(w["start"] - t0, 2), "end": round(w["end"] - t0, 2), "word": w["word"]}
                    for w in yt if t0 <= w["start"] < t0 + length]
            if len(cand) < 3:
                continue
            rows = align(mine, cand) if mine else []
            score = sum(r["ok"] for r in rows) / len(rows) if rows else 0.0
            if score > best_score:
                best, best_score = cand, score
        if not best or best_score < 0.2:
            skipped += 1
            continue
        mode = branding.script_mode(brand, post.get("look"))
        words = language.romanize_words(best) if mode == "roman" else best
        post["caption_check"] = {"source": "youtube", "checker": "makereel's live captions",
                                 "agree": round(best_score * 100),
                                 "other": [{"start": w["start"], "word": w["word"]} for w in mine]}
        post["captions_source"] = "youtube"
        _write_and_render(d, meta_file, post, _rebuild(post, current, words, post.get("hook"), brand, False, length),
                          brand)
        updated += 1
    if updated:
        info["yt_captions_done"] = time.time()
        (d / FOLDER_FILE).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"updated": updated, "skipped": skipped,
            "status": (f"{updated} reel now uses YouTube's captions" if updated == 1
                       else f"{updated} reels now use YouTube's captions")}


def pending_youtube_upgrades() -> list[str]:
    """Folders of live streams (recent, not done, not tried in the last hour) worth checking again."""
    import time
    out, now = [], time.time()
    for meta in root().glob(f"*/{FOLDER_FILE}") if root().is_dir() else []:
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (info.get("live_status") == "is_live" and not info.get("yt_captions_done")
                and now - meta.parent.stat().st_mtime < UPGRADE_FOR
                and now - info.get("yt_captions_tried", 0) > UPGRADE_EVERY
                and "youtube" in (info.get("url") or "")):
            out.append(meta.parent.name)
    return out


ZIP_NAME = "all-reels.zip"


def folder_zip(folder: str) -> dict:
    """Every reel of a folder plus its post text, in one zip, for posting in one go."""
    import zipfile
    d = _folder(folder)
    out = d / ZIP_NAME
    tmp = d / (ZIP_NAME + ".part")
    count = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:       # videos are already compressed
        for meta_file in sorted(d.glob("reel_*.json")):
            try:
                post = json.loads(meta_file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            video = d / post.get("file", "")
            if not video.is_file():
                continue
            z.write(video, video.name)
            z.writestr(f"{meta_file.stem}.txt", (post.get("caption") or "") + "\n")
            count += 1
    tmp.replace(out)
    return {"count": count, "download": _media_url(folder, ZIP_NAME, out) + "&download=1"}


def get_reel(folder: str, name: str) -> dict:
    meta_file, post = _reel_paths(folder, name)
    ass_text = (meta_file.parent / post["captions"]).read_text(encoding="utf-8")
    words = captions.parse_words(ass_text)
    d = meta_file.parent
    sec = _section(d, post)
    src_len = media_duration(d / post["source_clip"]) if sec else None
    return {**_summary(folder, name, post, d / post["file"]),
            "transcript": " ".join(w["word"] for w in words), "words": words, "ass": ass_text,
            "templates": {k: v["label"] for k, v in captions.TEMPLATES.items()},
            "safe_zone": _safe_zone(), "cards": post.get("cards") or [],
            "shots": post.get("shots") if post.get("fit") == "track" else None,
            **_camera_view(folder, d, post),
            "language": _language(d, post), "script": language.script_of(" ".join(w["word"] for w in words)),
            "can_trim": bool(sec), "length": sec[1] if sec else captions.length_of(ass_text),
            "room_before": sec[0] if sec else 0.0,
            "room_after": max(0.0, src_len - sec[0] - sec[1]) if sec else 0.0,
            "compare": _compare(post, words)}


def _compare(post: dict, words: list[dict]) -> dict | None:
    """The side-by-side caption check: caption words lined up with the second model's words."""
    from ..core.pipeline import align
    check = post.get("caption_check") or {}
    other = check.get("other")
    if not other or not words:
        return None
    rows = align(words, other)
    ok = sum(r["ok"] for r in rows)
    names = {"youtube": "YouTube's captions", "local": "makereel's captions"}
    return {"captions_from": names.get(check.get("source"), check.get("source")),
            "checked_by": (check.get("checker") if " " in check.get("checker", "")
                           else f"{check.get('checker', 'local')} model"), "agree": round(100 * ok / len(rows)),
            "rows": rows}


# --------------------------------------------------------------------------- helpers
def media_duration(path: Path) -> float:
    from ..core import media
    return media.duration(path)


def _section(d: Path, post: dict) -> tuple[float, float] | None:
    """(offset, length) of the reel inside its master clip, or None for reels made before masters existed."""
    src = d / post.get("source_clip", "-")
    if not src.is_file():
        return None
    if "src_offset" in post and "length" in post:
        return float(post["src_offset"]), float(post["length"])
    return 0.0, media_duration(src)          # 0.3.0 masters: the reel is the whole file


def _require_section(d: Path, post: dict) -> tuple[float, float]:
    sec = _section(d, post)
    if sec is None:
        raise InvalidInput("this reel was made before editing tools needed its master clip",
                           "Run its link again to get reels you can trim, split, reframe and export.")
    return sec


def _write_and_render(d: Path, meta_file: Path, post: dict, ass_text: str, brand: dict,
                      reraw: bool = False, plan: tuple | None = None) -> None:
    """Save captions + metadata, (re)make the clean 9:16 if needed, burn, and refresh exports."""
    ass_text = captions.set_cards(ass_text, post.get("cards"), post.get("length") or captions.length_of(ass_text))
    (d / post["captions"]).write_text(ass_text, encoding="utf-8")
    if reraw:
        fit = post.get("fit") or "blur"
        section = _section(d, post)
        plan = plan or render.plan_fit(d / post["source_clip"], render.MAIN_FORMAT, fit, section,
                                       post.get("shots") if fit == "track" else None)
        if plan[0] == "track" and getattr(plan[1], "shots", None):
            post["shots"] = plan[1].shots                  # remember the camera moves, for the editor
        render.make_raw(d / post["source_clip"], d / post["raw"], render.MAIN_FORMAT, fit, section, plan)
    render.burn(d / post["raw"], d / post["captions"], d / post["file"],
                branding.overlays_for(brand, d, post.get("logo", True)), branding.fonts_dir())
    meta_file.write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    for fmt, item in list((post.get("exports") or {}).items()):   # keep exports in step with edits
        if (d / item["file"]).exists():
            export_reel(d.name, meta_file.stem, fmt, item.get("fit") or post.get("fit") or "blur")


def _safe_zone() -> dict | None:
    """The app overlay area to keep clear on the 9:16 reel (shares of the frame), for the editor guide."""
    from ..core import safezone
    name = load_settings().brand.get("safe_zone", "all")
    zone = safezone.zone_for(name, *render.FORMATS[render.MAIN_FORMAT])
    return {"name": name, "label": safezone.LABELS[name], **zone.__dict__} if zone else None


def _language(d: Path, post: dict) -> str | None:
    return post.get("language") or folder_language(d) or load_settings().clip.get("language")


def _style(fmt: str, brand: dict, post: dict, words: list[dict], hook: str | None) -> captions.Style:
    script = language.script_of(" ".join(w["word"] for w in words) + " " + (hook or ""))
    return branding.style_for(fmt, brand, post.get("look"), script, post.get("fit"))


def _rebuild(post: dict, current: str, words: list[dict], hook: str | None, brand: dict, restyle: bool,
             length: float | None = None) -> str:
    style = _style(render.MAIN_FORMAT, brand, post, words, hook)
    if not restyle and f"Style: Caption,{style.font}," not in current:
        restyle = True          # the words changed script (e.g. romanised): the font has to follow
    style = style if restyle else None
    return captions.rebuild(current, words, hook, style, branding.template_for(brand, post.get("look")), length)


# --------------------------------------------------------------------------- editing
def update_reel(folder: str, name: str, *, hook: str | None = None, caption: str | None = None,
                transcript: str | None = None, words: list[dict] | None = None, offset: float | None = None,
                ass: str | None = None, logo: bool | None = None, restyle: bool = False,
                look: dict | None = None, fit: str | None = None, cards: list | None = None,
                camera: list | str | None = None) -> dict:
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
    - `look`: caption placement, background and template, e.g. to avoid subtitles already in the video:
      {"vertical": 0.4, "size": 0.9, "box": true, "box_colour": "#000000", "box_opacity": 0.6,
       "template": "pop"}. Keys left out keep their current value.
    - `fit`: how the 9:16 picture is framed: blur, crop, pad, track (follow the speaker)
      or split (two people, or webcam over gameplay).
    - `cards`: text overlays, replacing the current ones: [{"kind": "quote" | "note", "text", "start", "end",
      "position": "top" | "middle" | "bottom"}] or {"kind": "outro", "text", "secs"} (the last seconds).
    - `camera`: follow-the-speaker shots, replacing the found ones: [{"start": seconds, "x": 0..1 centre}],
      plus "wide": true on a shot that shows the whole frame (everyone at once),
      or "auto" to find them again from who is talking.
    """
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    current = (d / post["captions"]).read_text(encoding="utf-8")
    plan = None
    if cards is not None:
        try:
            post["cards"] = captions.clean_cards(cards, post.get("length") or captions.length_of(current))
        except (TypeError, ValueError) as e:
            raise InvalidInput(str(e)) from e
    new_hook = hook.strip() if hook is not None and hook.strip() else post.get("hook")
    brand = load_settings().brand
    reraw = False
    script_words = None
    if look is not None:
        old_mode = branding.script_mode(brand, post.get("look"))
        try:
            post["look"] = {**(post.get("look") or {}), **branding.clean_look(look)}
        except (TypeError, ValueError) as e:
            raise InvalidInput(str(e)) from e
        restyle = True
        mode = branding.script_mode(brand, post["look"])
        if mode != old_mode:
            script_words = _words_in_mode(d, post, captions.parse_words(current), old_mode, mode)
            base_hook = post.get("hook_original") or new_hook or ""
            new_hook = caption_hook(base_hook, script_words, mode) or new_hook
    if fit is not None and fit != post.get("fit"):
        if fit not in render.FITS + ("auto",):
            raise InvalidInput(f"fit must be auto or one of {', '.join(render.FITS)}")
        _require_section(d, post)
        if camera is None:
            post.pop("shots", None)                       # a new layout: find the camera moves afresh
        plan = render.plan_fit(d / post["source_clip"], render.MAIN_FORMAT, fit, _section(d, post),
                               post.get("shots") if fit == "track" else None)
        if fit == "auto":
            fit = plan[0]
        elif plan[0] != fit:
            raise InvalidInput({"split": "no two people or webcam found in this reel",
                                "track": "no steady face found in this reel"}[fit],
                               "The layout was left as it was.")
    if camera is not None:
        if (fit or post.get("fit")) != "track":
            raise InvalidInput("camera shots only apply to the follow-the-speaker layout")
        _require_section(d, post)
        if camera == "auto":
            post.pop("shots", None)
        else:
            shots = framing.clean_shots(camera, post.get("length"))
            if not shots:
                raise InvalidInput("give at least one camera shot: [{start, x}]")
            post["shots"] = shots
        reraw = True
    if fit is not None and fit != post.get("fit"):
        restyle = restyle or "split" in (fit, post.get("fit"))   # split-screen captions sit on the seam
        post["fit"], reraw = fit, True

    if ass is not None and ass.strip() and ass != current:
        text = ass
    else:
        timed = captions.parse_words(current)
        changed = False
        if script_words is not None:
            timed, changed = script_words, True
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
        if changed or restyle:
            text = _rebuild(post, current, timed, new_hook, brand, restyle, post.get("length"))
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
    if text != current:
        post["captions_edited"] = True        # never overwrite hand edits with YouTube's captions later

    _write_and_render(d, meta_file, post, text, brand, reraw, plan)
    return get_reel(folder, name)


def import_captions(folder: str, name: str, text: str) -> dict:
    """Replace the reel's captions with a subtitle file (SRT/VTT, of the reel or the whole video) or a
    plain transcript (fitted to the current timing, like editing the words)."""
    from ..core import subtitles
    if not text or not text.strip():
        raise InvalidInput("the file is empty")
    if len(text) > 5_000_000:
        raise InvalidInput("subtitle files must be under 5 MB")
    meta_file, post = _reel_paths(folder, name)
    cues = subtitles.parse_cues(text)
    if not cues:
        return update_reel(folder, name, transcript=text)
    length = post.get("length") or captions.length_of((meta_file.parent / post["captions"]).read_text("utf-8"))
    words = subtitles.on_reel_clock(subtitles.cues_to_words(cues), float(post.get("start") or 0), length)
    if not words:
        raise InvalidInput("none of the subtitles fall inside this reel",
                           "Use subtitles of this reel, or of the whole video it was cut from.")
    return update_reel(folder, name, words=words)


def _fresh_words(d: Path, post: dict, section: tuple[float, float] | None, mode: str | None = None) -> list[dict]:
    """Precise word timings for the reel (its section of the master), on the reel's clock,
    written the way `mode` asks (own script, English letters, or translated to English)."""
    clip = load_settings().clip
    mode = mode or branding.script_mode(load_settings().brand, post.get("look"))
    lang = _language(d, post)
    model = transcribe.model_for(clip["model"], lang, clip.get("model_other", "small"), mode)
    task = "translate" if mode == "english" and lang not in (None, "en") else "transcribe"
    if section is None:
        words = transcribe.words_in_file(d / post["raw"], model, lang, task)
    else:
        off, length = section
        words = [{**w, "start": round(w["start"] - off, 2), "end": round(w["end"] - off, 2)}
                 for w in transcribe.words_in(d / post["source_clip"], off, off + length, model, lang,
                                              precise=True, task=task)]
    from ..core.pipeline import keep_names
    return keep_names(language.romanize_words(words) if mode == "roman" else words, clip.get("names") or [])


def _words_in_mode(d: Path, post: dict, current: list[dict], old: str, new: str) -> list[dict]:
    """The reel's captions rewritten for a new script mode.

    Own script -> English letters converts the current words (your edits stay). Anything else
    listens to the reel again (a few seconds), because the original words can't be recovered
    from English letters or a translation.
    """
    if new == "roman" and old == "original":
        return language.romanize_words(current)
    fresh = _fresh_words(d, post, _section(d, post), new)
    if not fresh:
        raise InvalidInput("no speech found in this reel, so there's nothing to rewrite")
    return fresh


def autosync(folder: str, name: str) -> dict:
    """Re-time the captions from the reel's own audio, keeping the user's corrected words."""
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    fresh = _fresh_words(d, post, _section(d, post))
    if not fresh:
        raise InvalidInput("no speech found in this reel, so there's nothing to sync to")
    current = captions.parse_words((d / post["captions"]).read_text(encoding="utf-8"))
    text = " ".join(w["word"] for w in current) or " ".join(w["word"] for w in fresh)
    return update_reel(folder, name, words=captions.align(text, fresh))


def trim_reel(folder: str, name: str, start: float = 0.0, end: float = 0.0) -> dict:
    """Move the reel's edges. start/end are seconds to move each edge: negative = earlier.

    e.g. start=-2 adds two seconds before, end=-1.5 cuts the last one and a half seconds.
    Captions you've corrected are kept; newly revealed audio is transcribed.
    """
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    off, length = _require_section(d, post)
    src_len = media_duration(d / post["source_clip"])
    new_off = min(max(0.0, off + start), off + length - 1)
    new_end = min(src_len, max(new_off + 1, off + length + end))
    new_len = round(new_end - new_off, 3)
    if new_len < 3:
        raise InvalidInput("a reel must be at least 3 seconds long")
    shift = new_off - off
    current = (d / post["captions"]).read_text(encoding="utf-8")
    kept = [{**w, "start": round(w["start"] - shift, 2), "end": round(w["end"] - shift, 2)}
            for w in captions.parse_words(current)
            if 0 <= w["start"] - shift < new_len]
    old_from, old_to = -shift, length - shift          # where the old reel sits on the new clock
    fresh = [w for w in _fresh_words(d, post, (new_off, new_len))
             if w["start"] < old_from - 0.05 or w["start"] >= old_to - 0.05]
    words = sorted(kept + fresh, key=lambda w: w["start"])

    post["src_offset"], post["length"] = round(new_off, 3), new_len
    post["cards"] = captions.shift_cards(post.get("cards") or [], -shift, new_len)
    post["shots"] = framing.shift_shots(post.get("shots"), shift, new_len)
    post["start"] = round(post.get("start", 0) + shift, 2)
    post["end"] = round(post["start"] + new_len, 2)
    brand = load_settings().brand
    text = _rebuild(post, current, words, post.get("hook"), brand, False, new_len)
    _write_and_render(d, meta_file, post, text, brand, reraw=True)
    return get_reel(folder, name)


def split_reel(folder: str, name: str, at: float) -> dict:
    """Cut a reel in two at `at` seconds. The second half becomes a new reel in the same folder."""
    from ..core.pipeline import next_reel_name
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    off, length = _require_section(d, post)
    if not 2 <= at <= length - 2:
        raise InvalidInput("split at least 2 seconds from either end")
    current = (d / post["captions"]).read_text(encoding="utf-8")
    words = captions.parse_words(current)
    brand = load_settings().brand

    new = next_reel_name(d)
    second = {**post, "name": new, "file": f"{new}.mp4", "raw": f"{new}.raw.mp4", "captions": f"{new}.ass",
              "source_clip": f"{new}.src.mp4", "exports": {}, "src_offset": round(off + at, 3),
              "length": round(length - at, 3), "start": round(post.get("start", 0) + at, 2),
              "cards": captions.shift_cards(post.get("cards") or [], -at, round(length - at, 3)),
              "shots": framing.shift_shots(post.get("shots"), at, round(length - at, 3))}
    shutil.copyfile(d / post["source_clip"], d / second["source_clip"])   # each reel owns its master
    later = [{**w, "start": round(w["start"] - at, 2), "end": round(w["end"] - at, 2)} for w in words
             if w["start"] >= at]
    (d / f"{new}.json").write_text("{}", encoding="utf-8")                 # reserve the name
    _write_and_render(d, d / f"{new}.json", second,
                      _rebuild(second, current, later, second.get("hook"), brand, False, second["length"]),
                      brand, reraw=True)

    post["length"], post["end"] = round(at, 3), round(post.get("start", 0) + at, 2)
    post["cards"] = [c for c in captions.shift_cards(post.get("cards") or [], 0, at) if c["kind"] != "outro"]
    post["shots"] = framing.shift_shots(post.get("shots"), 0, at)
    earlier = [w for w in words if w["start"] < at]
    _write_and_render(d, meta_file, post, _rebuild(post, current, earlier, post.get("hook"), brand, False, at),
                      brand, reraw=True)
    return list_reels(folder)


SHORT_LENGTHS = (20, 30, 45, 60, 90)


def short_versions(folder: str, name: str, length: float = 45, count: int = 3) -> dict:
    """The best `count` parts of a long reel, each about `length` seconds, as new reels in the folder.

    Picks the loudest, wordiest stretches (the same signals that found the moment), never overlapping,
    and moves each edge into a pause so no short starts or ends mid-sentence. The long reel is kept.
    """
    import numpy as np

    from ..core import highlights, signals
    from ..core.pipeline import next_reel_name
    if length not in SHORT_LENGTHS:
        raise InvalidInput(f"short versions are {', '.join(map(str, SHORT_LENGTHS))} seconds long")
    if not 1 <= count <= 5:
        raise InvalidInput("make between 1 and 5 short versions")
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    off, total = _require_section(d, post)
    if total < length + 10:
        raise InvalidInput(f"this reel is {total:.0f}s; short versions need a reel at least {length + 10:.0f}s long")
    current = (d / post["captions"]).read_text(encoding="utf-8")
    words = captions.parse_words(current)

    loud = signals.loudness(d / post["source_clip"])[int(off): int(off + total) + 1]
    n = max(1, int(total))
    talk = np.zeros(n)                                   # words per second: keeps shorts on the talking bits
    for w in words:
        if 0 <= int(w["start"]) < n:
            talk[int(w["start"])] += 1
    curve, _ = highlights.signal_curve(n, loud, talk, "talk")
    picks = highlights.candidates(curve, k=count, pre=length * 0.6, post=length * 0.4)
    pauses = [(words[i]["end"] + words[i + 1]["start"]) / 2 for i in range(len(words) - 1)
              if words[i + 1]["start"] - words[i]["end"] > 0.35]

    def to_pause(t: float, lo: float, hi: float) -> float:
        near = [p for p in pauses if lo <= p <= hi]
        return min(near, key=lambda p: abs(p - t)) if near else t

    brand, made = load_settings().brand, []
    for c in sorted(picks, key=lambda c: c.start):
        a = max(0.0, c.start)
        a = to_pause(a, a - 3, a + 3)
        b = min(total, max(a + length, c.end))
        b = to_pause(b, b - 4, b + 3)
        if b - a < 5:
            continue
        a, b = round(max(0.0, a), 2), round(min(total, b), 2)
        new = next_reel_name(d)
        part = {**post, "name": new, "file": f"{new}.mp4", "raw": f"{new}.raw.mp4", "captions": f"{new}.ass",
                "source_clip": f"{new}.src.mp4", "exports": {}, "src_offset": round(off + a, 3),
                "length": round(b - a, 3), "start": round(post.get("start", 0) + a, 2),
                "end": round(post.get("start", 0) + b, 2), "short_of": name,
                "cards": [x for x in captions.shift_cards(post.get("cards") or [], -a, round(b - a, 3))
                          if x["kind"] != "outro"],
                "shots": framing.shift_shots(post.get("shots"), a, round(b - a, 3))}
        shutil.copyfile(d / post["source_clip"], d / part["source_clip"])
        inside = [{**w, "start": round(w["start"] - a, 2), "end": round(w["end"] - a, 2)} for w in words
                  if a <= w["start"] < b]
        (d / f"{new}.json").write_text("{}", encoding="utf-8")             # reserve the name
        _write_and_render(d, d / f"{new}.json", part,
                          _rebuild(part, current, inside, part.get("hook"), brand, False, part["length"]),
                          brand, reraw=True)
        made.append(new)
    if not made:
        raise InvalidInput("couldn't find a good stretch for a short version")
    return {**list_reels(folder), "made": made}


def merge_reels(folder: str, names: list[str]) -> dict:
    """Join reels (in the given order) into a new reel. The originals are kept."""
    from ..core import media
    from ..core.pipeline import next_reel_name
    if len(names) < 2:
        raise InvalidInput("pick at least two reels to join")
    parts = []
    for n in names:
        meta_file, post = _reel_paths(folder, n)
        parts.append((meta_file.parent, post, _require_section(meta_file.parent, post)))
    d = parts[0][0]
    first = parts[0][1]
    new = next_reel_name(d)
    src = d / f"{new}.src.mp4"

    # one master from the reels' sections, all scaled to the first one's frame size
    w, h = (int(x) for x in media.run([media.binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                                       "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                       str(d / first["source_clip"])], capture=True).decode().split(",")[:2])
    rate = media.output_fps(d / first["source_clip"])
    cmd = [media.binary("ffmpeg"), "-y", "-v", "error"]
    chains, labels = [], ""
    for i, (pd, post, (off, length)) in enumerate(parts):
        cmd += ["-ss", f"{off:.3f}", "-t", f"{length:.3f}", "-i", str(pd / post["source_clip"])]
        chains.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                      f"setsar=1,fps={rate}[v{i}];[{i}:a]aresample=48000[a{i}]")
        labels += f"[v{i}][a{i}]"
    graph = ";".join(chains) + f";{labels}concat=n={len(parts)}:v=1:a=1[v][a]"
    media.run(cmd + ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", *media.encoder_args("raw"),
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(src)])

    words, cards, shots, t = [], [], [], 0.0
    for i, (pd, post, (_, length)) in enumerate(parts):
        shots += [{**s, "start": s["start"] + t} for s in post.get("shots") or []]
        cards += [c for c in captions.shift_cards(post.get("cards") or [], t, t + length)
                  if c["kind"] != "outro" or i == len(parts) - 1]
        ass_text = (pd / post["captions"]).read_text(encoding="utf-8")
        words += [{**x, "start": round(x["start"] + t, 2), "end": round(x["end"] + t, 2)}
                  for x in captions.parse_words(ass_text)]
        t += length
    merged = {**first, "name": new, "file": f"{new}.mp4", "raw": f"{new}.raw.mp4", "captions": f"{new}.ass",
              "source_clip": src.name, "exports": {}, "src_offset": 0.0, "length": round(t, 3),
              "end": round(first.get("start", 0) + t, 2), "merged_from": names, "cards": cards,
              "shots": framing.clean_shots(shots) if all(p.get("shots") for _, p, _ in parts) else None}
    brand = load_settings().brand
    current = (d / first["captions"]).read_text(encoding="utf-8")
    (d / f"{new}.json").write_text("{}", encoding="utf-8")
    _write_and_render(d, d / f"{new}.json", merged,
                      _rebuild(merged, current, words, first.get("hook"), brand, False, t), brand, reraw=True)
    return get_reel(folder, new)


def export_reel(folder: str, name: str, fmt: str, fit: str | None = None) -> dict:
    """Make this reel in another shape (4x5, 1x1, 16x9 or 9x16 with a different fit)."""
    meta_file, post = _reel_paths(folder, name)
    d = meta_file.parent
    fit = fit or post.get("fit") or "blur"
    if fmt not in render.FORMATS or fit not in render.FITS:
        raise InvalidInput(f"format must be one of {', '.join(render.FORMATS)}; fit one of {', '.join(render.FITS)}")
    section = _require_section(d, post)
    brand = load_settings().brand
    main_ass = (d / post["captions"]).read_text(encoding="utf-8")
    words, hook = captions.parse_words(main_ass), captions.parse_hook(main_ass)
    ass = d / f"{name}.{fmt}.ass"
    text = captions.rebuild(main_ass, words, hook, _style(fmt, brand, post, words, hook),
                            branding.template_for(brand, post.get("look")), section[1])
    ass.write_text(captions.set_cards(text, post.get("cards"), section[1]), encoding="utf-8")
    out = d / f"{name}.{fmt}.mp4"
    overlays = branding.overlays_for(brand, d, post.get("logo", True), fmt)
    render.export(d / post["source_clip"], ass, out, fmt, fit, overlays,
                  branding.fonts_dir(), section, post.get("shots") if fit == "track" else None)
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
