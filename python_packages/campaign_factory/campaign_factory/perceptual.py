from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def pdq_hamming_distance(left: str, right: str) -> int | None:
    left_value = _normalize_pdq_hex(left)
    right_value = _normalize_pdq_hex(right)
    if not left_value or not right_value:
        return None
    return (int(left_value, 16) ^ int(right_value, 16)).bit_count()


def compute_pdq_fingerprint(
    path: str | Path, *, ffmpeg_binary: str = "ffmpeg"
) -> dict[str, Any]:
    media_path = Path(path)
    if not media_path.exists() or not media_path.is_file():
        return _unavailable("file_missing", f"media file not found: {media_path}")
    suffix = media_path.suffix.lower()
    if suffix not in IMAGE_EXTS | VIDEO_EXTS:
        return _unavailable(
            "unsupported_media_type", f"unsupported media type: {suffix or 'none'}"
        )
    try:
        import numpy as np
        import pdqhash
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        return _unavailable("dependency_unavailable", str(exc))

    frame_path = media_path
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if suffix in VIDEO_EXTS:
            ffmpeg = shutil.which(ffmpeg_binary)
            if not ffmpeg:
                return _unavailable("ffmpeg_unavailable", f"{ffmpeg_binary} not found")
            tmp_dir = tempfile.TemporaryDirectory(prefix="campaign_pdq_")
            frame_path = Path(tmp_dir.name) / "frame.jpg"
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(media_path),
                        "-vframes",
                        "1",
                        "-q:v",
                        "2",
                        "-y",
                        str(frame_path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
                return _unavailable("frame_extract_failed", detail or str(exc))
            except subprocess.TimeoutExpired:
                return _unavailable(
                    "frame_extract_timeout", "ffmpeg frame extraction timed out"
                )
        try:
            image = Image.open(frame_path).convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            return _unavailable("image_decode_failed", str(exc))
        hash_vector, quality = pdqhash.compute(np.array(image))
        fingerprint = _pdq_vector_to_hex(hash_vector)
        if not fingerprint:
            return _unavailable("hash_empty", "pdqhash returned an empty hash")
        return {
            "status": "available",
            "algorithm": "pdq_v1",
            "fingerprint": fingerprint,
            "quality": int(quality),
            "source": "first_frame" if suffix in VIDEO_EXTS else "image",
        }
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()


def _pdq_vector_to_hex(hash_vector: Any) -> str:
    bits = "".join(
        "1" if bool(item) else "0" for item in hash_vector.flatten().tolist()
    )
    if not bits:
        return ""
    return f"{int(bits, 2):0{len(bits) // 4}x}"


def _normalize_pdq_hex(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower()
    if len(normalized) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in normalized):
        return None
    return normalized


def _unavailable(code: str, detail: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "algorithm": "pdq_v1",
        "code": code,
        "detail": detail,
    }
