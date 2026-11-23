import pytest
from candidate import parse_text, round_trip


@pytest.mark.parametrize(
    "value",
    ["C:\\Users\\", "\\d+", "a\\'b", "it's", 'say "hi"', "a\\nb", "plain", "", "line1\nline2"],
)
def test_round_trips(value):
    assert round_trip(value) == {"value": value, "next": "sentinel", "keep": "original"}


def test_auto_quoting():
    assert round_trip("x\\", "auto")["value"] == "x\\"


@pytest.mark.parametrize("quote", ["'", '"'])
def test_escaped_backslash_does_not_swallow_following_binding(quote):
    assert parse_text("A=" + quote + "x\\\\" + quote + "\nB=next\n") == {"A": "x\\", "B": "next"}


def test_multiline_escaped_quote_and_ordinary_values():
    assert parse_text("A='a\\'b'\nB=plain#literal\nC='one\ntwo'\nD\n") == {
        "A": "a'b",
        "B": "plain#literal",
        "C": "one\ntwo",
        "D": None,
    }
