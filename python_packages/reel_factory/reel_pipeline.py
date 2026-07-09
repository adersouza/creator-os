"""Compatibility shim for the packaged Reel Factory reel_pipeline module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import reel_pipeline as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.reel_pipeline", run_name="__main__")
else:
    sys.modules[__name__] = _module
