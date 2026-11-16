"""Safe zones: the parts of a vertical reel that each app covers with its own buttons and text.

TikTok, Instagram Reels and YouTube Shorts draw the like/comment/share column down the right edge,
the account name and description across the bottom, and tabs or a search bar across the top.
Captions, the title and the logo are kept out of those areas so nothing important is hidden.

Values are shares of the frame (top, bottom, left, right), measured on a 1080x1920 reel from each
app's current layout. They are deliberately a little generous: apps move things between versions.
"all" is the strictest of the three, so one reel can be posted everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    top: float
    bottom: float
    left: float
    right: float

    def px(self, width: int, height: int) -> dict[str, int]:
        return {"top": round(self.top * height), "bottom": round(self.bottom * height),
                "left": round(self.left * width), "right": round(self.right * width)}


ZONES: dict[str, Zone] = {
    "tiktok": Zone(top=0.08, bottom=0.21, left=0.05, right=0.14),
    "reels": Zone(top=0.10, bottom=0.20, left=0.05, right=0.12),
    "shorts": Zone(top=0.08, bottom=0.19, left=0.05, right=0.13),
}
ZONES["all"] = Zone(*(max(getattr(z, f) for z in ZONES.values()) for f in ("top", "bottom", "left", "right")))
CHOICES = ("all", "tiktok", "reels", "shorts", "off")
LABELS = {"all": "All apps", "tiktok": "TikTok", "reels": "Instagram Reels", "shorts": "YouTube Shorts",
          "off": "Off"}


def zone_for(name: str | None, width: int, height: int) -> Zone | None:
    """The zone to keep clear for this shape. Only tall (9:16-like) videos get app overlays."""
    if not name or name == "off" or name not in ZONES or height / width < 1.5:
        return None
    return ZONES[name]
