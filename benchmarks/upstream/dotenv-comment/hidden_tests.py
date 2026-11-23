import pytest
from candidate import parse_text


@pytest.mark.parametrize("space", ["\t", "  ", " \t"])
def test_empty_values_with_various_whitespace(space):
    assert parse_text("A=" + space + "#ignored\r\nB=ok\r\n") == {"A": "", "B": "ok"}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("A=a#b", "a#b"),
        ("A=a #comment", "a"),
        ("A='# value'", "# value"),
        ('A="# value"', "# value"),
        ("A=", ""),
    ],
)
def test_unchanged_value_semantics(text, expected):
    assert parse_text(text) == {"A": expected}


def test_export_multiline_and_no_equals():
    assert parse_text("export A= #comment\nB='one\ntwo'\nC\n") == {
        "A": "",
        "B": "one\ntwo",
        "C": None,
    }
