"""Shared ffprobe helpers.

The factory packages re-implement the ``ffprobe`` invocation idiom in many
places with divergent error contracts. This module captures the single most
common shape — the width/height/duration of the first video stream — so the
clearest call sites can share one implementation. Sites with bespoke error
handling or different ``-show_entries`` selections keep their own probe.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def probe_video_stream(path: Path | str) -> dict[str, Any]:
    """Return ``{"width", "height", "duration"}`` for the first video stream.

    Runs ``ffprobe -select_streams v:0 -show_entries stream=width,height,duration``.
    Raises ``subprocess.CalledProcessError`` if ffprobe fails and ``ValueError``
    if the file has no video stream.
    """
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    streams = json.loads(raw).get("streams") or []
    if not streams:
        raise ValueError(f"no video stream found: {path}")
    stream = streams[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": float(stream.get("duration") or 0.0),
    }
