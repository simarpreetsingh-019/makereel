"""Two-stage moment picking (cheap first, expensive only where it matters).

Stage 1  loudness + chat over the whole video -> candidate windows.     (no transcription)
Stage 2  transcribe only the candidates -> add hype words / speech density -> keep the best.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import language

# Excited words, by language. Matched on whole words (lower-case, punctuation stripped);
# HYPE_PHRASES are matched inside the text (languages without spaces, and multi-word phrases).
HYPE_BY_LANGUAGE = {
    "en": {"oh", "no", "what", "wait", "bro", "dude", "yo", "yes", "lets", "let's", "go", "insane",
           "crazy", "dead", "died", "run", "help", "wow", "holy", "omg", "dang", "damn", "chat",
           "clip", "unbelievable", "impossible", "finally", "gg", "noo", "nooo", "what's", "how"},
    # Hindi / Urdu / Hinglish, in Devanagari and in English letters
    "hi": {"अरे", "अबे", "क्या", "भाई", "यार", "पागल", "बाप", "चलो", "मारो", "भागो", "भाग", "नहीं", "कमाल",
           "मस्त", "वाह", "ओए", "बचाओ", "गया", "गए", "रुको", "देखो", "सच", "भगवान", "ओह",
           "arre", "arey", "abe", "kya", "bhai", "bhau", "yaar", "pagal", "baap", "chalo", "maaro", "maro",
           "bhago", "bhaag", "nahi", "nahin", "kamaal", "kamal", "mast", "waah", "wah", "oye", "bachao",
           "ruko", "dekho", "sach", "bhagwan", "gaya", "gaye", "bhenchod", "op", "jhakaas"},
    # Punjabi, in Gurmukhi and in English letters
    "pa": {"ਓਏ", "ਬੱਲੇ", "ਵਾਹ", "ਕੀ", "ਯਾਰ", "ਵੀਰੇ", "ਭਾਜੀ", "ਚੱਕ", "ਸ਼ਾਬਾਸ਼", "ਬੱਸ", "ਹਾਏ",
           "balle", "oye", "veere", "veer", "paaji", "bhaji", "chak", "shabash", "shabaash", "haye"},
    "es": {"qué", "vamos", "dios", "increíble", "madre", "wey", "güey", "corre", "ayuda", "mira", "brutal",
           "joder", "hostia", "órale", "mierda", "loco", "locura", "imposible", "ostia", "noo"},
    "pt": {"nossa", "caramba", "vai", "mano", "corre", "socorro", "incrível", "caraca", "deus", "mds",
           "porra", "eita", "uau", "doido", "impossível"},
    "fr": {"quoi", "incroyable", "allez", "putain", "waouh", "attends", "oh", "dingue", "mdr"},
    "de": {"krass", "alter", "geil", "lauf", "hilfe", "wahnsinn", "digga", "boah", "nein"},
    "ar": {"والله", "يلا", "ايش", "مستحيل", "الله", "واو"},
    "ru": {"что", "блин", "капец", "давай", "офигеть", "нет", "беги", "жесть"},
    "tr": {"abi", "yok", "hadi", "inanılmaz", "kanka", "lan", "koş"},
    "id": {"anjay", "gila", "wkwk", "astaga", "ayo", "bang", "mantap", "anjir"},
}
HYPE_WORDS = set().union(*HYPE_BY_LANGUAGE.values())
HYPE_PHRASES = ("やばい", "すごい", "まじ", "うそ", "なに", "我的天", "卧槽", "天哪", "牛逼",
                "대박", "미쳤다", "헐", "no way", "let's go", "baap re", "बाप रे", "no manches", "meu deus")


def hype_count(words: list[dict]) -> int:
    """Excited words and exclamation marks in a list of timed words (any language)."""
    toks = [language.norm_token(x["word"]) for x in words]
    text = " ".join(x["word"].lower() for x in words)
    return (sum(t in HYPE_WORDS for t in toks) + sum(x["word"].endswith(("!", "！")) for x in words)
            + sum(text.count(p) for p in HYPE_PHRASES))


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


CALM = 8           # seconds of "back to normal" that end a moment
ACTIVE_Z = 0.3     # the interest curve counts as "still going" above this (robust z-score)
LEAD_MAX = 90      # a moment may reach back this far over its build-up (while it stays active)


def moment(curve: np.ndarray, peak: int, max_len: float, pre: float = 20, post: float = 12) -> tuple[int, int]:
    """The natural extent of the moment around `peak`: grow the end while the curve stays above normal
    (lulls up to CALM s are allowed), grow the start back over the build-up, cap at max_len.
    A quick reaction stays short; a long funny bit grows to minutes."""
    n = len(curve)
    s, e = int(max(0, peak - pre)), int(min(n, peak + post))
    calm, i = 0, e
    while i < n and i - s < max_len:
        calm = 0 if curve[i] > ACTIVE_Z else calm + 1
        if calm > CALM:
            break
        i += 1
    e = max(e, i - calm)                    # end where the activity last was, not after the lull
    j = s
    while j > 0 and peak - j < LEAD_MAX and e - j < max_len and curve[j - 1] > ACTIVE_Z:
        j -= 1
    return j, int(min(e, j + max_len))


def candidates(curve: np.ndarray, k: int, pre: float = 20, post: float = 12,
               max_len: float | None = None) -> list[Clip]:
    """Top-k non-overlapping windows around the curve's peaks; with max_len, each grows to its moment."""
    n, taken, out = len(curve), np.zeros(len(curve), bool), []
    for peak in np.argsort(curve)[::-1]:
        if len(out) >= k:
            break
        s, e = (moment(curve, int(peak), max_len, pre, post) if max_len
                else (int(max(0, peak - pre)), int(min(n, peak + post))))
        if taken[s:e].any():
            continue
        taken[s:e] = True
        out.append(Clip(float(s), float(e), float(peak), float(curve[peak])))
    return out


def rescore(c: Clip, words: list[dict], parts: dict, profile: str) -> Clip:
    """Stage 2: add hype-word and speech-density points from the transcript."""
    w = PROFILES[profile]
    inside = [x for x in words if c.start <= x["start"] < c.end]
    hype = hype_count(inside)
    dur = max(1.0, c.end - c.start)
    c.score += w["words"] * min(3.0, hype / dur * 10) + w["speech"] * min(3.0, len(inside) / dur)
    p = int(c.peak)
    c.reasons = [k for k in ("chat", "loud", "replays", "action")
                 if k in parts and p < len(parts[k]) and parts[k][p] > 1.0]
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
