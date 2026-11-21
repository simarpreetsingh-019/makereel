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
from . import branding, captions, highlights, judge, language, media, render, signals, sources, transcribe
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
            curve = _add_replays(curve, parts, meta, n)
            curve = _add_action(curve, parts, video, n, clip)
            cands = highlights.candidates(curve, k=clip["max_clips"] * 3, max_len=clip["max_len"])

    clip = resolve_language(video, [(c.start, c.end) for c in cands], {**clip, "_mode": branding.script_mode(brand)})
    meta = {**meta, "language": clip["language"]}
    write_folder_info(out_dir, meta)
    yt = _youtube_words(meta, clip, brand)
    log.info("[2/3] %s %d candidate windows", "reading YouTube's captions for" if yt
             else f"transcribing (whisper {clip['model']})", len(cands))
    for c in cands:
        with stage("transcribe"):
            lo, hi = max(0, c.start - 6), min(total, c.end + 8)
            words = ([w for w in yt if lo <= w["start"] < hi] if yt
                     else transcribe.words_in(video, lo, hi, clip["model"], clip["language"]))
        highlights.rescore(c, words, parts, clip["profile"])
    if ai and judge.enabled(ai):
        with stage("judge"):
            _apply_judge(cands, ai, clip["profile"])
    best = sorted(cands, key=lambda c: c.score, reverse=True)[: clip["max_clips"]]

    log.info("[3/3] rendering %d reels -> %s", len(best), out_dir.name)
    results = []
    for c in best:
        try:
            results.append(_render_one(video, c, meta, out_dir, clip, brand, total, yt))
        except MediaError as e:  # one bad clip shouldn't lose the others
            log.error("   reel at %.0fs failed: %s", c.start, e.message)
    if best and not results:
        raise MediaError("every reel failed to render; see the log above")
    return results


ACTION_WEIGHT = 0.5   # how much fast on-screen action counts (gameplay)
ACTION_MAX_LEN = 2 * 3600


def _add_action(curve: np.ndarray, parts: dict, video: Path, n: int, clip: dict) -> np.ndarray:
    """Add how much the picture changes (kills, crashes, chases) for gameplay videos up to 2 hours."""
    if clip.get("profile") != "gameplay" or n > ACTION_MAX_LEN or not clip.get("picture_signal", True):
        return curve
    try:
        with stage("signals"):
            m = signals.motion(video, n)
    except MediaError:
        return curve
    if not m.any():
        return curve
    parts["action"] = highlights.zscore(highlights._smooth(m, 3))
    return curve + ACTION_WEIGHT * parts["action"]


REPLAY_WEIGHT = 0.8   # how much YouTube's "most replayed" graph counts next to loudness and chat


def _add_replays(curve: np.ndarray, parts: dict, meta: dict, n: int) -> np.ndarray:
    """Add YouTube's "most replayed" graph (finished videos that have one) to the moment curve."""
    if meta.get("live_status") == "is_live":
        return curve
    heat = sources.youtube_heatmap(meta.get("url") or "")
    if not heat:
        return curve
    off, per_sec = float(meta.get("offset") or 0.0), np.zeros(n)
    for h in heat:
        a, b = int(max(0, h["start_time"] - off)), int(min(n, h["end_time"] - off + 1))
        if a < b:
            per_sec[a:b] = np.maximum(per_sec[a:b], float(h.get("value") or 0.0))
    if not per_sec.any():
        return curve
    parts["replays"] = highlights.zscore(per_sec)
    log.info("   using YouTube's most-replayed graph (%d points)", len(heat))
    return curve + REPLAY_WEIGHT * parts["replays"]


