"""Compatibility shim for the packaged Reel Factory export_approved module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import export_approved as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.export_approved", run_name="__main__")
else:
    sys.modules[__name__] = _module
