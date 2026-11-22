"""Which speech model hears your streams best? Scores each downloaded model on your own reels against
YouTube's captions of the same moments (YouTube's text is the reference, so treat scores as a guide).

    python -m makereel.services.speech_test --reels 4 --models hinglish indic-hi medium
"""
from __future__ import annotations

import argparse
import json
import time
from difflib import SequenceMatcher

from anyascii import anyascii

from ..core import language, models, sources, transcribe
from ..core.pipeline import similar
from . import library


def _norm(words: list[str]) -> list[str]:
    out = []
    for w in words:
        w = anyascii(language.romanize_text(w)).lower().strip(".,!?'\"।-")
        if w:
            out.append(w)
    return out


def score(reference: list[str], heard: list[str]) -> float:
    """Share of reference words the model got (sound-alike counts: भाई = bhai = bai)."""
    a, b = _norm(reference), _norm(heard)
    if not a:
        return 0.0
    ok = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            ok += i2 - i1
        elif tag == "replace":
            ok += sum(similar(x, y) for x, y in zip(a[i1:i2], b[j1:j2], strict=False))
    return ok / len(a)


def _reels(limit: int) -> list[dict]:
    """Reels with their audio, a YouTube link and a place in the video, newest folders first."""
    out = []
    root = library.root()
    for meta in sorted(root.glob("*/folder.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        info = json.loads(meta.read_text(encoding="utf-8"))
        url = info.get("url") or ""
        if "youtu" not in url:
            continue
        for f in sorted(meta.parent.glob("reel_*[0-9].json")):
            post = json.loads(f.read_text(encoding="utf-8"))
            audio = meta.parent / (post.get("raw") or post.get("file") or "-")
            if audio.is_file() and post.get("source_time") is not None:
                out.append({"folder": meta.parent.name, "reel": f.stem, "url": url, "audio": audio,
                            "at": float(post.get("source_start") or post["source_time"]),
                            "length": float(post.get("length") or (post.get("end", 0) - post.get("start", 0))),
                            "lang": post.get("language") or info.get("language")})
            if len([r for r in out if r["folder"] == meta.parent.name]) >= 2:   # 2 per video: more variety
                break
        if len(out) >= limit:
            break
    return out[:limit]


def run(reel_count: int = 4, names: list[str] | None = None) -> dict:
    names = [n for n in (names or list(models.CATALOG)) if models.installed(n)]
    results: dict[str, dict] = {n: {"scores": [], "seconds": 0.0} for n in names}
    yt_cache: dict[str, list] = {}
    used = []
    for r in _reels(reel_count * 3):
        if len(used) >= reel_count:
            break
        if r["url"] not in yt_cache:
            yt_cache[r["url"]] = sources.youtube_captions(r["url"], r["lang"]) or []
        yt = yt_cache[r["url"]]
        if not yt:
            continue
        length = min(r["length"], 90.0)
        heard_by = {}
        for n in names:
            if r["lang"] == "hi" and models.CATALOG[n]["english_only"]:
                continue
            t = time.time()
            words = transcribe.words_in(r["audio"], 0, length, n, r["lang"] or None, precise=True)
            results[n]["seconds"] += time.time() - t
            heard_by[n] = [w["word"] for w in words]
        # YouTube's words for the same moment: the shift (±20 s) that best fits what the models heard
        best, best_fit = [], -1.0
        for k in range(-40, 41):
            t0 = r["at"] + k / 2
            ref = [w["word"] for w in yt if t0 <= w["start"] < t0 + length]
            if len(ref) < 5:
                continue
            fit = sum(score(ref, h) for h in heard_by.values())
            if fit > best_fit:
                best, best_fit = ref, fit
        if not best:
            continue
        used.append(f'{r["folder"][:40]} / {r["reel"]}')
        for n, h in heard_by.items():
            results[n]["scores"].append(score(best, h))
    table = sorted(({"model": n, "label": models.CATALOG[n]["label"],
                     "score": round(100 * sum(v["scores"]) / len(v["scores"])) if v["scores"] else None,
                     "reels": len(v["scores"]), "seconds": round(v["seconds"], 1)}
                    for n, v in results.items()), key=lambda x: -(x["score"] or -1))
    return {"reels": used, "models": table}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reels", type=int, default=4)
    p.add_argument("--models", nargs="*")
    res = run(p.parse_args().reels, p.parse_args().models)
    print("Reels:", *res["reels"], sep="\n  ")
    for m in res["models"]:
        print(f'  {m["label"]:<28} {m["score"] if m["score"] is not None else "-":>4}%  on {m["reels"]} reels, '
              f'{m["seconds"]} s')


if __name__ == "__main__":
    main()
