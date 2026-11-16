"""Turn the brand kit (settings["brand"] + files in <data>/brand/) into render options."""
from __future__ import annotations

from pathlib import Path

from ..config import env
from . import language
from .captions import TEMPLATES, Style
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


def style_for(fmt: str, brand: dict, look: dict | None = None, script: str | None = None) -> Style:
    """Caption style for a format: the brand kit, plus this reel's own look overrides (if any).

    `script` is the captions' script (language.script_of): non-Latin captions get a font that has
    those letters, since most brand fonts don't.
    """
    w, h = FORMATS[fmt]
    look = look or {}
    font = language.font_for(script, brand["font"], fonts_dir()) if script else brand["font"]
    return Style(width=w, height=h, font=font, text_colour=brand["text_colour"],
                 highlight_colour=brand["highlight_colour"], outline_colour=brand["outline_colour"],
                 position=brand["caption_position"],
                 size=look.get("size", brand["caption_size"]),
                 vertical=look.get("vertical"),
                 box=look.get("box", brand.get("caption_box", False)),
                 box_colour=look.get("box_colour", brand.get("box_colour", "#000000")),
                 box_opacity=look.get("box_opacity", brand.get("box_opacity", 0.6)))


def script_mode(brand: dict, look: dict | None = None) -> str:
    """original | roman | english: how this reel's captions are written."""
    return (look or {}).get("script") or brand.get("caption_script", "original")


def template_for(brand: dict, look: dict | None = None) -> str:
    return (look or {}).get("template") or brand.get("caption_template", "classic")


def clean_look(look: dict) -> dict:
    """Validate a reel's caption look overrides. Raises ValueError with a readable message."""
    import re
    out = {}
    if look.get("vertical") is not None:
        v = float(look["vertical"])
        if not 0.02 <= v <= 0.9:
            raise ValueError("caption height must be between 2% and 90% from the bottom")
        out["vertical"] = round(v, 3)
    if look.get("size") is not None:
        v = float(look["size"])
        if not 0.5 <= v <= 2.0:
            raise ValueError("caption size must be between 50% and 200%")
        out["size"] = round(v, 2)
    if look.get("box") is not None:
        out["box"] = bool(look["box"])
    if look.get("box_colour") is not None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(look["box_colour"])):
            raise ValueError("background colour must look like #000000")
        out["box_colour"] = look["box_colour"]
    if look.get("box_opacity") is not None:
        v = float(look["box_opacity"])
        if not 0 <= v <= 1:
            raise ValueError("background opacity must be between 0 and 100%")
        out["box_opacity"] = round(v, 2)
    if look.get("template") is not None:
        if look["template"] not in TEMPLATES:
            raise ValueError(f"caption template must be one of {', '.join(TEMPLATES)}")
        out["template"] = look["template"]
    if look.get("script") is not None:
        if look["script"] not in language.SCRIPT_MODES:
            raise ValueError(f"caption script must be one of {', '.join(language.SCRIPT_MODES)}")
        out["script"] = look["script"]
    return out


def logo_for(brand: dict, enabled_on_reel: bool = True) -> Logo | None:
    path = logo_file()
    if not (path and brand["logo_enabled"] and enabled_on_reel):
        return None
    return Logo(path.resolve(), brand["logo_position"], brand["logo_scale"], brand["logo_opacity"])
