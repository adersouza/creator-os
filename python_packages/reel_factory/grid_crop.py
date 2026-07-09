"""Compatibility shim for the packaged Reel Factory grid_crop module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import grid_crop as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.grid_crop", run_name="__main__")
else:
    sys.modules[__name__] = _module
