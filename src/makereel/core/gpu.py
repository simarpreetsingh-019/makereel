"""NVIDIA GPU support for speech: find NVIDIA's CUDA libraries and check they really load.

The speech engine (CTranslate2) needs cuBLAS 12 and cuDNN 9 next to the NVIDIA driver. NVIDIA ships them
as ordinary Python packages (nvidia-cublas-cu12, nvidia-cudnn-cu12) for Windows and Linux, so makereel
can install them into its own environment with one command. Without them the GPU is skipped and speech
runs on the CPU; it never crashes a job.
"""
from __future__ import annotations

import ctypes
import glob
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

PACKAGES = ("nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10")
DOWNLOAD_GB = 1.2
_prepared = False
_broken = False          # a GPU error happened at runtime: use the CPU for the rest of this run


def _nvidia_dirs() -> list[Path]:
    """bin/ (Windows) and lib/ (Linux) folders of NVIDIA's pip packages, wherever Python keeps them."""
    out = []
    for base in {Path(p) for p in sys.path if p and Path(p).is_dir()}:
        for sub in ("bin", "lib"):
            out += [Path(d) for d in glob.glob(str(base / "nvidia" / "*" / sub)) if Path(d).is_dir()]
    return out


def prepare() -> None:
    """Make the pip-installed CUDA libraries findable by the speech engine (once per process)."""
    global _prepared
    if _prepared:
        return
    _prepared = True
    dirs = _nvidia_dirs()
    if not dirs:
        return
    if platform.system() == "Windows":
        os.environ["PATH"] = os.pathsep.join(str(d) for d in dirs) + os.pathsep + os.environ.get("PATH", "")
        for d in dirs:
            try:
                os.add_dll_directory(str(d))
            except (OSError, AttributeError):
                pass
    else:   # Linux: load them now, globally, so the engine's own dlopen finds them
        for pattern in ("libcublasLt.so.12*", "libcublas.so.12*", "libcudnn*.so.9*"):
            for d in dirs:
                for f in sorted(d.glob(pattern)):
                    try:
                        ctypes.CDLL(str(f), mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass


def libs_ok() -> bool:
    """True when cuBLAS and cuDNN load (what the speech engine needs on top of the driver)."""
    prepare()
    system = platform.system()
    if system == "Windows":
        names = (("cublas64_12.dll",), ("cudnn_ops64_9.dll", "cudnn64_9.dll"))
        loader = ctypes.WinDLL
    elif system == "Linux":
        names = (("libcublas.so.12",), ("libcudnn_ops.so.9", "libcudnn.so.9"))
        loader = ctypes.CDLL
    else:
        return False                                  # macOS: no CUDA
    for options in names:
        if not any(_loads(loader, n) for n in options):
            return False
    return True


def _loads(loader, name: str) -> bool:
    try:
        loader(name)
        return True
    except OSError:
        return False


def mark_broken(reason: str) -> None:
    global _broken
    if not _broken:
        log.warning("the GPU failed for speech (%s); using the CPU from now on", reason[:160])
    _broken = True


def broken() -> bool:
    return _broken


def is_gpu_error(e: BaseException) -> bool:
    low = str(e).lower()
    return any(w in low for w in ("cublas", "cudnn", "cuda", "cudart", "out of memory"))


def install_libs() -> bool:
    """Install NVIDIA's CUDA libraries into makereel's own environment. True when they then load."""
    global _prepared
    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", sys.executable, *PACKAGES] if uv
           else [sys.executable, "-m", "pip", "install", *PACKAGES])
    log.info("installing NVIDIA GPU libraries (about %.1f GB, once)", DOWNLOAD_GB)
    try:
        if subprocess.run(cmd).returncode != 0:
            return False
    except OSError as e:
        log.error("couldn't install the GPU libraries: %s", e)
        return False
    import importlib
    importlib.invalidate_caches()
    _prepared = False                       # look for the new folders
    return libs_ok()
