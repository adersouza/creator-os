"""Compatibility shim for the packaged Reel Factory embedding_index module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import embedding_index as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.embedding_index", run_name="__main__")
else:
    sys.modules[__name__] = _module
