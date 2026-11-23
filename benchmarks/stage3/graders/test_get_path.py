import copy

import pytest
from candidate import get_path


@pytest.mark.parametrize(
    "data,path,default,expected",
    [
        ({"a": {"b": 2}}, "a.b", 9, 2),
        ({"a.b": {"c": 3}}, "a" + chr(92) + ".b.c", 9, 3),
        ({"a" + chr(92) + "b": 4}, "a" + chr(92) * 2 + "b", 9, 4),
        ({"a": None}, "a", 9, None),
        ({"a": None}, "a.b", 9, 9),
        ({}, "missing", 9, 9),
        ({"a": [1, 2]}, "a.0", 9, 9),
        ({"中文": {"值": 7}}, "中文.值", None, 7),
    ],
)
def test_get(data, path, default, expected):
    before = copy.deepcopy(data)
    assert get_path(data, path, default) == expected
    assert data == before


@pytest.mark.parametrize(
    "path", ["", ".a", "a.", "a..b", "a" + chr(92), "a" + chr(92) + "x", "missing." + chr(92) + "x"]
)
def test_invalid(path):
    with pytest.raises(ValueError):
        get_path({}, path, 9)


def test_default_identity():
    default = []
    assert get_path({}, "missing", default) is default
