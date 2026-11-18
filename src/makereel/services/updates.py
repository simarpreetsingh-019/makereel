"""Updates from GitHub: tell the user when a new makereel release is out, and install it on request.

Releases are GitHub releases on the official repository, tagged like v0.7.0. Checking is one
small request to GitHub's public API (no account, nothing about the user is sent), at most every
few hours. Installing:
  - a git checkout (installed with `pip install -e .`): fetch the tag, check it out, reinstall;
  - otherwise: downloads the wheel attached to the release, checks it against the SHA-256 published
    next to it (like Thermo), and only then pip-installs that file.
Then the app restarts itself, but only when no reel is being made or recorded.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .. import __version__
from ..config import load_settings
from ..errors import Conflict, MakereelError

log = logging.getLogger(__name__)

CHECK_EVERY = 6 * 3600
# Updates only ever come from the official repository. It isn't a setting, so nothing in the app (or a
# web page talking to it) can point updates somewhere else. MAKEREEL_UPDATE_REPO is for testing a fork.
OFFICIAL_REPO = "simarpreetsingh-019/makereel"


def update_repo() -> str:
    return os.environ.get("MAKEREEL_UPDATE_REPO", OFFICIAL_REPO)
REPO_ROOT = Path(__file__).resolve().parents[3]       # the checkout, when installed from source
_state: dict = {"checked": 0.0, "latest": None, "error": None, "installing": False, "installed": None,
                "log": []}
_lock = threading.Lock()


def version_tuple(v: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Anything after the numbers (-beta, +local) is ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", (v or "").split("-")[0].split("+")[0])[:3]) or (0,)


def newer(latest: str, current: str = __version__) -> bool:
    return version_tuple(latest) > version_tuple(current)


def _fetch_latest(repo: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "makereel-updater"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets") or []}
    wheel = next((n for n in assets if n.startswith("makereel-") and n.endswith(".whl")), None)
    return {"version": data.get("tag_name", "").lstrip("v"), "tag": data.get("tag_name", ""),
            "notes": (data.get("body") or "")[:4000], "url": data.get("html_url"),
            "published": data.get("published_at"),
            "wheel": assets.get(wheel) if wheel else None,
            "sha256": assets.get(f"{wheel}.sha256") if wheel else None, "wheel_name": wheel}


def _download(url: str) -> bytes:
    from urllib.parse import urlparse
    if urlparse(url).hostname not in ("github.com", "objects.githubusercontent.com",
                                      "release-assets.githubusercontent.com"):
        raise MakereelError("the update file isn't hosted on GitHub; not downloading it")
    req = urllib.request.Request(url, headers={"User-Agent": "makereel-updater"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _verified_wheel(latest: dict, folder: Path) -> Path:
    """Download the release's wheel and install it only if it matches its published SHA-256."""
    import hashlib
    if not (latest.get("wheel") and latest.get("sha256")):
        raise MakereelError("this release has no verified package attached",
                            "Download it from the release page instead.")
    expected = _download(latest["sha256"]).decode("utf-8", "replace").split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise MakereelError("the release's checksum file is invalid; not installing it")
    data = _download(latest["wheel"])
    if hashlib.sha256(data).hexdigest() != expected:
        raise MakereelError("the downloaded package doesn't match its checksum; not installing it")
    _state["log"].append(f"verified {latest['wheel_name']} (sha256 {expected[:12]}…)")
    path = folder / Path(latest["wheel_name"]).name
    path.write_bytes(data)
    return path


def check(force: bool = False) -> dict:
    """What the app shows: current version, the latest release, and whether to offer an update."""
    settings = load_settings()
    repo = update_repo()
    with _lock:
        due = force or time.time() - _state["checked"] > CHECK_EVERY
        if repo and (settings["update_check"] or force) and due:
            try:
                _state["latest"], _state["error"] = _fetch_latest(repo), None
            except Exception as e:  # noqa: BLE001 - offline, no releases yet, rate limit...
                _state["error"] = "could not reach GitHub" if "urlopen" in repr(e) else str(e)[:160]
            _state["checked"] = time.time()
        latest = _state["latest"]
        return {"current": __version__, "repo": repo, "latest": latest, "error": _state["error"],
                "available": bool(latest and newer(latest["version"])), "checked": _state["checked"],
                "installing": _state["installing"], "installed": _state["installed"],
                "method": "git" if (REPO_ROOT / ".git").is_dir() else "pip", "log": _state["log"][-20:]}


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    _state["log"].append("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    _state["log"] += [l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()][-8:]
    if proc.returncode != 0:
        raise MakereelError(f"update step failed: {' '.join(cmd[:3])}…",
                            "See the update log; your current version still works.")


def install(busy: bool) -> dict:
    """Install the latest release in the background. `busy`: reels are being made or recorded."""
    info = check()
    if not info["available"]:
        raise Conflict("makereel is already up to date")
    if busy:
        raise Conflict("reels are being made or recorded right now",
                       "Update when they're done (or stop them in Jobs), so nothing is cut off.")
    with _lock:
        if _state["installing"]:
            return check()
        _state.update(installing=True, log=[], error=None)
    tag, repo = info["latest"]["tag"], info["repo"]
    if not re.fullmatch(r"v?\d+(\.\d+){0,3}", tag):   # passed to git/pip: plain version tags only
        raise MakereelError(f"the latest release has an unexpected tag {tag[:40]!r}; not installing it")

    def run() -> None:
        try:
            if info["method"] == "git":
                dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
                                       capture_output=True, text=True).stdout.strip()
                if dirty:                    # never overwrite someone's own edits to the code
                    raise MakereelError("this copy of makereel has local code changes",
                                        "Commit or stash them, then update (or run: git pull).")
                _run(["git", "fetch", "--tags", "--force", f"https://github.com/{repo}.git"], REPO_ROOT)
                _run(["git", "checkout", tag], REPO_ROOT)
                _run([sys.executable, "-m", "pip", "install", "--quiet", "-e", "."], REPO_ROOT)
            else:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    wheel = _verified_wheel(info["latest"], Path(tmp))
                    _run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", str(wheel)])
            _state["installed"] = info["latest"]["version"]
            log.info("makereel %s installed; restart to use it", tag)
        except Exception as e:  # noqa: BLE001
            _state["error"] = getattr(e, "message", str(e))
        finally:
            _state["installing"] = False

    threading.Thread(target=run, name="update", daemon=True).start()
    return check()


def restart(delay: float = 1.0) -> None:
    """Start this same command again (now running the new version) and exit this process.

    Waits `delay` seconds first, so the web request that asked for it gets its answer.
    """
    threading.Timer(delay, _restart_now).start()


def _restart_now() -> None:
    log.info("restarting makereel")
    args = [sys.executable, "-m", "makereel", *sys.argv[1:]]
    if os.name == "nt":                  # Windows: exec doesn't replace the process; start a new one
        subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        os._exit(0)
    os.execv(sys.executable, args)
