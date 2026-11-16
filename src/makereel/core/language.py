"""Languages and scripts: which script captions are in, writing them in English letters, and fonts.

Caption script modes (brand kit default, overridable per reel):
  original   the words as spoken, in their own script (हिंदी stays हिंदी)
  roman      the same words written in English letters ("kya baat hai"), Hinglish-style
  english    translated to English by the speech model (needs a fresh pass over the reel's audio)

Indian scripts (Devanagari, Gurmukhi, Bengali, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam)
are romanised by our own rules, tuned to how people type Hinglish and Punjabi in chat. Other
scripts use `anyascii` when it is installed.

Fonts: the brand font (Arial Black by default) only covers Latin, so captions in another script
use a Noto font for that script. It is downloaded once (~250 KB) into the brand fonts folder;
offline, a font that ships with the operating system is used instead.
"""
from __future__ import annotations

import logging
import platform
import re
import unicodedata
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

SCRIPT_MODES = ("original", "roman", "english")

# --------------------------------------------------------------------------- scripts
_RANGES = [  # (first, last, script)
    (0x0900, 0x097F, "devanagari"), (0x0980, 0x09FF, "bengali"), (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0A80, 0x0AFF, "gujarati"), (0x0B00, 0x0B7F, "oriya"), (0x0B80, 0x0BFF, "tamil"),
    (0x0C00, 0x0C7F, "telugu"), (0x0C80, 0x0CFF, "kannada"), (0x0D00, 0x0D7F, "malayalam"),
    (0x0D80, 0x0DFF, "sinhala"), (0x0E00, 0x0E7F, "thai"), (0x0590, 0x05FF, "hebrew"),
    (0x0600, 0x06FF, "arabic"), (0x0750, 0x077F, "arabic"), (0xFB50, 0xFEFF, "arabic"),
    (0x3040, 0x30FF, "japanese"), (0x4E00, 0x9FFF, "han"), (0x3400, 0x4DBF, "han"),
    (0xAC00, 0xD7AF, "hangul"), (0x1100, 0x11FF, "hangul"),
    (0x0400, 0x04FF, "cyrillic"), (0x0370, 0x03FF, "greek"),
]
INDIC = ("devanagari", "bengali", "gurmukhi", "gujarati", "oriya", "tamil", "telugu", "kannada", "malayalam")
LATIN_LIKE = ("latin", "cyrillic", "greek")   # covered by common caption fonts


def char_script(ch: str) -> str | None:
    o = ord(ch)
    for lo, hi, name in _RANGES:
        if lo <= o <= hi:
            return name
    return "latin" if ch.isalpha() else None


def script_of(text: str) -> str:
    """The main script of some text ('latin' when there are no letters)."""
    counts: dict[str, int] = {}
    for ch in text:
        s = char_script(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return "latin"
    if "japanese" in counts:                   # kana + kanji: Japanese
        counts["japanese"] += counts.pop("han", 0)
    return max(counts, key=counts.get)


def norm_token(word: str) -> str:
    """Lower-case word without punctuation, keeping vowel signs (\\w would drop Hindi matras)."""
    return "".join(c for c in word.lower() if c == "'" or unicodedata.category(c)[0] in "LMN")


# --------------------------------------------------------------------------- romanisation
# Devanagari table; other Indian scripts are mapped onto it (Unicode lays them out in parallel).
_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "ऩ": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y",
    "र": "r", "ऱ": "r", "ल": "l", "ळ": "l", "ऴ": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s",
    "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "य़": "y",
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y"}
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
           "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e", "ऎ": "e", "ऒ": "o"}
_MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
           "ौ": "au", "ॉ": "o", "ॅ": "e", "ॆ": "e", "ॊ": "o"}
