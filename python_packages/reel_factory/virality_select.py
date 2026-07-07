"""Compatibility shim for the packaged Reel Factory virality_select module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import virality_select as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.virality_select", run_name="__main__")
else:
    sys.modules[__name__] = _module
