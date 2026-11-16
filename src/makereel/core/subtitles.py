"""Read subtitle files (SRT, WebVTT) or a plain transcript, and write SRT.

Imported cues become timed words: each cue's time is shared between its words by length, which
is close enough for captions (a cue is a second or two) and much better than guessing.
"""
from __future__ import annotations

import html
import re

_CUE_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


def _secs(h: str | None, m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000


def parse_cues(text: str) -> list[dict]:
    """[{start, end, text}] from SRT or WebVTT. Empty when the text has no timestamps (a plain transcript)."""
    cues, cur = [], None
    for line in text.replace("\r", "").split("\n"):
        m = _CUE_TIME.search(line)
        if m:
            g = m.groups()
            cur = {"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": []}
            cues.append(cur)
        elif not line.strip():
            cur = None
        elif cur is not None:
            cur["text"].append(line)
    out = []
    for c in cues:
        words = html.unescape(_TAGS.sub("", " ".join(c["text"]))).split()
        if words and c["end"] > c["start"]:
            out.append({"start": c["start"], "end": c["end"], "text": " ".join(words)})
    # auto-generated YouTube VTT repeats each line in the next cue: drop words already shown
    return _dedupe_rolling(out)


def _dedupe_rolling(cues: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in cues:
        if out:
            prev = out[-1]["text"].split()
            words = c["text"].split()
            k = min(len(prev), len(words))
            while k and prev[-k:] != words[:k]:
                k -= 1
            if k:
                rest = words[k:]
                if not rest:
                    continue
                c = {**c, "text": " ".join(rest)}
        out.append(c)
    return out


def cues_to_words(cues: list[dict]) -> list[dict]:
    """Share each cue's time between its words, by number of letters (+1 so short words get a moment)."""
    words = []
    for c in cues:
        parts = c["text"].split()
        weights = [len(p) + 1 for p in parts]
        total, t = sum(weights), c["start"]
        span = c["end"] - c["start"]
        for p, wt in zip(parts, weights, strict=True):
            d = span * wt / total
            words.append({"word": p, "start": round(t, 3), "end": round(t + d * 0.95, 3)})
            t += d
    return words


def on_reel_clock(words: list[dict], reel_start: float, length: float) -> list[dict]:
    """Words for this reel. Subtitles of the whole video (times past the reel's length, or that cover its
    place in the video) are moved to the reel's clock; subtitles made for the reel are kept as they are."""
    if not words:
        return []
    if words[-1]["end"] > length + 1:          # longer than the reel: subtitles of the whole video
        return [{**w, "start": round(w["start"] - reel_start, 3), "end": round(w["end"] - reel_start, 3)}
                for w in words if reel_start <= w["start"] < reel_start + length]
    return [w for w in words if 0 <= w["start"] < length]


def _ts(t: float) -> str:
    ms = round(max(0.0, t) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(words: list[dict], per_line: int = 7, max_gap: float = 0.8) -> str:
    """SRT with short lines (a few words each, broken at pauses): ready for YouTube, Premiere, CapCut."""
    lines, cur = [], []
    for w in words:
        if cur and (len(cur) >= per_line or w["start"] - cur[-1]["end"] > max_gap):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return "".join(f"{i}\n{_ts(ln[0]['start'])} --> {_ts(ln[-1]['end'])}\n{' '.join(x['word'] for x in ln)}\n\n"
                   for i, ln in enumerate(lines, 1))
