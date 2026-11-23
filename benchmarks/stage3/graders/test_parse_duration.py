import pytest
from candidate import parse_duration


@pytest.mark.parametrize(
    "text,expected",
    [("0s", 0), ("1h2m3s", 3723), ("90m", 5400), (" 2h  5s ", 7205), ("10s", 10), ("1h", 3600)],
)
def test_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", " ", "-1s", "1.5h", "1m1h", "2s2s", "1H", "1h junk", "2 h"])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)
