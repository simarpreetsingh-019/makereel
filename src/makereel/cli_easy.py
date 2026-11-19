"""The friendly commands: `makereel start`, `makereel status` and `makereel help`.

start   one command for everything: checks the tools, sets up speech models the first time (asking who
        you clip and suggesting models for this computer), then opens makereel in the browser.
status  what's installed, running and recording, and how much space it takes, with a fix for each problem.
help    the commands people actually use, with examples.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request

from . import __version__
from .config import env, load_settings, save_settings

OK, WARN, BAD = "✓", "!", "✗"


def _say(mark: str, text: str, fix: str | None = None) -> None:
    print(f"  {mark} {text}")
    if fix:
        print(f"      → {fix}")


def _ask(question: str, default: str, yes: bool) -> str:
    if yes or not sys.stdin.isatty():
        return default
    try:
        answer = input(f"{question} ").strip()
    except EOFError:
        return default
    return answer or default


def _running(port: int) -> dict | None:
    """The running makereel's jobs (via its local API), or None if it isn't running."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/jobs", timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 - not running (or not reachable)
        return None


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


# --------------------------------------------------------------------------- checks shared by start/status
def check_tools() -> bool:
    """Print ffmpeg / Node / GPU checks. False when makereel can't make reels yet."""
    from .core import media, models, sources
    good = True
    try:
        ff = media.binary("ffmpeg")
        if media.system_info().get("libass"):
            _say(OK, f"ffmpeg with captions ({ff})")
        else:
            good = False
            _say(BAD, "ffmpeg can't draw captions", "install the full build: macOS `brew install ffmpeg-full` · "
                 "Windows `winget install Gyan.FFmpeg` · Linux `sudo apt install ffmpeg`")
    except Exception:  # noqa: BLE001
        good = False
        _say(BAD, "ffmpeg isn't installed", "run the makereel installer again, or install ffmpeg (see above)")
    if sources.JS_RUNTIMES:
        _say(OK, f"YouTube support ({', '.join(sources.JS_RUNTIMES)})")
    else:
        _say(WARN, "Node.js isn't installed: some YouTube videos won't download",
             "macOS `brew install node` · Windows `winget install OpenJS.NodeJS.LTS` · Linux `sudo apt install nodejs`")
    gpu = models.nvidia_gpu()
    if gpu:
        ready = models.cuda_ready()
        _say(OK if ready else WARN, f"NVIDIA {gpu['name']} ({gpu['vram_gb']} GB)"
             + (": speech runs on it" if ready else ""),
             None if ready else "its CUDA libraries aren't installed, so speech uses the CPU: run `makereel gpu`")
    return good


# --------------------------------------------------------------------------- start
def _setup_models(yes: bool) -> None:
    from .core import models
    print("\nFirst run: let's pick speech models for this computer.")
    pick = _ask("Who do you clip?  1) English streamers  2) Indian streamers (Hindi, Hinglish…)  3) Both  [3]",
                "3", yes)
    focus = {"1": "english", "2": "indian"}.get(pick, "both")
    pc = models.computer()
    rec = models.recommend(pc, focus)
    print(f"\n  This computer: {pc['ram_gb']:g} GB memory, {pc['cores']} cores, "
          f"{pc['gpu']['name'] if pc['gpu'] else 'no NVIDIA GPU'}, {pc['free_disk_gb']:g} GB free.")
    print(f"  Suggested: {models.CATALOG[rec['model']]['label']} for English, "
          f"{models.CATALOG[rec['model_other']]['label']} for Hindi and others ({rec['why']}).")
    if rec["download_gb"]:
        print(f"  Download: {rec['download_gb']:g} GB, once.")
    if _ask("Use these? [Y/n]", "y", yes).lower().startswith("n"):
        print("  Keeping the current models. Change them any time in the app: System → Speech models.")
        save_settings({"setup_done": True})
        return
    for name in dict.fromkeys((rec["model"], rec["model_other"])):
        st = models.download(name)
        while st["state"] == "downloading":
            print(f"\r  Downloading {name}… {st.get('percent', 0)}%   ", end="", flush=True)
            time.sleep(1.5)
            st = models.status(name)
        print(f"\r  {name}: {'ready' if st['state'] == 'done' else st.get('error', st['state'])}            ")
        if st["state"] != "done":
            print("  Download failed. makereel will download it on first use instead.")
    save_settings({"clip": {"model": rec["model"], "model_other": rec["model_other"]},
                   "speech_device": "auto", "setup_done": True})
    print("  Speech models set.")


