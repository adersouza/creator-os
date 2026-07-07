"""Compatibility shim for the packaged Reel Factory fetch_models module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import fetch_models as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.fetch_models", run_name="__main__")
else:
    sys.modules[__name__] = _module
