"""Compatibility shim for the packaged Reel Factory hook_tools module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import hook_tools as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.hook_tools", run_name="__main__")
else:
    sys.modules[__name__] = _module
