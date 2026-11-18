"""Helping the user past YouTube's "confirm you're not a bot" check.

- open YouTube in the user's own browser (the real app, not makereel's tab), so they can sign in;
- check what sign-in makereel can actually use, and say plainly what's wrong;
- accept a cookies.txt export of their YouTube sign-in, which works however the computer is locked down.
The cookies file stays in makereel's data folder (readable only by this user) and is sent only to YouTube.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

from ..core import sources
from ..errors import InvalidInput

MAX_COOKIES = 2 * 1024**2
APPS = {   # browser -> (macOS app name, Windows command, Linux commands)
    "chrome": ("Google Chrome", "chrome", ("google-chrome", "chromium")),
    "brave": ("Brave Browser", "brave", ("brave-browser", "brave")),
    "edge": ("Microsoft Edge", "msedge", ("microsoft-edge",)),
    "firefox": ("Firefox", "firefox", ("firefox",)),
    "safari": ("Safari", None, ()),
}


def open_youtube(browser: str) -> dict:
    """Open youtube.com in that browser app on this computer."""
    if browser not in APPS:
        raise InvalidInput("unknown browser")
    mac, win, linux = APPS[browser]
    url, system = "https://www.youtube.com/", platform.system()
    if system == "Darwin":
        cmd = ["open", "-a", mac, url]
    elif system == "Windows" and win:
        cmd = ["cmd", "/c", "start", "", win, url]
    else:
        exe = next((shutil.which(c) for c in linux if shutil.which(c)), None)
        if not exe:
            raise InvalidInput(f"{browser.title()} isn't installed here; open YouTube in it yourself")
        cmd = [exe, url]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise InvalidInput(f"couldn't open {browser.title()}: {e.strerror}") from e
    return {"opened": browser}


def save_cookies(data: bytes) -> dict:
    if not 0 < len(data) <= MAX_COOKIES:
        raise InvalidInput("the sign-in file is empty or too big")
    text = data.decode("utf-8", "replace")
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not lines or not all(len(l.split("\t")) >= 7 for l in lines[:20]):
        raise InvalidInput("that isn't a cookies.txt file",
                           "Export it with a 'cookies.txt' browser extension while on youtube.com.")
    if not any("youtube.com" in l.split("\t")[0] for l in lines):
        raise InvalidInput("the file has no YouTube cookies", "Export it while you're on youtube.com and signed in.")
    path = sources.cookies_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # keep only YouTube/Google cookies: the rest of the user's browsing is none of makereel's business
    keep = [l for l in text.splitlines() if l.startswith("#") or any(d in l.split("\t")[0]
                                                                     for d in ("youtube.com", "google.com"))]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return sources.check_sign_in()


def remove_cookies() -> dict:
    sources.cookies_file().unlink(missing_ok=True)
    return sources.check_sign_in()
