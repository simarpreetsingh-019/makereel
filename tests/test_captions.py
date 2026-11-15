import pytest

from makereel.core import captions
from makereel.core.captions import Style

WORDS = [{"start": 10.0 + i, "end": 10.5 + i, "word": w} for i, w in enumerate("hello there big world".split())]


def make():
    return captions.build_ass(WORDS, 10.0, 15.0, "Big title")


def test_round_trip_words_and_hook():
    ass = make()
    words = captions.parse_words(ass)
    assert [w["word"] for w in words] == ["HELLO", "THERE", "BIG", "WORLD"]
    assert words[0]["start"] == 0.0 and words[3]["start"] == 3.0
    assert captions.parse_hook(ass) == "BIG TITLE"


def test_align_spelling_fix_keeps_timing():
    words = captions.align("HELLO THERE GTA WORLD", captions.parse_words(make()))
    assert [w["word"] for w in words] == ["HELLO", "THERE", "GTA", "WORLD"]
    assert [w["start"] for w in words] == [0.0, 1.0, 2.0, 3.0]


def test_align_unchanged_words_keep_timing_when_words_are_added():
    words = captions.align("HELLO THERE VERY BIG WORLD", captions.parse_words(make()))
    by_word = {w["word"]: w["start"] for w in words}
    assert by_word["HELLO"] == 0.0 and by_word["BIG"] == 2.0 and by_word["WORLD"] == 3.0
    assert by_word["THERE"] < by_word["VERY"] < by_word["BIG"]


def test_align_handles_removed_words():
    words = captions.align("HELLO WORLD", captions.parse_words(make()))
    assert [(w["word"], w["start"]) for w in words] == [("HELLO", 0.0), ("WORLD", 3.0)]


def test_align_onto_fresh_transcription_uses_new_times():
    fresh = [{"start": 0.3, "end": 0.6, "word": "hello"}, {"start": 0.7, "end": 1.0, "word": "their"},
             {"start": 1.4, "end": 1.7, "word": "big"}, {"start": 1.8, "end": 2.2, "word": "world"}]
    words = captions.align("HELLO THERE BIG WORLD", fresh)
    assert [w["start"] for w in words] == [0.3, 0.7, 1.4, 1.8]


def test_shift_never_goes_negative():
    shifted = captions.shift(captions.parse_words(make()), -0.5)
    assert shifted[0]["start"] == 0.0 and shifted[1]["start"] == 0.5


def test_clean_timings_sorts_and_validates():
    assert [w["word"] for w in captions.clean_timings([{"start": 2, "end": 3, "word": "b"},
                                                      {"start": 1, "end": 2, "word": "a"}])] == ["a", "b"]
    with pytest.raises(ValueError):
        captions.clean_timings([{"start": "x", "end": 1, "word": "a"}])


def test_rebuild_keeps_custom_styles_unless_restyled():
    custom = make().replace("Arial Black,86", "Impact,90")
    words = captions.parse_words(custom)
    assert "Impact,90" in captions.rebuild(custom, words, "x")
    square = captions.rebuild(custom, words, "x", Style(width=1080, height=1080, font="Inter"))
    assert "PlayResY: 1080" in square and "Style: Caption,Inter," in square


def test_style_matches_original_reel_look():
    header = Style().header()
    assert "Style: Caption,Arial Black,86," in header and "PlayResX: 1080\nPlayResY: 1920" in header


def test_colours():
    assert captions.ass_colour("#FFDD00") == "&H0000DDFF"
    with pytest.raises(ValueError):
        captions.ass_colour("yellow")


def test_braces_are_stripped_from_words():
    ass = captions.build_ass([{"start": 0, "end": 1, "word": "{evil}"}], 0, 2, None)
    assert "{evil}" not in ass


def test_templates_are_distinct_and_readable():
    w = [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": x} for i, x in enumerate("one two three four".split())]
    active = {}
    for t in captions.TEMPLATES:
        ass = captions.build_ass(w, 0, 3, None, template=t)
        line = next(l for l in ass.splitlines() if l.startswith("Dialogue: 0"))
        active[t] = line.split(",,", 1)[1]
        assert [x["word"].lower() for x in captions.parse_words(ass)] == [x["word"] for x in w], t
    assert len(set(active.values())) == len(active)                 # every style looks different
    assert "\\c&H00141414&" in active["boxed"]                       # dark text on the box (readable)
    assert "\\c&H00FFFFFF&" in active["glow"] and "\\blur" in active["glow"]   # sharp white word, blurred halo
    assert active["single"].count(" ") == 0                          # one word at a time
    assert "one" in active["minimal"]                                # normal case
