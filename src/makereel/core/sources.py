"""Open anything yt-dlp can: live streams, past streams, long videos, Shorts (YouTube, Twitch, Kick...)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from ..errors import InvalidInput, SourceError

# YouTube needs a JavaScript runtime for its player checks; yt-dlp only tries deno by default.
log = logging.getLogger(__name__)
JS_RUNTIMES = {r: {} for r in ("deno", "node", "bun") if shutil.which(r)}
LIVE_STATUSES = ("is_live", "was_live", "not_live", "post_live", "is_upcoming")


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


BASE_OPTS = {"quiet": True, "logger": _QuietLogger(), "js_runtimes": JS_RUNTIMES}
COOKIE_BROWSERS = ("chrome", "firefox", "edge", "brave", "safari", "chromium", "opera", "vivaldi")


def cookies_browser() -> str | None:
    """The browser whose YouTube sign-in yt-dlp may use (setting: cookies_browser), or None."""
    from ..config import load_settings
    name = load_settings()["cookies_browser"]
    return name if name in COOKIE_BROWSERS else None


def cookies_file() -> Path:
    """A YouTube sign-in exported from the user's browser (cookies.txt). Kept only on this computer."""
    from ..config import env
    return env().data_dir / "youtube_cookies.txt"


def ydl_opts() -> dict:
    """yt-dlp options for every request. A sign-in (an uploaded cookies file, else a browser's) makes
    YouTube see a signed-in viewer, which avoids its "confirm you're not a bot" check."""
    if cookies_file().is_file():
        return {**BASE_OPTS, "cookiefile": str(cookies_file())}
    browser = cookies_browser()
    return {**BASE_OPTS, **({"cookiesfrombrowser": (browser,)} if browser else {})}


# Other YouTube clients that are often not asked to prove they aren't a bot. Tried, in turn, when the
# normal request is refused, before asking the user to sign in.
FALLBACK_CLIENTS = (["mweb"], ["tv", "web_safari"])


def _is_bot_check(e: Exception) -> bool:
    low = str(e).lower()
    return "not a bot" in low or "confirm you" in low


def check_sign_in() -> dict:
    """What makereel can use to look signed in to YouTube, in words the user can act on."""
    if cookies_file().is_file():
        try:
            from http.cookiejar import MozillaCookieJar
            jar = MozillaCookieJar(str(cookies_file()))
            jar.load(ignore_discard=True, ignore_expires=True)
            yt = [c for c in jar if "youtube.com" in c.domain]
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "source": "file",
                    "message": f"The sign-in file can't be read ({str(e)[:120]})."}
        signed = any(c.name in ("SID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID") for c in yt)
        return {"ok": signed, "source": "file", "message": "Using your uploaded YouTube sign-in."
                if signed else "The uploaded file has no YouTube sign-in in it. Export it while signed in to YouTube."}
    browser = cookies_browser()
    if not browser:
        return {"ok": False, "source": None,
                "message": "No sign-in set. makereel works without one until YouTube asks."}
    try:
        with yt_dlp.YoutubeDL({**BASE_OPTS, "cookiesfrombrowser": (browser,)}) as ydl:
            yt = [c for c in ydl.cookiejar if "youtube.com" in c.domain]
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Operation not permitted" in msg or "could not find" in msg:
            import platform
            where = ("System Settings → Privacy & Security → Full Disk Access, and turn it on for the app that runs "
                     "makereel (Terminal, or the makereel launcher), then restart makereel"
                     if platform.system() == "Darwin" else "your browser's profile folder permissions")
            return {"ok": False, "source": browser, "blocked": True,
                    "message": f"Your computer isn't letting makereel read {browser.title()}'s sign-in. "
                               f"Allow it in {where}. "
                               "Or upload a sign-in file instead (Settings → Upload sign-in file)."}
        return {"ok": False, "source": browser, "message": f"Couldn't read {browser.title()}'s sign-in: {msg[:160]}"}
    signed = any(c.name in ("SID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID") for c in yt)
    return {"ok": signed, "source": browser,
            "message": f"Using your {browser.title()} sign-in." if signed
            else f"{browser.title()} isn't signed in to YouTube. Open YouTube in {browser.title()} and sign in."}


@dataclass
class SourceInfo:
    """What we know about a link before downloading anything."""
    id: str
    title: str
    channel: str
    channel_url: str | None
    url: str
    duration: float | None
    live_status: str                    # one of LIVE_STATUSES
    streams: list[str] = field(default_factory=list)  # direct media URLs (live: video + audio)
    tags: list[str] = field(default_factory=list)
    offset: float = 0.0                 # seconds into the original where our file starts
    published: float | None = None      # unix time it was uploaded / premiered, when known

    def to_meta(self) -> dict:
        return asdict(self)


