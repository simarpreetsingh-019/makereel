"""Editable .ass caption files: build, read back, re-time, re-style.

Open any `reel_NN.ass` in a text editor (or Aegisub) to fix words, timing or style, then re-render
from the web app (Reels → Edit) or `makereel rerender`. Nothing is baked into images.

Look & feel lives in the [V4+ Styles] block, generated from a `Style` (export shape + brand kit).
ASS colours are &HAABBGGRR (alpha, blue, green, red); `ass_colour("#FFDD00")` converts from CSS hex.

Timing model: every word has a start and end on the reel's clock. One Caption line is written
per word (that word highlighted inside its group of `group` words), so the timings can be read
back exactly with `parse_words`. That makes the .ass file the single source of truth.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

# --------------------------------------------------------------------------- templates
# How the spoken word is shown inside its group. Every active tag starts with "\c&H..&" so
# parse_words can find the active word; past words (karaoke) use "\1c", which it ignores.
TEMPLATES: dict[str, dict] = {
    # spoken word in the highlight colour, slightly larger
    "classic": {"label": "Classic", "active": r"\c{hl}\fscx108\fscy108", "upper": True, "group": 3},
    # spoken word much bigger, springing in from bigger still
    "pop": {"label": "Pop", "active": r"\c{hl}\fscx150\fscy150\t(0,140,\fscx128\fscy128)",
            "upper": True, "group": 3},
    # dark text on a solid highlight-coloured box behind the spoken word
    "boxed": {"label": "Boxed word", "active": r"\c&H00141414&\3c{hl}\bord{box}\shad0", "upper": True, "group": 3},
    # white word with a soft coloured halo (only the outline is blurred, so the word stays sharp)
    "glow": {"label": "Glow", "active": r"\c&H00FFFFFF&\3c{hl}\bord{glow}\blur{blur}", "upper": True, "group": 3},
    # words fill with colour as they are spoken and stay filled
    "karaoke": {"label": "Karaoke fill", "active": r"\c{hl}\fscx108\fscy108", "past": r"\1c{hl}",
                "upper": True, "group": 4},
    # one big word at a time
    "single": {"label": "One word", "active": r"\c{hl}\fscx160\fscy160", "upper": True, "group": 1},
    # normal case, smaller, just a colour change
    "minimal": {"label": "Minimal", "active": r"\c{hl}", "upper": False, "group": 5, "scale": 0.75},
}
DEFAULT_TEMPLATE = "classic"

# --------------------------------------------------------------------------- style
POSITIONS = {"bottom": 2, "middle": 5, "top": 8}   # ASS numpad alignment (centred)


def ass_colour(hex_colour: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (alpha 0 = opaque)."""
    h = hex_colour.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        raise ValueError(f"not a colour: {hex_colour!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


@dataclass(frozen=True)
class Style:
    width: int = 1080
    height: int = 1920
    font: str = "Arial Black"
    text_colour: str = "#FFFFFF"
    highlight_colour: str = "#FFDD00"
    outline_colour: str = "#000000"
    position: str = "bottom"       # bottom | middle | top (captions); the title sits at the top
    size: float = 1.0              # scale on the default caption size
    vertical: float | None = None  # exact height: bottom of the captions at this share of the height
    box: bool = False              # background box behind the captions
    box_colour: str = "#000000"
    box_opacity: float = 0.6       # 0 = invisible, 1 = solid

    def header(self) -> str:
        short = min(self.width, self.height)          # scale text by the short side
        cap = round(short * 0.080 * self.size)        # 86 px on a 1080-wide reel
        hook = round(short * 0.057 * min(self.size, 1.2))
        if self.vertical is not None:                 # exact placement (e.g. above burned-in subtitles)
            align, margin_v = 2, round(self.height * self.vertical)
        else:
            align = POSITIONS[self.position]
            margin_v = {"bottom": round(self.height * 0.29), "middle": 0, "top": round(self.height * 0.22)}[
                self.position] if self.height > self.width else round(self.height * 0.08)
        hook_margin = round(self.height * 0.115) if self.height > self.width else round(self.height * 0.06)
        side = round(self.width * 0.055)
        text, outline = ass_colour(self.text_colour), ass_colour(self.outline_colour)
        if self.box:   # BorderStyle 4 (libass): translucent box in BackColour, outline kept; Shadow = padding
            border, back, shadow = 4, ass_colour(self.box_colour, round((1 - self.box_opacity) * 255)), round(cap * 0.2)
        else:
            border, back, shadow = 1, "&H80000000", 2
        return (
            "[Script Info]\n"
            "; Made by makereel. Edit freely, then re-render (web app: Edit -> Save)\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.width}\nPlayResY: {self.height}\n"
            "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Caption,{self.font},{cap},{text},{text},{outline},{back},-1,0,0,0,100,100,0,0,{border},"
            f"{max(2, round(cap * 0.08))},{shadow},{align},{side},{side},{margin_v},1\n"
            f"Style: Hook,{self.font},{hook},&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,"
            f"3,{round(hook * 0.29)},0,8,{side + 20},{side + 20},{hook_margin},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    @property
    def highlight(self) -> str:
        return ass_colour(self.highlight_colour) + "&"


DEFAULT_STYLE = Style()


# --------------------------------------------------------------------------- building
def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w: str, upper: bool = True) -> str:
    w = re.sub(r"[{}\\]", "", w)
    w = w.upper() if upper else w
    return w.rstrip(",.")  # keep ! and ? — they read well on screen


def build_ass(words: list[dict], start: float, end: float, hook: str | None,
              style: Style = DEFAULT_STYLE, template: str = DEFAULT_TEMPLATE, hook_secs: float = 3.0) -> str:
    """Words are on any clock; only those in [start, end) are used, re-based to start at 0."""
    tpl = TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE])
    group, upper = tpl["group"], tpl["upper"]
    font_px = min(style.width, style.height) * 0.080 * style.size
    active = (tpl["active"].replace("{hl}", style.highlight)
              .replace("{box}", str(max(6, round(font_px * 0.16))))
              .replace("{glow}", str(max(4, round(font_px * 0.12))))
              .replace("{blur}", str(max(3, round(font_px * 0.10)))))
    if tpl.get("scale"):   # smaller base text for this template
        style = replace(style, size=style.size * tpl["scale"])
    past = tpl.get("past", "").replace("{hl}", style.highlight)
    lines = [style.header()]
    if hook:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_secs)},Hook,,0,0,0,,{_clean(hook)}\n")
    ws = [w for w in words if start <= w["start"] < end and _clean(w["word"], upper)]
    for g in range(0, len(ws), group):
        chunk = ws[g:g + group]
        for i, w in enumerate(chunk):
            t0 = w["start"] - start
            nxt = chunk[i + 1]["start"] if i + 1 < len(chunk) else max(w["end"], w["start"] + 0.1) + 0.25
            t1 = min(nxt, end) - start
            if g + group < len(ws):  # don't overlap the next group
                t1 = min(t1, ws[g + group]["start"] - start)
            if t1 - t0 < 0.05:
                t1 = t0 + 0.05
            parts = []
            for j, c in enumerate(chunk):
                word = _clean(c["word"], upper)
                if j == i:
                    parts.append(f"{{{active}}}{word}{{\\r}}")
                elif j < i and past:
                    parts.append(f"{{{past}}}{word}{{\\r}}")
                else:
                    parts.append(word)
            text = " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(t0)},{_ts(t1)},Caption,,0,0,0,,{text}\n")
    return "".join(lines)


