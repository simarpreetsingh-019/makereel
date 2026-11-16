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


def _samples(video: Path, start: float, length: float, w: int, h: int, sw: int = SAMPLE_WIDTH,
             fps: float = SAMPLE_FPS):
    """Yield (time, BGR frame) at SAMPLE_FPS, downscaled to `sw` wide."""
    sh = int(round(h * sw / w / 2) * 2)
    proc = subprocess.Popen([media.binary("ffmpeg"), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                             "-i", str(video), "-vf", f"fps={fps},scale={sw}:{sh}", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = sw * sh * 3
    i = 0
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield i / fps, np.frombuffer(buf, np.uint8).reshape(sh, sw, 3)
        i += 1
    proc.wait()


def _faces(video: Path, start: float, length: float, w: int, h: int,
           sw: int = SAMPLE_WIDTH) -> list[list[tuple[float, float, float]]]:
    """Every face in each sample as (centre x, centre y, width), all shares of the frame. [] if no model."""
    import cv2
    model = model_path()
    if model is None:
        return []
    sw = min(sw, w)
    sh = int(round(h * sw / w / 2) * 2)
    det = cv2.FaceDetectorYN.create(str(model), "", (sw, sh), 0.6, 0.3, 50)
    out = []
    for _, frame in _samples(video, start, length, w, h, sw):
        _, faces = det.detect(frame)
        out.append([(float(f[0] + f[2] / 2) / sw, float(f[1] + f[3] / 2) / sh, float(f[2]) / sw)
                    for f in (faces if faces is not None else [])])
    return out


def follow(samples: list[list[tuple[float, float, float]]]) -> list[float | None]:
    """Horizontal centre of one tracked person per sample: big faces win, but the face near the one
    we were following is preferred, so the camera doesn't jump to someone in the background.
    Used when nobody's mouth can be read; follow_speaker() is preferred."""
    out: list[float | None] = []
    prev: float | None = None
    for faces in samples:
        best, best_score = None, -1e9
        for cx, _, size in faces:
            score = size - (abs(cx - prev) * 0.6 if prev is not None else 0)
            if score > best_score:
                best, best_score = cx, score
        prev = best if best is not None else prev
        out.append(best)
    return out


# ----------------------------------------------------------------------- who is talking
# Each face's mouth is cut out of every sample and compared with the same mouth one sample earlier:
# a talking mouth keeps changing, a listening one barely does. People are told apart by where they sit
# (podcast guests rarely swap seats). The camera moves to someone only after they have clearly talked
# more than the person on screen for a while, so a laugh or a "yeah" doesn't yank it across the room.
TRACK_FPS = 6              # mouths move fast: sample more often than for framing alone
TRACK_SAMPLE_WIDTH = 640   # and closer, so a mouth in a wide two-shot is more than a few pixels
SAME_PERSON = 0.12         # a face within this share of the width of a seat is that seat's person
TALK_WINDOW = 1.5          # seconds of mouth movement averaged to judge who is talking
SWITCH_RATIO = 1.4         # the other person must move their mouth this much more than the one shown...
SWITCH_HOLD = 0.8          # ...for this long before the camera moves
MIN_SHOT = 2.0             # and never cut away within this many seconds of the last move
LOST_GRACE = 1.0           # a face the detector misses for less than this many seconds is still there
CUT_DIFF = 40.0            # whole-frame change this big is an edit (camera cut), not a mouth


def _mouth_patch(gray, f, sw: int, sh: int):
    """Grey 32x16 cut-out around the mouth from YuNet's two mouth-corner landmarks, or None."""
    import cv2
    rx, ry, lx, ly = float(f[10]), float(f[11]), float(f[12]), float(f[13])
    fw, fh = float(f[2]), float(f[3])
    cx, cy = (rx + lx) / 2, (ry + ly) / 2
    half_w = max(abs(lx - rx) * 0.8, fw * 0.22)
    x0, x1 = int(cx - half_w), int(cx + half_w)
    y0, y1 = int(cy - fh * 0.18), int(cy + fh * 0.2)
    if x0 < 0 or y0 < 0 or x1 > sw or y1 > sh or x1 - x0 < 4 or y1 - y0 < 4:
        return None
    patch = cv2.resize(gray[y0:y1, x0:x1], (32, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    return patch - patch.mean()                         # ignore lighting changes


def _speaking_samples(video: Path, start: float, length: float, w: int, h: int):
    """Per sample: [(centre x, size, mouth movement or None)] and whether the shot changed (a cut)."""
    import cv2
    model = model_path()
    if model is None:
        return []
    sw = min(TRACK_SAMPLE_WIDTH, w)
    sh = int(round(h * sw / w / 2) * 2)
    det = cv2.FaceDetectorYN.create(str(model), "", (sw, sh), 0.6, 0.3, 50)
    out, prev_gray, prev_mouths = [], None, []
    for _, frame in _samples(video, start, length, w, h, sw, TRACK_FPS):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 36)).astype(np.float32)
        cut = prev_gray is not None and float(np.abs(small - prev_gray).mean()) > CUT_DIFF
        prev_gray = small
        _, faces = det.detect(frame)
        row, mouths = [], []
        for f in faces if faces is not None else []:
            cx, size = float(f[0] + f[2] / 2) / sw, float(f[2]) / sw
            patch = _mouth_patch(gray, f, sw, sh)
            move = None
            if patch is not None and not cut:
                near = [m for x, m in prev_mouths if abs(x - cx) < SAME_PERSON / 2]
                if near:
                    move = float(np.abs(patch - near[0]).mean())
            row.append((cx, size, move))
            if patch is not None:
                mouths.append((cx, patch))
        prev_mouths = mouths
        out.append((row, cut))
    return out


def follow_speaker(samples, fps: float = TRACK_FPS) -> list[float | None] | None:
    """Centre x of whoever is talking, per sample. None when mouths can't be read (fall back to follow())."""
    seats: list[float] = []                             # where each person sits (share of width)

    def seat_of(cx: float) -> int:
        for i, x in enumerate(seats):
            if abs(x - cx) < SAME_PERSON:
                seats[i] = x * 0.9 + cx * 0.1
                return i
        seats.append(cx)
        return len(seats) - 1

    rows = []
    for faces, cut in samples:
        rows.append(({seat_of(cx): (cx, size, move) for cx, size, move in faces}, cut))
    if not any(move is not None for faces, _ in rows for _, _, move in faces.values()):
        return None

    win = max(1, round(TALK_WINDOW * fps))
    hold, min_shot, grace = round(SWITCH_HOLD * fps), round(MIN_SHOT * fps), round(LOST_GRACE * fps)
    history: dict[int, list[float]] = {}
    last_x: dict[int, float] = {}
    last_seen: dict[int, int] = {}
    shown, since_move, ahead = None, 10 ** 6, 0
    out: list[float | None] = []
    for i, (faces, cut) in enumerate(rows):
        for seat, (cx, _, _) in faces.items():
            last_x[seat], last_seen[seat] = cx, i
        present = {seat for seat in last_seen if i - last_seen[seat] <= grace}
        for seat in present:
            move = faces.get(seat, (0, 0, None))[2]
            history.setdefault(seat, []).append(move if move is not None else 0.0)
            del history[seat][:-win]
        talk = {seat: float(np.mean(history[seat])) for seat in present}
        since_move += 1
        if cut:
            since_move = min_shot                       # a new shot: free to reframe right away
            present = set(faces)
        if shown not in present:                        # nobody yet, or the person shown has left the shot
            if faces:
                shown = max(faces, key=lambda s: (_talk_ahead(rows, i, s, win), faces[s][1]))
                since_move, ahead = 0, 0
        elif len(present) > 1:
            rival = max((s for s in present if s != shown), key=lambda s: talk[s])
            ahead = ahead + 1 if talk[rival] > max(talk[shown] * SWITCH_RATIO, 0.5) else 0
            if ahead >= hold and since_move >= min_shot:
                shown, since_move, ahead = rival, 0, 0
        out.append(last_x[shown] if shown in present else None)
    return out


def _talk_ahead(rows, i: int, seat: int, win: int) -> float:
    """Average mouth movement of `seat` over the next `win` samples: when the camera must pick someone
    without any history (start of the reel, after a cut), whoever is about to talk is the better guess."""
    moves = [f[seat][2] for f, _ in rows[i:i + win] if seat in f and f[seat][2] is not None]
    return float(np.mean(moves)) if moves else 0.0


def _face_centres(video: Path, start: float, length: float, w: int, h: int) -> tuple[list[float | None], float]:
    """(centre per sample, samples per second): the talking person if mouths can be read, else the biggest face."""
    centres = follow_speaker(_speaking_samples(video, start, length, w, h))
    if centres is not None:
        return centres, TRACK_FPS
    return follow(_faces(video, start, length, w, h)), SAMPLE_FPS


def camera_path(centres: list[float | None], fps: float = SAMPLE_FPS) -> list[tuple[float, float]] | None:
    """Keyframes (time, centre 0..1) for a calm virtual camera, or None if there's no one to follow."""
    seen = [c for c in centres if c is not None]
    if not centres or len(seen) / len(centres) < MIN_FACE_SHARE:
        return None
    # fill gaps with the nearest known value, then median-smooth out detector noise
    filled, last = [], seen[0]
    for c in centres:
        last = c if c is not None else last
        filled.append(last)
    k = max(3, round(fps * 5 / 3)) | 1                 # ~1.7 s of median smoothing
    padded = np.pad(np.array(filled), k // 2, mode="edge")
    smooth = [float(np.median(padded[i:i + k])) for i in range(len(filled))]

    keys = [(0.0, smooth[0])]
    cam = smooth[0]
    for i, target in enumerate(smooth):
        t = i / fps
        if abs(target - cam) > DEAD_ZONE and t >= keys[-1][0] + GLIDE_SECONDS:
            keys.append((t, cam))                       # hold until now...
            cam = target
            keys.append((t + GLIDE_SECONDS, cam))       # ...then glide to the speaker
    keys.append((len(smooth) / fps + 1, cam))
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
    keys = camera_path(*_face_centres(video, start, length, w, h))
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


# --------------------------------------------------------------------------- split screen
# Two layouts stacked in a 9:16 frame:
#   duo      two people side by side (podcast, interview): each gets half the height, top and bottom.
#   facecam  a streamer's small webcam over gameplay: the webcam on top (40%), the game below (60%).
MIN_DUO_SHARE = 0.4        # both people on screen together in at least 40% of samples
MIN_DUO_GAP = 0.22         # and at least this far apart (share of width)
FACECAM_MAX_SIZE = 0.13    # a webcam overlay's face is small...
FACECAM_SHARE = 0.4        # ...and nearly always there (in at least 40% of samples)...
FACECAM_STILL = 0.04       # ...and doesn't move (overlays are fixed on screen)
FACECAM_TOP = 0.4          # share of the reel's height given to the webcam
SPLIT_SAMPLE_WIDTH = 640   # webcam faces are small: look closer than for tracking


def split_plan(samples: list[list[tuple[float, float, float]]]) -> dict | None:
    """Pick a split layout from face samples, or None if neither fits.

    Returns {"kind": "duo", "people": [(cx, cy, size), (cx, cy, size)]} (left person first) or
    {"kind": "facecam", "face": (cx, cy, size)}. All values are shares of the frame.
    """
    if not samples:
        return None
    n = len(samples)
    faces = [f for fs in samples for f in fs if f[2] >= 0.04]
    if faces:
        # duo: split faces at the biggest horizontal gap, then check both sides are steady
        xs = sorted(f[0] for f in faces)
        gaps = [(b - a, (a + b) / 2) for a, b in zip(xs, xs[1:], strict=False)]
        if gaps:
            gap, cut = max(gaps)
            left = [f for f in faces if f[0] < cut]
            right = [f for f in faces if f[0] >= cut]
            # both people in the same frames (not one camera cutting between two single shots)
            together = sum(any(f[2] >= 0.04 and f[0] < cut for f in fs) and
                           any(f[2] >= 0.04 and f[0] >= cut for f in fs) for fs in samples) / n
            if gap >= MIN_DUO_GAP and together >= MIN_DUO_SHARE:
                med = lambda group, i: float(np.median([f[i] for f in group]))  # noqa: E731
                return {"kind": "duo", "people": [(med(g, 0), med(g, 1), med(g, 2)) for g in (left, right)]}
    # facecam: one small face that stays put
    small = [min(fs, key=lambda f: f[2]) for fs in samples if fs]
    small = [f for f in small if f[2] <= FACECAM_MAX_SIZE]
    if len(small) / n >= FACECAM_SHARE:
        cx, cy = float(np.median([f[0] for f in small])), float(np.median([f[1] for f in small]))
        steady = [f for f in small if abs(f[0] - cx) < FACECAM_STILL and abs(f[1] - cy) < FACECAM_STILL]
        if len(steady) / n >= FACECAM_SHARE:
            return {"kind": "facecam", "face": (cx, cy, float(np.median([f[2] for f in steady])))}
    return None


def _box(cx: float, cy: float, cw: float, ch: float, w: int, h: int) -> tuple[int, int, int, int]:
    """A cw x ch crop (pixels) centred on (cx, cy) (shares), kept inside the frame; even sizes."""
    cw, ch = min(cw, w), min(ch, h)
    cw, ch = int(cw) // 2 * 2, int(ch) // 2 * 2
    x = int(min(max(cx * w - cw / 2, 0), w - cw))
    y = int(min(max(cy * h - ch / 2, 0), h - ch))
    return x, y, cw, ch


def split_panels(plan: dict, w: int, h: int, out_w: int, out_h: int) -> list[tuple[tuple[int, int, int, int], int]]:
    """[(crop box in the source, panel height in the reel)], top panel first."""
    if plan["kind"] == "duo":
        top_h = out_h // 2 // 2 * 2
        heights = [top_h, out_h - top_h]
        panels = []
        for (cx, cy, size), ph in zip(plan["people"], heights, strict=True):
            aspect = out_w / ph
            ch = min(h, max(size * w * 3.2 / aspect, h * 0.45))      # head and shoulders, not just a face
            panels.append((_box(cx, cy + size * 0.35, ch * aspect, ch, w, h), ph))
        return panels
    cx, cy, size = plan["face"]
    top_h = round(out_h * FACECAM_TOP) // 2 * 2
    bottom_h = out_h - top_h
    aspect_t, aspect_b = out_w / top_h, out_w / bottom_h
    cw = size * w * 4.5                                               # the webcam frame around the face
    cam = _box(cx, cy, cw, cw / aspect_t, w, h)
    game = _box(0.5, 0.5, h * aspect_b, h, w, h)
    return [(cam, top_h), (game, bottom_h)]


def split_layout(video: Path, start: float, length: float, out_w: int, out_h: int):
    """Crop panels for fit='split', or None (no steady pair of people or webcam; caller falls back)."""
    try:
        w, h = _dimensions(video)
    except Exception:  # noqa: BLE001
        return None
    plan = split_plan(_faces(video, start, length, w, h, SPLIT_SAMPLE_WIDTH))
    if plan is None:
        log.info("   no two people or webcam found; using the single-speaker layout")
        return None
    log.info("   split screen: %s", plan["kind"])
    return split_panels(plan, w, h, out_w, out_h)