@dataclass
class Download:
    video: Path
    chat: Path | None
    info: SourceInfo


ANSI = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m(?=\S)")


def _friendly(e: Exception) -> SourceError:
    msg = ANSI.sub("", str(e)).replace("ERROR: ", "").split("\n")[0]
    hint = None
    low = msg.lower()
    if "private" in low or "sign in" in low or "members" in low:
        hint = "The video is private, members-only or age-restricted."
    elif "unavailable" in low or "not available" in low:
        hint = "Check the link. If it opens in a browser, update yt-dlp: pip install -U \"yt-dlp[default]\""
    elif "403" in low or "forbidden" in low:
        hint = ("YouTube refused this download (it does this now and then). Try again in a minute; if it "
                "keeps happening, set up a YouTube sign-in in Settings.")
    elif "not a bot" in low or "confirm you" in low:
        hint = ("YouTube asked makereel to prove it isn't a bot. In Settings, choose the browser you're signed in "
                "to YouTube with (Use my YouTube sign-in from), then try again.")
    elif "not currently live" in low or "offline" in low:
        hint = "The channel is not live right now."
    return SourceError(msg[:300], hint)


def _published(raw: dict) -> float | None:
    """Unix time a video went up: exact when YouTube gives it, else the start of its upload day (UTC)."""
    for key in ("release_timestamp", "timestamp"):
        if raw.get(key):
            return float(raw[key])
    day = raw.get("upload_date")
    if day and len(day) == 8:
        import calendar
        return float(calendar.timegm((int(day[:4]), int(day[4:6]), int(day[6:]), 0, 0, 0)))
    return None


def _info(raw: dict, url: str, offset: float = 0.0) -> SourceInfo:
    if raw.get("_type") == "playlist":  # e.g. /@channel/live redirect quirks
        raw = next(iter(raw.get("entries") or []), None) or {}
    if not raw.get("id"):
        raise SourceError("nothing playable at this link")
    status = raw.get("live_status") or ("is_live" if raw.get("is_live") else "not_live")
    return SourceInfo(
        id=raw["id"],
        title=raw.get("title") or raw["id"],
        channel=raw.get("channel") or raw.get("uploader") or "",
        channel_url=raw.get("channel_url") or raw.get("uploader_url"),
        url=raw.get("webpage_url") or url,
        duration=raw.get("duration"),
        live_status=status,
        streams=[f["url"] for f in raw.get("requested_formats") or [raw] if f.get("url")],
        tags=(raw.get("tags") or [])[:8],
        offset=offset,
        published=_published(raw),
    )


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise InvalidInput("paste a full link starting with https://")
    return url