def _youtube_words(meta: dict, clip: dict, brand: dict) -> list[dict] | None:
    """YouTube's captions on this file's clock, for finished YouTube videos (not while live, not when
    translating to English: those keep the local model)."""
    if meta.get("live_status") == "is_live" or not clip.get("youtube_captions", True):
        return None
    if branding.script_mode(brand) == "english" and clip.get("language") not in (None, "en"):
        return None
    words = sources.youtube_captions(meta.get("url") or "", clip.get("language"))
    if not words:
        return None
    off = float(meta.get("offset") or 0.0)
    return [{**w, "start": round(w["start"] - off, 2), "end": round(w["end"] - off, 2), "src": "youtube"}
            for w in words if w["start"] >= off]


def _render_one(video: Path, c: highlights.Clip, meta: dict, out_dir: Path, clip: dict, brand: dict,
                total: float, yt: list[dict] | None = None) -> dict:
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
        render.cut_source(video, s0, e0, src, int(clip.get("fps", 30)))
    with stage("sync"):
        check: dict = {}
        words = synced_words(src, section, c.words, c.start, clip, mode, yt, check)
    # the title comes from the precise words (the first, fast pass is rougher, more so outside English)
    hook_original = c.ai.get("title") or make_hook(" ".join(w["word"] for w in words) if mode == "original"
                                                   and words else c.text)
    hook = caption_hook(hook_original, words, mode)
    if not sane_title(hook):       # noise heard as words (gameplay): a clean title from the video instead
        log.info("   title from the speech looked like noise (%r); using the video's title", hook[:40])
        hook = hook_original = title_from_video(meta.get("title") or "")
    script = language.script_of(" ".join(w["word"] for w in words) + " " + hook)
    with stage("framing"):
        plan = render.plan_fit(src, render.MAIN_FORMAT, clip["layout"], section)
    ass.write_text(captions.build_ass(words, 0.0, section[1], hook,
                                      branding.style_for(render.MAIN_FORMAT, brand, None, script, plan[0]),
                                      branding.template_for(brand)), encoding="utf-8")
    with stage("render"):
        render.make_raw(src, raw, render.MAIN_FORMAT, plan[0], section, plan)
        render.burn(raw, ass, out, branding.overlays_for(brand, out_dir), branding.fonts_dir())
    if clip.get("silence"):
        render.trim_silence(out)

    post = {"file": out.name, "raw": raw.name, "source_clip": src.name, "captions": ass.name,
            "folder": out_dir.name, "name": name, "format": render.MAIN_FORMAT, "fit": plan[0],
            "shots": getattr(plan[1], "shots", None) if plan[0] == "track" else None,
            "src_offset": section[0], "length": section[1],
            "logo": True, "exports": {}, "score": round(c.score, 2), "why": c.reasons, "hook": hook,
            "hook_original": hook_original, "language": clip.get("language"),
            "ai": c.ai or None,
            "start": c.start, "end": c.end, "caption_check": check or None,
            "source_start": round(c.start + float(meta.get("offset") or 0.0), 2),   # time in the original video
            **credits(meta, c.start, clip["profile"], hook, brand)}
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
    model = transcribe.model_for(clip["model"], lang, clip.get("model_other", "small"), clip.get("_mode"))
    if model != clip["model"]:
        log.info("   using the '%s' speech model for %s (more accurate than '%s' outside English)",
                 model, lang, clip["model"])
    return {**clip, "language": lang or None, "model": model}


def sane_title(text: str) -> bool:
    """False for titles made of noise: tokens with no real letter (stray marks like "ैॉॉ"), mostly 1-2
    character bits, or under two words."""
    import unicodedata
    toks = [t.strip(".,!?\"'।") for t in text.split()]
    toks = [t for t in toks if t]
    if len(toks) < 2:
        return False
    letterless = sum(not any(unicodedata.category(ch).startswith("L") for ch in t) for t in toks)
    tiny = sum(len(t) <= 2 for t in toks)
    return letterless == 0 and tiny <= len(toks) * 0.5


def title_from_video(title: str) -> str:
    """A short title from the video's own: before any "|", without dates, times or "#tags"."""
    t = title.split("|")[0]
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b|#\S+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—:")
    return (t or "Watch this moment")[:60]


