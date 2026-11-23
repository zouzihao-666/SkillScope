"""Future independent grader; not evidence of model performance."""

import copy

import pytest
from candidate import deduplicate


@pytest.mark.parametrize(
    "items,expected",
    [
        ([], []),
        ([3, 1, 3, 2, 1], [3, 1, 2]),
        ([[1], [2], [1]], [[1], [2]]),
        ([{"x": 1}, {"x": 1}, {"x": 2}], [{"x": 1}, {"x": 2}]),
        ([1, True, 2, 1.0], [1, 2]),
    ],
)
def test_deduplicate(items, expected):
    original = copy.deepcopy(items)
    result = deduplicate(items)
    assert result == expected
    assert items == original
    assert result is not items