def offer_gpu(yes: bool) -> None:
    """NVIDIA GPU but no CUDA libraries: offer the one-time download that makes speech run on the GPU."""
    from .core import gpu, models
    if not models.gpu_needs_libs():
        return
    g = models.nvidia_gpu()
    print(f"\nYour {g['name']} can make speech recognition several times faster.")
    print(f"  It needs NVIDIA's CUDA libraries: about {gpu.DOWNLOAD_GB} GB, downloaded once.")
    if _ask("Install them now? [Y/n]", "y", yes).lower().startswith("n"):
        print("  Skipped. Speech uses the CPU. Run `makereel gpu` any time to add them.")
        return
    if gpu.install_libs():
        print("  ✓ GPU ready: speech runs on your NVIDIA GPU.")
    else:
        print("  ✗ The GPU libraries didn't install or load; speech uses the CPU. `makereel gpu` to try again.")


def cmd_gpu(a) -> None:
    from .core import gpu, models
    if models.nvidia_gpu() is None:
        print("No NVIDIA GPU found here. Speech runs on the CPU (on Macs that's the normal, fast path).")
        return
    if gpu.libs_ok():
        print("✓ NVIDIA GPU libraries are installed; speech runs on the GPU.")
        return
    offer_gpu(yes=True)


# --------------------------------------------------------------------------- YouTube sign-in file
def cmd_signin(a) -> None:
    """Use a cookies.txt export as makereel's YouTube sign-in (or remove it with --remove)."""
    from pathlib import Path

    from .core import sources
    from .services import youtube
    if a.remove:
        print(youtube.remove_cookies()["message"])
        return
    if not a.file:
        st = sources.check_sign_in()
        print(("✓ " if st["ok"] else "! ") + st["message"])
        print("\nTo add a sign-in file: export cookies.txt from youtube.com with a 'Get cookies.txt LOCALLY' "
              "browser extension, then run: makereel signin cookies.txt")
        return
    path = Path(a.file).expanduser()
    if not path.is_file():
        print(f"No file at {path}")
        sys.exit(1)
    st = youtube.save_cookies(path.read_bytes())
    print(("✓ " if st["ok"] else "! ") + st["message"])
    print("  Only the YouTube and Google lines were kept, in makereel's own folder. You can delete the exported file.")


# --------------------------------------------------------------------------- update
UPDATE_SOURCE = "makereel @ https://github.com/simarpreetsingh-019/makereel/archive/refs/heads/main.zip"


