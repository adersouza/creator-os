"""Compatibility shim for the packaged Reel Factory overnight_grid_worker module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import overnight_grid_worker as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.overnight_grid_worker", run_name="__main__")
else:
    sys.modules[__name__] = _module