_VIRAMA, _NUKTA_SIGN = "्", "़"
_NASAL = {"ं": "n", "ँ": "n", "ः": "h"}
_GURMUKHI_ADDAK, _GURMUKHI_TIPPI = "ੱ", "ੰ"   # ੱ doubles the next consonant; ੰ is a nasal
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_INDIC_BASE = {"devanagari": 0x0900, "bengali": 0x0980, "gurmukhi": 0x0A00, "gujarati": 0x0A80,
               "oriya": 0x0B00, "tamil": 0x0B80, "telugu": 0x0C00, "kannada": 0x0C80, "malayalam": 0x0D00}


def _to_devanagari(word: str) -> str:
    """Map any Indian script onto Devanagari code points (keeps Gurmukhi's addak and tippi)."""
    out = []
    for ch in word:
        o = ord(ch)
        if ch in (_GURMUKHI_ADDAK, _GURMUKHI_TIPPI):
            out.append(ch)
            continue
        for base in _INDIC_BASE.values():
            if base <= o < base + 0x80:
                ch = chr(0x0900 + o - base)
                break
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def _indic_word(word: str) -> str:
    """One word of an Indian script in English letters, Hinglish style (schwa dropped where people drop it)."""
    s = _to_devanagari(word)
    # syllables: (consonant letters or "", vowel sound or None for the inherent 'a', nasal)
    syl: list[list] = []
    i, double_next = 0, False
    while i < len(s):
        ch = s[i]
        if ch == _GURMUKHI_ADDAK:
            double_next = True
        elif ch in _CONS or (ch + _NUKTA_SIGN) in _CONS:
            c = _CONS.get(ch, "")
            if i + 1 < len(s) and s[i + 1] == _NUKTA_SIGN:
                c = _NUKTA.get(ch, c)
                i += 1
            if double_next:
                c, double_next = c[0] + c, False
            if syl and syl[-1][1] == "":            # previous consonant had a virama: a cluster
                syl[-1][0] += c
                syl[-1][1] = None
            else:
                syl.append([c, None, ""])
        elif ch == _VIRAMA and syl:
            syl[-1][1] = ""                         # no vowel (yet): joins the next consonant
        elif ch in _MATRAS and syl:
            syl[-1][1] = _MATRAS[ch]
        elif ch in _VOWELS:
            syl.append(["", _VOWELS[ch], ""])
        elif ch in _NASAL or ch == _GURMUKHI_TIPPI:
            if syl:
                syl[-1][2] = "n" if ch != "ः" else "h"
        elif ch in _DIGITS:
            syl.append([_DIGITS[ch], "", ""])
        elif ch.isascii():
            syl.append([ch, "", ""])
        i += 1
    if not syl:
        return ""
    # inherent 'a': dropped at the end of a word, and before a syllable with its own vowel
    # (करना -> karna, not karana), but kept in the first syllable and after clusters.
    for k, (c, v, nas) in enumerate(syl):
        if v is not None:
            continue
        last = k == len(syl) - 1
        if last:
            syl[k][1] = "" if (k > 0 and not nas) else "a"
        elif k > 0 and syl[k + 1][1] not in (None, "") and syl[k - 1][1] not in ("",) and len(c) <= 2:
            syl[k][1] = ""
        else:
            syl[k][1] = "a"
    text = ""
    for k, (c, v, nas) in enumerate(syl):
        if nas == "n" and k + 1 < len(syl) and syl[k + 1][0][:1] in ("p", "b", "m"):
            nas = "m"
        text += c + (v or "") + nas
    # endings as people type them: kya (not kyaa), nahi, hu
    text = text.replace("chchh", "cch").replace("chch", "cch")
    text = re.sub(r"aa$", "a", text)
    text = re.sub(r"ee(n?)$", r"i\1", text)
    text = re.sub(r"oo(n?)$", r"u\1", text)
    text = re.sub(r"aai$", "ai", text)
    return text


