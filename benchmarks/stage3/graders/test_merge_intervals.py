import copy

import pytest
from candidate import merge_intervals


@pytest.mark.parametrize(
    "items,expected",
    [
        ([], []),
        ([[1, 2]], [[1, 2]]),
        ([[5, 7], [1, 3], [2, 6]], [[1, 7]]),
        ([[1, 2], [2, 4]], [[1, 4]]),
        ([[1, 10], [2, 3], [10, 11]], [[1, 11]]),
        ([[3, 3], [1, 1]], [[1, 1], [3, 3]]),
        ([[-3, -1], [-1, 0], [2, 4]], [[-3, 0], [2, 4]]),
        ([[1, 2], [1, 2]], [[1, 2]]),
        ([[0.1, 0.5], [0.5, 0.9]], [[0.1, 0.9]]),
    ],
)
def test_merge(items, expected):
    before = copy.deepcopy(items)
    result = merge_intervals(items)
    assert result == expected
    assert items == before
    assert result is not items


@pytest.mark.parametrize("items", [[[2, 1]], [[0, 10], [8, 3]]])
def test_reversed(items):
    with pytest.raises(ValueError):
        merge_intervals(items)
