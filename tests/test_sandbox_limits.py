import subprocess
import sys

import pytest

from skillscope.sandbox import CandidateError, bounded_process


def test_stdout_is_bounded_before_it_can_exhaust_host_memory():
    with pytest.raises(CandidateError, match="output limit"):
        bounded_process([sys.executable, "-c", "import os; os.write(1, b'x' * 1000000)"], b"", 10)


def test_process_wall_timeout_kills_the_client():
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_process([sys.executable, "-c", "import time; time.sleep(5)"], b"", 0.2)
