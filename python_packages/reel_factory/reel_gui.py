"""Compatibility shim for the packaged Reel Factory reel_gui module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import reel_gui as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.reel_gui", run_name="__main__")
else:
    sys.modules[__name__] = _module
