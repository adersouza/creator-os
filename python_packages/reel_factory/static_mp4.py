"""Compatibility shim for the packaged Reel Factory static_mp4 module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import static_mp4 as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.static_mp4", run_name="__main__")
else:
    sys.modules[__name__] = _module
