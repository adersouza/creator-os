"""Compatibility shim for the packaged Reel Factory render_plan module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import render_plan as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.render_plan", run_name="__main__")
else:
    sys.modules[__name__] = _module
