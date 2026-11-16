import pytest

from makereel.core import captions

WORDS = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("one two three four".split())]


def _ass():
    return captions.build_ass(WORDS, 0, 10, "TITLE")


def test_cards_are_written_and_replaced():
    cards = captions.clean_cards([{"kind": "quote", "text": "best line ever", "start": 1, "end": 4},
                                  {"kind": "outro", "text": "Follow for more", "secs": 3}], 10)
    text = captions.set_cards(_ass(), cards, 10)
    assert text.count("Style: Card,") == 1
    assert "“best line ever”" in text and "0:00:07.00,0:00:10.00,Card" in text
    again = captions.set_cards(text, cards[:1], 10)
    assert again.count(",Card,,") == 1 and again.count("Style: Card,") == 1
    assert captions.parse_words(again) == captions.parse_words(_ass())   # captions untouched
    assert ",Card,," not in captions.set_cards(again, [], 10)


def test_bad_cards_are_refused():
    for bad in ([{"kind": "x", "text": "a", "start": 0, "end": 2}],
                [{"kind": "note", "text": "", "start": 0, "end": 2}],
                [{"kind": "note", "text": "a", "start": 2, "end": 2.2}], [{"kind": "outro", "text": "a", "secs": 30}]):
        with pytest.raises(ValueError):
            captions.clean_cards(bad, 10)


def test_shift_cards_after_trim():
    cards = [{"kind": "note", "text": "a", "start": 1, "end": 3, "position": "top"},
             {"kind": "note", "text": "b", "start": 8, "end": 9, "position": "top"},
             {"kind": "outro", "text": "c", "secs": 2, "position": "middle"}]
    out = captions.shift_cards(cards, -2, 5)
    assert out[0]["start"] == 0 and out[0]["end"] == 1
    assert [c["text"] for c in out] == ["a", "c"]
