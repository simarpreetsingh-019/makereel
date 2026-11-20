from makereel.core import captions, highlights, language, transcribe
from makereel.core.branding import clean_look


def test_script_detection():
    assert language.script_of("क्या बात है") == "devanagari"
    assert language.script_of("ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ") == "gurmukhi"
    assert language.script_of("hola amigos!") == "latin"
    assert language.script_of("やばい本当") == "japanese"
    assert language.script_of("123 !!") == "latin"


def test_hinglish_romanisation():
    cases = {"क्या": "kya", "बात": "baat", "है": "hai", "भाई": "bhai", "करना": "karna", "कमाल": "kamaal",
             "समझ": "samajh", "चलो": "chalo", "नहीं": "nahin", "ज़िंदगी": "zindgi", "अच्छा": "accha",
             "दोस्तों": "doston"}
    for word, roman in cases.items():
        assert language.romanize(word) == roman, word


def test_punjabi_romanisation_and_punctuation():
    assert language.romanize("ਬੱਲੇ") == "balle"
    assert language.romanize("ਵੀਰੇ!") == "veere!"
    assert language.romanize("है।") == "hai."
    assert language.romanize("already latin") == "already latin"


def test_romanised_words_keep_timing():
    words = [{"start": 0.0, "end": 0.4, "word": "क्या"}, {"start": 0.4, "end": 0.9, "word": "बात"}]
    out = language.romanize_words(words)
    assert [w["word"] for w in out] == ["kya", "baat"] and out[1]["start"] == 0.4


def test_hype_in_other_languages():
    ws = lambda t: [{"word": w} for w in t.split()]  # noqa: E731
    assert highlights.hype_count(ws("अरे भाई क्या")) == 3
    assert highlights.hype_count(ws("arre bhai kya")) == 3
    assert highlights.hype_count(ws("vamos increíble")) == 2
    assert highlights.hype_count(ws("これはやばい")) == 1


def test_align_keeps_hindi_vowel_signs():
    # \w-based cleaning used to drop matras, so different words looked the same
    assert captions._norm("की") != captions._norm("का")
    timed = [{"start": 0.0, "end": 0.5, "word": "क्या"}, {"start": 0.5, "end": 1.0, "word": "बात"}]
    out = captions.align("क्या बात", timed)
    assert out[1]["start"] == 0.5


def test_bigger_model_outside_english():
    assert transcribe.model_for("base", "hi", "small") == "small"
    assert transcribe.model_for("base", "en", "small") == "base"
    assert transcribe.model_for("medium", "hi", "small") == "medium"
    assert transcribe.model_for("base", "hi", "same") == "base"
    assert transcribe.model_for("base", None, "small") == "base"


def test_fonts_for_scripts(tmp_path):
    assert language.font_for("latin", "Arial Black", tmp_path) == "Arial Black"
    (tmp_path / "NotoSansDevanagari-Bold.ttf").write_bytes(b"\0\1\0\0")
    assert language.font_for("devanagari", "Arial Black", tmp_path, download=False) == "Noto Sans Devanagari"
    assert language.font_for("gurmukhi", "Arial Black", tmp_path, download=False) != ""


def test_look_script_validation():
    assert clean_look({"script": "roman"}) == {"script": "roman"}
    try:
        clean_look({"script": "klingon"})
    except ValueError:
        pass
    else:
        raise AssertionError


def test_language_switch_needs_a_clear_win():
    from makereel.core import transcribe
    pick = transcribe.pick_language
    assert pick([("en", 0.9), ("hi", 0.05)], "hi", {"hi", "en"}, "hi") == "en"       # clearly English
    assert pick([("en", 0.5), ("hi", 0.4)], "hi", {"hi", "en"}, "hi") == "hi"        # unsure: stay
    assert pick([("fr", 0.9), ("hi", 0.05)], "hi", {"hi", "en"}, "hi") == "hi"       # not allowed: stay


def test_caption_agreement_ignores_script():
    from makereel.core.pipeline import agreement
    a = [{"word": "भाई"}, {"word": "GTA5"}, {"word": "मिशन"}]
    b = [{"word": "bhai"}, {"word": "gta5"}, {"word": "mission"}]
    assert agreement(a, b) > 0.3
