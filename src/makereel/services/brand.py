"""Brand kit files: one logo and any number of fonts, stored in <data>/brand/."""
from __future__ import annotations

import re
from pathlib import Path

from ..core import branding
from ..errors import InvalidInput, NotFound

MAX_LOGO_BYTES = 5 * 1024**2
MAX_FONT_BYTES = 20 * 1024**2
LOGO_TYPES = {b"\x89PNG": "logo.png", b"RIFF": "logo.webp", b"\xff\xd8\xff": "logo.jpg"}
FONT_SUFFIXES = (".ttf", ".otf")


def save_logo(data: bytes) -> dict:
    if not 0 < len(data) <= MAX_LOGO_BYTES:
        raise InvalidInput("the logo must be an image under 5 MB")
    name = next((n for magic, n in LOGO_TYPES.items() if data.startswith(magic)), None)
    if name is None:
        raise InvalidInput("the logo must be a PNG (best: transparent background), WebP or JPG")
    delete_logo()
    (branding.brand_dir() / name).write_bytes(data)
    return info()


def delete_logo() -> None:
    for n in branding.LOGO_NAMES:
        (branding.brand_dir() / n).unlink(missing_ok=True)


def save_font(filename: str, data: bytes) -> dict:
    name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)
    if not name.lower().endswith(FONT_SUFFIXES):
        raise InvalidInput("fonts must be .ttf or .otf files")
    if not 0 < len(data) <= MAX_FONT_BYTES:
        raise InvalidInput("the font file is empty or larger than 20 MB")
    (branding.fonts_dir() / name).write_bytes(data)
    return info()


def delete_font(name: str) -> None:
    path = branding.fonts_dir() / Path(name).name
    if not path.is_file():
        raise NotFound(f"no font {name}")
    path.unlink()


def info() -> dict:
    logo = branding.logo_file()
    return {"logo": f"/brand/{logo.name}?v={int(logo.stat().st_mtime)}" if logo else None,
            "fonts": sorted(p.name for p in branding.fonts_dir().iterdir()
                            if p.suffix.lower() in FONT_SUFFIXES)}
