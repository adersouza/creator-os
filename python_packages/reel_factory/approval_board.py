"""Compatibility shim for the packaged Reel Factory approval_board module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import approval_board as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.approval_board", run_name="__main__")
else:
    sys.modules[__name__] = _module
