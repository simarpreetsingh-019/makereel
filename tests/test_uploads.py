"""Watching channels for new uploads (not only live streams)."""
import json
import time

import pytest

from makereel.config import ConfigError, since_cutoff, validate_since
from makereel.core import sources
from makereel.services import watcher as watcher_mod
from makereel.services.watcher import Watcher, uploads_wait


def test_uploads_url():
    assert sources.channel_uploads_url("@name") == "https://www.youtube.com/@name/videos"
    assert sources.channel_uploads_url("https://www.youtube.com/@name/live") == "https://www.youtube.com/@name/videos"
    assert sources.channel_uploads_url("https://youtube.com/channel/UC1/") == "https://youtube.com/channel/UC1/videos"
    assert sources.channel_uploads_url("twitch.tv/name") is None


def test_published_from_info():
    assert sources._published({"timestamp": 100}) == 100.0
    assert sources._published({"upload_date": "20260102"}) == 1767312000.0
    assert sources._published({}) is None


def test_since_settings():
    assert validate_since("24h") == "24h" and validate_since("2026-11-01") == "2026-11-01"
    with pytest.raises(ConfigError):
        validate_since("yesterday")
    assert since_cutoff("new", 1000.0) is None
    assert since_cutoff("48h", 200000.0) == 200000.0 - 48 * 3600


def test_uploads_wait():
    assert uploads_wait("10") == 600
    assert all(240 <= uploads_wait("random") <= 1800 for _ in range(50))


class FakeJobs:
    def __init__(self):
        self.links = []

    def submit_link(self, url, options):
        self.links.append(url.rsplit("=", 1)[1])


def _up(i):
    return sources.Upload(i, f"https://www.youtube.com/watch?v={i}", i, 600)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    listing, ages = {}, {}
    monkeypatch.setattr(watcher_mod.sources, "recent_uploads", lambda ch: listing[ch])
    now = time.time()

    class Probe:
        def __init__(self, url):
            self.published = now - ages[url.rsplit("=", 1)[1]] * 3600

    monkeypatch.setattr(watcher_mod.sources, "probe", Probe)
    jobs = FakeJobs()
    return Watcher(jobs, tmp_path / "makereel.json"), jobs, listing, ages, tmp_path


def test_new_only_skips_back_catalogue(setup):
    w, jobs, listing, _, tmp = setup
    listing["@a"] = [_up("v2"), _up("v1")]
    settings = {"channels": ["@a"], "uploads_since": "new"}
    w._check_uploads(settings)
    assert jobs.links == []
    listing["@a"] = [_up("v4"), _up("v3"), _up("v2")]
    w._check_uploads(settings)
    assert jobs.links == ["v3", "v4"]                      # oldest first
    w._check_uploads(settings)
    assert jobs.links == ["v3", "v4"]                      # never twice
    assert json.loads((tmp / "seen_uploads.json").read_text())["@a"]["done"] == ["v3", "v4"]


def test_lookback_catches_up_then_widening_finds_more(setup):
    w, jobs, listing, ages, _ = setup
    listing["@a"] = [_up("a"), _up("b"), _up("c"), _up("d")]
    ages.update(a=2, b=20, c=30, d=60)                     # hours ago
    w._check_uploads({"channels": ["@a"], "uploads_since": "24h"})
    assert jobs.links == ["b", "a"]
    w._check_uploads({"channels": ["@a"], "uploads_since": "48h"})
    assert jobs.links == ["b", "a", "c"]                   # c was skipped before; d is still too old


def test_old_seen_file_format_is_upgraded(setup):
    w, jobs, listing, _, tmp = setup
    (tmp / "seen_uploads.json").write_text(json.dumps({"@a": ["v1"]}))
    listing["@a"] = [_up("v2"), _up("v1")]
    w._check_uploads({"channels": ["@a"], "uploads_since": "new"})
    assert jobs.links == ["v2"]


def test_ydl_opts_with_and_without_browser_sign_in(monkeypatch):
    import makereel.config as config
    real = config.load_settings
    assert "cookiesfrombrowser" not in sources.ydl_opts()
    signed_in = real().__class__({**real().data, "cookies_browser": "chrome"})
    monkeypatch.setattr(config, "load_settings", lambda *a: signed_in)
    assert sources.ydl_opts()["cookiesfrombrowser"] == ("chrome",)
    assert "--cookies-from-browser" in sources.live_chat_command("https://youtu.be/x", __import__("pathlib").Path("c"))
