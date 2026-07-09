"""Compatibility shim for the packaged Reel Factory rate_output module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import rate_output as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.rate_output", run_name="__main__")
else:
    sys.modules[__name__] = _module
