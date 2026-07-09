"""Compatibility shim for the packaged Reel Factory thumbnail_gen module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import thumbnail_gen as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.thumbnail_gen", run_name="__main__")
else:
    sys.modules[__name__] = _module
