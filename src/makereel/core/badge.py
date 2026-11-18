"""Creator badge: the channel's round profile picture and @handle, shown in a corner of every reel.

It credits the creator on the video itself (not only in the post text). Built once per folder as
`creator_badge.png` and placed like the logo. Nothing here is required: on any failure (offline,
no channel link, no picture) the reel is simply made without a badge.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path

import yt_dlp

from . import media
from .sources import ydl_opts

log = logging.getLogger(__name__)

BADGE_FILE = "creator_badge.png"
FAILED_FILE = ".creator_badge_failed"     # don't hit the network again on every re-render
FONT_URL = "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Bold.ttf"
SIZE, PAD, FONT_SIZE = 128, 14, 60        # picture size, padding, text size (px) of the badge image


def _avatar_and_handle(channel_url: str) -> tuple[str | None, str | None]:
    opts = {**ydl_opts(), "extract_flat": True, "playlist_items": "0", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        raw = ydl.extract_info(channel_url, download=False) or {}
    thumbs = [t for t in raw.get("thumbnails") or [] if "avatar" in str(t.get("id", ""))]
    best = next((t for t in thumbs if t.get("id") == "avatar_uncropped"), None) or (
        max(thumbs, key=lambda t: t.get("width") or 0) if thumbs else None)
    handle = raw.get("uploader_id") or raw.get("channel") or raw.get("uploader")
    return (best or {}).get("url"), handle


def clean_handle(handle: str | None) -> str:
    """Letters, digits and . _ - only (safe inside ffmpeg's text filter), with a leading @."""
    h = re.sub(r"[^A-Za-z0-9._-]", "", (handle or "").lstrip("@"))[:30]
    return f"@{h}" if h else ""


def _text_width(text: str) -> int:
    """Rough width of `text` in Noto Sans Bold at FONT_SIZE (no font library needed)."""
    per = sum(0.68 if c.isupper() or c in "@mwMW" else 0.56 if c.isalnum() else 0.36 for c in text)
    return int(per * FONT_SIZE) + 8


def _font(fonts_dir: Path) -> Path | None:
    path = fonts_dir / "NotoSans-Bold.ttf"
    if path.is_file():
        return path
    try:
        with urllib.request.urlopen(FONT_URL, timeout=20) as r:
            data = r.read()
        if data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            fonts_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path
    except OSError as e:
        log.warning("   could not download the badge font (%s)", e)
    return None


def _ff_path(path: Path) -> str:
    """A path inside an ffmpeg filter option: quoted, with ':' escaped (Windows drive letters)."""
    return "'" + path.resolve().as_posix().replace(":", "\\:") + "'"


def build(avatar: Path, handle: str, out: Path, font: Path | None) -> None:
    """Badge image: a dark rounded pill, the picture as a circle on the left, the handle on the right."""
    text_w = _text_width(handle) if handle and font else 0
    h = SIZE + 2 * PAD
    w = h + (text_w + PAD * 2 if text_w else 0)
    r = h / 2
    pill = (f"if(lt(X\\,{r})\\,lte(hypot(X-{r}\\,Y-{r})\\,{r})\\,"
            f"if(gt(X\\,{w - r})\\,lte(hypot(X-{w - r}\\,Y-{r})\\,{r})\\,1))*150")
    circle = f"if(lte(hypot(X-{SIZE / 2 - 0.5}\\,Y-{SIZE / 2 - 0.5})\\,{SIZE / 2})\\,255\\,0)"
    graph = (f"[0:v]format=rgba,geq=r=0:g=0:b=0:a='{pill}'[bg];"
             f"[1:v]scale={SIZE}:{SIZE}:force_original_aspect_ratio=increase,crop={SIZE}:{SIZE},format=rgba,"
             f"geq=r='r(X\\,Y)':g='g(X\\,Y)':b='b(X\\,Y)':a='{circle}'[av];"
             f"[bg][av]overlay={PAD}:{PAD}")
    if text_w:
        graph += (f",drawtext=fontfile={_ff_path(font)}:text='{handle}':fontcolor=white:"
                  f"fontsize={FONT_SIZE}:x={h + PAD // 2}:y=(h-text_h)/2")
    media.run([media.binary("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}",
               "-i", str(avatar), "-filter_complex", graph, "-frames:v", "1", str(out)])


def ensure(folder: Path, channel_url: str | None, channel: str | None, fonts_dir: Path) -> Path | None:
    """The folder's badge image, made on first use. None when it can't be made."""
    out = folder / BADGE_FILE
    if out.is_file():
        return out
    if not channel_url or (folder / FAILED_FILE).exists():
        return None
    try:
        url, handle = _avatar_and_handle(channel_url)
        if not url:
            raise ValueError("no profile picture")
        avatar = folder / "creator_avatar.jpg"
        with urllib.request.urlopen(url, timeout=20) as r:
            avatar.write_bytes(r.read())
        build(avatar, clean_handle(handle) or clean_handle(channel), out, _font(fonts_dir))
        avatar.unlink(missing_ok=True)
        log.info("   creator badge made for %s", handle or channel)
        return out
    except Exception as e:  # noqa: BLE001 - a badge is a nice-to-have, never a reason to fail a reel
        log.warning("   no creator badge (%s)", str(e).split("\n")[0][:120])
        (folder / FAILED_FILE).write_text(str(e)[:200], encoding="utf-8")
        return None
