"""Configuration, in two layers.

1. **Environment** (`MAKEREEL_*` variables, or a `.env` file in the working directory):
   how and where this install runs, plus secrets. Never written by the app.
2. **Settings** (`makereel.json`): what the user tunes from the web app or by hand
   (channels, clip lengths, limits). Read fresh on every use, so edits apply without a restart.

See docs/CONFIGURATION.md for every option.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import re
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
    "min_len": 15,           # shortest reel (s); each reel's length follows its moment, between these two
    "max_len": 180,          # longest reel (s), up to 300
    "model": "base",         # whisper size: tiny | base | small | medium | large-v3
    "layout": "auto",        # auto (from what is on screen) | blur | crop | pad | track | split
    "language": None,        # None = auto-detect (once per video, so every reel matches)
    "model_other": "small",  # model for non-English speech when `model` is tiny/base ("same" = don't switch)
    "silence": False,        # trim dead air with auto-editor (talk content)
    "fps": 30,               # 30, or 60 to keep smooth motion from 50/60 fps sources (gameplay)
}

BRAND_DEFAULTS: dict[str, Any] = {
    "logo_enabled": True,           # show the uploaded logo (if any) on reels
    "logo_position": "top-right",   # top-left | top-right | bottom-left | bottom-right
    "logo_scale": 0.16,             # logo width as a share of the video width
    "logo_opacity": 0.9,
    "creator_badge": "top-left",    # creator's picture + @handle on reels: off | top-left | top-right | ...
    "creator_badge_place": "corner",  # corner: small, tucked into the corner (may sit under app buttons) | safe
    "font": "Arial Black",          # any installed font, or one uploaded in the Brand tab
    "text_colour": "#FFFFFF",
    "highlight_colour": "#FFDD00",
    "outline_colour": "#000000",
    "caption_position": "bottom",   # bottom | middle | top
    "caption_size": 1.0,
    "caption_template": "classic",  # classic | pop | boxed | glow | karaoke | single | minimal
    "caption_box": False,           # background box behind captions (helps over busy or captioned video)
    "box_colour": "#000000",
    "box_opacity": 0.6,
    "caption_script": "original",   # original (own script) | roman (English letters) | english (translated)
    "safe_zone": "all",             # keep captions/logo clear of app buttons: all | tiktok | reels | shorts | off
    "credit_footer": True,          # add "Made with makereel" to the post text (opt out here)
}

AI_DEFAULTS: dict[str, Any] = {
    "provider": "off",       # off | local (Ollama, LM Studio...) | claude | openai (any OpenAI-compatible API)
    "model": "",             # empty = the provider's default
    "base_url": "",          # for local / openai; empty = the provider's default
    "weight": 0.5,           # 0 = signals only, 1 = AI only
}

SETTINGS_DEFAULTS: dict[str, Any] = {
    "channels": [],          # "@handle", channel URLs, twitch.tv/x, kick.com/x
    "inbox": "inbox.txt",    # headless use: paste links here, one per line
    "poll_minutes": 4,
    "max_parallel_live": 2,
    "watch_uploads": True,   # also clip new uploads and finished premieres (YouTube), not only live streams
    "uploads_since": "new",  # first check of a channel: "new" (only what comes next), "24h", "48h" or "YYYY-MM-DD"
    "uploads_every": "5",    # minutes between upload checks, or "random" (anything from 4 to 30 each time)
    "keep_days": 7,          # delete reels older than this
    "keep_source": False,    # keep downloaded videos after clipping
    "buffer_minutes": 10,    # live rolling buffer
    "clips_per_hour": 6,     # per live stream
    "max_height": 720,       # source resolution to download
    "cookies_browser": "",   # use this browser's YouTube sign-in (chrome, firefox, edge, safari...): avoids bot checks
    "speech_device": "auto", # where speech recognition runs: auto (NVIDIA GPU if usable) | gpu | cpu
    "setup_done": False,     # the first-run setup (model suggestions) was finished or skipped
    "watching": False,       # the channel watcher was on when makereel last ran (it starts again)
    "update_repo": "simarpreetsingh-019/makereel",   # GitHub repo whose releases are offered as updates ("" = off)
    "update_check": True,    # look for a new release when the app starts (one small request)
    "reels_folder": "",      # where reel folders are saved ("" = ./output); MAKEREEL_OUTPUT_DIR wins if set
    "work_folder": "",       # temporary downloads and live buffers ("" = ./downloads); MAKEREEL_WORK_DIR wins
    "clip": CLIP_DEFAULTS,
    "brand": BRAND_DEFAULTS,
    "ai": AI_DEFAULTS,
}

INT_SETTINGS = ("poll_minutes", "max_parallel_live", "keep_days", "buffer_minutes",
                "clips_per_hour", "max_height")
CLIP_CHOICES = {"profile": ("gameplay", "talk"), "layout": ("auto", "blur", "crop", "pad", "track", "split"),
                "model": ("tiny", "base", "small", "medium", "distil-large-v3", "large-v3"),
                "model_other": ("same", "small", "medium", "large-v3")}


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

    @property
    def ai(self) -> dict[str, Any]:
        return self.data["ai"]

    def with_clip(self, **overrides: Any) -> Settings:
        """A copy with some clip options replaced (None and "" mean 'keep the default')."""
        data = copy.deepcopy(self.data)
        data["clip"].update({k: v for k, v in overrides.items() if v not in (None, "")})
        validate_clip(data["clip"])
        return Settings(data)


def validate_clip(clip: dict[str, Any]) -> None:
    clip.setdefault("model_other", "small")
    try:
        clip["fps"] = int(clip.get("fps") or 30)
    except (TypeError, ValueError) as e:
        raise ConfigError("clip.fps must be 30 or 60") from e
    if clip["fps"] not in (30, 60):
        raise ConfigError("clip.fps must be 30 or 60")
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
    if not 3 <= clip["min_len"] <= clip["max_len"] <= 300:
        raise ConfigError("clip lengths must satisfy 3 <= min_len <= max_len <= 300")


def validate_brand(brand: dict[str, Any]) -> None:
    import re
    if brand.get("logo_position") not in ("top-left", "top-right", "bottom-left", "bottom-right"):
        raise ConfigError("brand.logo_position must be top-left, top-right, bottom-left or bottom-right")
    if brand.get("creator_badge", "off") not in ("off", "top-left", "top-right", "bottom-left", "bottom-right"):
        raise ConfigError("brand.creator_badge must be off or a corner (top-left, top-right, ...)")
    if brand.get("creator_badge_place", "corner") not in ("corner", "safe"):
        raise ConfigError("brand.creator_badge_place must be corner or safe")
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
    from .core.captions import TEMPLATES
    from .core.language import SCRIPT_MODES
    if brand.setdefault("caption_script", "original") not in SCRIPT_MODES:
        raise ConfigError(f"brand.caption_script must be one of {', '.join(SCRIPT_MODES)}")
    from .core.safezone import CHOICES as SAFE_CHOICES
    if brand.setdefault("safe_zone", "all") not in SAFE_CHOICES:
        raise ConfigError(f"brand.safe_zone must be one of {', '.join(SAFE_CHOICES)}")
    if brand.get("caption_template") not in TEMPLATES:
        raise ConfigError(f"brand.caption_template must be one of {', '.join(TEMPLATES)}")


def validate_ai(ai: dict[str, Any]) -> None:
    if ai.get("provider") not in ("off", "local", "claude", "openai"):
        raise ConfigError("ai.provider must be off, local, claude or openai")
    try:
        ai["weight"] = float(ai.get("weight", 0.5))
    except (TypeError, ValueError) as e:
        raise ConfigError("ai.weight must be a number between 0 and 1") from e
    if not 0 <= ai["weight"] <= 1:
        raise ConfigError("ai.weight must be between 0 and 1")
    base = str(ai.get("base_url") or "")
    if base and not base.startswith(("http://", "https://")):
        raise ConfigError("ai.base_url must start with http:// or https://")
    ai["model"], ai["base_url"] = str(ai.get("model") or "").strip(), base.strip()


def load_settings(path: Path | None = None) -> Settings:
    path = path or env().config_file
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON: {e}") from e
    data = copy.deepcopy(SETTINGS_DEFAULTS)
    data.update({k: v for k, v in raw.items() if k in SETTINGS_DEFAULTS and k not in ("clip", "brand", "ai")})
    data["clip"].update({k: v for k, v in (raw.get("clip") or {}).items() if k in CLIP_DEFAULTS})
    data["brand"].update({k: v for k, v in (raw.get("brand") or {}).items() if k in BRAND_DEFAULTS})
    data["ai"].update({k: v for k, v in (raw.get("ai") or {}).items() if k in AI_DEFAULTS})
    validate_clip(data["clip"])
    validate_brand(data["brand"])
    validate_ai(data["ai"])
    return Settings(data)


UPLOADS_EVERY = ("4", "5", "10", "15", "30", "60", "random")


def validate_since(value: Any) -> str:
    v = str(value or "new").strip()
    if v in ("new", "24h", "48h"):
        return v
    try:
        datetime.date.fromisoformat(v)
    except ValueError as e:
        raise ConfigError("uploads_since must be new, 24h, 48h or a date like 2026-11-01") from e
    return v


def since_cutoff(value: str, now: float) -> float | None:
    """Unix time from which uploads are clipped; None = only uploads that appear from now on."""
    if value == "24h":
        return now - 24 * 3600
    if value == "48h":
        return now - 48 * 3600
    if value and value != "new":
        d = datetime.date.fromisoformat(value)
        return datetime.datetime(d.year, d.month, d.day).timestamp()   # midnight, this computer's time
    return None


def validate_folder(value: Any) -> str:
    """'' (the default) or an absolute folder path we can write to (created if missing)."""
    raw = str(value or "").strip().strip('"')
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ConfigError("give the full path of the folder, e.g. /Users/you/Movies/makereel or D:\\Reels")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".makereel-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise ConfigError(f"makereel can't save files in {path}: {e.strerror or e}") from e
    return str(path)


def reels_dir() -> Path:
    """Where reel folders go: MAKEREEL_OUTPUT_DIR if set, else the reels_folder setting, else ./output."""
    if os.environ.get("MAKEREEL_OUTPUT_DIR"):
        return env().output_dir
    return Path(load_settings()["reels_folder"] or env().output_dir)


def work_dir() -> Path:
    """Temporary downloads and live buffers: MAKEREEL_WORK_DIR, else the work_folder setting, else ./downloads."""
    if os.environ.get("MAKEREEL_WORK_DIR"):
        return env().work_dir
    return Path(load_settings()["work_folder"] or env().work_dir)


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
    if "uploads_since" in changes:
        current["uploads_since"] = validate_since(changes["uploads_since"])
    if "uploads_every" in changes:
        every = str(changes["uploads_every"]).strip()
        if every not in UPLOADS_EVERY:
            raise ConfigError(f"uploads_every must be one of {', '.join(UPLOADS_EVERY)}")
        current["uploads_every"] = every
    if "cookies_browser" in changes:
        browser = str(changes["cookies_browser"] or "").strip().lower()
        if browser not in ("", "chrome", "firefox", "edge", "brave", "safari", "chromium", "opera", "vivaldi"):
            raise ConfigError("cookies_browser must be empty or one of chrome, firefox, edge, brave, safari...")
        current["cookies_browser"] = browser
    for key in ("reels_folder", "work_folder"):
        if key in changes:
            current[key] = validate_folder(changes[key])
    if "speech_device" in changes:
        if changes["speech_device"] not in ("auto", "gpu", "cpu"):
            raise ConfigError("speech_device must be auto, gpu or cpu")
        current["speech_device"] = changes["speech_device"]
    if "update_repo" in changes:
        repo = str(changes["update_repo"] or "").strip().removeprefix("https://github.com/").strip("/")
        if repo and not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo):
            raise ConfigError("update_repo must look like owner/repo")
        current["update_repo"] = repo
    for key in ("keep_source", "watch_uploads", "setup_done", "update_check", "watching"):
        if key in changes:
            current[key] = bool(changes[key])
    if isinstance(changes.get("clip"), dict):
        current["clip"].update({k: v for k, v in changes["clip"].items()
                                if k in CLIP_DEFAULTS and v != ""})
        validate_clip(current["clip"])
    if isinstance(changes.get("ai"), dict):
        current["ai"].update({k: v for k, v in changes["ai"].items() if k in AI_DEFAULTS})
        validate_ai(current["ai"])
    if isinstance(changes.get("brand"), dict):
        current["brand"].update({k: v for k, v in changes["brand"].items() if k in BRAND_DEFAULTS})
        validate_brand(current["brand"])
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return Settings(current)
