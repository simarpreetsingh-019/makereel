"""Command line.

  makereel web                    the web app (http://localhost:8765)
  makereel run <link>             live stream, past stream, long video or Short (auto-detected)
  makereel local <file.mp4>       a video file you already have
  makereel rerender <folder> <reel> [--transcript TEXT] [--hook TEXT]
  makereel daemon                 24/7 without the web UI: watch channels + inbox.txt
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

from . import __version__, logs
from .config import env, load_settings
from .core.live import LiveSession
from .errors import MakereelError

log = logging.getLogger("makereel.cli")

CLIP_FLAGS = ("profile", "max_clips", "min_len", "max_len", "model", "language", "layout")


def _clip_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("reel options (override makereel.json)")
    g.add_argument("--profile", choices=["gameplay", "talk"])
    g.add_argument("--max-clips", type=int)
    g.add_argument("--min-len", type=float)
    g.add_argument("--max-len", type=float)
    g.add_argument("--model", help="speech model: tiny, base, small, medium, large-v3")
    g.add_argument("--language", help="e.g. en, hi (auto-detect if omitted)")
    g.add_argument("--layout", choices=["blur", "crop"])
    g.add_argument("--trim-silence", action="store_true", help="cut dead air (needs auto-editor)")


def _settings(a: argparse.Namespace):
    s = load_settings().with_clip(**{k: getattr(a, k) for k in CLIP_FLAGS})
    if a.trim_silence:
        s.clip["silence"] = True
    return s


def cmd_run(a: argparse.Namespace) -> None:
    from .services import runner
    result = runner.run_link(a.url, _settings(a), a.section)
    if isinstance(result, LiveSession):
        result.run()


def cmd_local(a: argparse.Namespace) -> None:
    from .services import runner
    runner.run_file(Path(a.file), _settings(a), a.title, a.credit, a.credit_url)


def cmd_rerender(a: argparse.Namespace) -> None:
    from .services import library
    library.update_reel(a.folder, a.reel, hook=a.hook, transcript=a.transcript)
    log.info("re-rendered %s/%s", a.folder, a.reel)


def cmd_web(a: argparse.Namespace) -> None:
    from .api.server import serve
    serve(a.host, a.port, a.password, not a.no_browser, a.watch)


def cmd_daemon(a: argparse.Namespace) -> None:
    from .services.jobs import JobManager
    from .services.watcher import Watcher
    watcher = Watcher(JobManager())
    watcher.start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        watcher.stop()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="makereel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"makereel {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("web", help="the web app")
    p.add_argument("--host", help="default 127.0.0.1; 0.0.0.0 to reach it from other devices")
    p.add_argument("--port", type=int)
    p.add_argument("--password", help="required off localhost (or MAKEREEL_WEB_PASSWORD)")
    p.add_argument("--watch", action="store_true", help="start watching channels right away")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_web)

    p = sub.add_parser("run", help="any link: live, past stream, video, Short")
    p.add_argument("url")
    p.add_argument("--section", help='only part of a long video, e.g. "1:00:00-2:30:00"')
    _clip_args(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("local", help="a video file you already have")
    p.add_argument("file")
    p.add_argument("--title")
    p.add_argument("--credit", help="creator name")
    p.add_argument("--credit-url", help="creator's channel link")
    _clip_args(p)
    p.set_defaults(fn=cmd_local)

    p = sub.add_parser("rerender", help="apply caption edits and burn them in again")
    p.add_argument("folder", help="folder name inside the output directory")
    p.add_argument("reel", help="e.g. reel_01")
    p.add_argument("--transcript", help="the whole caption text, corrected")
    p.add_argument("--hook", help="new on-screen title")
    p.set_defaults(fn=cmd_rerender)

    p = sub.add_parser("daemon", help="24/7 without the web UI")
    p.set_defaults(fn=cmd_daemon)
    return ap


def main(argv: list[str] | None = None) -> None:
    try:
        logs.setup(env().log_level)
        args = parser().parse_args(argv)
        args.fn(args)
    except MakereelError as e:
        log.error("✗ %s", e.message)
        if e.hint:
            log.error("  → %s", e.hint)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
