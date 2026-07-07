"""Compatibility shim for the packaged Reel Factory feature_extract module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import feature_extract as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.feature_extract", run_name="__main__")
else:
    sys.modules[__name__] = _module
