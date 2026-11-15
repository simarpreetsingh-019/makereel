import pytest

from makereel import config
from makereel.core import branding, render
from makereel.errors import ConfigError, InvalidInput
from makereel.services import bench, brand


@pytest.mark.parametrize("fmt", list(render.FORMATS))
@pytest.mark.parametrize("fit", render.FITS)
def test_reframe_filter_targets_exact_size(fmt, fit):
    w, h = render.FORMATS[fmt]
    graph = render.reframe_filter(fmt, fit)
    assert graph.startswith("[0:v]") and graph.endswith("[v]") and f"{w}:{h}" in graph


def test_reframe_rejects_unknown():
    with pytest.raises(ValueError):
        render.reframe_filter("3x2", "blur")


def test_style_for_formats_scales_text():
    b = config.load_settings().brand
    tall, wide = branding.style_for("9x16", b), branding.style_for("16x9", b)
    assert (tall.width, tall.height) == (1080, 1920) and (wide.width, wide.height) == (1920, 1080)
    assert "Fontsize" in wide.header()


def test_brand_validation():
    config.save_settings({"brand": {"highlight_colour": "#00FF88", "logo_position": "bottom-left"}})
    assert config.load_settings().brand["highlight_colour"] == "#00FF88"
    for bad in ({"text_colour": "red"}, {"logo_position": "centre"}, {"logo_scale": 5}, {"font": "a,b"}):
        with pytest.raises(ConfigError):
            config.save_settings({"brand": bad})


def test_logo_upload_checks_type():
    with pytest.raises(InvalidInput):
        brand.save_logo(b"not an image")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    assert brand.save_logo(png)["logo"].startswith("/brand/logo.png")
    assert branding.logo_for(config.load_settings().brand) is not None
    assert branding.logo_for(config.load_settings().brand, enabled_on_reel=False) is None
    brand.delete_logo()
    assert branding.logo_file() is None


def test_credit_footer_is_opt_out():
    from makereel.core import pipeline
    meta = {"url": "u", "channel": "c", "title": "t", "tags": [], "offset": 0}
    assert pipeline.CREDIT_FOOTER in pipeline.credits(meta, 0, "gameplay", "h", {"credit_footer": True})["caption"]
    assert pipeline.CREDIT_FOOTER not in pipeline.credits(meta, 0, "gameplay", "h", {"credit_footer": False})["caption"]


def test_bench_report_has_no_personal_data(monkeypatch):
    result = {"id": "abc", "time": 1, "device": {"makereel": "0.3.0", "os": "Darwin 25", "arch": "arm64",
              "cpu": "Apple M5", "cores_physical": 10, "cores_logical": 10, "ram_gb": 16.0, "gpu": "Apple M5",
              "encoder": "h264_videotoolbox", "ffmpeg": "8.0", "python": "3.12", "threads": 2, "on_battery": False},
              "input": {"name": "test video", "seconds": 19.1}, "model": "base", "reels": 1, "wall_s": 9.0,
              "speed_x": 2.1, "per_reel_s": 9.0, "download_s": None,
              "stages_s": {"render": 4.0, "transcribe": 1.0}, "cpu_seconds": 7.0, "cpu_avg_pct": 30.0,
              "cpu_peak_pct": 80.0, "ram_peak_mb": 600, "disk_peak_mb": 12.0, "output_mb": 6.0, "gpu_avg_pct": None}
    md = bench.report_markdown(result)
    assert "Apple M5" in md and "9.0s" in md and "/Users/" not in md
    monkeypatch.setattr(bench, "REPO_URL", "https://github.com/x/makereel")
    assert bench.share_url(result).startswith("https://github.com/x/makereel/issues/new?labels=benchmark")


def test_caption_box_and_height():
    from makereel.core.captions import Style
    plain = Style().header()
    boxed = Style(box=True, box_colour="#FF0000", box_opacity=0.6, vertical=0.45).header()
    cap = next(l for l in boxed.splitlines() if l.startswith("Style: Caption"))
    fields = cap.split(",")
    assert fields[15] == "4"                       # BorderStyle 4 = translucent box, outline kept
    assert fields[6] == "&H660000FF"               # 40% transparent red (ASS alpha 0x66)
    assert fields[18] == "2" and fields[21] == str(round(1920 * 0.45))   # bottom-centred, 45% up
    assert next(l for l in plain.splitlines() if l.startswith("Style: Caption")).split(",")[15] == "1"


def test_clean_look_validates():
    assert branding.clean_look({"vertical": "0.4", "box": 1, "box_opacity": 0.5}) == \
        {"vertical": 0.4, "box": True, "box_opacity": 0.5}
    for bad in ({"vertical": 2}, {"size": 9}, {"box_colour": "black"}, {"box_opacity": -1}):
        with pytest.raises(ValueError):
            branding.clean_look(bad)


def test_reel_look_overrides_brand():
    b = config.load_settings().brand
    s = branding.style_for("1x1", b, {"vertical": 0.5, "box": True})
    assert s.vertical == 0.5 and s.box and s.width == s.height == 1080
