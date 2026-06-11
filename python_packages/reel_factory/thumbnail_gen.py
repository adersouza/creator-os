#!/usr/bin/env python3
"""Generate deterministic review thumbnails for rendered outputs."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def thumbnail_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_thumb.png")


def generate_thumbnail(video_path: Path, *, ffmpeg: str = "ffmpeg",
                       at_seconds: float = 1.5,
                       overwrite: bool = False) -> Path:
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    out = thumbnail_path_for(video_path)
    if out.exists() and not overwrite:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-ss", f"{at_seconds:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", "scale=540:-2",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "thumbnail ffmpeg failed")
    return out


def generate_thumbnails(root: Path, *, clip: str | None = None,
                        overwrite: bool = False) -> dict:
    root = Path(root).resolve()
    proc = root / "02_processed"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    if clip:
        candidates = sorted((proc / clip).glob("*.mp4"))
    else:
        candidates = sorted(proc.glob("*/*.mp4"))
    created: list[str] = []
    failed: dict[str, str] = {}
    for video in candidates:
        if video.stem.endswith("_thumb"):
            continue
        try:
            created.append(str(generate_thumbnail(video, ffmpeg=ffmpeg, overwrite=overwrite)))
        except Exception as e:
            failed[str(video)] = str(e)
    return {"created": created, "failed": failed, "count": len(created)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    print(json.dumps(generate_thumbnails(Path(args.root), clip=args.clip, overwrite=args.overwrite), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
