"""Compatibility shim for the packaged Reel Factory campaign_factory module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import campaign_factory as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.campaign_factory", run_name="__main__")
else:
    sys.modules[__name__] = _module
