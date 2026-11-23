"""Compatibility module for historical experiment scripts."""

import sys

from skillscope.repository import workspace as _implementation

sys.modules[__name__] = _implementation
