"""Compatibility shim for the packaged Reel Factory audio_provider module."""

from __future__ import annotations

import runpy
import sys

from reel_factory import audio_provider as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.audio_provider", run_name="__main__")
else:
    sys.modules[__name__] = _module
