"""Speech-model suggestions per computer, model choice per language, and update version checks."""
from makereel.core import models, transcribe
from makereel.services import updates


def pc(ram, gpu=None, cuda=False, disk=100):
    return {"ram_gb": ram, "cores": 8, "free_disk_gb": disk, "gpu": gpu, "cuda": cuda}


def test_recommendations(monkeypatch):
    monkeypatch.setattr(models, "installed", lambda name: False)
    r = models.recommend(pc(16, {"name": "NVIDIA GeForce RTX 4070", "vram_gb": 12.0}, cuda=True))
    assert (r["model"], r["model_other"], r["device"]) == ("distil-large-v3", "large-v3", "gpu")
    assert models.recommend(pc(16))["model_other"] == "medium"                # Mac / no NVIDIA
    assert models.recommend(pc(8))[("model")] == "small"
    assert models.recommend(pc(4))["model_other"] == "small"
    # a GPU whose CUDA libraries aren't installed doesn't count
    assert models.recommend(pc(8, {"name": "RTX", "vram_gb": 12.0}, cuda=False))["device"] == "cpu"
    assert models.recommend(pc(16), "indian")["model"] == "small"
    assert not models.recommend(pc(16, disk=1))["fits_disk"]


def test_model_per_language():
    mf = transcribe.model_for
    assert mf("distil-large-v3", "en", "large-v3") == "distil-large-v3"
    assert mf("distil-large-v3", "hi", "large-v3") == "large-v3"          # English-only can't do Hindi
    assert mf("distil-large-v3", "hi", "same") == "small"
    assert mf("base", "hi", "small") == "small"
    assert mf("large-v3", "hi", "medium") == "large-v3"                   # keep the bigger one
    assert mf("medium", None, "small") == "medium"


def test_versions():
    assert updates.version_tuple("v0.10.2") == (0, 10, 2)
    assert updates.newer("0.7.0", "0.6.0") and updates.newer("v0.10.0", "0.9.9")
    assert not updates.newer("0.6.0", "0.6.0") and not updates.newer("0.6.0-beta", "0.6.0")


def test_update_check_off_means_no_request(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(updates, "_fetch_latest", lambda repo: called.append(repo))
    from makereel.config import save_settings
    save_settings({"update_check": False})
    info = updates.check()                          # turned off: no request to GitHub at all
    assert info["available"] is False and called == []
    assert info["repo"] == "simarpreetsingh-019/makereel"


def test_hinglish_routing():
    mf = transcribe.model_for
    assert mf("distil-large-v3", "hi", "hinglish") == "hinglish"            # Hindi speech -> Hinglish
    assert mf("distil-large-v3", "en", "hinglish") == "distil-large-v3"     # English stays on the English model
    assert mf("base", "hi", "hinglish", "original") != "hinglish"           # Hindi script wanted: not Hinglish
    assert mf("base", "ta", "hinglish") != "hinglish"                       # Tamil: Hinglish model can't


def test_indian_focus_suggests_hinglish(monkeypatch):
    monkeypatch.setattr(models, "installed", lambda name: False)
    assert models.recommend(pc(16), "indian")["model_other"] == "hinglish"
    assert models.recommend(pc(4), "indian")["model_other"] == "hinglish-lite"
    assert models.source("hinglish").endswith("-ct2") and models.source("small") == "small"