def caption_hook(hook: str, words: list[dict], mode: str) -> str:
    """The on-screen title in the captions' script."""
    if mode == "roman":
        return language.romanize_text(hook)
    if mode == "english" and language.script_of(hook) not in language.LATIN_LIKE:
        return make_hook(" ".join(w["word"] for w in words))
    return hook


def _norm(word: str) -> str:
    from anyascii import anyascii
    return anyascii(word).lower().strip(".,!?\"'।:;-")


SAME_WORD = 0.6   # spelling similarity above which two words count as the same word (hamare / hamaare)


def _sounds(word: str) -> str:
    """Rough sound of a word for comparing spellings across scripts and romanizations."""
    w = _norm(word)
    for a, b in (("aa", "a"), ("ee", "i"), ("oo", "u"), ("ii", "i"), ("w", "v"), ("ph", "f"), ("z", "j"),
                 ("q", "k"), ("y", "i")):
        w = w.replace(a, b)
    return w


def similar(a: str, b: str) -> bool:
    from difflib import SequenceMatcher
    x, y = _sounds(a), _sounds(b)
    return x == y or (bool(x) and bool(y) and SequenceMatcher(None, x, y).ratio() >= SAME_WORD)


def keep_names(words: list[dict], names: list[str]) -> list[dict]:
    """Write names exactly as the user listed them (streamers, places, in-jokes), whatever the model heard:
    a caption word that sounds like a listed name becomes that name (punctuation kept)."""
    names = [n.strip() for n in names or [] if n.strip() and " " not in n.strip()]
    if not names:
        return words
    out = []
    for w in words:
        core = w["word"].strip(".,!?\"'।")
        hit = next((n for n in names if len(core) >= 4 and (core.lower() == n.lower() or similar(core, n))), None)
        out.append({**w, "word": w["word"].replace(core, hit)} if hit else w)
    return out


def align(words: list[dict], other: list[dict], window: float = 0.6) -> list[dict]:
    """Line two transcripts of the same audio up word by word, whatever their script (भाई = bhai).

    One row per caption word: {"word", "alt", "ok"}. ok=False marks words the other model heard differently
    ("alt" is its version; "" when it heard nothing there). With timings on both sides, each word is compared
    with what the other model heard at the same moment (no drift when they split speech differently);
    without timings, by word order.
    """
    if words and other and all("start" in w for w in words) and all("start" in w for w in other):
        rows = []
        for w in words:
            near = [o for o in other if abs(o["start"] - w["start"]) <= window]
            hit = next((o for o in near if similar(w["word"], o["word"])), None)
            best = hit or (min(near, key=lambda o: abs(o["start"] - w["start"])) if near else None)
            rows.append({"word": w["word"], "alt": best["word"] if best else "", "ok": hit is not None})
        return rows
    from difflib import SequenceMatcher
    a, b = [_norm(w["word"]) for w in words], [_norm(w["word"]) for w in other]
    rows = [{"word": w["word"], "alt": "", "ok": False} for w in words]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows[i1 + k].update(alt=other[j1 + k]["word"], ok=True)
        elif tag == "replace":
            for k in range(min(i2 - i1, j2 - j1)):     # pair in order; no word is reused
                rows[i1 + k].update(alt=other[j1 + k]["word"],
                                    ok=similar(words[i1 + k]["word"], other[j1 + k]["word"]))
    return rows


def agreement(a: list[dict], b: list[dict]) -> float:
    """Share of words two transcripts have in common, script-independent (हाँ and haan match)."""
    from anyascii import anyascii

    def norm(ws):
        return {anyascii(w["word"]).lower().strip(".,!?\"'") for w in ws if w["word"].strip()}
    x, y = norm(a), norm(b)
    return len(x & y) / max(1, min(len(x), len(y)))