def probe(url: str, max_height: int = 720) -> SourceInfo:
    """Metadata only (one small request)."""
    opts = {**ydl_opts(), "skip_download": True,
            "format": f"bv*[height<={max_height}]+ba/best[height<={max_height}]/best"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return _info(ydl.extract_info(validate_url(url), download=False), url)
    except DownloadError as e:
        if not _is_bot_check(e):
            raise _friendly(e) from e
        first = e
    for clients in FALLBACK_CLIENTS:          # "not a bot?": try clients YouTube usually doesn't challenge
        try:
            with yt_dlp.YoutubeDL({**opts, "extractor_args": {"youtube": {"player_client": clients}}}) as ydl:
                info = _info(ydl.extract_info(url, download=False), url)
            log.info("YouTube asked for a bot check; continuing as its %s client", "/".join(clients))
            return info
        except DownloadError:
            continue
    from . import notify
    notify.bot_check(url)
    raise _friendly(first) from first


def download(url: str, out_dir: Path, section: str | None = None, chat: bool = True,
             max_height: int = 720) -> Download:
    """720p by default: plenty for a 1080x1920 reel, half the disk and decode work of 1080p."""
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **ydl_opts(),           # with the user's YouTube sign-in, like every other request
        "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/bv*[height<={max_height}]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
    }
    if chat:
        opts.update({"writesubtitles": True, "subtitleslangs": ["live_chat"]})
    offset = 0.0
    if section:
        start, end = parse_section(section)
        offset = start
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(start, end)])
        opts["force_keyframes_at_cuts"] = True
    validate_url(url)
    info, first = None, None
    # YouTube sometimes refuses a download (403) or wants a bot check: try its other clients before failing
    for clients in (None, *FALLBACK_CLIENTS):
        try:
            attempt = opts if clients is None else {**opts, "extractor_args": {"youtube": {"player_client": clients}}}
            with yt_dlp.YoutubeDL(attempt) as ydl:
                info = _info(ydl.extract_info(url, download=True), url, offset)
            if clients:
                log.info("YouTube refused the first download; it worked as its %s client", "/".join(clients))
            break
        except DownloadError as e:
            first = first or e
            low = str(e).lower()
            if not ("403" in low or "forbidden" in low or _is_bot_check(e)):
                raise _friendly(e) from e
    if info is None:
        if _is_bot_check(first):
            from . import notify
            notify.bot_check(url)
        raise _friendly(first) from first
    video = next((p for p in out_dir.glob(f"{info.id}.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
    if video is None:
        raise SourceError("download finished but no video file was written")
    chat_file = out_dir / f"{info.id}.live_chat.json"
    (out_dir / f"{info.id}.meta.json").write_text(json.dumps(info.to_meta(), indent=2), encoding="utf-8")
    return Download(video, chat_file if chat_file.exists() else None, info)


def live_chat_command(url: str, out_base: Path) -> list[str]:
    """yt-dlp subprocess that follows live chat (same interpreter, so it works on every OS)."""
    js = ["--js-runtimes", ",".join(JS_RUNTIMES)] if JS_RUNTIMES else []
    browser = cookies_browser()
    cookies = ["--cookies-from-browser", browser] if browser else []
    return [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs", "--sub-langs",
            "live_chat", "-o", str(out_base), "--quiet", *js, *cookies, url]


def channel_live_url(channel: str) -> str:
    """'@name', a channel URL, or a direct link -> a URL that resolves to the current live stream."""
    c = channel.strip().rstrip("/")
    if c.startswith("@"):
        return f"https://www.youtube.com/{c}/live"
    if "youtube.com/" in c and any(k in c for k in ("/@", "/channel/", "/c/")) and not c.endswith("/live"):
        return c + "/live"
    return c  # twitch.tv/name and kick.com/name already point at the live stream


MIN_UPLOAD_SECONDS = 90    # shorter uploads are Shorts already: nothing to cut


def channel_uploads_url(channel: str) -> str | None:
    """'@name' or a YouTube channel URL -> its Videos tab (new uploads and finished premieres).

    None for Twitch/Kick: their past broadcasts are the live streams we already clip.
    """
    c = channel.strip().rstrip("/")
    if c.startswith("@"):
        return f"https://www.youtube.com/{c}/videos"
    if "youtube.com/" in c and any(k in c for k in ("/@", "/channel/", "/c/")):
        for tab in ("/live", "/videos", "/streams", "/shorts", "/featured"):
            if c.endswith(tab):
                c = c[: -len(tab)]
        return c + "/videos"
    return None


@dataclass
class Upload:
    id: str
    url: str
    title: str
    duration: float | None


def recent_uploads(channel: str, count: int = 15) -> list[Upload]:
    """The newest few uploads of a channel, newest first, from one small listing request.

    Upcoming premieres (no length yet) and Shorts are left out.
    """
    url = channel_uploads_url(channel)
    if not url:
        return []
    opts = {**ydl_opts(), "extract_flat": "in_playlist", "playlistend": count, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False) or {}
    except DownloadError as e:
        raise _friendly(e) from e
    out = []
    for e in (raw.get("entries") or [])[:count]:
        if not e or not e.get("id") or e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        dur = e.get("duration")
        if dur is None or dur < MIN_UPLOAD_SECONDS:
            continue
        link = e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
        if not link.startswith("http"):
            link = f"https://www.youtube.com/watch?v={e['id']}"
        out.append(Upload(e["id"], link, e.get("title") or e["id"], dur))
    return out


def parse_timestamp(ts: str) -> float:
    """'1:02:03' / '62:03' / '3723' -> seconds."""
    total = 0.0
    try:
        for part in ts.strip().split(":"):
            total = total * 60 + float(part)
    except ValueError as e:
        raise InvalidInput(f"not a time: {ts!r} (use h:mm:ss)") from e
    return total


def parse_section(section: str) -> tuple[float, float]:
    """'1:00:00-2:30:00' -> (3600, 9000)."""
    if "-" not in section:
        raise InvalidInput("section must look like 1:00:00-2:30:00")
    a, b = section.split("-", 1)
    start, end = parse_timestamp(a), parse_timestamp(b)
    if end <= start:
        raise InvalidInput("section end must be after its start")
    return start, end
