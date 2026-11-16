"""Video file -> best moments -> rendered reels + ready-to-post metadata.

Moments are picked in two stages (cheap first, expensive only where it matters):
1. loudness + chat over the whole file -> 3x as many candidate windows as reels wanted
2. transcribe only those windows -> re-rank by hype words and speech -> keep the best
Each kept moment is snapped to pauses and a scene cut, then rendered (see render.py).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import MediaError
from . import branding, captions, highlights, judge, language, media, render, signals, transcribe
from .metrics import stage

log = logging.getLogger(__name__)

BASE_TAGS = {
    "gameplay": ["#gta6", "#gaming", "#gamingclips", "#streamer", "#fyp"],
    "talk": ["#podcast", "#clips", "#viral", "#fyp"],
}
FOLDER_FILE = "folder.json"   # describes the source video of a folder
MARGIN = 6.0                  # seconds kept either side of each reel in its master clip (for trimming)


def process(video: Path, meta: dict, out_dir: Path, clip: dict[str, Any], brand: dict[str, Any],
            chat: Path | None = None, chat_counts: np.ndarray | None = None,
            ai: dict[str, Any] | None = None) -> list[dict]:
    """Make up to clip['max_clips'] reels from `video` into `out_dir`. Returns their metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    known = folder_language(out_dir)          # a live stream's earlier chunks already detected it
    if known and not clip.get("language"):
        clip = {**clip, "language": known}
    write_folder_info(out_dir, meta)
    with stage("probe"):
        total = media.duration(video)
    if total < 3:
        raise MediaError(f"{video.name} is empty or unreadable")
    n = max(1, int(total))

    if total <= clip["max_len"] * 1.5:
        # A Short or short video: one reel, trimmed to max_len around the loudest bit.
        with stage("signals"):
            loud = signals.loudness(video)
        peak = int(np.argmax(loud)) if len(loud) else 0
        start = 0.0 if total <= clip["max_len"] else max(0.0, min(peak - clip["max_len"] * 0.6,
                                                                  total - clip["max_len"]))
        cands = [highlights.Clip(start, min(total, start + clip["max_len"]), float(peak), 1.0)]
        parts = {"loud": highlights.zscore(loud), "chat": np.zeros(n)}
        log.info("[1/3] short video (%.0fs): making one reel", total)
    else:
        log.info("[1/3] scanning %.0f min for loudness and chat spikes", total / 60)
        with stage("signals"):
            loud = signals.loudness(video)
            counts = (chat_counts if chat_counts is not None
                      else signals.chat_activity(chat, n, meta.get("offset", 0.0)))
            curve, parts = highlights.signal_curve(n, loud, counts, clip["profile"])
            cands = highlights.candidates(curve, k=clip["max_clips"] * 3)

    clip = resolve_language(video, [(c.start, c.end) for c in cands], clip)
    meta = {**meta, "language": clip["language"]}
    write_folder_info(out_dir, meta)
    log.info("[2/3] transcribing %d candidate windows (whisper %s)", len(cands), clip["model"])
    for c in cands:
        with stage("transcribe"):
            words = transcribe.words_in(video, max(0, c.start - 6), min(total, c.end + 8),
                                        clip["model"], clip["language"])
        highlights.rescore(c, words, parts, clip["profile"])
    if ai and judge.enabled(ai):
        with stage("judge"):
            _apply_judge(cands, ai, clip["profile"])
    best = sorted(cands, key=lambda c: c.score, reverse=True)[: clip["max_clips"]]

    log.info("[3/3] rendering %d reels -> %s", len(best), out_dir.name)
    results = []
    for c in best:
        try:
            results.append(_render_one(video, c, meta, out_dir, clip, brand, total))
        except MediaError as e:  # one bad clip shouldn't lose the others
            log.error("   reel at %.0fs failed: %s", c.start, e.message)
    if best and not results:
        raise MediaError("every reel failed to render; see the log above")
    return results