def romanize(word: str) -> str:
    """A word in English letters (unchanged if it already is)."""
    if all(ord(c) < 0x250 for c in word):
        return word
    sc = script_of(word)
    if sc in INDIC:
        lead = re.match(r"^\W*", word).group(0)                     # type: ignore[union-attr]
        trail = re.search(r"[!?.,।॥]*$", word).group(0)             # type: ignore[union-attr]
        core = word[len(lead): len(word) - len(trail)] if trail else word[len(lead):]
        return lead + _indic_word(core) + trail.replace("।", ".").replace("॥", ".")
    try:
        from anyascii import anyascii
        return anyascii(word).strip() or word
    except ImportError:
        flat = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode()
        return flat or word


def romanize_words(words: list[dict]) -> list[dict]:
    return [{**w, "word": romanize(w["word"])} for w in words]


def romanize_text(text: str) -> str:
    return " ".join(romanize(t) for t in text.split())


# --------------------------------------------------------------------------- fonts
_NOTO = {"devanagari": "Devanagari", "gurmukhi": "Gurmukhi", "bengali": "Bengali", "gujarati": "Gujarati",
         "oriya": "Oriya", "tamil": "Tamil", "telugu": "Telugu", "kannada": "Kannada",
         "malayalam": "Malayalam", "sinhala": "Sinhala", "thai": "Thai", "arabic": "Arabic",
         "hebrew": "Hebrew"}
_NOTO_URL = ("https://github.com/notofonts/notofonts.github.io/raw/main/fonts/"
             "NotoSans{n}/hinted/ttf/NotoSans{n}-Bold.ttf")
# fonts that ship with the operating system (used offline, and for Chinese/Japanese/Korean,
# whose Noto fonts are too big to download on the fly)
_SYSTEM = {
    "Darwin": {"devanagari": "Kohinoor Devanagari", "gurmukhi": "Gurmukhi MN", "bengali": "Kohinoor Bangla",
               "gujarati": "Gujarati Sangam MN", "tamil": "Tamil Sangam MN", "telugu": "Kohinoor Telugu",
               "kannada": "Kannada Sangam MN", "malayalam": "Malayalam Sangam MN", "oriya": "Oriya Sangam MN",
               "thai": "Thonburi", "arabic": "Geeza Pro", "hebrew": "Arial Hebrew", "japanese": "Hiragino Sans",
               "han": "PingFang SC", "hangul": "Apple SD Gothic Neo", "sinhala": "Sinhala Sangam MN"},
    "Windows": {"devanagari": "Nirmala UI", "gurmukhi": "Nirmala UI", "bengali": "Nirmala UI",
                "gujarati": "Nirmala UI", "tamil": "Nirmala UI", "telugu": "Nirmala UI", "kannada": "Nirmala UI",
                "malayalam": "Nirmala UI", "oriya": "Nirmala UI", "sinhala": "Nirmala UI", "thai": "Leelawadee UI",
                "arabic": "Segoe UI", "hebrew": "Segoe UI", "japanese": "Yu Gothic UI", "han": "Microsoft YaHei",
                "hangul": "Malgun Gothic"},
    "Linux": {"japanese": "Noto Sans CJK JP", "han": "Noto Sans CJK SC", "hangul": "Noto Sans CJK KR"},
}


def font_for(script: str, brand_font: str, fonts_dir: Path, download: bool = True) -> str:
    """Font family for captions in `script`: the brand font for Latin, else one that has the letters."""
    if script in LATIN_LIKE:
        return brand_font
    if script in _NOTO:
        family = f"Noto Sans {_NOTO[script]}"
        path = fonts_dir / f"NotoSans{_NOTO[script]}-Bold.ttf"
        if path.is_file():
            return family
        if download:
            try:
                url = _NOTO_URL.format(n=_NOTO[script])
                with urllib.request.urlopen(url, timeout=20) as r:
                    data = r.read()
                if data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.replace(path)
                    log.info("   downloaded caption font %s", family)
                    return family
            except OSError as e:
                log.warning("   could not download %s (%s); using a system font", family, e)
    return _SYSTEM.get(platform.system(), {}).get(script, brand_font)
