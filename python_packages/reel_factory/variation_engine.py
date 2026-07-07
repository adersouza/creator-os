"""Compatibility shim for the packaged Reel Factory variation_engine module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import variation_engine as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.variation_engine", run_name="__main__")
else:
    sys.modules[__name__] = _module
