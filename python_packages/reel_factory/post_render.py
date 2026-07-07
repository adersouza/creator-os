"""Compatibility shim for the packaged Reel Factory post_render module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import post_render as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.post_render", run_name="__main__")
else:
    sys.modules[__name__] = _module
