"""Render reels in any shape, with captions and an optional logo.

Files per reel (all in the video's folder):
  reel_NN.src.mp4      the moment in its original shape plus a few seconds either side (so it can
                       be trimmed or extended later), loudness-normalised, no captions. The master
                       every format is made from. The reel itself is [src_offset, src_offset + length].
  reel_NN.raw.mp4      the main 9:16 version without captions, so caption edits only re-burn.
  reel_NN.mp4          the main reel: raw + captions (+ logo).
  reel_NN.<fmt>.mp4    other exports (4x5, 1x1, 16x9...), made on demand from src.

Editing captions only repeats the last step, so fixes take seconds.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import media

log = logging.getLogger(__name__)

FORMATS: dict[str, tuple[int, int]] = {
    "9x16": (1080, 1920),   # Reels, Shorts, TikTok, Stories
    "4x5": (1080, 1350),    # Instagram feed (largest in-feed size)
    "1x1": (1080, 1080),    # feed posts, LinkedIn, X
    "16x9": (1920, 1080),   # YouTube, X, websites
}
FITS = ("blur", "crop", "pad", "track")   # blurred fill · crop to fill · black bars · follow the speaker
LOGO_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
MAIN_FORMAT = "9x16"


@dataclass(frozen=True)
class Logo:
    path: Path
    position: str = "top-right"
    scale: float = 0.16          # logo width as a share of the video width
    opacity: float = 0.9
    clear_top: float = 0.0       # share of the height to stay below (app tabs / search bar)
    clear_bottom: float = 0.0    # share of the height to stay above (account name, description)


def _check_format(fmt: str, fit: str) -> tuple[int, int]:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    if fit not in FITS:
        raise ValueError(f"fit must be one of {', '.join(FITS)}")
    return FORMATS[fmt]


def reframe_filter(fmt: str, fit: str, track: tuple[str, int, int] | None = None) -> str:
    """Filter chain (input [0:v] → output [v]) that turns any shape into `fmt`.

    fit="track" needs `track` from framing.crop_expression; without it, it falls back to blur.
    """
    w, h = _check_format(fmt, fit)
    if fit == "track":
        if track is None:
            fit = "blur"
        else:
            expr, cw, ch = track
            return f"[0:v]crop=w={cw}:h={ch}:x='{expr}':y=0,scale={w}:{h},setsar=1,fps=30[v]"
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={w}:{h}"
    contain = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if fit == "crop":
        return f"[0:v]{cover},setsar=1,fps=30[v]"
    if fit == "pad":
        return f"[0:v]{contain},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30[v]"
    sw, sh = w // 4, h // 4   # blur a small copy: same look, a fraction of the work
    return (f"[0:v]split[a][b];[a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"boxblur=10:2,eq=brightness=-0.08,scale={w}:{h}[bg];[b]{contain}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[v]")


def _overlay_filters(label: str, ass: Path | None, fonts_dir: Path | None, logo: Logo | None,
                     width: int, logo_input: int) -> tuple[str, str]:
    """Append captions and logo after `label`; returns (filter text, final label)."""
    parts, cur = [], label
    if ass is not None:
        fonts = f":fontsdir={fonts_dir.as_posix()}" if fonts_dir and fonts_dir.is_dir() else ""
        parts.append(f"[{cur}]ass={ass.name}{fonts}[c]")
        cur = "c"
    if logo is not None:
        m = round(width * 0.04)
        x = str(m) if "left" in logo.position else f"W-w-{m}"
        y = (f"max({m}\\,H*{logo.clear_top:.3f})" if "top" in logo.position
             else f"H-h-max({m}\\,H*{logo.clear_bottom:.3f})")
        parts.append(f"[{logo_input}:v]scale={round(width * logo.scale)}:-2,format=rgba,"
                     f"colorchannelmixer=aa={logo.opacity:.2f}[lg];[{cur}][lg]overlay={x}:{y}[o]")
        cur = "o"
    return ";".join(parts), cur


def _encode(inputs: list[Path], graph: str, out_label: str, out: Path, cwd: Path,
            audio: str = "copy", section: tuple[float, float] | None = None) -> None:
    """Run one ffmpeg graph to a temp file, then swap it in (a failure never leaves a broken file).

    `section` = (start, length) of input 0 to use (the reel's part of its master clip).
    """
    tmp = out.with_name(out.stem + ".tmp.mp4")
    cmd = [media.binary("ffmpeg"), "-y", "-v", "error"]
    if section is not None:
        audio = "aac"   # cutting needs a re-encode of the audio too
    for i, path in enumerate(inputs):
        if i == 0 and section is not None:
            cmd += ["-ss", f"{section[0]:.3f}", "-t", f"{section[1]:.3f}"]
        if i > 0 and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            cmd += ["-loop", "1"]   # a still logo lasts the whole video
        cmd += ["-i", str(path.resolve()) if path.parent != cwd else path.name]
    cmd += ["-filter_complex", graph, "-map", f"[{out_label}]", "-map", "0:a?", "-shortest",
            *media.encoder_args("final"), "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if audio == "copy" else ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", tmp.name]
    media.run(cmd, cwd=cwd)
    tmp.replace(out)


def cut_source(src: Path, start: float, end: float, out: Path) -> None:
    """The moment in its original shape, loudness-normalised (-14 LUFS): the master for every format."""
    media.run([media.binary("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-vf", "fps=30,setsar=1",
               *media.encoder_args("raw"), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
               "-movflags", "+faststart", str(out)])


def track_for(source: Path, fmt: str, fit: str, section: tuple[float, float] | None):
    """Speaker-tracking crop for fit='track' (None otherwise, or when nobody is on screen)."""
    if fit != "track":
        return None
    from . import framing
    start, length = section or (0.0, media.duration(source))
    w, h = FORMATS[fmt]
    return framing.crop_expression(source, start, length, w, h)


def make_raw(source: Path, raw: Path, fmt: str = MAIN_FORMAT, fit: str = "blur",
             section: tuple[float, float] | None = None) -> None:
    """Reframe the reel's part of the master into `fmt`, without captions (cached so caption edits are fast)."""
    track = track_for(source, fmt, fit, section)
    _encode([source], reframe_filter(fmt, fit, track), "v", raw, raw.parent, section=section)


def burn(raw: Path, ass: Path, out: Path, logo: Logo | None = None, fonts_dir: Path | None = None) -> None:
    """Captions (+ logo) on top of an already-reframed video."""
    media.require_libass()
    width = int(_probe_width(raw))
    inputs = [raw] + ([logo.path] if logo else [])
    graph, label = _overlay_filters("0:v", ass, fonts_dir, logo, width, 1)
    _encode(inputs, graph, label, out, out.parent)


def export(source: Path, ass: Path, out: Path, fmt: str, fit: str, logo: Logo | None = None,
           fonts_dir: Path | None = None, section: tuple[float, float] | None = None) -> None:
    """One pass: the reel's part of the master → any format, with captions and logo."""
    media.require_libass()
    w, _ = _check_format(fmt, fit)
    inputs = [source] + ([logo.path] if logo else [])
    graph, label = _overlay_filters("v", ass, fonts_dir, logo, w, 1)
    track = track_for(source, fmt, fit, section)
    _encode(inputs, reframe_filter(fmt, fit, track) + ";" + graph, label, out, out.parent, section=section)


def _probe_width(path: Path) -> float:
    out = media.run([media.binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width", "-of", "csv=p=0", str(path)], capture=True)
    try:
        return float(out.decode().strip().split()[0])
    except (ValueError, IndexError):
        return 1080.0


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
