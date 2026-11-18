"""End-to-end live-stream test against a fake live stream served from this computer (no YouTube).

ffmpeg plays a talking clip on a loop, in real time, as an HLS live stream (the format YouTube uses),
with a loud burst every 40 s. A real LiveSession records it and must:
  - make reels from the loud moments,
  - survive "Sign in to confirm you're not a bot" failures of the live check midway,
  - keep its rolling buffer at the size limit instead of growing,
  - stop cleanly and delete its buffer.
Slow (about 4 minutes), so it only runs with MAKEREEL_LIVE_E2E=1 and a clip in MAKEREEL_LIVE_CLIP.
"""
import functools
import http.server
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from makereel.config import load_settings
from makereel.core import live, media, sources
from makereel.errors import SourceError

CLIP = os.environ.get("MAKEREEL_LIVE_CLIP", "")
pytestmark = pytest.mark.skipif(os.environ.get("MAKEREEL_LIVE_E2E") != "1" or not Path(CLIP).is_file(),
                                reason="set MAKEREEL_LIVE_E2E=1 and MAKEREEL_LIVE_CLIP=<a talking clip>")


@pytest.fixture
def fake_live(tmp_path):
    hls = tmp_path / "hls"
    hls.mkdir()
    # loop forever, in real time, 4x louder for 3 s every 40 s: a "moment" the session should clip
    ff = subprocess.Popen([
        media.binary("ffmpeg"), "-v", "error", "-re", "-stream_loop", "-1", "-i", CLIP,
        "-af", "volume='if(lt(mod(t,40),3),4,0.35)':eval=frame", "-c:v", "libx264", "-preset", "ultrafast",
        "-g", "60", "-c:a", "aac", "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments", str(hls / "live.m3u8")])
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=str(hls))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for _ in range(40):
        if (hls / "live.m3u8").exists():
            break
        time.sleep(0.5)
    yield f"http://127.0.0.1:{httpd.server_address[1]}/live.m3u8"
    ff.terminate()
    httpd.shutdown()


def test_live_session_end_to_end(tmp_path, fake_live, monkeypatch):
    info = sources.SourceInfo(id="fakelive", title="Fake live", channel="Test", channel_url=None,
                              url="https://example.invalid/live", duration=None, live_status="is_live",
                              streams=[fake_live])
    calls = {"n": 0}

    def probe(url, max_height=720):
        calls["n"] += 1
        if calls["n"] in (2, 3):          # YouTube's bot check, twice in a row, after the first recording
            raise SourceError("Sign in to confirm you're not a bot", "use your browser sign-in")
        return info

    monkeypatch.setattr(sources, "probe", probe)
    monkeypatch.setattr(live.sources, "live_chat_command", lambda url, out: ["true"])   # no chat here
    monkeypatch.setattr(live, "WARMUP", 30)
    monkeypatch.setattr(live, "MIN_GAP", 35)
    settings = load_settings()
    out, work = tmp_path / "out", tmp_path / "work"
    session = live.LiveSession(info, out, work, {**settings.clip, "model": "base"}, settings.brand,
                               buffer_minutes=1, clips_per_hour=10)
    session.keep_secs = 60
    runner = threading.Thread(target=session.run, daemon=True)
    runner.start()

    # first recording ends after ~20 s of feed: force a reconnect so the live check runs again
    time.sleep(25)
    if session.proc and session.proc.poll() is None:
        session.proc.terminate()

    deadline, peak = time.time() + 300, 0
    while time.time() < deadline and len(session.made) < 2:
        peak = max(peak, sum(1 for f in session.buf.glob("*.ts")))
        time.sleep(3)
    session.stop.set()
    runner.join(120)

    reels = sorted(out.glob("reel_*[0-9].mp4"))
    assert len(reels) >= 2, f"expected reels from the loud moments, got {len(reels)}"
    assert calls["n"] >= 4, "the session should have kept going after the bot-check failures"
    # 60 s kept + the window around a pending moment (30 s before, 18 after) in 6 s pieces, plus slack
    assert peak <= 25, f"buffer grew to {peak} pieces; old ones aren't being deleted"
    assert not session.buf.exists(), "the buffer folder should be deleted when the session ends"
    assert not runner.is_alive()
