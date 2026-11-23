"""Rebuild the manually authored teaching corpus; never use model experiment results here."""

import json
import subprocess
import sys
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "benchmarks/stage3"

SKILLS = {
    "root-cause": (
        ["investigate"],
        "Trace a failing example from the written contract to the current implementation. Explain the mechanism of the defect before proposing a repair. Consider whether several symptoms share one cause.",
    ),
    "minimal-fix": (
        ["implement"],
        "Preserve public names and signatures. Prefer a small, direct repair and avoid unrelated abstractions or new dependencies. Check that the small repair still satisfies the complete written contract.",
    ),
    "edge-cases": (
        ["verify"],
        "Review empty inputs, single elements, repeated values, boundary values, and invalid inputs described by the contract. Try a counterexample to the proposed algorithm, rather than relying only on a happy-path example.",
    ),
    "input-validation": (
        ["investigate", "implement"],
        "Separate input validation from the main transformation. Validate the entire input when the contract requires invalid inputs to raise, even if an early lookup or a shortcut could otherwise return a result.",
    ),
    "compatibility": (
        ["investigate", "verify"],
        "Treat the public interface and documented exception types as compatibility requirements. Avoid mutating caller-owned inputs unless requested. Preserve behavior that the task does not ask to change.",
    ),
    "python-idioms": (
        ["implement"],
        "Consider standard-library and built-in tools before writing a broad custom framework. Sorting, sets, comprehensions, heapq, and regular expressions can simplify repairs. Check ordering, equality, escaping, and duplicate semantics before choosing an idiom.",
    ),
}

