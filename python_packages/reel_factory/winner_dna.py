"""Compatibility shim for the packaged Reel Factory winner_dna module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import winner_dna as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.winner_dna", run_name="__main__")
else:
    sys.modules[__name__] = _module