def cmd_update(a) -> None:
    """Install the latest makereel from GitHub over this one (settings, reels and models are kept)."""
    import os
    import platform
    import subprocess
    from pathlib import Path

    from .core import gpu, models
    print(f"makereel {__version__}: updating to the latest version from GitHub…")
    here = Path(__file__).resolve()
    if any((p / ".git").is_dir() for p in here.parents):
        print("This is a developer copy (a git checkout). Update it with: git pull")
        return
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"))
    if not Path(uv).exists():
        print("uv isn't installed, so update by running the installer again (see the README).")
        sys.exit(1)
    if _running(a.port or env().port) is not None:
        print("makereel is running. Close it first (Ctrl+C in its window), then run `makereel update` again.")
        sys.exit(1)
    cmd = [uv, "tool", "install", "--force", "--reinstall", "--python", "3.12"]
    if models.nvidia_gpu() is not None or gpu.libs_ok():
        print("  NVIDIA GPU: including its speech libraries.")
        cmd += ["--with", "nvidia-cublas-cu12", "--with", "nvidia-cudnn-cu12>=9,<10"]
    cmd.append(UPDATE_SOURCE)
    if platform.system() == "Windows":
        # Windows can't replace makereel.exe while it runs (and this is makereel.exe). A small script waits for
        # this process to end, updates, then says how it went, in its own window.
        import tempfile
        quoted = " ".join("'" + c.replace("'", "''") + "'" for c in cmd)
        ps1 = Path(tempfile.gettempdir()) / "makereel-update.ps1"
        ps1.write_text("\n".join([
            f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue",
            "Write-Host 'Updating makereel...'",
            f"& {quoted}",
            "if ($LASTEXITCODE -eq 0) { Write-Host 'makereel is up to date. Start it with: makereel start' "
            "-ForegroundColor Green } else { Write-Host 'The update failed: run the installer again.' "
            "-ForegroundColor Red }",
            "if (-not $env:MAKEREEL_UPDATE_NO_WAIT) { Read-Host 'Press Enter to close' }",
            "exit $LASTEXITCODE",
        ]), encoding="utf-8")
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]
        if os.environ.get("MAKEREEL_UPDATE_NO_WAIT"):     # tests: run it here and now, no extra window
            sys.exit(subprocess.run(args).returncode)
        subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        print("The update continues in a new window (makereel has to close first).")
        return
    if subprocess.run(cmd).returncode != 0:
        print("\nThe update failed. Run the installer again (see the README).")
        sys.exit(1)
    new = subprocess.run([shutil.which("makereel") or "makereel", "--version"], capture_output=True, text=True)
    print(f"\n✓ Updated: {new.stdout.strip() or 'done'}. Start it with: makereel start")


def cmd_start(a) -> None:
    import webbrowser
    port = a.port or env().port
    print(f"makereel {__version__}")
    if _running(port) is not None:
        print(f"makereel is already running: opening http://localhost:{port}")
        webbrowser.open(f"http://localhost:{port}")
        return
    print("\nChecking this computer:")
    if not check_tools():
        print("\nFix the item marked ✗ above, then run `makereel start` again.")
        sys.exit(1)
    offer_gpu(a.yes)
    if not load_settings()["setup_done"]:
        _setup_models(a.yes)
    print(f"\nStarting makereel at http://localhost:{port}  (leave this window open; Ctrl+C to stop)\n")
    from .api.server import serve
    serve(port=port, open_browser=not a.no_browser)