TASKS = {
    "merge-intervals": {
        "function": "merge_intervals",
        "instruction": """Repair merge_intervals(intervals). Each interval is a two-number list [start, end].
Return a new list sorted by start with all overlapping OR touching closed intervals merged.
An empty input returns []. A reversed interval (start > end) anywhere in the input must raise ValueError.
Numbers are finite. Do not mutate the input or its nested intervals. Preserve the function signature.
Use only the Python standard library.""",
        "starter": "def merge_intervals(intervals):\n    intervals.sort()\n    return intervals\n",
        "reference": """def merge_intervals(intervals):
    if any(start > end for start, end in intervals):
        raise ValueError('reversed interval')
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result
""",
        "grader": """import copy
import pytest
from candidate import merge_intervals

@pytest.mark.parametrize('items,expected', [
    ([], []), ([[1, 2]], [[1, 2]]),
    ([[5, 7], [1, 3], [2, 6]], [[1, 7]]),
    ([[1, 2], [2, 4]], [[1, 4]]),
    ([[1, 10], [2, 3], [10, 11]], [[1, 11]]),
    ([[3, 3], [1, 1]], [[1, 1], [3, 3]]),
    ([[-3, -1], [-1, 0], [2, 4]], [[-3, 0], [2, 4]]),
    ([[1, 2], [1, 2]], [[1, 2]]),
    ([[0.1, 0.5], [0.5, 0.9]], [[0.1, 0.9]]),
])
def test_merge(items, expected):
    before = copy.deepcopy(items)
    result = merge_intervals(items)
    assert result == expected
    assert items == before
    assert result is not items

@pytest.mark.parametrize('items', [[[2, 1]], [[0, 10], [8, 3]]])
def test_reversed(items):
    with pytest.raises(ValueError):
        merge_intervals(items)
""",
    },
    "get-path": {
        "function": "get_path",
        "instruction": r"""Repair get_path(data, path, default). Traverse nested dictionaries using a dotted string path.
A backslash escapes only a dot or another backslash: a\.b.c addresses key 'a.b' then key 'c'.
The empty path, empty segments, trailing backslash, and other escapes are invalid and must raise ValueError.
Validate the COMPLETE path before traversal, even if an earlier key is missing.
Return default for a missing key or a non-dictionary encountered before the end. Return stored None as None.
Do not mutate inputs. Arguments are ordinary JSON values; path is a string. Preserve the signature.
Use only the Python standard library.""",
        "starter": "def get_path(data, path, default):\n    for key in path.split('.'):\n        data = data[key]\n    return data\n",
        "reference": r"""def get_path(data, path, default):
    parts, segment = [], []
    index = 0
    while index < len(path):
        char = path[index]
        if char == chr(92):
            index += 1
            if index == len(path) or path[index] not in ('.', chr(92)):
                raise ValueError('invalid escape')
            segment.append(path[index])
        elif char == '.':
            if not segment:
                raise ValueError('empty segment')
            parts.append(''.join(segment))
            segment = []
        else:
            segment.append(char)
        index += 1
    if not segment:
        raise ValueError('empty segment')
    parts.append(''.join(segment))
    for key in parts:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data
""",
        "grader": r"""import copy
import pytest
from candidate import get_path

@pytest.mark.parametrize('data,path,default,expected', [
    ({'a': {'b': 2}}, 'a.b', 9, 2),
    ({'a.b': {'c': 3}}, 'a' + chr(92) + '.b.c', 9, 3),
    ({'a' + chr(92) + 'b': 4}, 'a' + chr(92) * 2 + 'b', 9, 4),
    ({'a': None}, 'a', 9, None),
    ({'a': None}, 'a.b', 9, 9),
    ({}, 'missing', 9, 9),
    ({'a': [1, 2]}, 'a.0', 9, 9),
    ({'中文': {'值': 7}}, '中文.值', None, 7),
])
def test_get(data, path, default, expected):
    before = copy.deepcopy(data)
    assert get_path(data, path, default) == expected
    assert data == before

@pytest.mark.parametrize('path', ['', '.a', 'a.', 'a..b', 'a' + chr(92),
                                  'a' + chr(92) + 'x', 'missing.' + chr(92) + 'x'])
def test_invalid(path):
    with pytest.raises(ValueError):
        get_path({}, path, 9)

def test_default_identity():
    default = []
    assert get_path({}, 'missing', default) is default
""",
    },
    "toposort": {
        "function": "toposort",
        "instruction": """Repair toposort(graph). graph maps each string node to a list of its prerequisite node names.
Include nodes mentioned only as prerequisites. Repeated prerequisites count only once.
Return a topological ordering, choosing the lexicographically smallest CURRENTLY AVAILABLE node at every step.
For example {'a': ['z'], 'b': []} returns ['b', 'z', 'a'].
Raise ValueError for any cycle including self-loops. Empty input returns []. Do not mutate input dictionaries or lists.
Keys and prerequisite names are strings, values are lists. Preserve the signature and use only the standard library.""",
        "starter": "def toposort(graph):\n    return sorted(graph)\n",
        "reference": """def toposort(graph):
    import heapq
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)
    dependencies = {node: set(graph.get(node, [])) for node in nodes}
    children = {node: [] for node in nodes}
    for node, deps in dependencies.items():
        for dep in deps:
            children[dep].append(node)
    ready = [node for node in nodes if not dependencies[node]]
    heapq.heapify(ready)
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for child in children[node]:
            dependencies[child].remove(node)
            if not dependencies[child]:
                heapq.heappush(ready, child)
    if len(result) != len(nodes):
        raise ValueError('cycle')
    return result
""",
        "grader": """import copy
import pytest
from candidate import toposort

@pytest.mark.parametrize('graph,expected', [
    ({}, []), ({'b': [], 'a': []}, ['a', 'b']),
    ({'a': ['b']}, ['b', 'a']),
    ({'a': ['z'], 'b': []}, ['b', 'z', 'a']),
    ({'a': ['b', 'b'], 'b': []}, ['b', 'a']),
    ({'d': ['b', 'c'], 'b': ['a'], 'c': ['a']}, ['a', 'b', 'c', 'd']),
    ({'z': ['x'], 'a': [], 'x': ['a']}, ['a', 'x', 'z']),
    ({'c': ['b'], 'a': [], 'b': []}, ['a', 'b', 'c']),
])
def test_order(graph, expected):
    before = copy.deepcopy(graph)
    assert toposort(graph) == expected
    assert graph == before

@pytest.mark.parametrize('graph', [{'a': ['a']}, {'a': ['b'], 'b': ['a']},
                                 {'a': [], 'b': ['c'], 'c': ['b']}])
def test_cycle(graph):
    with pytest.raises(ValueError):
        toposort(graph)
""",
    },
    "parse-duration": {
        "function": "parse_duration",
        "instruction": """Repair parse_duration(text). Parse one or more nonnegative integer counts immediately followed by lowercase h, m, s.
Units may be omitted but must occur at most once in h-then-m-then-s order. Allow whitespace around and between tokens.
Counts may exceed 59; for example '90m' is 5400 seconds. Return integer total seconds.
Reject empty/whitespace-only input, negative/decimal values, repeated/out-of-order units, uppercase units and junk with ValueError.
Preserve the function signature. Use only the standard library.""",
        "starter": "def parse_duration(text):\n    return int(text[:-1])\n",
        "reference": r"""def parse_duration(text):
    import re
    match = re.fullmatch(r'\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s\s*)?', text)
    if match is None or all(value is None for value in match.groups()):
        raise ValueError('invalid duration')
    hours, minutes, seconds = (int(value or 0) for value in match.groups())
    return 3600 * hours + 60 * minutes + seconds
""",
        "grader": """import pytest
from candidate import parse_duration

@pytest.mark.parametrize('text,expected', [('0s', 0), ('1h2m3s', 3723), ('90m', 5400),
    (' 2h  5s ', 7205), ('10s', 10), ('1h', 3600)])
def test_duration(text, expected):
    assert parse_duration(text) == expected

@pytest.mark.parametrize('text', ['', ' ', '-1s', '1.5h', '1m1h', '2s2s', '1H', '1h junk', '2 h'])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)
""",
    },
}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def main():
    specs = []
    for name, (stages, text) in SKILLS.items():
        write(DEST / f"skills/{name}.md", f"# {name}\n\n{text}")
        specs.append({"id": name, "file": f"skills/{name}.md", "stages": stages})
    tasks = []
    references = {
        "clamp": "def clamp(value, lower, upper):\n    if lower > upper: raise ValueError()\n    return min(upper, max(lower, value))\n",
        "deduplicate": "def deduplicate(items):\n    out = []\n    for item in items:\n        if item not in out: out.append(item)\n    return out\n",
    }
    for name in (
        "clamp",
        "merge-intervals",
        "get-path",
        "toposort",
        "deduplicate",
        "parse-duration",
    ):
        task_root = DEST / f"tasks/{name}"
        if name in ("clamp", "deduplicate"):
            for filename in ("instruction.md", "starter.py"):
                destination = task_root / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                copyfile(ROOT / f"examples/tasks/{name}/{filename}", destination)
            write(
                DEST / f"graders/test_{name.replace('-', '_')}.py",
                (ROOT / f"examples/graders/test_{name}.py").read_text(encoding="utf-8"),
            )
            write(DEST / f"references/{name}.py", references[name])
        else:
            item = TASKS[name]
            write(task_root / "instruction.md", item["instruction"])
            write(task_root / "starter.py", item["starter"])
            write(DEST / f"graders/test_{name.replace('-', '_')}.py", item["grader"])
            write(DEST / f"references/{name}.py", item["reference"])
        tasks.append(
            {
                "id": name,
                "split": "holdout" if name in ("deduplicate", "parse-duration") else "discovery",
                "instruction_file": f"tasks/{name}/instruction.md",
                "starter_file": f"tasks/{name}/starter.py",
                "grader_file": f"graders/test_{name.replace('-', '_')}.py",
            }
        )
    write(
        DEST / "experiment.json",
        json.dumps(
            {
                "schema_version": 1,
                "name": "skillscope-stage3",
                "model": "deepseek-flash",
                "skills": specs,
                "tasks": tasks,
            },
            indent=2,
        ),
    )
    subprocess.run([sys.executable, "-m", "ruff", "format", str(DEST)], check=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", str(DEST)], check=True)


if __name__ == "__main__":
    main()
