"""Compatibility shim for the packaged Reel Factory caption_bank module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import caption_bank as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.caption_bank", run_name="__main__")
else:
    sys.modules[__name__] = _module
