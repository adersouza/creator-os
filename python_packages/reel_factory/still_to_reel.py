"""Compatibility shim for the packaged Reel Factory still_to_reel module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import still_to_reel as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.still_to_reel", run_name="__main__")
else:
    sys.modules[__name__] = _module
