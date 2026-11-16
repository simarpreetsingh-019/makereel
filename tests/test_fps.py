import shutil
import subprocess

import pytest

from makereel.core import media, render

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _video(path, rate):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=s=320x180:r={rate}:d=2",
                    "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.mark.parametrize(("source", "wanted", "expected"), [(60, 60, 60), (60, 30, 30), (30, 60, 30)])
def test_master_keeps_real_60_fps_only(tmp_path, source, wanted, expected):
    src = _video(tmp_path / "in.mp4", source)
    out = tmp_path / "src.mp4"
    render.cut_source(src, 0, 1.5, out, wanted)
    assert round(media.frame_rate(out)) == expected
    raw = tmp_path / "raw.mp4"
    render.make_raw(out, raw, "9x16", "blur")
    assert round(media.frame_rate(raw)) == expected
