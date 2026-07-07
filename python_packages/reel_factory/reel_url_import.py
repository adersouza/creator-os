"""Compatibility shim for the packaged Reel Factory reel_url_import module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import reel_url_import as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.reel_url_import", run_name="__main__")
else:
    sys.modules[__name__] = _module
