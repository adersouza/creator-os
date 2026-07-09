"""Compatibility shim for the packaged Reel Factory asset_prompt_contract module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import asset_prompt_contract as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.asset_prompt_contract", run_name="__main__")
else:
    sys.modules[__name__] = _module
