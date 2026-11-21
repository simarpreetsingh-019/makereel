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
from ..errors import MakereelError, SourceError
from . import media, pipeline, signals, sources, transcribe

log = logging.getLogger(__name__)

SEGMENT_SECS = 6                 # length of each buffer piece
LEAD, TAIL = 20, 3               # a reel starts this long before its moment's peak, ends this long after it calms
MIN_AFTER = 12                   # ...and runs at least this long past the peak
CALM = 8                         # seconds back to normal that end a moment (it stays open while it lasts)
JUMP = 0.6                       # 60% above the 3-minute baseline counts as a spike
MIN_GAP = 75                     # seconds between spikes
WARMUP = 90                      # seconds of baseline before spikes can fire
PROBE_TIMEOUT = 90               # one "is it still live?" check may take this long before it counts as failed
STALL = 300                      # no new video for this long: finish with what we have and end the session
LANG_SURE = 0.6                  # detect a stream's language once, when at least this sure
HYPE_WORDS = 2                   # excited words heard in the last 10 s that count as a moment signal
RETRY_FOR = 600                  # keep retrying a failing live check this long before giving up
CHAT_BACKLOG_SECS = 45           # ignore chat for this long: yt-dlp replays old messages first


class LiveSession:
    """Records one live stream and turns spikes into reels in `out_dir`. Stop with `.stop.set()`."""

    def __init__(self, info: sources.SourceInfo, out_dir: Path, work_dir: Path, clip: dict, brand: dict,
                 buffer_minutes: int = 10, clips_per_hour: int = 6, max_height: int = 720):
        self.info, self.clip, self.brand, self.max_height = info, clip, brand, max_height
        self.ai: dict | None = None     # set by the runner when the AI judge is on
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
        self.language: str | None = None
        self.stream_delta: float | None = None   # seconds into the stream when recording began
        self.heard: list[dict] = []              # rough words from the live listener: {"t", "word"}
        self.proc: subprocess.Popen | None = None

    # ------------------------------------------------------------------ stats (read by the web app)
    def stats(self) -> dict:
        return {"seconds": len(self.db), "reels": len(self.made), "chat": sum(self.chat.values())}

    # ------------------------------------------------------------------ recording
    def _record(self) -> None:
        # A failed check is usually YouTube being briefly unhappy (rate limits, its bot check), not the
        # stream ending: keep trying with growing gaps for RETRY_FOR seconds. A stream that really ended
        # answers "not live", which stops at once.
        tries, empty, failing_since = 0, 0, None
        while not self.stop.is_set():
            try:
                info = self._probe()
                tries, failing_since = 0, None
            except MakereelError as e:
                failing_since = failing_since or time.time()
                waited = time.time() - failing_since
                if waited > RETRY_FOR:
                    log.warning("live check kept failing for %d min (%s); stopping", waited // 60, e.message)
                    break
                gap = min(15 * 2 ** tries, 120)
                tries += 1
                log.warning("live check failed (%s); trying again in %ds", e.message, gap)
                if e.hint and tries == 1:
                    log.warning("  %s", e.hint)
                self.stop.wait(gap)
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
            if self.stream_delta is None and info.published:
                # where this recording sits in the stream (for the "exact moment" link, and for swapping in
                # YouTube's captions after the stream); fine-tuned later by matching words
                self.stream_delta = max(0.0, time.time() - info.published - self.clock)
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
            empty = 0 if got > 30 else empty + 1
            if empty >= 3:                    # the feed opens but gives (almost) nothing, three times running
                log.warning("the stream gives no video; stopping")
                break
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
            try:
                proc.wait(10)                  # reap it (no zombie left behind)
            except subprocess.TimeoutExpired:
                proc.kill()

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
        protect = min((p["t"] for p in self.pending), default=1e18) - LEAD - 5
        while self.segments and self.segments[0][2] < min(self.clock - self.keep_secs, protect):
            self.segments.pop(0)[0].unlink(missing_ok=True)

    def _spike(self) -> None:
        n = len(self.db)
        if n < WARMUP:
            return
        amp = 10 ** (np.array(self.db[-190:]) / 20)
        cur = amp[-5:].mean()
        chat = [self.chat.get(t, 0) for t in range(max(0, n - 190), n)]
        c_now = sum(chat[-8:]) / 8
        # a moment in progress stays open while it's still louder or chattier than before it began
        hype = self._recent_hype(n)
        for p in self.pending:
            if cur > p["base"] * (1 + JUMP / 2) or c_now >= max(1.0, p["cbase"] * 1.5) or hype >= HYPE_WORDS:
                p["last"] = float(n)
        if self.pending or n - self.last_spike < MIN_GAP:
            return
        base = amp[:-10].mean()
        why = []
        if cur / max(base, 1e-6) - 1 >= JUMP:
            why.append("loud")
        if hype >= HYPE_WORDS:
            why.append("hype words")
        c_base = sum(chat[:-10]) / max(1, len(chat) - 10)
        if c_now >= max(1.5, c_base * (1 + JUMP)):
            why.append("chat")
        if why:
            self.last_spike = n
            t = float(n - 3)
            self.pending.append({"t": t, "why": why, "base": base, "cbase": c_base, "last": t})
            log.info("  spike at %ds (%s)", n - 3, ", ".join(why))

    def _moment_over(self, p: dict) -> bool:
        """True once the moment has calmed down (or hit the longest-reel limit) and its end is recorded."""
        n, longest = len(self.db), float(self.clip.get("max_len", 180))
        calmed = n - p["last"] >= CALM and n - p["t"] >= MIN_AFTER
        too_long = n - (p["t"] - LEAD) >= longest
        end = min(max(p["last"], p["t"] + MIN_AFTER) + TAIL, p["t"] - LEAD + longest)
        if self.stop.is_set():
            return True                    # stopping: make the reel from whatever was recorded
        return (calmed or too_long) and self.clock >= end

    def _clip(self, spike: dict) -> None:
        hour_ago = time.time() - 3600
        self.made = [t for t in self.made if t > hour_ago]
        if len(self.made) >= self.per_hour:
            log.info("  hourly reel limit reached; skipping spike")
            return
        longest = float(self.clip.get("max_len", 180))
        a = spike["t"] - LEAD
        b = min(max(spike.get("last", spike["t"]), spike["t"] + MIN_AFTER) + TAIL, a + longest)
        log.info("  moment %ds-%ds (%ds) ready", a, b, b - a)
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
            meta = {**self.info.to_meta(), "offset": float(win_start) + (self.stream_delta or 0.0)}
            clip = {**self.clip, "max_clips": 1, "language": self._language(win) or self.clip.get("language")}
            reels = pipeline.process(win, meta, self.out, clip, self.brand, chat_counts=chat, ai=self.ai)
            self.made.append(time.time())
            if reels:
                from . import notify
                notify.reel_ready(self.info.title, reels[0].get("hook", ""))
        finally:
            win.unlink(missing_ok=True)

    def _probe(self) -> sources.SourceInfo:
        """sources.probe with a time limit: a request YouTube leaves hanging must not freeze the session."""
        box: dict = {}

        def call() -> None:
            try:
                box["info"] = sources.probe(self.info.url, self.max_height)
            except Exception as e:  # noqa: BLE001
                box["error"] = e
        t = threading.Thread(target=call, name="live-probe", daemon=True)
        t.start()
        t.join(PROBE_TIMEOUT)
        if t.is_alive():
            raise SourceError(f"YouTube didn't answer within {PROBE_TIMEOUT}s")
        if "error" in box:
            e = box["error"]
            raise e if isinstance(e, MakereelError) else SourceError(str(e)[:200])
        return box["info"]

    def _language(self, win: Path) -> str | None:
        """The stream's language, decided once: from its folder if a past session knew it, else detected
        on the first reel when sure. Guessing per reel from gameplay noise flips between languages."""
        if self.language is None:
            self.language = pipeline.folder_language(self.out) or None
        if self.language is None and self.clip.get("language"):
            self.language = self.clip["language"]
        if self.language is None:
            try:
                n = media.duration(win)
                windows = [(s, min(n, s + 30)) for s in (0, n / 3, 2 * n / 3)]
                lang, prob = transcribe.detect_language(win, windows, self.clip["model"])
                if lang and prob >= LANG_SURE:
                    self.language = lang
                    log.info("  stream language: %s (%.0f%% sure); used for every reel", lang, prob * 100)
            except MakereelError as e:
                log.warning("  language detection skipped: %s", e.message)
        return self.language

    # ------------------------------------------------------------------ live listener (rough words)
    def _listener_model(self) -> str | None:
        """A tiny model to hear every piece: Hinglish lite (Hindi streams) or base, if already downloaded.
        Off in Cool-and-quiet mode or when switched off, to spare the CPU."""
        from . import models
        if not self.clip.get("live_words", True) or media.cpu_mode() == "quiet":
            return None
        for name in (("hinglish-lite", "base") if (self.clip.get("language") or "hi") == "hi" else ("base",)):
            if models.installed(name):
                return name
        return None

    def _listen(self) -> None:
        """Rough words for every new piece, from a small separate model (1 thread, never the main one)."""
        from faster_whisper import WhisperModel

        from . import models
        name = self._listener_model()
        try:
            model = WhisperModel(models.source(name), device="cpu", compute_type="int8", cpu_threads=1)
        except Exception as e:  # noqa: BLE001
            log.warning("  live listener unavailable (%s)", str(e)[:100])
            return
        lang = "en" if name in models.HINGLISH else self.clip.get("language")
        heard_pieces: set[str] = set()          # by name: old pieces leave the front of the list
        while not self.stop.is_set():
            pieces = [p for p in list(self.segments) if p[0].name not in heard_pieces]
            if not pieces:
                self.stop.wait(2)
                continue
            for path, t0, _t1 in pieces:
                heard_pieces.add(path.name)
                try:
                    audio = transcribe._pcm(path, 0.0, 7.0)
                    segs, _ = model.transcribe(audio, language=lang, beam_size=1, vad_filter=True,
                                               condition_on_previous_text=False)
                    self.heard += [{"t": t0 + float(s.start), "word": w} for s in segs for w in s.text.split()]
                except Exception:  # noqa: BLE001 - a piece already deleted, or unreadable: skip it
                    continue
            self.heard = self.heard[-2000:]

    def _recent_hype(self, n: int) -> int:
        from .highlights import hype_count
        recent = [{"word": w["word"]} for w in self.heard if w["t"] >= n - 10]
        return hype_count(recent) if recent else 0

    def _clear_leftovers(self) -> None:
        """Pieces left by an earlier session of this stream that didn't end cleanly (makereel was closed
        or restarted mid-stream). Only one session records a stream at a time, so they're unused."""
        stale = [f for f in self.buf.iterdir() if f.is_file()] if self.buf.is_dir() else []
        for f in stale:
            f.unlink(missing_ok=True)
        if stale:
            log.info("  cleared %d leftover buffer files from an earlier session", len(stale))

    def run(self) -> None:
        log.info("LIVE: recording '%s' (%s)", self.info.title, self.info.channel)
        self._clear_leftovers()
        logs.spawn(self._record, "live-record")
        logs.spawn(self._follow_chat, "live-chat")
        if self._listener_model():
            logs.spawn(self._listen, "live-listen")
        try:
            last_growth, last_clock = time.time(), self.clock
            while not self.stop.is_set() or self.pending:
                self._scan()
                if self.clock > last_clock:
                    last_growth, last_clock = time.time(), self.clock
                elif not self.stop.is_set() and time.time() - last_growth > STALL:
                    log.warning("  no new video for %d min; finishing with what was recorded", STALL // 60)
                    self.stop.set()             # pending moments are made from what's there, then we end
                self._spike()
                ready = [p for p in self.pending if self._moment_over(p)]
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
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            shutil.rmtree(self.buf, ignore_errors=True)
            log.info("LIVE: '%s' ended", self.info.title)