def _render_one(video: Path, c: highlights.Clip, meta: dict, out_dir: Path, clip: dict, brand: dict,
                total: float) -> dict:
    highlights.snap(c, clip["min_len"], clip["max_len"], total)
    with stage("scenes"):
        cuts = signals.scene_cuts(video, c.start, c.start + 3)
    if cuts:
        c.start = round(cuts[0], 2)
    mode = branding.script_mode(brand)
    name = next_reel_name(out_dir)
    src, raw, ass, out = (out_dir / f"{name}{ext}" for ext in (".src.mp4", ".raw.mp4", ".ass", ".mp4"))

    s0, e0 = max(0.0, c.start - MARGIN), min(total, c.end + MARGIN)
    section = (round(c.start - s0, 3), round(c.end - c.start, 3))     # the reel inside its master
    with stage("render"):
        render.cut_source(video, s0, e0, src)
    with stage("sync"):
        words = synced_words(src, section, c.words, c.start, clip, mode)
    # the title comes from the precise words (the first, fast pass is rougher, more so outside English)
    hook_original = c.ai.get("title") or make_hook(" ".join(w["word"] for w in words) if mode == "original"
                                                   and words else c.text)
    hook = caption_hook(hook_original, words, mode)
    script = language.script_of(" ".join(w["word"] for w in words) + " " + hook)
    ass.write_text(captions.build_ass(words, 0.0, section[1], hook,
                                      branding.style_for(render.MAIN_FORMAT, brand, None, script),
                                      branding.template_for(brand)), encoding="utf-8")
    with stage("render"):
        render.make_raw(src, raw, render.MAIN_FORMAT, clip["layout"], section)
        render.burn(raw, ass, out, branding.logo_for(brand), branding.fonts_dir())
    if clip.get("silence"):
        render.trim_silence(out)

    post = {"file": out.name, "raw": raw.name, "source_clip": src.name, "captions": ass.name,
            "folder": out_dir.name, "name": name, "format": render.MAIN_FORMAT, "fit": clip["layout"],
            "src_offset": section[0], "length": section[1],
            "logo": True, "exports": {}, "score": round(c.score, 2), "why": c.reasons, "hook": hook,
            "hook_original": hook_original, "language": clip.get("language"),
            "ai": c.ai or None,
            "start": c.start, "end": c.end, **credits(meta, c.start, clip["profile"], hook, brand)}
    (out_dir / f"{name}.json").write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("   %s  %.1f-%.1fs  score %.2f  %s", name, c.start, c.end, c.score, c.reasons)
    return post


def resolve_language(video: Path, windows: list[tuple[float, float]], clip: dict) -> dict:
    """Detect the video's language once (unless set) and pick a model that handles it well."""
    lang = clip.get("language")
    if not lang:
        try:
            with stage("transcribe"):
                lang, prob = transcribe.detect_language(video, windows, clip["model"])
            if lang:
                log.info("   language: %s (%.0f%% sure)", lang, prob * 100)
        except MediaError as e:
            log.warning("   language detection skipped: %s", e.message)
    model = transcribe.model_for(clip["model"], lang, clip.get("model_other", "small"))
    if model != clip["model"]:
        log.info("   using the '%s' speech model for %s (more accurate than '%s' outside English)",
                 model, lang, clip["model"])
    return {**clip, "language": lang or None, "model": model}


def caption_hook(hook: str, words: list[dict], mode: str) -> str:
    """The on-screen title in the captions' script."""
    if mode == "roman":
        return language.romanize_text(hook)
    if mode == "english" and language.script_of(hook) not in language.LATIN_LIKE:
        return make_hook(" ".join(w["word"] for w in words))
    return hook


def synced_words(clip_file: Path, section: tuple[float, float], source_words: list[dict], clip_start: float,
                 clip: dict, mode: str = "original") -> list[dict]:
    """Caption timings measured on the finished clip itself (auto-sync).

    The first transcription ran on the long source with fast settings; cutting and re-encoding can
    shift things by a few hundred milliseconds. Re-transcribing the short clip precisely gives
    timings on exactly the audio viewers hear. Falls back to the source timings if it finds nothing.
    """
    off, length = section
    translate = mode == "english" and clip.get("language") not in (None, "en")
    try:
        precise = [{**w, "start": round(w["start"] - off, 2), "end": round(w["end"] - off, 2)}
                   for w in transcribe.words_in(clip_file, off, off + length, clip["model"], clip["language"],
                                                precise=True, task="translate" if translate else "transcribe")]
    except MediaError as e:
        log.warning("   caption sync skipped: %s", e.message)
        precise = []
    words = precise or [{**w, "start": w["start"] - clip_start, "end": w["end"] - clip_start}
                        for w in source_words if w["start"] >= clip_start]
    return language.romanize_words(words) if mode == "roman" else words


