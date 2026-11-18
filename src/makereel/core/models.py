"""Speech models: which ones exist, which are downloaded, and which suit this computer.

makereel uses two speech models: one for English streams (`clip.model`) and one for Hindi and other
Indian languages (`clip.model_other`). The setup step reads this computer's memory, disk and NVIDIA
GPU, asks who the user clips (English streamers, Indian streamers, or both) and suggests a pair.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

# name -> what the setup screen shows. size_gb: download; ram_gb: memory it needs on the CPU;
# english_only: can't do Hindi at all; translate: can write English captions from Hindi speech.
CATALOG: dict[str, dict] = {
    "base": {"label": "Base", "size_gb": 0.15, "ram_gb": 1, "english_only": False, "translate": False,
             "note": "Tiny and quick. Fine for clear English on old or small computers."},
    "small": {"label": "Small", "size_gb": 0.5, "ram_gb": 2, "english_only": False, "translate": True,
              "note": "Good English, usable Hindi. Runs on almost anything."},
    "medium": {"label": "Medium", "size_gb": 1.5, "ram_gb": 5, "english_only": False, "translate": True,
               "note": "Clearly better Hindi and Hinglish. Wants 8 GB of memory."},
    "distil-large-v3": {"label": "Distil large v3 (English)", "size_gb": 1.5, "ram_gb": 4, "english_only": True,
                        "translate": False,
                        "note": "Near-best English accuracy and fast. English only: "
                                "Hindi streams use the other model."},
    "large-v3": {"label": "Large v3", "size_gb": 3.1, "ram_gb": 10, "english_only": False, "translate": True,
                 "note": "The most accurate for Hindi and mixed Hindi-English. Best with an NVIDIA GPU."},
}
ENGLISH_CHOICES = ("base", "small", "medium", "distil-large-v3", "large-v3")
OTHER_CHOICES = ("small", "medium", "large-v3")
FOCUS = ("english", "indian", "both")


# --------------------------------------------------------------------------- this computer
def nvidia_gpu() -> dict | None:
    """{"name", "vram_gb"} of the first NVIDIA GPU, or None."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        name, mem = (p.strip() for p in out[0].split(",")[:2])
        return {"name": name, "vram_gb": round(float(mem) / 1024, 1)}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def cuda_ready() -> bool:
    """True when the speech engine can actually use an NVIDIA GPU (driver + CUDA libraries)."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def computer(models_dir: Path | None = None) -> dict:
    disk = psutil.disk_usage(str(models_dir or Path.home()))
    return {"ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
            "cores": psutil.cpu_count(logical=False) or psutil.cpu_count() or 1,
            "free_disk_gb": round(disk.free / 1024**3, 1), "gpu": nvidia_gpu(), "cuda": cuda_ready()}


# --------------------------------------------------------------------------- suggestions
def recommend(pc: dict, focus: str = "both") -> dict:
    """The model pair (and where to run it) that suits this computer, with the reason in words."""
    ram, gpu = pc["ram_gb"], pc.get("gpu")
    vram = gpu["vram_gb"] if gpu and pc.get("cuda") else 0
    if vram >= 6:
        english, other, why = "distil-large-v3", "large-v3", f"{gpu['name']} with {vram:g} GB can run the largest model"
    elif ram >= 16:
        english, other, why = "distil-large-v3", "medium", f"{ram:g} GB of memory, no usable NVIDIA GPU"
    elif ram >= 8:
        english, other, why = "small", "medium", f"{ram:g} GB of memory"
    else:
        english, other, why = "base", "small", f"only {ram:g} GB of memory: the light models keep it responsive"
    if focus == "indian":
        # Indian streamers still speak English now and then: keep a decent English model, spend the space on Hindi
        english = "small" if english == "distil-large-v3" and vram < 6 else english
    needed = sum(CATALOG[m]["size_gb"] for m in {english, other} if not installed(m))
    return {"model": english, "model_other": other, "device": "gpu" if vram >= 4 else "cpu", "why": why,
            "download_gb": round(needed, 1), "fits_disk": needed + 2 < pc["free_disk_gb"], "focus": focus}


# --------------------------------------------------------------------------- downloads
def _repo(name: str) -> str:
    from faster_whisper.utils import _MODELS
    return _MODELS[name]


def installed(name: str) -> bool:
    try:                                  # faster-whisper fetches only the files it needs: ask it, not the hub
        from faster_whisper import download_model
        return (Path(download_model(name, local_files_only=True)) / "model.bin").is_file()
    except Exception:  # noqa: BLE001 - not in the cache (or unknown)
        return False


def _cache_bytes(name: str) -> int:
    d = _cache_dir(name)
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d and d.is_dir() else 0


_downloads: dict[str, dict] = {}     # name -> {"state": "downloading" | "done" | "failed" | "cancelled", ...}
_procs: dict[str, subprocess.Popen] = {}
_dl_lock = threading.Lock()


def _cache_dir(name: str) -> Path | None:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return None
    return Path(HF_HUB_CACHE) / ("models--" + _repo(name).replace("/", "--"))


def download(name: str) -> dict:
    """Start downloading a model in a separate process (so Stop can end it at once)."""
    import sys
    if name not in CATALOG:
        raise ValueError(f"unknown model {name}")
    with _dl_lock:
        if installed(name):
            _downloads[name] = {"state": "done"}
        elif _downloads.get(name, {}).get("state") != "downloading":
            code = "import sys; from faster_whisper import download_model; download_model(sys.argv[1])"
            proc = subprocess.Popen([sys.executable, "-c", code, name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            _procs[name], _downloads[name] = proc, {"state": "downloading"}

            def wait() -> None:
                err = proc.communicate()[1].decode("utf-8", "replace").strip().splitlines()
                with _dl_lock:
                    if _downloads.get(name, {}).get("state") == "cancelled":
                        return
                    _procs.pop(name, None)
                    if proc.returncode == 0:
                        _downloads[name] = {"state": "done"}
                        log.info("speech model '%s' downloaded", name)
                    else:
                        _downloads[name] = {"state": "failed", "error": (err[-1] if err else "download failed")[:200]}
            threading.Thread(target=wait, name=f"download-{name}", daemon=True).start()
    return status(name)


def cancel(name: str) -> dict:
    """Stop a download and remove what it had fetched so far."""
    with _dl_lock:
        proc = _procs.pop(name, None)
        if proc is not None and proc.poll() is None:
            _downloads[name] = {"state": "cancelled"}
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            d = _cache_dir(name)
            if d is not None:
                shutil.rmtree(d, ignore_errors=True)
            log.info("download of '%s' stopped", name)
    return status(name)


def delete(name: str) -> dict:
    """Remove a downloaded model from disk (it is downloaded again if it's ever needed)."""
    cancel(name)
    d = _cache_dir(name)
    if d is not None and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        log.info("speech model '%s' deleted", name)
    with _dl_lock:
        _downloads.pop(name, None)
    return status(name)


def status(name: str) -> dict:
    st = dict(_downloads.get(name) or {})
    if st.get("state") in (None, "cancelled"):
        st = {"state": "done" if installed(name) else "missing"}
    if st["state"] == "downloading":
        total = CATALOG[name]["size_gb"] * 1024**3
        st["percent"] = min(99, round(_cache_bytes(name) / total * 100))
    return st


def catalog() -> list[dict]:
    return [{"name": n, **info, **status(n)} for n, info in CATALOG.items()]
