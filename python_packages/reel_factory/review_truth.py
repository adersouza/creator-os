"""Compatibility shim for the packaged Reel Factory review_truth module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import review_truth as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.review_truth", run_name="__main__")
else:
    sys.modules[__name__] = _module
