#!/usr/bin/env python3
"""Mux local audio-library tracks onto rendered silent outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any


FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac"}


def probe_media(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def audio_stream_count(path: Path) -> int:
    try:
        data = probe_media(path)
    except Exception:
        return 0
    return sum(1 for s in data.get("streams", []) if s.get("codec_type") == "audio")


def duration_seconds(path: Path) -> float:
    data = probe_media(path)
    try:
        return float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def audio_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:8]


def output_path_for(video: Path, audio: Path) -> Path:
    return video.with_name(f"{video.stem}_audio_{audio_id(audio)}.mp4")


def _audio_meta(path: Path) -> dict[str, Any]:
    meta_path = path.with_suffix(".json")
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def discover_audio(root: Path, *, tag: str | None = None) -> list[Path]:
    audio_dir = root / "03_audio_library"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tracks = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    if not tag:
        return tracks
    out = []
    for track in tracks:
        meta = _audio_meta(track)
        tags = meta.get("tags") or []
        if tag in tags or tag in track.stem.split("_"):
            out.append(track)
    return out


def audio_library_health(root: Path, *, tag: str | None = None) -> dict[str, Any]:
    tracks = discover_audio(root, tag=tag)
    blocking_reason = "" if tracks else "audio_library_empty"
    return {
        "schema": "reel_factory.audio_library_health.v1",
        "trackCount": len(tracks),
        "tag": tag,
        "nativeAudioIntentReady": True,
        "localMuxReady": bool(tracks),
        "blockingReason": blocking_reason,
        "wouldWriteProductionState": False,
    }


def select_audio(root: Path, *, tag: str | None = None,
                 seed: int = 42, target_duration: float | None = None) -> Path:
    tracks = discover_audio(root, tag=tag)
    if not tracks:
        raise FileNotFoundError(f"no audio tracks found in 03_audio_library for tag={tag!r}")
    rng = random.Random(f"{seed}|{tag}|{round(target_duration or 0, 1)}")
    return rng.choice(tracks)


def mux_audio(video: Path, audio: Path, *, out: Path | None = None,
              audio_volume: float = 0.82, fade_seconds: float = 0.15,
              overwrite: bool = False) -> Path:
    video = Path(video)
    audio = Path(audio)
    out = out or output_path_for(video, audio)
    if out.exists() and not overwrite:
        return out
    dur = max(0.1, duration_seconds(video))
    fade_out_start = max(0.0, dur - fade_seconds)
    af = (
        f"volume={audio_volume:.3f},"
        f"afade=t=in:st=0:d={fade_seconds:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_seconds:.3f}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-hide_banner", "-y", "-nostdin",
        "-i", str(video),
        "-stream_loop", "-1", "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k",
        "-af", af,
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "ffmpeg audio mux failed")
    return out


def mux_root(root: Path, *, clip: str | None = None, audio_tag: str | None = None,
             seed: int = 42, audio_volume: float = 0.82,
             fade_seconds: float = 0.15, overwrite: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    proc = root / "02_processed"
    videos = sorted((proc / clip).glob("*.mp4")) if clip else sorted(proc.glob("*/*.mp4"))
    videos = [v for v in videos if "_audio_" not in v.stem]
    created: list[str] = []
    skipped: list[str] = []
    failed: dict[str, str] = {}
    for video in videos:
        if audio_stream_count(video) > 0:
            skipped.append(str(video))
            continue
        try:
            track = select_audio(root, tag=audio_tag, seed=seed, target_duration=duration_seconds(video))
            created.append(str(mux_audio(
                video, track,
                audio_volume=audio_volume,
                fade_seconds=fade_seconds,
                overwrite=overwrite,
            )))
        except Exception as e:
            failed[str(video)] = str(e)
    return {"created": created, "skipped": skipped, "failed": failed, "count": len(created)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    health = sub.add_parser("health")
    health.add_argument("--root", default=".")
    health.add_argument("--audio-tag")
    ap.add_argument("--root", default=".")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--audio-tag", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--audio-volume", type=float, default=0.82)
    ap.add_argument("--fade-seconds", type=float, default=0.15)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    if args.cmd == "health":
        print(json.dumps(audio_library_health(Path(args.root), tag=args.audio_tag), indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(mux_root(
        Path(args.root),
        clip=args.clip,
        audio_tag=args.audio_tag,
        seed=args.seed,
        audio_volume=args.audio_volume,
        fade_seconds=args.fade_seconds,
        overwrite=args.overwrite,
    ), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
