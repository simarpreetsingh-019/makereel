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


def _device() -> str:
    """'cuda' when speech should run on the NVIDIA GPU, else 'cpu' (setting: speech_device)."""
    from ..config import load_settings
    from . import models
    want = load_settings()["speech_device"]
    return "cuda" if want != "cpu" and models.cuda_ready() else "cpu"


def _get(size: str):
    global _model, _model_name, _last_used
    if _model is None or _model_name != size:
        from faster_whisper import WhisperModel
        device = _device()
        log.info("loading speech model '%s' on the %s (first use downloads it)", size,
                 "GPU" if device == "cuda" else "CPU")
        try:
            if device == "cuda":
                try:
                    _model = WhisperModel(size, device="cuda", compute_type="float16")
                except Exception as e:  # noqa: BLE001 - driver / CUDA libraries / GPU memory: use the CPU
                    log.warning("GPU unavailable for speech (%s); using the CPU", str(e).split("\n")[0][:120])
                    device = "cpu"
            if device == "cpu":
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


def _pcm(video: Path, start: float, end: float) -> np.ndarray:
    pcm = media.run([media.binary("ffmpeg"), "-v", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                     "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture=True)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def detect_language(video: Path, windows: list[tuple[float, float]], size: str = "base") -> tuple[str | None, float]:
    """(language code, confidence) of the speech in up to three windows of a file, judged together.

    Detecting once per video (instead of per clip) keeps every reel of a video in the same
    language and script, which matters for mixed speech like Hinglish.
    """
    if size in ENGLISH_ONLY:            # an English-only model always "hears" English
        size = "small"
    audio = np.concatenate([_pcm(video, s, min(e, s + 30)) for s, e in windows[:3]] or [np.zeros(0, np.float32)])
    if len(audio) < 16000 * 2:
        return None, 0.0
    with _lock:
        lang, prob, _ = _get(size).detect_language(audio, vad_filter=True,
                                                     language_detection_segments=min(3, len(windows)))
    return lang, float(prob)


def words_in(video: Path, start: float, end: float, size: str = "base",
             language: str | None = None, precise: bool = False, task: str = "transcribe") -> list[dict]:
    """Transcribe [start, end] of a file; word times are on the file's clock.

    task="translate" gives English words whatever the spoken language (for English captions).

    precise=True is for syncing captions on a finished reel: a wider beam search for better
    words and word timings. It costs a little more, but reels are short.
    """
    audio = _pcm(video, start, end)
    if len(audio) < 16000:  # under a second: nothing worth transcribing
        return []
    with _lock:
        segments, _ = _get(size).transcribe(
            audio, word_timestamps=True, language=language, task=task,
            beam_size=5 if precise else 1,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300 if precise else 2000},
            condition_on_previous_text=not precise)
        return [{"start": round(float(w.start) + start, 2), "end": round(float(w.end) + start, 2),
                 "word": w.word.strip()} for s in segments for w in (s.words or [])]


def words_in_file(video: Path, size: str = "base", language: str | None = None,
                  task: str = "transcribe") -> list[dict]:
    """Precise word timings for a whole (short) file, e.g. a rendered reel."""
    return words_in(video, 0.0, media.duration(video), size, language, precise=True, task=task)


RANK = ("tiny", "base", "small", "medium", "distil-large-v3", "large-v3")
ENGLISH_ONLY = ("distil-large-v3",)


def model_for(size: str, language: str | None, other: str) -> str:
    """The speech model for this language: `size` for English, `other` for Hindi and the rest.

    An English-only model can't hear Hindi at all, and small sizes are weak outside English, so for
    non-English speech the other model is used unless the main one is the bigger multilingual one.
    """
    if not language or language == "en" or other == "same":
        return size if size not in ENGLISH_ONLY or not language or language == "en" else "small"
    if size in ENGLISH_ONLY or RANK.index(other) > RANK.index(size):
        return other
    return size
