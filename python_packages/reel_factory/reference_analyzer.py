"""Compatibility shim for the packaged Reel Factory reference_analyzer module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import reference_analyzer as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.reference_analyzer", run_name="__main__")
else:
    sys.modules[__name__] = _module
