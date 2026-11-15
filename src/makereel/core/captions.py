"""Build an editable .ass subtitle file for a clip.

Open any `*.ass` next to a reel in a text editor (or Aegisub) to fix words, timing or style,
then re-render from the web app (Reels → Edit) or `makereel rerender <clip>.json`. Nothing is baked into images.

Look & feel lives in the [V4+ Styles] block: change the font, size, colours or position there
once. Colours are &HAABBGGRR (alpha, blue, green, red), e.g. yellow = &H0000DDFF.
"""
from __future__ import annotations

import re

HIGHLIGHT = "&H0000DDFF&"  # active word colour (yellow)

HEADER = """[Script Info]
; Made by makereel. Edit freely, then re-render (web app: Edit -> Save, or: makereel rerender <clip>.json)
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,560,1
Style: Hook,Arial Black,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w: str) -> str:
    w = re.sub(r"[{}\\]", "", w).upper()
    return w.rstrip(",.")  # keep ! and ? — they read well on screen


def build_ass(words: list[dict], start: float, end: float, hook: str | None,
              group: int = 3, hook_secs: float = 3.0) -> str:
    """Words are on the source clock; output times are relative to `start`."""
    lines = [HEADER]
    if hook:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_secs)},Hook,,0,0,0,,{_clean(hook)}\n")
    ws = [w for w in words if start <= w["start"] < end and _clean(w["word"])]
    for g in range(0, len(ws), group):
        chunk = ws[g:g + group]
        for i, w in enumerate(chunk):
            t0 = w["start"] - start
            nxt = chunk[i + 1]["start"] if i + 1 < len(chunk) else w["end"] + 0.25
            t1 = min(nxt, end) - start
            if g + group < len(ws):  # don't overlap the next group
                t1 = min(t1, ws[g + group]["start"] - start)
            text = " ".join(
                f"{{\\c{HIGHLIGHT}\\fscx108\\fscy108}}{_clean(c['word'])}{{\\r}}" if j == i
                else _clean(c["word"]) for j, c in enumerate(chunk))
            lines.append(f"Dialogue: 0,{_ts(t0)},{_ts(t1)},Caption,,0,0,0,,{text}\n")
    return "".join(lines)


def set_hook(ass: str, hook: str) -> str:
    """Replace the on-screen title line's text."""
    return "".join(l.rsplit(",,", 1)[0] + ",," + _clean(hook) + "\n" if ",Hook,," in l else l
                   for l in ass.splitlines(keepends=True))


# --------------------------------------------------------------------------- transcript editing
_TIME = re.compile(r"(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_ACTIVE = re.compile(r"\{\\c&H[0-9A-Fa-f]+&[^}]*\}(.*?)\{\\r\}")


def _secs(ts: str) -> float:
    h, m, s = _TIME.fullmatch(ts.strip()).groups()  # type: ignore[union-attr]
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_words(ass: str) -> list[dict]:
    """Recover the timed words from a caption file (one highlighted word per Caption line).

    Times are relative to the reel's start. This is what the transcript editor shows.
    """
    words = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:") or ",Caption," not in line:
            continue
        fields = line.split(",", 9)
        m = _ACTIVE.search(fields[9]) if len(fields) == 10 else None
        if m:
            words.append({"start": _secs(fields[1]), "end": _secs(fields[2]), "word": m.group(1)})
    return words


def header_of(ass: str) -> str:
    """Everything up to and including the [Events] Format line (keeps the user's style edits)."""
    marker = "Format: Layer"
    i = ass.find(marker, ass.find("[Events]"))
    return ass[: ass.index("\n", i) + 1] if i >= 0 else HEADER


def retime(words: list[dict], text: str) -> list[dict]:
    """Map an edited transcript back onto the original word timings.

    Same number of words -> each keeps its slot (pure spelling fixes). Otherwise the new words
    are spread evenly over the same total span, so added or removed words still stay in sync.
    """
    new = text.split()
    if not new or not words:
        return []
    if len(new) == len(words):
        return [{**w, "word": n} for w, n in zip(words, new, strict=True)]
    start, end = words[0]["start"], words[-1]["end"]
    step = (end - start) / len(new)
    return [{"start": round(start + i * step, 2), "end": round(start + (i + 1) * step, 2), "word": n}
            for i, n in enumerate(new)]


def rebuild(ass: str, text: str, hook: str | None) -> str:
    """New caption file from an edited transcript, keeping styles and the reel's length."""
    words = retime(parse_words(ass), text)
    length = max([w["end"] for w in words] + [_last_end(ass)])
    body = build_ass(words, 0.0, length + 0.5, hook)
    return header_of(ass) + body[len(HEADER):]


def _last_end(ass: str) -> float:
    ends = [_secs(l.split(",", 3)[2]) for l in ass.splitlines() if l.startswith("Dialogue:")]
    return max(ends, default=0.0)
