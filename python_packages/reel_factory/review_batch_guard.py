"""Compatibility shim for the packaged Reel Factory review_batch_guard module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import review_batch_guard as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.review_batch_guard", run_name="__main__")
else:
    sys.modules[__name__] = _module
