"""Creator memory: per streamer, the names and in-jokes their reels' captions should get right.

Stored on this computer (data/creators/<channel>.json). Names are written exactly as listed in that
creator's captions; notes give the AI word-fixer context. "Suggest" offers words that keep coming up
across the creator's reels.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..config import env
from ..core import captions
from . import library

FOLDER_FILE = "folder.json"


def _file(channel: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", channel.strip())[:80] or "unknown"
    return env().data_dir / "creators" / f"{safe}.json"


def load(channel: str | None) -> dict:
    if not channel:
        return {"channel": "", "names": [], "notes": ""}
    try:
        data = json.loads(_file(channel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"channel": channel, "names": data.get("names") or [], "notes": data.get("notes") or ""}


def save(channel: str, names: list[str], notes: str) -> dict:
    path = _file(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [n.strip()[:40] for n in names if n.strip()][:200]
    path.write_text(json.dumps({"names": clean, "notes": notes.strip()[:2000]}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return load(channel)


def channels() -> list[str]:
    """Creators that have reels in the library."""
    out = set()
    root = library.root()
    for meta in root.glob(f"*/{FOLDER_FILE}") if root.is_dir() else []:
        try:
            ch = json.loads(meta.read_text(encoding="utf-8")).get("channel")
        except (OSError, ValueError):
            continue
        if ch:
            out.add(ch)
    return sorted(out, key=str.lower)


COMMON = set("""the and you that this with have what your just like they there their about from would
when were will then them than been into because hain nahi nahin kya bhai haan bhi kuch aur yeh woh mein
kaise kyun abhi phir sirf matlab achha theek bahut sabko hamare tumhare unka unki iska uska""".split())


def suggest(channel: str, limit: int = 15) -> list[str]:
    """Words that keep coming up across this creator's reels (capitalised or long, in 2+ reels)."""
    seen_in = Counter()
    root = library.root()
    for meta in root.glob(f"*/{FOLDER_FILE}") if root.is_dir() else []:
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("channel") != channel:
                continue
        except (OSError, ValueError):
            continue
        for ass in meta.parent.glob("reel_*[0-9].ass"):
            words = {w["word"].strip(".,!?\"'।") for w in captions.parse_words(ass.read_text(encoding="utf-8"))}
            for w in words:
                if len(w) >= 4 and w.lower() not in COMMON and (w[:1].isupper() or len(w) >= 7) and not w.isupper():
                    seen_in[w] += 1
    known = {n.lower() for n in load(channel)["names"]}
    return [w for w, c in seen_in.most_common(limit * 3) if c >= 2 and w.lower() not in known][:limit]
