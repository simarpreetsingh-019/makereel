"""Desktop notifications for things that need the user while makereel works in the background.

Used when YouTube stops makereel with its "confirm you're not a bot" check, so the user hears about it
even if the makereel tab isn't open. At most one notification per kind every 15 minutes.
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import time

log = logging.getLogger(__name__)
QUIET_FOR = 15 * 60
_last: dict[str, float] = {}


def send(kind: str, title: str, message: str) -> bool:
    now = time.time()
    if now - _last.get(kind, 0) < QUIET_FOR:
        return False
    _last[kind] = now
    title, message = title.replace('"', "'")[:80], message.replace('"', "'")[:200]
    system = platform.system()
    try:
        if system == "Darwin":
            cmd = ["osascript", "-e", f'display notification "{message}" with title "{title}" sound name "Ping"']
        elif system == "Windows":
            ps = ("Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                  f'$n.ShowBalloonTip(10000, "{title}", "{message}", "Info"); Start-Sleep 11; $n.Dispose()')
            cmd = ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps]
        elif shutil.which("notify-send"):
            cmd = ["notify-send", title, message]
        else:
            return False
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.debug("notification failed: %s", e)
        return False


def bot_check(url: str) -> None:
    send("bot", "makereel: YouTube wants a sign-in",
         "YouTube is asking makereel to prove it isn't a bot. Open makereel → Settings to fix it; "
         "recording retries on its own.")
