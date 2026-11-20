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

from ..errors import MediaError
from . import media

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None
_model_name: str | None = None      # size + threads, so changing the processing mode reloads it
_last_used = 0.0


def _on_gpu() -> bool:
    return bool(_model_name and _model_name.endswith("@cuda"))


def _with_fallback(size: str, call):
    """Run `call(model)`; if the GPU fails mid-way (missing CUDA library, out of memory), switch to the CPU
    for the rest of this run and try once more, instead of failing the job."""
    from . import gpu
    try:
        return call(_get(size))
    except RuntimeError as e:
        if not (_on_gpu() and gpu.is_gpu_error(e)):
            raise
        gpu.mark_broken(str(e))
        return call(_get(size))


def _device() -> str:
    """'cuda' when speech should run on the NVIDIA GPU, else 'cpu' (setting: speech_device)."""
    from ..config import load_settings
    from . import models
    want = load_settings()["speech_device"]
    return "cuda" if want != "cpu" and models.cuda_ready() else "cpu"


def _get(size: str):
    global _model, _model_name, _last_used
    device = _device()
    key = f"{size}@{media.cpu_threads()}@{device}"
    if _model is None or _model_name != key:
        from faster_whisper import WhisperModel
        log.info("loading speech model '%s' on the %s (first use downloads it)", size,
                 "GPU" if device == "cuda" else "CPU")
        try:
            if device == "cuda":
                try:
                    _model = WhisperModel(size, device="cuda", compute_type="float16")
                except Exception as e:  # noqa: BLE001 - driver / CUDA libraries / GPU memory: use the CPU
                    from . import gpu
                    gpu.mark_broken(str(e).split("\n")[0])
                    device, key = "cpu", f"{size}@{media.cpu_threads()}@cpu"
            if device == "cpu":
                _model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=media.cpu_threads())
        except Exception as e:  # noqa: BLE001 - network / disk / bad name
            raise MediaError(f"could not load speech model '{size}': {e}") from e
        _model_name = key
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


def _downloaded_multilingual() -> str | None:
    """A multilingual model already on disk (the user's other model first), to avoid a new download."""
    from ..config import load_settings
    from . import models
    other = load_settings().clip.get("model_other")
    for name in (other, "small", "medium", "large-v3", "base"):
        if name and name in models.CATALOG and name not in ENGLISH_ONLY and models.installed(name):
            return name
    return None


def detect_language(video: Path, windows: list[tuple[float, float]], size: str = "base") -> tuple[str | None, float]:
    """(language code, confidence) of the speech in up to three windows of a file, judged together.

    Detecting once per video (instead of per clip) keeps every reel of a video in the same
    language and script, which matters for mixed speech like Hinglish.
    """
    if size in ENGLISH_ONLY:            # an English-only model always "hears" English
        size = _downloaded_multilingual() or "small"
    audio = np.concatenate([_pcm(video, s, min(e, s + 30)) for s, e in windows[:3]] or [np.zeros(0, np.float32)])
    if len(audio) < 16000 * 2:
        return None, 0.0
    with _lock:
        lang, prob, _ = _with_fallback(size, lambda m: m.detect_language(
            audio, vad_filter=True, language_detection_segments=min(3, len(windows))))
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
        def run(model):      # the segments are produced lazily: a GPU error shows up while reading them
            segments, _ = model.transcribe(
                audio, word_timestamps=True, language=language, task=task,
                beam_size=5 if precise else 1,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 300 if precise else 2000},
                condition_on_previous_text=not precise)
            return [{"start": round(float(w.start) + start, 2), "end": round(float(w.end) + start, 2),
                     "word": w.word.strip()} for s in segments for w in (s.words or [])]
        return _with_fallback(size, run)


SWITCH_SURE = 0.6       # switch away from the stream's language only when the model is at least this sure
SHORT_SENTENCE = 1.5    # sentences shorter than this keep the previous sentence's language (too little to judge)


def sentences(audio: np.ndarray, gap: float = 0.45, longest: float = 15.0) -> list[tuple[int, int]]:
    """Speech in `audio` split at pauses into sentence-sized pieces (sample ranges)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    parts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=int(gap * 1000), speech_pad_ms=150,
                                                    max_speech_duration_s=longest))
    out: list[list[int]] = []
    for p in parts:
        if out and p["start"] - out[-1][1] < gap * 16000 and p["end"] - out[-1][0] < longest * 16000:
            out[-1][1] = p["end"]
        else:
            out.append([p["start"], p["end"]])
    return [(a, b) for a, b in out]


def pick_language(probs: list[tuple[str, float]], primary: str, allowed: set[str], previous: str) -> str:
    """The sentence's language among the allowed ones; stays on `previous` unless clearly another."""
    scores = {lang: p for lang, p in probs if lang in allowed}
    if not scores:
        return previous
    best = max(scores, key=scores.get)
    if best != previous and scores[best] >= SWITCH_SURE and scores[best] > scores.get(previous, 0) * 2:
        return best
    return previous


def words_by_sentence(video: Path, start: float, end: float, size: str, primary: str | None,
                      other: str = "small", allowed: set[str] | None = None) -> list[dict]:
    """Captions for speech that switches language between sentences (Hindi, then English, then Hindi):
    each sentence is detected and transcribed in its own language, with the model suited to it.

    Only `allowed` languages are considered (by default the stream's language and English), so game
    noise can't come out as a random language. Each word carries its "lang".
    """
    audio = _pcm(video, start, end)
    if len(audio) < 16000:
        return []
    primary = primary or "en"
    allowed = allowed or {primary, "en"}
    detector = model_for(size, primary if primary != "en" else "hi", other)   # a multilingual model
    words: list[dict] = []
    current = primary
    with _lock:
        for a, b in sentences(audio):
            chunk = audio[a:b]
            if (b - a) / 16000 >= SHORT_SENTENCE and len(allowed) > 1:
                _, _, probs = _with_fallback(detector, lambda m, c=chunk: m.detect_language(c))
                current = pick_language(probs, primary, allowed, current)

            def run(model, c=chunk, lang=current):
                segs, _ = model.transcribe(c, word_timestamps=True, language=lang, beam_size=5,
                                           condition_on_previous_text=False)
                return [w for s in segs for w in (s.words or [])]
            for w in _with_fallback(detector, run):   # one multilingual model for every sentence (no reloads)
                if w.word.strip():
                    words.append({"start": round(float(w.start) + start + a / 16000, 2),
                                  "end": round(float(w.end) + start + a / 16000, 2),
                                  "word": w.word.strip(), "lang": current})
    return words


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
