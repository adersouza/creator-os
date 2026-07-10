from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import imagehash
from PIL import Image

ALGORITHM = "frame_sampled_phash_v1"
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic"}


def media_identity(path: Path) -> dict[str, Any]:
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(f"rendered media not found: {media_path}")
    samples = _phash_samples(media_path)
    if not samples:
        raise ValueError(f"perceptual fingerprint unavailable: {media_path}")
    return {
        "contentFingerprint": _sha256_file(media_path),
        "perceptualFingerprint": "phash64:" + ".".join(samples),
        "perceptualClusterId": "phash64:" + ".".join(samples),
        "perceptualAlgorithm": ALGORITHM,
        "perceptualSamples": samples,
    }


def enrich_lineage_identity(
    lineage: dict[str, Any],
    media_path: Path,
    *,
    source_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(lineage)
    identity = media_identity(media_path)
    result.update(identity)
    source_family = _source_family_id(source_lineage or result)
    result["sourceFamilyId"] = source_family or None
    return result


def _phash_samples(path: Path) -> list[str]:
    if path.suffix.lower() in _IMAGE_EXTENSIONS:
        with Image.open(path) as image:
            return [str(imagehash.phash(image.convert("RGB")))]
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe are required for video pHash")
    duration = _duration_seconds(path, ffprobe)
    fractions = (0.0, 0.5, 0.95)
    timestamps = [max(0.0, duration * fraction) for fraction in fractions]
    samples: list[str] = []
    with tempfile.TemporaryDirectory(prefix="reel-phash-") as temp_dir:
        for index, timestamp in enumerate(timestamps):
            frame = Path(temp_dir) / f"frame-{index}.png"
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-y",
                    str(frame),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            if completed.returncode != 0 or not frame.exists():
                continue
            with Image.open(frame) as image:
                samples.append(str(imagehash.phash(image.convert("RGB"))))
    return samples


def _duration_seconds(path: Path, ffprobe: str) -> float:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    try:
        duration = float(completed.stdout.strip())
    except ValueError:
        duration = 0.0
    return max(duration, 0.001)


def _source_family_id(value: Any) -> str:
    keys = (
        "sourceFamilyId",
        "source_family_id",
        "referencePattern",
        "clusterKey",
        "patternCardId",
        "referenceId",
        "sourceReferenceId",
    )
    stack = [value]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        for key in keys:
            text = str(current.get(key) or "").strip()
            if text:
                return text
        stack.extend(item for item in current.values() if isinstance(item, dict))
    return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
