"""Compatibility shim for the packaged Reel Factory audio importer."""

from __future__ import annotations

import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("reel_factory.audio_library_import", run_name="__main__")
else:
    from reel_factory import audio_library_import as _module

    sys.modules[__name__] = _module
