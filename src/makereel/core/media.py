"""ffmpeg / ffprobe access: find the binaries, pick an encoder, run commands with clear errors."""
from __future__ import annotations

import functools
import platform
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ..config import env
from ..errors import DependencyMissing, MediaError

# Homebrew's ffmpeg-full (has libass) is keg-only: it sits next to plain ffmpeg without replacing it.
_SEARCH_DIRS = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")

INSTALL_HINT = ("macOS: brew install ffmpeg-full · Windows: winget install Gyan.FFmpeg · "
                "Linux: sudo apt install ffmpeg · or set MAKEREEL_FFMPEG_DIR")


@functools.cache
def binary(name: str) -> str:
    """Absolute path to ffmpeg/ffprobe, preferring MAKEREEL_FFMPEG_DIR, then ffmpeg-full, then PATH."""
    dirs = [env().ffmpeg_dir or "", *_SEARCH_DIRS]
    for d in dirs:
        for exe in (name, name + ".exe"):
            if d and (Path(d) / exe).is_file():
                return str(Path(d) / exe)
    found = shutil.which(name)
    if not found:
        raise DependencyMissing(f"{name} is not installed", INSTALL_HINT)
    return found


def run(cmd: Sequence[str], *, cwd: Path | None = None, capture: bool = False) -> bytes:
    """Run a media command; raise MediaError with the tool's own message on failure."""
    try:
        proc = subprocess.run(list(cmd), cwd=cwd, capture_output=True)
    except FileNotFoundError as e:
        raise DependencyMissing(f"{cmd[0]} is not installed", INSTALL_HINT) from e
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="ignore").strip().splitlines()[-3:]
        raise MediaError(f"{Path(cmd[0]).name} failed: {' / '.join(tail) or 'exit ' + str(proc.returncode)}")
    return proc.stdout if capture else b""


@functools.cache
def _listing(kind: str) -> str:
    try:
        return subprocess.run([binary("ffmpeg"), "-hide_banner", f"-{kind}"],
                              capture_output=True, text=True).stdout
    except (DependencyMissing, OSError):
        return ""


def has_libass() -> bool:
    return any(len(p) > 1 and p[1] == "ass" for p in (l.split() for l in _listing("filters").splitlines()))


def require_libass() -> None:
    if not has_libass():
        raise DependencyMissing("this ffmpeg can't draw text captions (it was built without libass)",
                                INSTALL_HINT)


@functools.cache
def _encoder_works(args: tuple[str, ...]) -> bool:
    """Encoders can be compiled in but unusable (no GPU / driver), so try one tiny frame."""
    try:
        r = subprocess.run([binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                            *args, "-frames:v", "1", "-f", "null", "-"], capture_output=True)
        return r.returncode == 0
    except (DependencyMissing, OSError):
        return False


def _encoder_options(rate: str) -> dict[str, list[str]]:
    return {
        "h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-b:v", rate, "-maxrate", rate, "-allow_sw", "1"],
        "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", rate],
        "h264_qsv": ["-c:v", "h264_qsv", "-b:v", rate],
        "h264_amf": ["-c:v", "h264_amf", "-b:v", rate],
        "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", str(env().threads)],
    }


@functools.cache
def encoder_name() -> str:
    """Hardware encoder when one works (a fraction of x264's CPU and power), else libx264.

    macOS: VideoToolbox. Windows/Linux: NVIDIA NVENC, Intel Quick Sync, AMD AMF.
    """
    options = _encoder_options("8M")
    if env().encoder in options:
        return env().encoder  # type: ignore[return-value]
    listed = _listing("encoders")
    for name in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"):
        if name in listed and _encoder_works(tuple(options[name])):
            return name
    return "libx264"


def encoder_args(quality: str = "final") -> list[str]:
    return _encoder_options("8M" if quality == "final" else "12M")[encoder_name()]


def duration(path: Path) -> float:
    out = run([binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)], capture=True)
    try:
        return float(out.decode().strip() or 0)
    except ValueError:
        return 0.0


def system_info() -> dict:
    try:
        ffmpeg = binary("ffmpeg")
    except DependencyMissing:
        ffmpeg = None
    return {"os": f"{platform.system()} {platform.machine()}", "python": platform.python_version(),
            "ffmpeg": ffmpeg, "libass": bool(ffmpeg) and has_libass(),
            "encoder": encoder_name() if ffmpeg else None, "threads": env().threads}

