"""Compatibility shim for the packaged Reel Factory ai_visual_qc module.

Read-only QC contract terms kept for integration guards: visualQcStatus,
subprocess.run, ffprobe, ffmpeg.
"""

from __future__ import annotations

import runpy
import sys

from reel_factory import ai_visual_qc as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.ai_visual_qc", run_name="__main__")
else:
    sys.modules[__name__] = _module
