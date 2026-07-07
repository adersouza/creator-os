"""Compatibility shim for the packaged Reel Factory slideshow_factory module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import slideshow_factory as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.slideshow_factory", run_name="__main__")
else:
    sys.modules[__name__] = _module
