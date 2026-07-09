"""Compatibility shim for the packaged Reel Factory anatomy_qc module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import anatomy_qc as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.anatomy_qc", run_name="__main__")
else:
    sys.modules[__name__] = _module