def set_hook(ass: str, hook: str) -> str:
    """Replace the on-screen title line's text."""
    return "".join(l.rsplit(",,", 1)[0] + ",," + _clean(hook) + "\n" if ",Hook,," in l else l
                   for l in ass.splitlines(keepends=True))


# --------------------------------------------------------------------------- reading back
_TIME = re.compile(r"(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_ACTIVE = re.compile(r"\{\\c&H[0-9A-Fa-f]+&[^}]*\}(.*?)\{\\r\}")


def _secs(ts: str) -> float:
    h, m, s = _TIME.fullmatch(ts.strip()).groups()  # type: ignore[union-attr]
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_words(ass: str) -> list[dict]:
    """The timed words of a caption file, on the reel's clock (one highlighted word per Caption line)."""
    words = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:") or ",Caption," not in line:
            continue
        fields = line.split(",", 9)
        m = _ACTIVE.search(fields[9]) if len(fields) == 10 else None
        if m:
            words.append({"start": _secs(fields[1]), "end": _secs(fields[2]), "word": m.group(1)})
    return words


def parse_hook(ass: str) -> str | None:
    for line in ass.splitlines():
        if line.startswith("Dialogue:") and ",Hook,," in line:
            return line.rsplit(",,", 1)[1]
    return None


def header_of(ass: str) -> str:
    """Everything up to and including the [Events] Format line (keeps the user's style edits)."""
    i = ass.find("Format: Layer", ass.find("[Events]"))
    return ass[: ass.index("\n", i) + 1] if i >= 0 else DEFAULT_STYLE.header()


