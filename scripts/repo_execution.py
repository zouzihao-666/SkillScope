"""Import-only multi-module grading prototype using the existing external Docker grader.

The bootstrap below is a string. Candidate Python is compiled/executed only by
the container worker; this module never imports candidate project modules.
File-system assets, subprocess projects and namespace packages are not supported.
"""

import json
from pathlib import Path

from scripts.repo_workspace import Workspace
from skillscope.sandbox import grade

BOOTSTRAP = """
import importlib.abc as _abc
import importlib.util as _util
import sys as _sys

class _WorkspaceLoader(_abc.MetaPathFinder, _abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _SOURCES:
            return None
        source, is_package, filename = _SOURCES[fullname]
        return _util.spec_from_loader(fullname, self, is_package=is_package)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source, is_package, filename = _SOURCES[module.__name__]
        module.__file__ = '<workspace/' + filename + '>'
        exec(compile(source, module.__file__, 'exec'), module.__dict__)

_sys.meta_path.insert(0, _WorkspaceLoader())
"""


def bundle(workspace: Workspace) -> str:
    sources = {}
    for path, text in workspace.snapshot().items():
        package = path.endswith("/__init__.py")
        name = path[:-12] if package else path[:-3]
        components = name.split("/")
        if not all(component.isidentifier() for component in components):
            raise ValueError("Prototype requires importable Python module names")
        name = ".".join(components)
        if name in sources:
            raise ValueError("Ambiguous module/package name")
        sources[name] = (text, package, path)
    return "_SOURCES = " + repr(sources) + "\n" + BOOTSTRAP + "\n" + workspace.adapter


def grade_workspace(
    workspace: Workspace, docker: str, image: str, output: Path, hidden: bool = False
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    (output / "workspace.json").write_text(
        json.dumps(
            {
                "task": workspace.task_id,
                "initial_fingerprint": workspace.initial_fingerprint,
                "current_fingerprint": workspace.fingerprint(),
                "files": workspace.snapshot(),
                "grading": "hidden" if hidden else "public",
                "execution": "virtual Python modules inside Docker; no physical project filesystem",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    grader = workspace.hidden_grader if hidden else workspace.public_grader
    return grade(bundle(workspace), grader, docker, image, output)
