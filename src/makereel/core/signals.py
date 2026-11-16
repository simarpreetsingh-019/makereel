"""Cheap per-second signals: loudness, chat activity, scene cuts. No transcription here."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from . import media

log = logging.getLogger(__name__)

SAMPLE_RATE = 8000  # Hz: plenty for loudness, tiny to stream
CHAT_HYPE = ("lol", "lmao", "omg", "no way", "clip", "wtf", "😂", "🤣", "💀", "🔥", "pog",
             "insane", "holy", "!!!", "kekw", "goat", "w ", "lets go", "let's go", "😭", "😱", "🤯",
             # other languages' chat: laughs and shouts
             "haha", "jaja", "kkkk", "mdr", "xd", "wkwk", "ㅋㅋ", "www", "草", "哈哈",
             "bhai", "op bolte", "kya baat", "arre", "balle", "oye", "waah", "😍",
             "vamos", "golazo", "nossa", "krass", "يا", "ههه", "ахах", "жесть")


def loudness(video: Path) -> np.ndarray:
    """dB per second, streamed in 1-minute blocks so a 10-hour VOD uses only a few MB."""
    proc = subprocess.Popen([media.binary("ffmpeg"), "-v", "error", "-i", str(video), "-vn", "-ac", "1",
                             "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    second = SAMPLE_RATE * 2
    out, carry = [], b""
    assert proc.stdout is not None
    while True:
        block = proc.stdout.read(second * 60)
        if not block:
            break
        block = carry + block
        n = len(block) // second
        carry = block[n * second:]
        if n:
            out.append(level_db(block[: n * second], n))
    proc.wait()
    return np.concatenate(out) if out else np.zeros(1)


def level_db(pcm: bytes, n: int) -> np.ndarray:
    """RMS level in dBFS for each of `n` equal slices of 16-bit mono PCM."""
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return 20 * np.log10(np.sqrt((a.reshape(n, -1) ** 2).mean(axis=1) + 1e-9))


def chat_weight(line: str) -> tuple[float | None, int]:
    """(offset seconds or None, weight) for one yt-dlp live_chat JSON line. Hype messages count double."""
    try:
        d = json.loads(line)
    except ValueError:
        return None, 0
    replay = d.get("replayChatItemAction", d)
    t = replay.get("videoOffsetTimeMsec")
    weight = 0
    for action in replay.get("actions", []):
        msg = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
        if not msg:
            continue
        text = "".join(r.get("text", r.get("emoji", {}).get("emojiId", ""))
                       for r in msg.get("message", {}).get("runs", [])).lower() + " "
        weight += 2 if any(h in text for h in CHAT_HYPE) else 1
    return (int(t) / 1000 if t is not None else None), weight


def chat_activity(chat_file: Path | None, n: int, offset: float = 0.0) -> np.ndarray:
    """Weighted chat messages per second from a chat replay file (zeros if there is none)."""
    act = np.zeros(n)
    if not chat_file or not Path(chat_file).exists():
        return act
    with open(chat_file, encoding="utf-8", errors="ignore") as f:
        for line in f:
            t, w = chat_weight(line)
            if t is not None and w and 0 <= int(t - offset) < n:
                act[int(t - offset)] += w
    return act


def scene_cuts(video: Path, start: float, end: float) -> list[float]:
    """Hard cuts in [start, end] via PySceneDetect (used to start clips on a fresh shot).

    Optional polish: any failure just means "no cut found".
    """
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(video), ContentDetector(threshold=27), start_time=start, end_time=end)
        return [s[0].get_seconds() for s in scenes[1:]]
    except Exception as e:  # noqa: BLE001
        log.debug("scene detection skipped: %s", e)
        return []
