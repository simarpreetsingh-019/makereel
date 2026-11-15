"""Speaker-aware framing: follow the person on screen when cropping to a narrower shape.

1. Sample the clip at 3 frames per second, downscaled (cheap: a few hundred ms for a 45 s reel).
2. Detect faces with OpenCV's YuNet (a 230 KB model, downloaded once to <data>/models/).
3. Track one person: prefer the face closest to where we were looking, weighted by size, so the
   crop doesn't jump between people in the background.
4. Move a virtual camera with a dead zone: it holds still while the speaker stays near the centre
   and glides when they move away. That reads as a calm, deliberate camera rather than a jittery one.
5. Turn the camera path into an ffmpeg crop expression of time `t` (piecewise linear keyframes).

If too few frames have a face (gameplay, screen recordings), `crop_expression` returns None and the
caller falls back to the blurred-fill layout.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from ..config import env
from . import media

log = logging.getLogger(__name__)

MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
SAMPLE_FPS = 3
SAMPLE_WIDTH = 320
MIN_FACE_SHARE = 0.4      # need a face in at least 40% of samples to track
DEAD_ZONE = 0.07          # camera holds until the subject is this far (share of width) off target
GLIDE_SECONDS = 0.6       # how long a camera move takes


def model_path() -> Path | None:
    """The YuNet model, downloaded and checksum-verified on first use. None if unavailable (offline)."""
    path = env().data_dir / "models" / "face_detection_yunet_2023mar.onnx"
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log.info("downloading the face detection model (230 KB, once)")
        data = urllib.request.urlopen(MODEL_URL, timeout=30).read()
    except OSError as e:
        log.warning("face model download failed (%s); using the blurred layout", e)
        return None
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        log.warning("face model checksum mismatch; not using it")
        return None
    path.write_bytes(data)
    return path


def _dimensions(video: Path) -> tuple[int, int]:
    out = media.run([media.binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)], capture=True)
    w, h = out.decode().strip().split("\n")[0].split(",")[:2]
    return int(w), int(h)


def _samples(video: Path, start: float, length: float, w: int, h: int):
    """Yield (time, BGR frame) at SAMPLE_FPS, downscaled to SAMPLE_WIDTH."""
    sw = SAMPLE_WIDTH
    sh = int(round(h * sw / w / 2) * 2)
    proc = subprocess.Popen([media.binary("ffmpeg"), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                             "-i", str(video), "-vf", f"fps={SAMPLE_FPS},scale={sw}:{sh}", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = sw * sh * 3
    i = 0
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield i / SAMPLE_FPS, np.frombuffer(buf, np.uint8).reshape(sh, sw, 3)
        i += 1
    proc.wait()


def _face_centres(video: Path, start: float, length: float, w: int, h: int) -> list[float | None]:
    """Horizontal centre (0..1) of the tracked face in each sample, or None when there is no face."""
    import cv2
    model = model_path()
    if model is None:
        return []
    sh = int(round(h * SAMPLE_WIDTH / w / 2) * 2)
    det = cv2.FaceDetectorYN.create(str(model), "", (SAMPLE_WIDTH, sh), 0.6, 0.3, 50)
    out: list[float | None] = []
    prev: float | None = None
    for _, frame in _samples(video, start, length, w, h):
        _, faces = det.detect(frame)
        if faces is None or len(faces) == 0:
            out.append(None)
            continue
        # score = size, minus a penalty for being far from the face we were following
        best, best_score = None, -1e9
        for f in faces:
            fx, fw = f[0], f[2]
            cx = (fx + fw / 2) / SAMPLE_WIDTH
            size = fw / SAMPLE_WIDTH
            score = size - (abs(cx - prev) * 0.6 if prev is not None else 0)
            if score > best_score:
                best, best_score = cx, score
        prev = best
        out.append(best)
    return out


def camera_path(centres: list[float | None]) -> list[tuple[float, float]] | None:
    """Keyframes (time, centre 0..1) for a calm virtual camera, or None if there's no one to follow."""
    seen = [c for c in centres if c is not None]
    if not centres or len(seen) / len(centres) < MIN_FACE_SHARE:
        return None
    # fill gaps with the nearest known value, then median-smooth out detector noise
    filled, last = [], seen[0]
    for c in centres:
        last = c if c is not None else last
        filled.append(last)
    k = 5
    padded = np.pad(np.array(filled), k // 2, mode="edge")
    smooth = [float(np.median(padded[i:i + k])) for i in range(len(filled))]

    keys = [(0.0, smooth[0])]
    cam = smooth[0]
    for i, target in enumerate(smooth):
        t = i / SAMPLE_FPS
        if abs(target - cam) > DEAD_ZONE and t >= keys[-1][0] + GLIDE_SECONDS:
            keys.append((t, cam))                       # hold until now...
            cam = target
            keys.append((t + GLIDE_SECONDS, cam))       # ...then glide to the speaker
    keys.append((len(smooth) / SAMPLE_FPS + 1, cam))
    return keys


def crop_expression(video: Path, start: float, length: float, out_w: int, out_h: int) -> tuple[str, int, int] | None:
    """(x expression, crop width, crop height) following the speaker, or None to fall back to blur."""
    try:
        w, h = _dimensions(video)
    except Exception:  # noqa: BLE001
        return None
    crop_w = int(h * out_w / out_h) // 2 * 2
    if crop_w >= w:                                     # target is as wide as the source: nothing to track
        return None
    keys = camera_path(_face_centres(video, start, length, w, h))
    if keys is None:
        log.info("   no steady face found; using the blurred layout")
        return None

    def x_at(c: float) -> int:
        return int(min(max(c * w - crop_w / 2, 0), w - crop_w))

    # piecewise-linear x(t), built from the end backwards: if(lt(t,t1), seg1, if(lt(t,t2), seg2, ... last))
    expr = str(x_at(keys[-1][1]))
    for (t0, c0), (t1, c1) in reversed(list(zip(keys[:-1], keys[1:], strict=True))):
        x0, x1 = x_at(c0), x_at(c1)
        seg = str(x0) if x0 == x1 or t1 <= t0 else f"{x0}+({x1 - x0})*(t-{t0:.2f})/{t1 - t0:.2f}"
        expr = f"if(lt(t\\,{t1:.2f})\\,{seg}\\,{expr})"
    return expr, crop_w, h