def length_of(ass: str) -> float:
    ends = [_secs(l.split(",", 3)[2]) for l in ass.splitlines() if l.startswith("Dialogue:")]
    return max(ends, default=0.0)


# --------------------------------------------------------------------------- timing
def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


def align(text: str, timed: list[dict]) -> list[dict]:
    """Give each word of `text` a time, taken from the best-matching word in `timed`.

    Words that match (same spelling, ignoring case and punctuation) keep that word's timing;
    changed, added or missing words are fitted between their matched neighbours. This keeps
    captions in sync when the user rewrites part of the text, and is how auto-sync maps the
    user's corrected words onto a fresh transcription.
    """
    new = text.split()
    if not new:
        return []
    if not timed:
        return []
    out: list[dict | None] = [None] * len(new)
    sm = difflib.SequenceMatcher(a=[_norm(w) for w in new], b=[_norm(w["word"]) for w in timed],
                                 autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and a1 - a0 == b1 - b0):
            for k in range(a1 - a0):   # 1:1 (exact, or a same-length correction)
                t = timed[b0 + k]
                out[a0 + k] = {"start": t["start"], "end": t["end"], "word": new[a0 + k]}
        elif tag == "replace" and b1 > b0:   # different counts: spread over the replaced span
            s, e = timed[b0]["start"], timed[b1 - 1]["end"]
            step = (e - s) / (a1 - a0)
            for k in range(a1 - a0):
                out[a0 + k] = {"start": round(s + k * step, 2), "end": round(s + (k + 1) * step, 2),
                               "word": new[a0 + k]}
    # inserted words (no counterpart): fit them into the gap between their neighbours
    i = 0
    while i < len(out):
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j] is None:
            j += 1
        lo = out[i - 1]["end"] if i > 0 else (timed[0]["start"])            # type: ignore[index]
        hi = out[j]["start"] if j < len(out) else max(lo + 0.3 * (j - i), timed[-1]["end"])  # type: ignore[index]
        first = i
        if hi - lo < 0.15 * (j - i) and i > 0:
            # no gap to fit into: share the previous word's slot with the inserted words
            first, lo = i - 1, out[i - 1]["start"]                         # type: ignore[index]
        if hi <= lo:
            hi = lo + 0.25 * (j - first)
        step = (hi - lo) / (j - first)
        for k in range(first, j):
            out[k] = {"start": round(lo + (k - first) * step, 2), "end": round(lo + (k - first + 1) * step, 2),
                      "word": new[k]}
        i = j
    return _monotonic(out)  # type: ignore[arg-type]


def _monotonic(words: list[dict]) -> list[dict]:
    """Starts never go backwards; ends are never before starts."""
    last = 0.0
    for w in words:
        w["start"] = round(max(w["start"], last), 2)
        w["end"] = round(max(w["end"], w["start"] + 0.05), 2)
        last = w["start"]
    return words


def shift(words: list[dict], seconds: float) -> list[dict]:
    """Move every caption earlier (negative) or later (positive)."""
    return _monotonic([{**w, "start": max(0.0, w["start"] + seconds), "end": max(0.05, w["end"] + seconds)}
                       for w in words])


def clean_timings(words: list[dict]) -> list[dict]:
    """Validate words coming from the timing editor."""
    out = []
    for w in words:
        try:
            out.append({"start": float(w["start"]), "end": float(w["end"]), "word": str(w["word"]).strip()})
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("each word needs start, end and word") from e
    return _monotonic(sorted([w for w in out if w["word"]], key=lambda w: w["start"]))


def rebuild(ass: str, words: list[dict], hook: str | None, style: Style | None = None,
            template: str = DEFAULT_TEMPLATE, length: float | None = None) -> str:
    """New caption file from timed words. Keeps the existing styles unless a new `style` is given."""
    length = length if length is not None else max([w["end"] for w in words] + [length_of(ass)])
    body = build_ass(words, 0.0, length + 0.5, hook, style or DEFAULT_STYLE, template)
    head = style.header() if style else header_of(ass)
    return head + body[body.index("Format: Layer"):].split("\n", 1)[1]
