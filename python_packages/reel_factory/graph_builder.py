"""Compatibility shim for the packaged Reel Factory graph_builder module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import graph_builder as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.graph_builder", run_name="__main__")
else:
    sys.modules[__name__] = _module
