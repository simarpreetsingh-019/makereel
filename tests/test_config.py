
import pytest

from makereel import config
from makereel.errors import ConfigError


def test_defaults_without_file():
    s = config.load_settings()
    assert s["poll_minutes"] == 4 and s.clip["profile"] == "gameplay"


def test_save_validates_and_merges():
    config.save_settings({"channels": [" @a ", "", "@b"], "poll_minutes": "6", "clip": {"max_clips": 3}})
    s = config.load_settings()
    assert s["channels"] == ["@a", "@b"] and s["poll_minutes"] == 6 and s.clip["max_clips"] == 3


@pytest.mark.parametrize("bad", [{"nope": 1}, {"poll_minutes": 0}, {"clip": {"profile": "x"}},
                                 {"clip": {"min_len": 50, "max_len": 10}}])
def test_bad_settings_rejected(bad):
    with pytest.raises(ConfigError):
        config.save_settings(bad)


def test_with_clip_ignores_blank_overrides():
    s = config.load_settings().with_clip(profile="", max_clips=None, layout="crop")
    assert s.clip["profile"] == "gameplay" and s.clip["layout"] == "crop"


def test_env_and_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("MAKEREEL_THREADS", raising=False)
    (tmp_path / ".env").write_text("MAKEREEL_THREADS=3\n# comment\nMAKEREEL_ALLOWED_ORIGINS=https://a.app/, https://b.app\n")
    config._env_cache = None
    e = config.env()
    assert e.threads == 3 and e.allowed_origins == ("https://a.app", "https://b.app")


def test_invalid_json_is_a_config_error(tmp_path):
    (tmp_path / "makereel.json").write_text("{oops")
    with pytest.raises(ConfigError):
        config.load_settings()
