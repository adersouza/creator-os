"""Compatibility shim for the packaged Reel Factory project_config module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import project_config as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.project_config", run_name="__main__")
else:
    sys.modules[__name__] = _module
