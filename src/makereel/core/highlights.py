"""Two-stage moment picking (cheap first, expensive only where it matters).

Stage 1  loudness + chat over the whole video -> candidate windows.     (no transcription)
Stage 2  transcribe only the candidates -> add hype words / speech density -> keep the best.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

HYPE_WORDS = {
    "oh", "no", "what", "wait", "bro", "dude", "yo", "yes", "lets", "let's", "go", "insane",
    "crazy", "dead", "died", "run", "help", "wow", "holy", "omg", "dang", "damn", "chat",
    "clip", "unbelievable", "impossible", "finally", "gg", "noo", "nooo", "what's", "how",
}

PROFILES = {  # weights: loudness, chat, hype words, speech density
    "gameplay": dict(loud=1.0, chat=1.4, words=0.7, speech=0.2),
    "talk":     dict(loud=0.4, chat=0.8, words=0.6, speech=0.8),
}


@dataclass
class Clip:
    """A candidate moment, in seconds on the source file's clock."""
    start: float
    end: float
    peak: float
    score: float
    text: str = ""
    reasons: list = field(default_factory=list)
    words: list = field(default_factory=list, repr=False)
    ai: dict = field(default_factory=dict)      # AI judge scores, title and reason (if enabled)


def zscore(x):
    """Robust z-score (median-centred); flat input -> zeros."""
    return np.zeros_like(x) if x.std() < 1e-6 else (x - np.median(x)) / (x.std() + 1e-6)


def _smooth(x, k):
    """Moving average of width k."""
    return np.convolve(x, np.ones(k) / k, mode="same") if len(x) >= k else x


def signal_curve(n: int, loud: np.ndarray, chat: np.ndarray, profile: str):
    """Combined per-second interest curve plus its normalised parts (for explaining picks)."""
    w = PROFILES[profile]
    parts = {"loud": zscore(_smooth(np.resize(loud, n), 3)),
             "chat": np.roll(zscore(_smooth(np.resize(chat, n), 8)), -6)}  # chat reacts ~6 s late
    return _smooth(w["loud"] * parts["loud"] + w["chat"] * parts["chat"], 5), parts


def candidates(curve: np.ndarray, k: int, pre: float = 20, post: float = 12) -> list[Clip]:
    """Top-k non-overlapping windows around the curve's peaks."""
    n, taken, out = len(curve), np.zeros(len(curve), bool), []
    for peak in np.argsort(curve)[::-1]:
        if len(out) >= k:
            break
        s, e = int(max(0, peak - pre)), int(min(n, peak + post))
        if taken[s:e].any():
            continue
        taken[s:e] = True
        out.append(Clip(float(s), float(e), float(peak), float(curve[peak])))
    return out


def rescore(c: Clip, words: list[dict], parts: dict, profile: str) -> Clip:
    """Stage 2: add hype-word and speech-density points from the transcript."""
    w = PROFILES[profile]
    inside = [x for x in words if c.start <= x["start"] < c.end]
    toks = [re.sub(r"[^\w']", "", x["word"].lower()) for x in inside]
    hype = sum(t in HYPE_WORDS for t in toks) + sum(x["word"].endswith("!") for x in inside)
    dur = max(1.0, c.end - c.start)
    c.score += w["words"] * min(3.0, hype / dur * 10) + w["speech"] * min(3.0, len(inside) / dur)
    p = int(c.peak)
    c.reasons = [k for k in ("chat", "loud") if p < len(parts[k]) and parts[k][p] > 1.0]
    if hype >= 3:
        c.reasons.append("words")
    c.words = words
    return c


def snap(c: Clip, min_len: float, max_len: float, total: float) -> Clip:
    """Move edges into pauses so we never start or end mid-sentence."""
    ws = c.words
    pauses = [(ws[i]["end"] + ws[i + 1]["start"]) / 2 for i in range(len(ws) - 1)
              if ws[i + 1]["start"] - ws[i]["end"] > 0.5]
    s, e = c.start, c.end
    near_s = [p for p in pauses if s - 6 <= p <= s + 3]
    near_e = [p for p in pauses if e - 3 <= p <= e + 8]
    if near_s:
        s = min(near_s, key=lambda p: abs(p - s))
    if near_e:
        e = min(near_e, key=lambda p: abs(p - e))
    if e - s < min_len:
        e = s + min_len
    e = min(e, s + max_len, total)
    c.start, c.end = round(max(0.0, s), 2), round(e, 2)
    c.text = " ".join(x["word"] for x in ws if c.start <= x["start"] < c.end)
    return c
