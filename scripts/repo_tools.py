"""Compatibility module for historical experiment scripts."""

import sys

from skillscope.repository import tools as _implementation

sys.modules[__name__] = _implementation
