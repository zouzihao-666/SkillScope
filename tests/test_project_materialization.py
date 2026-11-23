import os

import pytest

from skillscope.sandbox import materialize_project


@pytest.mark.parametrize(
    "files",
    [
        {"../escape.py": ""},
        {"/absolute.py": ""},
        {"C:/file.py": ""},
        {"a\\b.py": ""},
        {"a//b.py": ""},
        {"candidate.py": ""},
        {"CANDIDATE.py": ""},
        {"candidate.py/module.py": ""},
        {"a.py": "", "A.py": ""},
        {"a": "", "a/b.py": ""},
        {"nul.txt": ""},
        {"a./b.py": ""},
        {"a/b.py ": ""},
        {"a?.py": ""},
        {"x.py": None},
        {"big.py": "x" * 65537},
        {f"{i}.py": "" for i in range(17)},
    ],
)
def test_inventory_rejected_before_any_write(tmp_path, files):
    with pytest.raises(ValueError):
        materialize_project(tmp_path, files)
    assert not list(tmp_path.iterdir())


def test_materialization_writes_resources_without_executing_python(tmp_path):
    files = {"pkg/code.py": "raise RuntimeError('never on host')", "pkg/data.json": '{"x":1}'}
    materialize_project(tmp_path, files)
    assert {
        str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file()
    } == set(files)
    assert (tmp_path / "pkg/data.json").read_text() == files["pkg/data.json"]
    if os.name != "nt":
        assert tmp_path.stat().st_mode & 0o777 == 0o755
        assert (tmp_path / "pkg/data.json").stat().st_mode & 0o777 == 0o444
