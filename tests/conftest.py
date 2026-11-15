"""Point every test at a throwaway output dir and config so real data is never touched."""
import pytest

from makereel import config


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAKEREEL_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("MAKEREEL_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("MAKEREEL_CONFIG", str(tmp_path / "makereel.json"))
    config._env_cache = None
    yield tmp_path
    config._env_cache = None
