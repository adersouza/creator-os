"""Compatibility shim for the packaged Reel Factory queue_admin module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import queue_admin as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.queue_admin", run_name="__main__")
else:
    sys.modules[__name__] = _module
