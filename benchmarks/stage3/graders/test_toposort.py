import copy

import pytest
from candidate import toposort


@pytest.mark.parametrize(
    "graph,expected",
    [
        ({}, []),
        ({"b": [], "a": []}, ["a", "b"]),
        ({"a": ["b"]}, ["b", "a"]),
        ({"a": ["z"], "b": []}, ["b", "z", "a"]),
        ({"a": ["b", "b"], "b": []}, ["b", "a"]),
        ({"d": ["b", "c"], "b": ["a"], "c": ["a"]}, ["a", "b", "c", "d"]),
        ({"z": ["x"], "a": [], "x": ["a"]}, ["a", "x", "z"]),
        ({"c": ["b"], "a": [], "b": []}, ["a", "b", "c"]),
    ],
)
def test_order(graph, expected):
    before = copy.deepcopy(graph)
    assert toposort(graph) == expected
    assert graph == before


@pytest.mark.parametrize(
    "graph", [{"a": ["a"]}, {"a": ["b"], "b": ["a"]}, {"a": [], "b": ["c"], "c": ["b"]}]
)
def test_cycle(graph):
    with pytest.raises(ValueError):
        toposort(graph)
