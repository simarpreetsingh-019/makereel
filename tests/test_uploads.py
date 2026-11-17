"""Watching channels for new uploads (not only live streams)."""
import json

from makereel.core import sources
from makereel.services import watcher as watcher_mod
from makereel.services.watcher import Watcher


def test_uploads_url():
    assert sources.channel_uploads_url("@name") == "https://www.youtube.com/@name/videos"
    assert sources.channel_uploads_url("https://www.youtube.com/@name/live") == "https://www.youtube.com/@name/videos"
    assert sources.channel_uploads_url("https://youtube.com/channel/UC1/") == "https://youtube.com/channel/UC1/videos"
    assert sources.channel_uploads_url("twitch.tv/name") is None


class FakeJobs:
    def __init__(self):
        self.links = []

    def submit_link(self, url, options):
        self.links.append(url)


def _up(i):
    return sources.Upload(i, f"https://www.youtube.com/watch?v={i}", i, 600)


def test_first_look_skips_then_new_uploads_are_clipped(tmp_path, monkeypatch):
    listing = {"@a": [_up("v2"), _up("v1")]}
    monkeypatch.setattr(watcher_mod.sources, "recent_uploads", lambda ch: listing[ch])
    jobs = FakeJobs()
    w = Watcher(jobs, tmp_path / "makereel.json")
    settings = {"channels": ["@a"]}

    w._check_uploads(settings)                      # first look: back catalogue is not clipped
    assert jobs.links == []
    assert json.loads((tmp_path / "seen_uploads.json").read_text())["@a"] == ["v2", "v1"]

    listing["@a"] = [_up("v4"), _up("v3"), _up("v2")]
    w._check_uploads(settings)                      # two new ones, oldest first
    assert jobs.links == ["https://www.youtube.com/watch?v=v3", "https://www.youtube.com/watch?v=v4"]

    w._check_uploads(settings)                      # nothing new: nothing queued twice
    assert len(jobs.links) == 2
