"""Compatibility shim for the packaged Reel Factory reference_grid_production module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import reference_grid_production as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.reference_grid_production", run_name="__main__")
else:
    sys.modules[__name__] = _module
