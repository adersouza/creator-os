"""Compatibility shim for the packaged Reel Factory generate_variants module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import generate_variants as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.generate_variants", run_name="__main__")
else:
    sys.modules[__name__] = _module
