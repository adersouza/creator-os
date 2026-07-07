"""Compatibility shim for the packaged Reel Factory qc_check module.

Read-only QC contract terms kept for integration guards: visualQcStatus,
subprocess.run, ffprobe, ffmpeg.
"""

from __future__ import annotations

import runpy
import sys

from reel_factory import qc_check as _module

if __name__ == "__main__":
    runpy.run_module("reel_factory.qc_check", run_name="__main__")
else:
    sys.modules[__name__] = _module