def _apply_judge(cands: list[highlights.Clip], ai: dict, profile: str) -> None:
    """Blend the AI judge's 0-10 scores into the signal scores (weight from settings)."""
    items = [{"id": i, "length": c.end - c.start, "why": c.reasons,
              "text": " ".join(w["word"] for w in c.words if c.start <= w["start"] < c.end)}
             for i, c in enumerate(cands)]
    scores = judge.judge(items, ai, profile)
    if not scores:
        return
    ai_norm = [sum(scores[i][k] for k in judge.CRITERIA) / 40 if i in scores else None for i in range(len(cands))]
    for c, s, i in zip(cands, judge.blend([c.score for c in cands], ai_norm, ai.get("weight", 0.5)),
                       range(len(cands)), strict=True):
        c.score = round(s * 10, 2)
        if i in scores:
            c.ai = scores[i]
            c.reasons.append("ai")


def next_reel_name(out_dir: Path) -> str:
    """reel_01, reel_02, ... (keeps counting across live-stream spikes in the same folder)."""
    taken = [int(m.group(1)) for p in out_dir.glob("reel_*.json") if (m := re.match(r"reel_(\d+)", p.stem))]
    return f"reel_{max(taken, default=0) + 1:02d}"


def folder_language(out_dir: Path) -> str | None:
    try:
        return json.loads((out_dir / FOLDER_FILE).read_text(encoding="utf-8")).get("language")
    except (OSError, ValueError):
        return None


def write_folder_info(out_dir: Path, meta: dict) -> None:
    keys = ("id", "title", "channel", "channel_url", "url", "live_status", "duration", "language")
    info = {k: meta.get(k) for k in keys}
    (out_dir / FOLDER_FILE).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")


CREDIT_FOOTER = "✂️ Made with makereel"


def credits(meta: dict, start: float, profile: str, hook: str, brand: dict | None = None) -> dict:
    """Credit block for every post: creator, link to the exact moment, tags."""
    t = int(start + meta.get("offset", 0.0))
    url = meta.get("url", "")
    moment = f"{url}{'&' if '?' in url else '?'}t={t}s" if "youtube.com/watch" in url else url
    creator = meta.get("channel") or ""
    creator_tag = "#" + re.sub(r"\W", "", creator).lower() if creator else ""
    video_tags = ["#" + re.sub(r"\W", "", x).lower() for x in meta.get("tags", [])[:3]]
    tags = [x for x in [creator_tag, *video_tags, *BASE_TAGS[profile]] if len(x) > 1]
    lines = [f"{hook} 😳", ""]
    if creator:
        lines.append(f"🎥 Credit: {creator} ({meta.get('channel_url') or url})")
    lines += [f"📺 Original: \"{meta.get('title', '')}\"", f"⏱ Moment: {moment}",
              "All rights belong to the original creator.", "", " ".join(dict.fromkeys(tags))]
    if brand is None or brand.get("credit_footer", True):
        lines += ["", CREDIT_FOOTER]
    return {"source": moment, "source_time": t, "creator": creator,
            "creator_url": meta.get("channel_url"), "caption": "\n".join(lines)}


def make_hook(text: str, max_words: int = 7) -> str:
    """Pick the punchiest sentence of the transcript as the on-screen title."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?।？！。])\s*", text) if len(s.split()) >= 2]

    def punch(s: str) -> int:
        return s.count("!") * 2 + ("?" in s) + highlights.hype_count([{"word": t} for t in s.split()])

    best = max(sentences, key=punch, default=text)
    words = best.split()[:max_words]
    return " ".join(words).rstrip(",.") if words else "WAIT FOR IT"