def synced_words(clip_file: Path, section: tuple[float, float], source_words: list[dict], clip_start: float,
                 clip: dict, mode: str = "original", yt: list[dict] | None = None,
                 report: dict | None = None) -> list[dict]:
    """Caption timings measured on the finished clip itself (auto-sync).

    The first transcription ran on the long source with fast settings; cutting and re-encoding can
    shift things by a few hundred milliseconds. Re-transcribing the short clip precisely gives
    timings on exactly the audio viewers hear. Falls back to the source timings if it finds nothing.
    """
    off, length = section
    translate = mode == "english" and clip.get("language") not in (None, "en")
    if yt:
        # YouTube's captions for this reel (exact: same timeline as the download), double-checked with a
        # quick local pass. If they barely match (wrong track), the local captions are used instead.
        # reel time 0 = video time clip_start, so a word's reel time is its video time - clip_start
        mine = [{**w, "start": round(w["start"] - clip_start, 2), "end": round(w["end"] - clip_start, 2)}
                for w in yt if 0 <= w["start"] - clip_start < length]
        if mine:
            checker = (transcribe.checker_for("youtube", clip.get("language")) if clip.get("caption_check", True)
                       else None) or clip["model"]
            try:
                check = transcribe.words_in(clip_file, off, off + length, checker, clip["language"])
            except MediaError:
                check = []
            check = [{**w, "start": w["start"] - off, "end": w["end"] - off} for w in check]
            score = agreement(mine, check) if check else 1.0
            if len(check) < 8 or score >= 0.15:
                log.info("   captions: YouTube's (%d%% match with the %s model)", round(score * 100), checker)
                if report is not None and check:
                    report.update(source="youtube", checker=checker, agree=round(score * 100),
                                  other=[{"start": round(w["start"], 2), "word": w["word"]} for w in check])
                return keep_names(language.romanize_words(mine) if mode == "roman" else mine, clip.get("names") or [])
            log.info("   YouTube's captions don't match this reel (%d%%); using the local ones", round(score * 100))
    try:
        if not translate and clip.get("mixed_languages", True):
            # language per sentence: Hindi stays Hindi, English stays English, within one reel
            found = transcribe.words_by_sentence(clip_file, off, off + length, clip["model"], clip["language"],
                                                 clip.get("model_other", "small"))
        else:
            found = transcribe.words_in(clip_file, off, off + length, clip["model"], clip["language"],
                                        precise=True, task="translate" if translate else "transcribe")
        precise = [{**w, "start": round(w["start"] - off, 2), "end": round(w["end"] - off, 2)} for w in found]
    except MediaError as e:
        log.warning("   caption sync skipped: %s", e.message)
        precise = []
    words = precise or [{**w, "start": w["start"] - clip_start, "end": w["end"] - clip_start}
                        for w in source_words if w["start"] >= clip_start]
    if precise and report is not None and clip.get("caption_check", True) and not translate:
        _second_opinion(clip_file, section, words, clip, mode, report)
    words = language.romanize_words(words) if mode == "roman" else words
    return keep_names(words, clip.get("names") or [])


def _second_opinion(clip_file: Path, section: tuple[float, float], words: list[dict], clip: dict, mode: str,
                    report: dict) -> None:
    """A different model listens to the same reel; the editor shows where the two disagree (in yellow)."""
    off, length = section
    main = transcribe.model_for(clip["model"], clip.get("language"), clip.get("model_other", "small"), mode)
    checker = transcribe.checker_for(main, clip.get("language"))
    if not checker:
        return
    try:
        other = transcribe.words_in(clip_file, off, off + length, checker, clip.get("language"), precise=True)
    except MediaError:
        return
    other = [{"start": round(w["start"] - off, 2), "word": w["word"]} for w in other]
    score = agreement(words, other) if other else 0.0
    log.info("   caption check: %d%% match with the %s model", round(score * 100), checker)
    report.update(source="local", checker=checker, agree=round(score * 100), other=other)


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
