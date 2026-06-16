#!/usr/bin/env python3
"""Create a simple vertical MP4 reel from one still image.

This is the local equivalent of the common "single photo -> simple reel" edit:
make a 9:16 MP4, optionally mux a local audio file, or attach a native audio
intent sidecar for platform audio selection later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from audio_intent import write_audio_intent
from audio_mux import mux_audio, select_audio as select_local_audio
from audio_provider import select_audio as select_audio_metadata


SCHEMA = "reel_factory.photo_reel.v1"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
MOTION_STYLES = {"hold", "slow_zoom"}
AUDIO_MODES = {"silent", "native_trending", "local_mux"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video_filter(*, width: int, height: int, duration: float, fps: int, motion: str) -> str:
    base = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if motion == "hold":
        return f"{base},format=yuv420p"
    if motion == "slow_zoom":
        frames = max(1, int(round(duration * fps)))
        return (
            f"{base},"
            f"zoompan=z='min(zoom+0.00075,1.055)':d={frames}:s={width}x{height}:fps={fps},"
            f"trim=duration={duration:.3f},format=yuv420p"
        )
    raise ValueError(f"motion must be one of {sorted(MOTION_STYLES)}")


def build_photo_reel_ffmpeg_cmd(
    *,
    image: Path,
    out: Path,
    duration: float = 5.0,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    motion: str = "slow_zoom",
    ffmpeg: str = FFMPEG,
) -> list[str]:
    if duration <= 0:
        raise ValueError("duration must be positive")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{duration:.3f}",
        "-i",
        str(image),
        "-vf",
        _video_filter(width=width, height=height, duration=duration, fps=fps, motion=motion),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(out),
    ]


def _run(cmd: list[str], *, timeout: int = 180) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "ffmpeg photo reel render failed")


def create_photo_reel(
    *,
    image: Path,
    out: Path,
    root: Path = Path("."),
    duration: float = 5.0,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    motion: str = "slow_zoom",
    audio_mode: str = "native_trending",
    platform: str = "instagram_reels",
    audio_file: Path | None = None,
    audio_tag: str | None = None,
    seed: int | str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    image = Path(image).expanduser().resolve()
    out = Path(out).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if not image.exists():
        raise FileNotFoundError(f"image not found: {image}")
    if audio_mode not in AUDIO_MODES:
        raise ValueError(f"audio_mode must be one of {sorted(AUDIO_MODES)}")
    if motion not in MOTION_STYLES:
        raise ValueError(f"motion must be one of {sorted(MOTION_STYLES)}")
    if out.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {out}")

    out.parent.mkdir(parents=True, exist_ok=True)
    audio_selection: dict[str, Any] | None = None
    audio_intent_path: Path | None = None

    with tempfile.TemporaryDirectory(prefix="photo-reel-") as tmp:
        silent_out = out if audio_mode != "local_mux" else Path(tmp) / f"{out.stem}.silent.mp4"
        cmd = build_photo_reel_ffmpeg_cmd(
            image=image,
            out=silent_out,
            duration=duration,
            fps=fps,
            width=width,
            height=height,
            motion=motion,
        )
        _run(cmd)
        if audio_mode == "local_mux":
            track = Path(audio_file).expanduser().resolve() if audio_file else select_local_audio(
                root,
                tag=audio_tag,
                seed=int(seed) if isinstance(seed, int) or (isinstance(seed, str) and seed.isdigit()) else 42,
                target_duration=duration,
            )
            mux_audio(silent_out, track, out=out, overwrite=True)
            audio_selection = {
                "mode": "local_mux",
                "audio_file": str(track),
                "audio_tag": audio_tag,
            }
        elif audio_mode == "native_trending":
            audio_selection = select_audio_metadata(root, mode="AUTO_TRENDING", seed=seed)
            audio_intent_path = write_audio_intent(
                out,
                mode="native_trending_audio",
                platform=platform,
                notes="Attach this as native platform audio during in-app/editor review; do not assume audio is muxed into the MP4.",
                audio_selection=audio_selection,
            )

    lineage = {
        "schema": SCHEMA,
        "sourceImage": str(image),
        "sourceImageHash": _sha256(image),
        "outputPath": str(out),
        "outputHash": _sha256(out),
        "durationSeconds": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "aspectRatio": "9:16",
        "motion": motion,
        "audioMode": audio_mode,
        "audioSelection": audio_selection,
        "audioIntentPath": str(audio_intent_path) if audio_intent_path else "",
        "createdAt": int(time.time()),
        "draftExported": 0,
        "scheduled": 0,
        "published": 0,
        "writesProductionState": False,
        "wouldWriteProductionState": False,
    }
    lineage_path = out.with_suffix(out.suffix + ".photo_reel_lineage.json")
    lineage_path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lineage["lineagePath"] = str(lineage_path)
    return lineage


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--motion", choices=sorted(MOTION_STYLES), default="slow_zoom")
    ap.add_argument("--audio-mode", choices=sorted(AUDIO_MODES), default="native_trending")
    ap.add_argument("--platform", default="instagram_reels")
    ap.add_argument("--audio-file", type=Path)
    ap.add_argument("--audio-tag")
    ap.add_argument("--seed")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    result = create_photo_reel(
        image=args.image,
        out=args.out,
        root=args.root,
        duration=args.duration,
        fps=args.fps,
        motion=args.motion,
        audio_mode=args.audio_mode,
        platform=args.platform,
        audio_file=args.audio_file,
        audio_tag=args.audio_tag,
        seed=args.seed,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
