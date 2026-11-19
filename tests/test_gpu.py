"""A GPU without NVIDIA's CUDA libraries must never crash speech: it falls back to the CPU."""
import sys
import types

import numpy as np

from makereel.core import gpu, models, transcribe


class FakeModel:
    def __init__(self, size, device="cpu", **kw):
        self.device = device

    def detect_language(self, audio, **kw):
        if self.device == "cuda":   # what his RTX 4070 did: the model loads, then the first call fails
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return "en", 0.97, []


def test_gpu_error_falls_back_to_cpu(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(models, "cuda_ready", lambda: not gpu.broken())   # "GPU looks usable" until it fails
    monkeypatch.setattr(gpu, "_broken", False)
    monkeypatch.setattr(transcribe, "_model", None)
    monkeypatch.setattr(transcribe, "_model_name", None)
    monkeypatch.setattr(transcribe, "_pcm", lambda *a: np.zeros(16000 * 5, np.float32))
    video = tmp_path / "v.mp4"
    lang, prob = transcribe.detect_language(video, [(0, 5)], "small")
    assert lang == "en" and gpu.broken()                # finished on the CPU, and remembers the GPU failed
    assert transcribe._model_name.endswith("@cpu")


def test_gpu_error_detection():
    assert gpu.is_gpu_error(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))
    assert gpu.is_gpu_error(RuntimeError("CUDA failed with error out of memory"))
    assert not gpu.is_gpu_error(RuntimeError("file not found"))
