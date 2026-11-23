"""Future independent grader: a sandbox must supply a module named candidate.

These tests intentionally are not in the project's own pytest collection.
The runner is not implemented in milestone 1.
"""

import pytest
from candidate import clamp


@pytest.mark.parametrize(
    "value,lower,upper,expected",
    [
        (5, 0, 10, 5),
        (-1, 0, 10, 0),
        (11, 0, 10, 10),
        (0, 0, 10, 0),
        (10, 0, 10, 10),
        (2, 3, 3, 3),
        (0.5, 0.0, 1.0, 0.5),
        (-5, -4, -2, -4),
    ],
)
def test_clamp(value, lower, upper, expected):
    assert clamp(value, lower, upper) == expected


def test_invalid_interval():
    with pytest.raises(ValueError):
        clamp(5, 10, 0)
