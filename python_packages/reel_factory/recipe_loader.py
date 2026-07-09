"""Compatibility shim for the packaged Reel Factory recipe_loader module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import recipe_loader as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.recipe_loader", run_name="__main__")
else:
    sys.modules[__name__] = _module
