"""Word-level speech to text, only for the stretches we might clip.

faster-whisper (CTranslate2, int8) keeps memory low: ~150 MB for `base`, ~500 MB for `small`.
The model loads on first use and is released after a quiet spell (`release_if_idle`), so a
24/7 install doesn't sit on RAM between streams.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from pathlib import Path

import numpy as np

from ..config import env
from ..errors import MediaError
from . import media

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None
_model_name: str | None = None
_last_used = 0.0


def _get(size: str):
    global _model, _model_name, _last_used
    if _model is None or _model_name != size:
        from faster_whisper import WhisperModel
        log.info("loading speech model '%s' (first use downloads it)", size)
        try:
            _model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=env().threads)
        except Exception as e:  # noqa: BLE001 - network / disk / bad name
            raise MediaError(f"could not load speech model '{size}': {e}") from e
        _model_name = size
    _last_used = time.time()
    return _model


def release_if_idle(seconds: float = 600) -> None:
    global _model
    with _lock:
        if _model is not None and time.time() - _last_used > seconds:
            _model = None
            gc.collect()
            log.debug("speech model released")


def words_in(video: Path, start: float, end: float, size: str = "base",
             language: str | None = None, precise: bool = False) -> list[dict]:
    """Transcribe [start, end] of a file; word times are on the file's clock.

    precise=True is for syncing captions on a finished reel: a wider beam search for better
    words and word timings. It costs a little more, but reels are short.
    """
    pcm = media.run([media.binary("ffmpeg"), "-v", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                     "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture=True)
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if len(audio) < 16000:  # under a second: nothing worth transcribing
        return []
    with _lock:
        segments, _ = _get(size).transcribe(
            audio, word_timestamps=True, language=language,
            beam_size=5 if precise else 1,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300 if precise else 2000},
            condition_on_previous_text=not precise)
        return [{"start": round(w.start + start, 2), "end": round(w.end + start, 2), "word": w.word.strip()}
                for s in segments for w in (s.words or [])]


def words_in_file(video: Path, size: str = "base", language: str | None = None) -> list[dict]:
    """Precise word timings for a whole (short) file, e.g. a rendered reel."""
    return words_in(video, 0.0, media.duration(video), size, language, precise=True)
