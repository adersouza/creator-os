"""Compatibility shim for the packaged Reel Factory metrics_store module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import metrics_store as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.metrics_store", run_name="__main__")
else:
    sys.modules[__name__] = _module
