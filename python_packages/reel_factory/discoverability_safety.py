"""Compatibility shim for the packaged Reel Factory discoverability_safety module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import discoverability_safety as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.discoverability_safety", run_name="__main__")
else:
    sys.modules[__name__] = _module
