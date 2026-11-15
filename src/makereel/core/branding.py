"""Turn the brand kit (settings["brand"] + files in <data>/brand/) into render options."""
from __future__ import annotations

from pathlib import Path

from ..config import env
from .captions import Style
from .render import FORMATS, Logo

LOGO_NAMES = ("logo.png", "logo.webp", "logo.jpg")


def brand_dir() -> Path:
    path = env().data_dir / "brand"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fonts_dir() -> Path:
    path = brand_dir() / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logo_file() -> Path | None:
    return next((brand_dir() / n for n in LOGO_NAMES if (brand_dir() / n).is_file()), None)


def style_for(fmt: str, brand: dict) -> Style:
    w, h = FORMATS[fmt]
    return Style(width=w, height=h, font=brand["font"], text_colour=brand["text_colour"],
                 highlight_colour=brand["highlight_colour"], outline_colour=brand["outline_colour"],
                 position=brand["caption_position"], size=brand["caption_size"])


def logo_for(brand: dict, enabled_on_reel: bool = True) -> Logo | None:
    path = logo_file()
    if not (path and brand["logo_enabled"] and enabled_on_reel):
        return None
    return Logo(path.resolve(), brand["logo_position"], brand["logo_scale"], brand["logo_opacity"])
