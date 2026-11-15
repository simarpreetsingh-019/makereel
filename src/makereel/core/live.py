"""Clip a stream while it is live, with flat disk and memory use.

- ffmpeg stream-copies the feed into 6-second .ts pieces (almost no CPU: no decoding) and
  at the same time pipes 8 kHz mono audio to us for a loudness reading every second.
- yt-dlp follows the live chat in the background; we count messages per second.
- Pieces older than `buffer_minutes` are deleted, so disk use never grows.
- Nothing is transcribed until loudness or chat jumps well above the last 3 minutes. Then the
  pieces around that moment are joined (stream copy) and sent through the normal pipeline.

Idea credit: PeakCut's rolling-buffer recorder (MIT).
"""
from __future__ import annotations

import collections
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .. import logs
from ..errors import MakereelError
from . import media, pipeline, signals, sources

log = logging.getLogger(__name__)

SEGMENT_SECS = 6                 # length of each buffer piece
BEFORE, AFTER = 30, 18           # seconds kept around a spike
JUMP = 0.6                       # 60% above the 3-minute baseline counts as a spike
MIN_GAP = 75                     # seconds between spikes
WARMUP = 90                      # seconds of baseline before spikes can fire
CHAT_BACKLOG_SECS = 45           # ignore chat for this long: yt-dlp replays old messages first


