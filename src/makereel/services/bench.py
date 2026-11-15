"""Benchmarks: how fast makereel is on this device, and what it costs in CPU, memory and disk.

A run makes reels from a fixed test video (or one you choose) into a temporary folder, while a
sampler watches the whole process tree (makereel + ffmpeg) every 0.25 s. Results go to
<data>/benchmarks.jsonl so each version can be compared with the last one on the same machine.

Nothing is ever sent anywhere. `share_report()` builds a text report with hardware and timings
only (no names, paths or links you processed) that the user can choose to post.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import psutil

from .. import __version__
from ..config import env, load_settings
from ..core import media, metrics, pipeline, sources, transcribe
from ..errors import NotFound

log = logging.getLogger(__name__)

TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # 19 s, public, stable since 2005
TEST_ID = "jNQXAC9IVRw"
STAGES = ("probe", "signals", "transcribe", "judge", "scenes", "render", "sync")
REPO_URL = os.environ.get("MAKEREEL_REPO_URL", "").rstrip("/")


# --------------------------------------------------------------------------- device profile
def _run(cmd: list[str], timeout: float = 4) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _cpu_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.machine()
    if system == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith(("model name", "hardware")):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if system == "Windows":
        return platform.processor() or _run(["wmic", "cpu", "get", "name"]).splitlines()[-1].strip()
    return platform.processor() or platform.machine()


def _gpu_name() -> str | None:
    system = platform.system()
    if shutil.which("nvidia-smi"):
        return _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).splitlines()[0] or None
    if system == "Darwin":
        m = re.search(r"Chipset Model: (.+)", _run(["system_profiler", "SPDisplaysDataType"], 8))
        return m.group(1).strip() if m else None
    if system == "Windows":
        lines = _run(["wmic", "path", "win32_VideoController", "get", "name"]).splitlines()[1:]
        return ", ".join(l.strip() for l in lines if l.strip()) or None
    if system == "Linux" and shutil.which("lspci"):
        gpus = [l.split(": ", 1)[1] for l in _run(["lspci"]).splitlines() if " VGA " in l or "3D controller" in l]
        return ", ".join(gpus) or None
    return None


def device_profile() -> dict:
    """Hardware and software facts only: nothing that identifies the person or machine."""
    mem = psutil.virtual_memory()
    ffmpeg_version = ""
    try:
        ffmpeg_version = _run([media.binary("ffmpeg"), "-version"]).split("\n")[0].split(" ")[2]
    except Exception:  # noqa: BLE001
        pass
    return {
        "os": f"{platform.system()} {platform.release()}", "arch": platform.machine(),
        "cpu": _cpu_name(), "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(), "ram_gb": round(mem.total / 1024**3, 1),
        "gpu": _gpu_name(), "encoder": media.encoder_name(), "ffmpeg": ffmpeg_version,
        "python": platform.python_version(), "makereel": __version__, "threads": env().threads,
        "on_battery": _on_battery(),
    }


def _on_battery() -> bool | None:
    try:
        b = psutil.sensors_battery()
        return None if b is None else not b.power_plugged
    except (AttributeError, NotImplementedError):
        return None


# --------------------------------------------------------------------------- sampling
class Sampler:
    """Polls this process and its children (ffmpeg, yt-dlp) for memory and CPU."""

    def __init__(self, interval: float = 0.25, watch_dir: Path | None = None):
        self.interval, self.watch_dir = interval, watch_dir
        self.peak_rss = 0
        self.cpu_samples: list[float] = []
        self.peak_disk = 0
        self.gpu_samples: list[float] = []
        self._stop = threading.Event()
        self._proc = psutil.Process()
        self._cpu_seen: dict[int, float] = {}

    def _tree(self) -> list[psutil.Process]:
        try:
            return [self._proc, *self._proc.children(recursive=True)]
        except psutil.Error:
            return [self._proc]

    def _loop(self) -> None:
        cores = psutil.cpu_count() or 1
        for p in self._tree():
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass
        while not self._stop.wait(self.interval):
            rss, cpu = 0, 0.0
            for p in self._tree():
                try:
                    rss += p.memory_info().rss
                    cpu += p.cpu_percent(None)
                    t = p.cpu_times()
                    self._cpu_seen[p.pid] = t.user + t.system
                except psutil.Error:
                    continue
            self.peak_rss = max(self.peak_rss, rss)
            self.cpu_samples.append(cpu / cores)   # % of the whole machine
            if self.watch_dir and self.watch_dir.exists():
                size = sum(f.stat().st_size for f in self.watch_dir.rglob("*") if f.is_file())
                self.peak_disk = max(self.peak_disk, size)
            if shutil.which("nvidia-smi") and len(self.cpu_samples) % 8 == 0:
                out = _run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], 2)
                if out.split("\n")[0].strip().isdigit():
                    self.gpu_samples.append(float(out.split("\n")[0]))

    def __enter__(self):
        self._t0 = time.perf_counter()
        self._times0 = os.times()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.wall = time.perf_counter() - self._t0
        t = os.times()
        own = (t.user - self._times0.user) + (t.system - self._times0.system)
        children = (t.children_user - self._times0.children_user) + (t.children_system - self._times0.children_system)
        tracked = sum(v for pid, v in self._cpu_seen.items() if pid != self._proc.pid)
        self.cpu_seconds = own + max(children, tracked)   # Windows reports no children_* times


# --------------------------------------------------------------------------- running
def _results_file() -> Path:
    env().data_dir.mkdir(parents=True, exist_ok=True)
    return env().data_dir / "benchmarks.jsonl"


def _test_input(video: str | None) -> tuple[Path, dict, float | None]:
    """A local file to benchmark on (downloaded once and cached), its metadata, and download time."""
    cache = env().data_dir / "bench"
    if video and Path(video).is_file():
        p = Path(video)
        return p, {"id": p.stem, "title": p.stem, "url": "", "tags": [], "offset": 0.0}, None
    url = video or TEST_VIDEO
    cached = next((p for p in cache.glob(f"{TEST_ID}.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
    if url == TEST_VIDEO and cached:
        return cached, {"id": TEST_ID, "title": "benchmark", "url": TEST_VIDEO, "tags": [], "offset": 0.0}, None
    t0 = time.perf_counter()
    dl = sources.download(url, cache, chat=False)
    return dl.video, {**dl.info.to_meta(), "title": "benchmark"}, round(time.perf_counter() - t0, 2)


def run(video: str | None = None, model: str | None = None, cold: bool = True) -> dict:
    """Run one benchmark and save it. `cold` unloads the speech model first (counts loading time)."""
    settings = load_settings()
    clip = {**settings.clip, "max_clips": 3}
    if model:
        clip["model"] = model
    source, meta, download_s = _test_input(video)
    duration = media.duration(source)
    if cold:
        transcribe.release_if_idle(0)
    log.info("benchmark: %s (%.0fs of video), model %s", source.name, duration, clip["model"])
    with tempfile.TemporaryDirectory(prefix="makereel-bench-") as tmp:
        out = Path(tmp)
        with Sampler(watch_dir=out) as s, metrics.record() as stages:
            reels = pipeline.process(source, meta, out, clip, settings.brand)
        output_mb = sum(f.stat().st_size for f in out.glob("*.mp4")) / 1024**2
    cpu = s.cpu_samples or [0.0]
    result = {
        "id": uuid.uuid4().hex[:8], "time": time.time(), "device": device_profile(),
        "input": {"name": "test video" if not video else "custom", "seconds": round(duration, 1)},
        "model": clip["model"], "reels": len(reels),
        "wall_s": round(s.wall, 2),
        "speed_x": round(duration / s.wall, 2) if s.wall else None,   # seconds of video per second
        "per_reel_s": round(s.wall / max(1, len(reels)), 2),
        "download_s": download_s,
        "stages_s": {k: round(stages.get(k, 0.0), 2) for k in STAGES},
        "cpu_seconds": round(s.cpu_seconds, 2),
        # average from total CPU time (exact); peak from samples (short ffmpeg runs can slip between them)
        "cpu_avg_pct": round(s.cpu_seconds / max(s.wall, 1e-6) / (psutil.cpu_count() or 1) * 100, 1),
        "cpu_peak_pct": round(max(cpu), 1),
        "ram_peak_mb": round(s.peak_rss / 1024**2), "disk_peak_mb": round(s.peak_disk / 1024**2, 1),
        "output_mb": round(output_mb, 1),
        "gpu_avg_pct": round(sum(s.gpu_samples) / len(s.gpu_samples), 1) if s.gpu_samples else None,
    }
    with _results_file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
    log.info("benchmark done: %.1fs total, %.1f CPU-s, peak %d MB RAM", s.wall, s.cpu_seconds, result["ram_peak_mb"])
    return result


# --------------------------------------------------------------------------- history + reports
def history() -> list[dict]:
    f = _results_file()
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return sorted(out, key=lambda r: r["time"], reverse=True)


def get(result_id: str) -> dict:
    found = next((r for r in history() if r["id"] == result_id), None)
    if found is None:
        raise NotFound(f"no benchmark {result_id}")
    return found


def compare(result: dict) -> dict | None:
    """Change vs the previous run on the same CPU with the same input and model (negative = better)."""
    prev = next((r for r in history() if r["time"] < result["time"] and r["device"]["cpu"] == result["device"]["cpu"]
                 and r["model"] == result["model"] and r["input"] == result["input"]), None)
    if prev is None:
        return None

    def pct(key):
        a, b = prev.get(key), result.get(key)
        return round((b - a) / a * 100, 1) if a and b is not None else None

    return {"against": prev["id"], "against_version": prev["device"]["makereel"],
            "wall_pct": pct("wall_s"), "cpu_seconds_pct": pct("cpu_seconds"), "ram_peak_pct": pct("ram_peak_mb")}


def report_markdown(result: dict) -> str:
    d = result["device"]
    stages = " · ".join(f"{k} {v}s" for k, v in result["stages_s"].items() if v)
    rows = [
        ("makereel", d["makereel"]), ("OS", f"{d['os']} ({d['arch']})"), ("CPU", d["cpu"]),
        ("Cores", f"{d['cores_physical']} physical / {d['cores_logical']} logical"),
        ("RAM", f"{d['ram_gb']} GB"), ("GPU", d["gpu"] or "unknown"), ("Encoder", d["encoder"]),
        ("Speech model", f"{result['model']} ({d['threads']} threads)"),
        ("On battery", {True: "yes", False: "no"}.get(d["on_battery"], "n/a")),
        ("Input", f"{result['input']['name']}, {result['input']['seconds']}s → {result['reels']} "
                  f"reel{'s' if result['reels'] != 1 else ''}"),
        ("Total time", f"{result['wall_s']}s ({result['speed_x']}× real time, {result['per_reel_s']}s per reel)"),
        ("Stages", stages), ("CPU time", f"{result['cpu_seconds']} CPU-seconds"),
        ("CPU load", f"avg {result['cpu_avg_pct']}%, peak {result['cpu_peak_pct']}% of the machine"),
        ("Peak RAM", f"{result['ram_peak_mb']} MB"), ("GPU load", f"{result['gpu_avg_pct']}%" if
                                                      result["gpu_avg_pct"] is not None else "not measurable here"),
        ("Disk", f"peak {result['disk_peak_mb']} MB while working, {result['output_mb']} MB of reels"),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"### makereel benchmark\n\n| | |\n|---|---|\n{body}\n\n<!-- id {result['id']} -->\n"


def share_url(result: dict) -> str | None:
    """A pre-filled GitHub issue the user can review and submit. None if no repository is configured."""
    if not REPO_URL:
        return None
    title = f"Benchmark: {result['device']['cpu']} · {result['device']['os']} · v{result['device']['makereel']}"
    return f"{REPO_URL}/issues/new?labels=benchmark&title={quote(title)}&body={quote(report_markdown(result))}"
