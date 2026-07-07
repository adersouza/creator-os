"""Compatibility shim for the packaged Reel Factory media_metadata module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import media_metadata as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.media_metadata", run_name="__main__")
else:
    sys.modules[__name__] = _module
