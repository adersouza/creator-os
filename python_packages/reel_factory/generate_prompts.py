"""Compatibility shim for the packaged Reel Factory generate_prompts module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import generate_prompts as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.generate_prompts", run_name="__main__")
else:
    sys.modules[__name__] = _module
