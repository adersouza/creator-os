"""Compatibility shim for the packaged Reel Factory whisper_sync module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import whisper_sync as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.whisper_sync", run_name="__main__")
else:
    sys.modules[__name__] = _module
