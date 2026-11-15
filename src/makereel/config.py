"""Configuration, in two layers.

1. **Environment** (`MAKEREEL_*` variables, or a `.env` file in the working directory):
   how and where this install runs, plus secrets. Never written by the app.
2. **Settings** (`makereel.json`): what the user tunes from the web app or by hand
   (channels, clip lengths, limits). Read fresh on every use, so edits apply without a restart.

See docs/CONFIGURATION.md for every option.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError


# --------------------------------------------------------------------------- environment
def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader (KEY=value, # comments). Real environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as e:
        raise ConfigError(f"{name} must be a whole number, got {value!r}") from e


@dataclass(frozen=True)
class Env:
    config_file: Path
    output_dir: Path
    work_dir: Path
    data_dir: Path
    host: str
    port: int
    password: str | None
    allowed_origins: tuple[str, ...]
    threads: int
    ffmpeg_dir: str | None
    encoder: str | None
    log_level: str

    @classmethod
    def load(cls) -> Env:
        load_dotenv()
        origins = _env("MAKEREEL_ALLOWED_ORIGINS", "") or ""
        return cls(
            config_file=Path(_env("MAKEREEL_CONFIG", "makereel.json")),
            output_dir=Path(_env("MAKEREEL_OUTPUT_DIR", "output")),
            work_dir=Path(_env("MAKEREEL_WORK_DIR", "downloads")),
            data_dir=Path(_env("MAKEREEL_DATA_DIR", "data")),
            host=_env("MAKEREEL_HOST", "127.0.0.1"),
            port=_env_int("PORT", _env_int("MAKEREEL_PORT", 8765)),
            password=_env("MAKEREEL_WEB_PASSWORD"),
            allowed_origins=tuple(o.strip().rstrip("/") for o in origins.split(",") if o.strip()),
            threads=_env_int("MAKEREEL_THREADS", 2),
            ffmpeg_dir=_env("MAKEREEL_FFMPEG_DIR"),
            encoder=_env("MAKEREEL_ENCODER"),
            log_level=(_env("MAKEREEL_LOG_LEVEL", "INFO") or "INFO").upper(),
        )


_env_cache: Env | None = None


def env() -> Env:
    global _env_cache
    if _env_cache is None:
        _env_cache = Env.load()
    return _env_cache


# --------------------------------------------------------------------------- settings
CLIP_DEFAULTS: dict[str, Any] = {
    "profile": "gameplay",   # gameplay | talk
    "max_clips": 8,
    "min_len": 15,
    "max_len": 45,
    "model": "base",         # whisper size: tiny | base | small | medium | large-v3
    "layout": "blur",        # blur | crop
    "language": None,        # None = auto-detect
    "silence": False,        # trim dead air with auto-editor (talk content)
}

BRAND_DEFAULTS: dict[str, Any] = {
    "logo_enabled": True,           # show the uploaded logo (if any) on reels
    "logo_position": "top-right",   # top-left | top-right | bottom-left | bottom-right
    "logo_scale": 0.16,             # logo width as a share of the video width
    "logo_opacity": 0.9,
    "font": "Arial Black",          # any installed font, or one uploaded in the Brand tab
    "text_colour": "#FFFFFF",
    "highlight_colour": "#FFDD00",
    "outline_colour": "#000000",
    "caption_position": "bottom",   # bottom | middle | top
    "caption_size": 1.0,
    "caption_box": False,           # background box behind captions (helps over busy or captioned video)
    "box_colour": "#000000",
    "box_opacity": 0.6,
    "credit_footer": True,          # add "Made with makereel" to the post text (opt out here)
}

SETTINGS_DEFAULTS: dict[str, Any] = {
    "channels": [],          # "@handle", channel URLs, twitch.tv/x, kick.com/x
    "inbox": "inbox.txt",    # headless use: paste links here, one per line
    "poll_minutes": 4,
    "max_parallel_live": 2,
    "keep_days": 7,          # delete reels older than this
    "keep_source": False,    # keep downloaded videos after clipping
    "buffer_minutes": 10,    # live rolling buffer
    "clips_per_hour": 6,     # per live stream
    "max_height": 720,       # source resolution to download
    "clip": CLIP_DEFAULTS,
    "brand": BRAND_DEFAULTS,
}

INT_SETTINGS = ("poll_minutes", "max_parallel_live", "keep_days", "buffer_minutes",
                "clips_per_hour", "max_height")
CLIP_CHOICES = {"profile": ("gameplay", "talk"), "layout": ("blur", "crop"),
                "model": ("tiny", "base", "small", "medium", "large-v3")}


@dataclass
class Settings:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(SETTINGS_DEFAULTS))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @property
    def clip(self) -> dict[str, Any]:
        return self.data["clip"]

    @property
    def brand(self) -> dict[str, Any]:
        return self.data["brand"]

    def with_clip(self, **overrides: Any) -> Settings:
        """A copy with some clip options replaced (None and "" mean 'keep the default')."""
        data = copy.deepcopy(self.data)
        data["clip"].update({k: v for k, v in overrides.items() if v not in (None, "")})
        validate_clip(data["clip"])
        return Settings(data)


def validate_clip(clip: dict[str, Any]) -> None:
    for key, choices in CLIP_CHOICES.items():
        if clip.get(key) not in choices:
            raise ConfigError(f"clip.{key} must be one of {', '.join(choices)}, got {clip.get(key)!r}")
    for key in ("max_clips", "min_len", "max_len"):
        try:
            clip[key] = int(clip[key]) if key == "max_clips" else float(clip[key])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"clip.{key} must be a number") from e
    if not 1 <= clip["max_clips"] <= 50:
        raise ConfigError("clip.max_clips must be between 1 and 50")
    if not 3 <= clip["min_len"] <= clip["max_len"] <= 180:
        raise ConfigError("clip lengths must satisfy 3 <= min_len <= max_len <= 180")


def validate_brand(brand: dict[str, Any]) -> None:
    import re
    if brand.get("logo_position") not in ("top-left", "top-right", "bottom-left", "bottom-right"):
        raise ConfigError("brand.logo_position must be top-left, top-right, bottom-left or bottom-right")
    if brand.get("caption_position") not in ("bottom", "middle", "top"):
        raise ConfigError("brand.caption_position must be bottom, middle or top")
    for key in ("text_colour", "highlight_colour", "outline_colour", "box_colour"):
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(brand.get(key, ""))):
            raise ConfigError(f"brand.{key} must be a colour like #FFDD00")
    for key, lo, hi in (("logo_scale", 0.03, 0.6), ("logo_opacity", 0.05, 1.0), ("caption_size", 0.5, 2.0),
                         ("box_opacity", 0.0, 1.0)):
        try:
            brand[key] = float(brand[key])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"brand.{key} must be a number") from e
        if not lo <= brand[key] <= hi:
            raise ConfigError(f"brand.{key} must be between {lo} and {hi}")
    if not str(brand.get("font", "")).strip() or any(c in str(brand["font"]) for c in ",{}\\"):
        raise ConfigError("brand.font must be a plain font name")
    brand["logo_enabled"] = bool(brand.get("logo_enabled"))
    brand["credit_footer"] = bool(brand.get("credit_footer"))
    brand["caption_box"] = bool(brand.get("caption_box"))


def load_settings(path: Path | None = None) -> Settings:
    path = path or env().config_file
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON: {e}") from e
    data = copy.deepcopy(SETTINGS_DEFAULTS)
    data.update({k: v for k, v in raw.items() if k in SETTINGS_DEFAULTS and k not in ("clip", "brand")})
    data["clip"].update({k: v for k, v in (raw.get("clip") or {}).items() if k in CLIP_DEFAULTS})
    data["brand"].update({k: v for k, v in (raw.get("brand") or {}).items() if k in BRAND_DEFAULTS})
    validate_clip(data["clip"])
    validate_brand(data["brand"])
    return Settings(data)


def save_settings(changes: dict[str, Any], path: Path | None = None) -> Settings:
    """Validate and merge `changes` into makereel.json. Unknown keys are rejected."""
    path = path or env().config_file
    current = load_settings(path).data
    unknown = set(changes) - set(SETTINGS_DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown settings: {', '.join(sorted(unknown))}")
    if "channels" in changes:
        if not isinstance(changes["channels"], list):
            raise ConfigError("channels must be a list")
        current["channels"] = [str(c).strip() for c in changes["channels"] if str(c).strip()]
    for key in INT_SETTINGS:
        if changes.get(key) not in (None, ""):
            try:
                value = int(changes[key])
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{key} must be a whole number") from e
            if value < 1:
                raise ConfigError(f"{key} must be at least 1")
            current[key] = value
    if "keep_source" in changes:
        current["keep_source"] = bool(changes["keep_source"])
    if isinstance(changes.get("clip"), dict):
        current["clip"].update({k: v for k, v in changes["clip"].items()
                                if k in CLIP_DEFAULTS and v != ""})
        validate_clip(current["clip"])
    if isinstance(changes.get("brand"), dict):
        current["brand"].update({k: v for k, v in changes["brand"].items() if k in BRAND_DEFAULTS})
        validate_brand(current["brand"])
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return Settings(current)
