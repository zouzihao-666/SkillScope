import pytest
from candidate import parse_text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("\ufeff", {}),
        ("\ufeff# comment\nA=1", {"A": "1"}),
        ("\ufeffexport A=1", {"A": "1"}),
        ("A='\ufeffvalue'", {"A": "\ufeffvalue"}),
        ("A=1\n\ufeffB=2", {"A": "1", "\ufeffB": "2"}),
        ("\ufeff\ufeffA=1", {"\ufeffA": "1"}),
    ],
)
def test_boundary_cases(text, expected):
    assert parse_text(text) == expected
