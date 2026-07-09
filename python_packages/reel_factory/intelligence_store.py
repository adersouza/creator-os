"""Compatibility shim for the packaged Reel Factory intelligence_store module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import intelligence_store as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.intelligence_store", run_name="__main__")
else:
    sys.modules[__name__] = _module
