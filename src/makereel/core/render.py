"""Render a reel in two cheap steps.

1. `<name>.raw.mp4`  the moment, reframed to 9:16, loudness-normalised, no captions.
2. `<name>.mp4`      raw + `<name>.ass` burned in with libass.

Editing captions only repeats step 2, so fixes take seconds.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from . import captions, media

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920


def _reframe(layout: str) -> str:
    if layout == "crop":
        return f"scale=-2:{HEIGHT},crop={WIDTH}:{HEIGHT},setsar=1"
    # full frame (HUD, minimap, facecam all visible) over a blurred fill
    return (f"split[a][b];[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
            f"boxblur=10:2,eq=brightness=-0.08,scale={WIDTH}:{HEIGHT}[bg];"
            f"[b]scale={WIDTH}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")


def cut_raw(src: Path, start: float, end: float, raw: Path, layout: str = "blur") -> None:
    media.run([media.binary("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(src), "-filter_complex", f"[0:v]{_reframe(layout)},fps=30[v]",
               "-map", "[v]", "-map", "0:a?", *media.encoder_args("raw"), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
               "-movflags", "+faststart", str(raw)])


def burn(raw: Path, ass: Path, out: Path) -> None:
    """Burn captions into `raw`. Writes to a temp file first so a failure never leaves a broken reel."""
    media.require_libass()
    tmp = out.with_name(out.stem + ".tmp.mp4")
    # run inside the folder so the filter argument is a plain file name (no escaping, works on Windows)
    media.run([media.binary("ffmpeg"), "-y", "-v", "error", "-i", raw.name, "-vf", f"ass={ass.name}",
               *media.encoder_args("final"), "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", tmp.name], cwd=out.parent)
    tmp.replace(out)


def render_clip(src: Path, start: float, end: float, words: list[dict], out: Path,
                layout: str = "blur", hook: str | None = None) -> dict:
    raw, ass = out.with_suffix(".raw.mp4"), out.with_suffix(".ass")
    ass.write_text(captions.build_ass(words, start, end, hook), encoding="utf-8")
    cut_raw(src, start, end, raw, layout)
    burn(raw, ass, out)
    return {"file": out.name, "raw": raw.name, "captions": ass.name}


def trim_silence(path: Path) -> None:
    """Optional Auto-Editor pass to cut dead air (talk content, not gameplay)."""
    exe = shutil.which("auto-editor")
    if not exe:
        log.warning("auto-editor not installed; skipping silence trim (pip install 'makereel[silence]')")
        return
    tmp = path.with_name(path.stem + "_ae.mp4")
    result = subprocess.run([exe, str(path), "--margin", "0.25s", "--no-open", "-o", str(tmp)],
                            capture_output=True)
    if result.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        log.warning("silence trim failed; keeping the untrimmed reel")
