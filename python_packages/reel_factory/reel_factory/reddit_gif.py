"""Render the image-first Reddit lane as a GIF only when rules require it."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def render_reddit_gif(
    still_path: Path,
    output_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    still = still_path.expanduser().resolve()
    output = output_path.expanduser().resolve()
    if not still.is_file():
        raise FileNotFoundError(f"reddit GIF source image not found: {still}")
    with Image.open(still) as image:
        source_size = list(image.size)
        image.verify()
    command = _command(still, output)
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw = tempfile.mkstemp(
            prefix=f".{output.stem}.", suffix=".partial.gif", dir=output.parent
        )
        os.close(descriptor)
        partial = Path(raw)
        partial.unlink()
        try:
            completed = subprocess.run(
                _command(still, partial),
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode != 0:
                detail = completed.stderr or completed.stdout or "ffmpeg failed"
                raise RuntimeError(detail[-2000:])
            with Image.open(partial) as image:
                frame_count = int(getattr(image, "n_frames", 1))
                if (
                    image.format != "GIF"
                    or not bool(getattr(image, "is_animated", False))
                    or frame_count < 2
                ):
                    raise RuntimeError("reddit GIF render is not animated")
                output_size = list(image.size)
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
    else:
        output_size = [720, 1280]
        frame_count = 36
    digest = (
        hashlib.sha256(output.read_bytes()).hexdigest()
        if output.is_file() and not dry_run
        else None
    )
    return {
        "schema": "reel_factory.reddit_gif_render.v1",
        "sourcePath": str(still),
        "sourceSize": source_size,
        "outputPath": str(output),
        "outputSize": output_size,
        "frameCount": frame_count,
        "durationSeconds": 3,
        "fps": 12,
        "motion": "identity_safe_center_zoom_1.2_percent",
        "sha256": digest,
        "ffmpegCommand": command,
        "dryRun": dry_run,
    }


def _command(still: Path, output: Path) -> list[str]:
    filters = (
        "scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=720:1280,"
        "zoompan=z='min(zoom+0.00035,1.012)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=720x1280:fps=12,"
        "split[s0][s1];[s0]palettegen=max_colors=192[p];"
        "[s1][p]paletteuse=dither=sierra2_4a"
    )
    return [
        FFMPEG,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-loop",
        "1",
        "-framerate",
        "12",
        "-i",
        str(still),
        "-t",
        "3",
        "-lavfi",
        filters,
        "-loop",
        "0",
        str(output),
    ]
