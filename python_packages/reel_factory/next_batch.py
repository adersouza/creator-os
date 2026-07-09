"""Compatibility shim for the packaged Reel Factory next_batch module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import next_batch as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.next_batch", run_name="__main__")
else:
    sys.modules[__name__] = _module
