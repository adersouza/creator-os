"""Compatibility shim for the packaged Reel Factory analysis_reports module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import analysis_reports as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.analysis_reports", run_name="__main__")
else:
    sys.modules[__name__] = _module
