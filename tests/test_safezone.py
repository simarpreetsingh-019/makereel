from pathlib import Path

from makereel.core import safezone
from makereel.core.captions import Style
from makereel.core.render import Logo, _overlay_filters


def _caption_style(header: str) -> list[str]:
    return next(l for l in header.splitlines() if l.startswith("Style: Caption")).split(",")


def test_all_is_strictest():
    z = safezone.ZONES["all"]
    for other in ("tiktok", "reels", "shorts"):
        o = safezone.ZONES[other]
        assert z.top >= o.top and z.bottom >= o.bottom and z.right >= o.right


def test_only_tall_formats_get_a_zone():
    assert safezone.zone_for("all", 1080, 1920) is not None
    assert safezone.zone_for("all", 1080, 1080) is None
    assert safezone.zone_for("off", 1080, 1920) is None


def test_captions_lifted_and_kept_off_the_button_column():
    z = safezone.ZONES["tiktok"]
    st = Style(vertical=0.05, safe=(z.top, z.bottom, z.left, z.right))
    f = _caption_style(st.header())
    margin_l, margin_r, margin_v = int(f[-4]), int(f[-3]), int(f[-2])
    assert margin_v == round(1920 * z.bottom)
    assert margin_r == round(1080 * z.right) > margin_l


def test_no_zone_keeps_exact_placement():
    f = _caption_style(Style(vertical=0.05).header())
    assert int(f[-2]) == round(1920 * 0.05) and f[-4] == f[-3]


def test_logo_stays_below_top_tabs():
    graph, _ = _overlay_filters("0:v", None, None, Logo(Path("l.png"), "top-right", clear_top=0.1), 1080, 1)
    assert "H*0.100" in graph
