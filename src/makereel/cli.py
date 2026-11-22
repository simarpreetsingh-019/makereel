"""Command line.

  makereel start                  set up the first time, then open makereel in your browser
  makereel status                 what's installed, running and recording, and the space it uses
  makereel help                   the everyday commands, with examples
  makereel web                    the web app (http://localhost:8765)
  makereel run <link>             live stream, past stream, long video or Short (auto-detected)
  makereel local <file.mp4>       a video file you already have
  makereel rerender <folder> <reel> [--transcript TEXT] [--hook TEXT] [--offset S] [--sync]
  makereel export <folder> <reel> --format 4x5|1x1|16x9|9x16 [--fit blur|crop|pad|track|split]
  makereel bench [--video LINK_OR_FILE] [--model base]   speed, CPU, RAM and disk on this device
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

CLIP_FLAGS = ("profile", "max_clips", "min_len", "max_len", "model", "model_other", "language", "layout", "fps")


def _clip_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("reel options (override makereel.json)")
    g.add_argument("--profile", choices=["gameplay", "talk"])
    g.add_argument("--max-clips", type=int)
    g.add_argument("--min-len", type=float)
    g.add_argument("--max-len", type=float)
    g.add_argument("--model", help="speech model for English: tiny, base, small, medium, distil-large-v3, large-v3, parakeet")
    g.add_argument("--language", help="e.g. en, hi, pa (auto-detected once per video if omitted)")
    g.add_argument("--fps", type=int, choices=(30, 60), help="60 keeps smooth motion from 60 fps sources")
    g.add_argument("--model-other", dest="model_other", choices=("same", "small", "medium", "large-v3", "hinglish", "hinglish-lite", "indic-hi"),
                   help="speech model for Hindi and other languages (used when it's bigger than --model, "
                        "or --model is English-only)")
    g.add_argument("--layout", choices=["auto", "blur", "crop", "pad", "track", "split"])
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
    if a.sync:
        library.autosync(a.folder, a.reel)
    if a.hook or a.transcript or a.offset or not a.sync:
        library.update_reel(a.folder, a.reel, hook=a.hook, transcript=a.transcript, offset=a.offset)
    log.info("re-rendered %s/%s", a.folder, a.reel)


def cmd_export(a: argparse.Namespace) -> None:
    from .services import library
    reel = library.export_reel(a.folder, a.reel, a.format, a.fit)
    log.info("exported %s/%s as %s", a.folder, a.reel, a.format)
    log.debug("%s", reel["exports"])


def cmd_bench(a: argparse.Namespace) -> None:
    from .services import bench
    result = bench.run(a.video, a.model)
    print("\n" + bench.report_markdown(result))
    diff = bench.compare(result)
    if diff:
        print(f"vs previous run (v{diff['against_version']}): time {diff['wall_pct']:+}% · "
              f"CPU {diff['cpu_seconds_pct']:+}% · RAM {diff['ram_peak_pct']:+}%  (negative = better)")
    url = bench.share_url(result)
    print(f"\nShare it (optional, you review before posting): {url}" if url
          else "\nTo share: copy the table above into an issue or PR on the project's repository.")


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
    sub = ap.add_subparsers(dest="command")
    from . import cli_easy

    p = sub.add_parser("start", help="set up (first time) and open makereel in your browser")
    p.add_argument("--port", type=int)
    p.add_argument("--yes", action="store_true", help="accept the suggested setup without asking")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cli_easy.cmd_start)

    p = sub.add_parser("status", help="what's installed, running and recording")
    p.set_defaults(fn=cli_easy.cmd_status)

    p = sub.add_parser("update", aliases=["upgrade"], help="get the latest version from GitHub")
    p.add_argument("--port", type=int)
    p.set_defaults(fn=cli_easy.cmd_update)

    p = sub.add_parser("signin", help="use a YouTube sign-in file (cookies.txt), or check the sign-in")
    p.add_argument("file", nargs="?", help="cookies.txt exported from youtube.com")
    p.add_argument("--remove", action="store_true", help="stop using the sign-in file")
    p.set_defaults(fn=cli_easy.cmd_signin)

    p = sub.add_parser("gpu", help="use an NVIDIA GPU for speech (installs NVIDIA's libraries)")
    p.set_defaults(fn=cli_easy.cmd_gpu)

    p = sub.add_parser("help", help="the everyday commands, with examples")
    p.set_defaults(fn=cli_easy.cmd_help)

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
    p.add_argument("--offset", type=float, help="move captions earlier (-0.3) or later (0.3), in seconds")
    p.add_argument("--sync", action="store_true", help="re-time captions from the reel's own audio")
    p.set_defaults(fn=cmd_rerender)

    p = sub.add_parser("export", help="the same reel in another shape")
    p.add_argument("folder")
    p.add_argument("reel")
    p.add_argument("--format", required=True, choices=["9x16", "4x5", "1x1", "16x9"])
    p.add_argument("--fit", choices=["blur", "crop", "pad", "track", "split"])
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("bench", help="benchmark this device")
    p.add_argument("--video", help="a link or file (default: a fixed 19-second test video)")
    p.add_argument("--model", help="speech model to test (default: from settings)")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("daemon", help="24/7 without the web UI")
    p.set_defaults(fn=cmd_daemon)
    return ap


def main(argv: list[str] | None = None) -> None:
    try:
        logs.setup(env().log_level)
        args = parser().parse_args(argv)
        if not getattr(args, "fn", None):          # plain `makereel`: show the friendly help
            from .cli_easy import cmd_help
            cmd_help(args)
            return
        args.fn(args)
    except MakereelError as e:
        log.error("✗ %s", e.message)
        if e.hint:
            log.error("  → %s", e.hint)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
