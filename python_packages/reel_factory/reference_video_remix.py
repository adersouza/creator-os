"""Compatibility shim for the packaged Reel Factory reference-video remix planner."""

from __future__ import annotations

import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("reel_factory.reference_video_remix", run_name="__main__")
else:
    from reel_factory import reference_video_remix as _module

    sys.modules[__name__] = _module
