"""Compatibility shim for the packaged Reel Factory operator_tools module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import operator_tools as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.operator_tools", run_name="__main__")
else:
    sys.modules[__name__] = _module
