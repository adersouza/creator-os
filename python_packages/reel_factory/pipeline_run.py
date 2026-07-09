"""Compatibility shim for the packaged Reel Factory pipeline_run module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import pipeline_run as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.pipeline_run", run_name="__main__")
else:
    sys.modules[__name__] = _module
