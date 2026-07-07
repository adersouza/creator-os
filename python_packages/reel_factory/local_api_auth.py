"""Compatibility shim for the packaged Reel Factory local_api_auth module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import local_api_auth as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.local_api_auth", run_name="__main__")
else:
    sys.modules[__name__] = _module
