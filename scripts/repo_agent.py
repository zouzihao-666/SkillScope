"""Compatibility entry point; implementation lives in the installed package."""

import sys

from skillscope.repository import agent as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
