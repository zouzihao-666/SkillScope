from pathlib import Path
from shutil import copytree

import pytest

from skillscope.loader import load_experiment

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def config(tmp_path):
    copytree(EXAMPLES, tmp_path / "examples")
    return tmp_path / "examples" / "experiment.json"


@pytest.fixture
def experiment(config):
    return load_experiment(config)
