"""Compatibility shim for the packaged Reel Factory frame_hash_check module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import frame_hash_check as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.frame_hash_check", run_name="__main__")
else:
    sys.modules[__name__] = _module
