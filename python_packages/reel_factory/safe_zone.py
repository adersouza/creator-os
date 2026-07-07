"""Compatibility shim for the packaged Reel Factory safe_zone module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import safe_zone as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.safe_zone", run_name="__main__")
else:
    sys.modules[__name__] = _module
