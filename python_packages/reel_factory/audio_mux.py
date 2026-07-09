"""Compatibility shim for the packaged Reel Factory audio_mux module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import audio_mux as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.audio_mux", run_name="__main__")
else:
    sys.modules[__name__] = _module
