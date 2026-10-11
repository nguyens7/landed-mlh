import pytest

from normalize import collapse_run, lex, normalize_for_wer, spell_callsign


@pytest.mark.parametrize("text,expected", [
    ("five hundred", "500"),
    ("one thousand five hundred", "1500"),
    ("fifteen hundred", "1500"),
    ("niner hundred", "900"),
    ("one thousand", "1000"),
    ("one thousand two hundred feet", "1200 feet"),
    ("two six four six", "2646"),
    ("seven seven zero zero", "7700"),
    ("1,500 feet", "1500 feet"),
])
def test_spoken_numbers(text, expected):
    assert normalize_for_wer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("MEDEVAC Two Six Four Six X-Ray", "medevac 2646x"),
    ("November Three One Two Lima Mike", "n312lm"),
    ("N2646X", "n2646x"),
    ("oscar kilo mike delta hotel", "okmdh"),
    ("MEDEVAC Seven Six One November Yankee", "medevac 761ny"),
])
def test_phonetic_letters(text, expected):
    assert normalize_for_wer(text) == expected


def test_lone_letter_stays_a_word():
    assert normalize_for_wer("runway two seven and a left") == "runway 27 and a left"


def test_lexer_tokens():
    assert lex("MEDEVAC Two Six X-Ray, five hundred") == ["medevac", "2", "6", "X", ",", "5", "hundred"]


def test_collapse_run_tens():
    assert collapse_run(["seventy", "5"]) == "75"
    assert collapse_run(["twenty", "5", "hundred"]) == "2500"


def test_spell_callsign():
    assert spell_callsign("2646X") == "Two Six Four Six X-Ray"