# --------------------------------------------------------------------------- status
def cmd_status(a) -> None:
    from .core import models, sources
    from .services import storage, updates
    port = env().port
    settings = load_settings()
    print(f"makereel {__version__}")
    info = updates.check()
    if info.get("available"):
        _say(WARN, f"version {info['latest']['version']} is available", "update in the app: System → Updates")
    elif info.get("latest"):
        _say(OK, "up to date")

    print("\nRunning")
    jobs = _running(port)
    if jobs is None:
        _say(WARN, "makereel isn't running", "start it with `makereel start`")
    else:
        jobs = jobs.get("jobs", jobs)
        _say(OK, f"makereel is running at http://localhost:{port}")
        live = [j for j in jobs if j["status"] == "live" and j["kind"] != "watcher"]
        watching = any(j["kind"] == "watcher" and j["status"] == "live" for j in jobs)
        _say(OK if watching else WARN, "watching channels" if watching else "not watching channels",
             None if watching else "turn it on in Settings, if you want 24/7 clipping")
        for j in live:
            lv = j.get("live") or {}
            stuck = any(w in (j.get("last_line") or "").lower() for w in ("not a bot", "confirm you"))
            _say(BAD if stuck else OK, f"recording: {j['title'][:60]} · {lv.get('seconds', 0) // 60} min · "
                 f"{j.get('reels', 0)} reels", "YouTube wants a sign-in: Settings → Test sign-in" if stuck else None)
        busy = [j for j in jobs if j["status"] in ("running", "queued")]
        if busy:
            _say(OK, f"{len(busy)} job(s) making reels")

    print("\nThis computer")
    from .core import sysmon
    sysmon.snapshot()
    time.sleep(1)
    ld = sysmon.snapshot()
    _say(OK if ld["cpu"] < 80 else WARN, f"CPU {ld['cpu']:.0f}% in use · memory {ld['ram_used']:.0f}%")
    if ld["temp"] is not None:
        mark = {"normal": OK, "warm": WARN, "hot": BAD}[ld["heat"]]
        _say(mark, f"CPU temperature {ld['temp']:.0f} °C ({ld['heat']})",
             "Settings → Processing → Cool and quiet, or fewer reels per hour" if ld["heat"] == "hot" else None)

    print("\nTools")
    check_tools()

    print("\nSpeech models")
    clip = settings.clip
    for role, name in (("English", clip["model"]), ("Hindi and others", clip["model_other"])):
        if name in models.CATALOG:
            ok = models.installed(name)
            _say(OK if ok else WARN, f"{role}: {name}{'' if ok else ' (downloads on first use)'}")
        else:
            _say(OK, f"{role}: {name}")
    if not settings["setup_done"]:
        _say(WARN, "setup not finished", "run `makereel start`, or System → Speech models in the app")

    print("\nYouTube sign-in")
    sign = sources.check_sign_in()
    _say(OK if sign["ok"] else (BAD if sign.get("blocked") else WARN), sign["message"])

    print("\nFiles")
    st = storage.info()
    _say(OK, f"reels: {st['reels_folder']} ({_gb(st['reels_bytes'])})")
    _say(OK, f"cache: {st['work_folder']} ({_gb(st['cache_bytes'])})",
         "clear it in the app: Settings → Clear cache" if st["cache_bytes"] > 2e9 else None)
    free = st["free_bytes"]
    _say(OK if free > 5e9 else WARN, f"{_gb(free)} free on this disk",
         None if free > 5e9 else "running low: clear the cache or move reels to another drive")
    if shutil.which("makereel") is None and sys.prefix == sys.base_prefix:   # not a developer's venv
        _say(WARN, "the `makereel` command isn't on your PATH", "open a new terminal window after installing")


# --------------------------------------------------------------------------- help
HELP = """makereel: turn live streams and videos into captioned reels.

Everyday
  makereel start                 set up (first time) and open makereel in your browser
  makereel status                what's installed, running and recording, and how much space it uses
  makereel update                get the latest version from GitHub (keeps settings, reels and models)
  makereel gpu                   use an NVIDIA GPU for speech (one-time download of NVIDIA's libraries)
  makereel signin cookies.txt    use a YouTube sign-in file (fixes "confirm you're not a bot"); no file: check it
  makereel help                  this list

Make reels from the terminal
  makereel run "<link>"          any link: a live stream is clipped as it happens, anything else right away
  makereel run "<link>" --language hi          say the spoken language (saves time; en, hi, pa, es…)
  makereel run "<long video>" --section "1:00:00-2:30:00"
  makereel local video.mp4 --credit "Name" --credit-url "https://youtube.com/@name"

Edit and export
  makereel rerender "<folder>" reel_01 --transcript "fixed caption text…"   (or --sync, --offset -0.2)
  makereel export "<folder>" reel_01 --format 4x5

Other
  makereel web                   the app only, without the first-run checks
  makereel daemon                24/7 channel watching without the app
  makereel bench                 measure speed, CPU, memory and disk on this computer
  makereel --version

Each command has more options: makereel <command> --help
Guide: https://github.com/simarpreetsingh-019/makereel/blob/main/docs/GETTING_STARTED.md
"""


def cmd_help(a) -> None:
    print(HELP)
