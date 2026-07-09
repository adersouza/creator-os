"""Compatibility shim for the packaged Reel Factory higgsfield_cost_preflight module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import higgsfield_cost_preflight as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.higgsfield_cost_preflight", run_name="__main__")
else:
    sys.modules[__name__] = _module