class LiveSession:
    """Records one live stream and turns spikes into reels in `out_dir`. Stop with `.stop.set()`."""

    def __init__(self, info: sources.SourceInfo, out_dir: Path, work_dir: Path, clip: dict,
                 buffer_minutes: int = 10, clips_per_hour: int = 6, max_height: int = 720):
        self.info, self.clip, self.max_height = info, clip, max_height
        self.out = out_dir
        self.buf = work_dir / f"live_{info.id}"
        self.buf.mkdir(parents=True, exist_ok=True)
        self.keep_secs = buffer_minutes * 60
        self.per_hour = clips_per_hour
        self.db: list[float] = []                  # loudness, one value per second
        self.chat: collections.Counter = collections.Counter()
        self.segments: list[tuple[Path, float, float]] = []
        self.csv_seen = 0
        self.clock = 0.0
        self.pending: list[dict] = []
        self.made: list[float] = []
        self.last_spike = -MIN_GAP
        self.stop = threading.Event()
        self.proc: subprocess.Popen | None = None

    # ------------------------------------------------------------------ stats (read by the web app)
    def stats(self) -> dict:
        return {"seconds": len(self.db), "reels": len(self.made), "chat": sum(self.chat.values())}

    # ------------------------------------------------------------------ recording
    def _record(self) -> None:
        fails = 0
        while not self.stop.is_set() and fails < 3:
            try:
                info = sources.probe(self.info.url, self.max_height)
            except MakereelError as e:
                log.warning("live check failed (%s); retrying", e.message)
                fails += 1
                self.stop.wait(15)
                continue
            if info.live_status != "is_live":
                log.info("stream is no longer live")
                break
            cmd = [media.binary("ffmpeg"), "-v", "error", "-reconnect", "1", "-reconnect_streamed", "1",
                   "-reconnect_delay_max", "10"]
            for url in info.streams:
                cmd += ["-i", url]
            audio = "1:a:0" if len(info.streams) > 1 else "0:a:0"   # live often has separate A/V feeds
            cmd += ["-map", "0:v:0", "-map", audio, "-c", "copy", "-f", "segment",
                    "-segment_time", str(SEGMENT_SECS), "-reset_timestamps", "1", "-segment_format", "mpegts",
                    "-segment_list", "list.csv", "-segment_list_type", "csv", "-segment_list_flags", "+live",
                    f"s{int(time.time())}_%06d.ts",
                    "-map", audio, "-vn", "-ac", "1", "-ar", str(signals.SAMPLE_RATE), "-f", "s16le", "pipe:1"]
            (self.buf / "list.csv").unlink(missing_ok=True)
            self.csv_seen = 0
            with open(self.buf / "ffmpeg.log", "ab") as err:
                self.proc = subprocess.Popen(cmd, cwd=self.buf, stdout=subprocess.PIPE, stderr=err)
                got, second = 0, signals.SAMPLE_RATE * 2
                assert self.proc.stdout is not None
                while True:
                    data = self.proc.stdout.read(second)
                    if len(data) < second:
                        break
                    got += 1
                    self.db.append(float(signals.level_db(data, 1)[0]))
                self.proc.wait()
            fails = 0 if got > 30 else fails + 1
        self.stop.set()

    def _follow_chat(self) -> None:
        """yt-dlp writes live chat as it arrives; count new lines against our own clock."""
        try:
            proc = subprocess.Popen(sources.live_chat_command(self.info.url, self.buf / "chat"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("live chat unavailable: %s", e)
            return
        files = [self.buf / "chat.live_chat.json.part", self.buf / "chat.live_chat.json"]
        pos, first = 0, True
        try:
            while not self.stop.is_set():
                f = next((x for x in files if x.exists()), None)
                if f:
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        if first:  # the first batch is backlog from before we joined
                            fh.seek(0, 2)
                            first = False
                        else:
                            fh.seek(pos)
                            for line in fh:
                                _, weight = signals.chat_weight(line)
                                if len(self.db) > CHAT_BACKLOG_SECS:
                                    self.chat[len(self.db)] += weight
                        pos = fh.tell()
                self.stop.wait(2)
        finally:
            proc.terminate()

    # ------------------------------------------------------------------ buffer
    def _scan(self) -> None:
        lst = self.buf / "list.csv"
        if not lst.exists():
            return
        rows = [r.split(",") for r in lst.read_text().splitlines() if r.count(",") >= 2]
        for name, a, b in (r[:3] for r in rows[self.csv_seen:]):
            dur = max(0.0, float(b) - float(a))
            self.segments.append((self.buf / name, self.clock, self.clock + dur))
            self.clock += dur
        self.csv_seen = len(rows)
        protect = min((p["t"] for p in self.pending), default=1e18) - BEFORE - 5
        while self.segments and self.segments[0][2] < min(self.clock - self.keep_secs, protect):
            self.segments.pop(0)[0].unlink(missing_ok=True)

    def _spike(self) -> None:
        n = len(self.db)
        if n < WARMUP or n - self.last_spike < MIN_GAP:
            return
        amp = 10 ** (np.array(self.db[-190:]) / 20)
        base, cur = amp[:-10].mean(), amp[-5:].mean()
        why = []
        if cur / max(base, 1e-6) - 1 >= JUMP:
            why.append("loud")
        chat = [self.chat.get(t, 0) for t in range(max(0, n - 190), n)]
        c_base, c_now = sum(chat[:-10]) / max(1, len(chat) - 10), sum(chat[-8:]) / 8
        if c_now >= max(1.5, c_base * (1 + JUMP)):
            why.append("chat")
        if why:
            self.last_spike = n
            self.pending.append({"t": float(n - 3), "why": why})
            log.info("  spike at %ds (%s)", n - 3, ", ".join(why))

    def _clip(self, spike: dict) -> None:
        hour_ago = time.time() - 3600
        self.made = [t for t in self.made if t > hour_ago]
        if len(self.made) >= self.per_hour:
            log.info("  hourly reel limit reached; skipping spike")
            return
        a, b = spike["t"] - BEFORE, spike["t"] + AFTER
        parts = [s for s in self.segments if s[2] > a and s[1] < b]
        if not parts:
            return
        win_start = int(parts[0][1])
        (self.buf / "join.txt").write_text("".join(f"file '{p[0].name}'\n" for p in parts))
        win = self.buf / f"win_{int(spike['t'])}.mp4"
        media.run([media.binary("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0",
                   "-i", "join.txt", "-c", "copy", "-bsf:a", "aac_adtstoasc", win.name], cwd=self.buf)
        try:
            chat = np.array([self.chat.get(win_start + i, 0) for i in range(int(media.duration(win)) + 1)])
            meta = {**self.info.to_meta(), "offset": float(win_start)}
            pipeline.process(win, meta, self.out, {**self.clip, "max_clips": 1}, chat_counts=chat)
            self.made.append(time.time())
        finally:
            win.unlink(missing_ok=True)

    def run(self) -> None:
        log.info("LIVE: recording '%s' (%s)", self.info.title, self.info.channel)
        logs.spawn(self._record, "live-record")
        logs.spawn(self._follow_chat, "live-chat")
        try:
            while not self.stop.is_set() or self.pending:
                self._scan()
                self._spike()
                ready = [p for p in self.pending if self.clock >= p["t"] + AFTER or self.stop.is_set()]
                for p in ready:
                    self.pending.remove(p)
                    try:
                        self._clip(p)
                    except MakereelError as e:  # keep recording even if one reel fails
                        log.error("  reel failed: %s", e.message)
                time.sleep(2)
        except KeyboardInterrupt:
            self.stop.set()
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()  # don't leave ffmpeg behind, however we stopped
            shutil.rmtree(self.buf, ignore_errors=True)
            log.info("LIVE: '%s' ended", self.info.title)
