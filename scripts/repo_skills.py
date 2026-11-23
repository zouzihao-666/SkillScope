"""Compatibility module for historical experiment scripts."""

import sys

from skillscope.repository import guides as _implementation

sys.modules[__name__] = _implementation
