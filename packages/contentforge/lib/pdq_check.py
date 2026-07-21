#!/usr/bin/env python3
"""
PDQ hash similarity checker for ContentForge.
Uses Meta's pdqhash library — the exact algorithm used by Instagram/Facebook in production.
Threshold: Hamming distance <= 31 out of 256 bits = flagged as duplicate.
"""

import json
import os
import subprocess
import sys

import numpy as np

try:
    import pdqhash
except ImportError:
    print(
        json.dumps({"error": "pdqhash not installed. Run: pip3 install pdqhash Pillow"})
    )
    sys.exit(1)

from PIL import Image


def compute_pdq(image_path):
    """Compute PDQ hash for an image file. Returns (hash_vector, quality) or (None, error)."""
    try:
        img = Image.open(image_path).convert("RGB")
        arr = np.array(img)
        hash_vector, quality = pdqhash.compute(arr)
        return hash_vector, quality, None
    except Exception as e:
        return None, 0, str(e)


def extract_frame(video_path, output_path):
    """Extract first frame from video as JPEG for PDQ hashing."""
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                output_path,
            ],
            capture_output=True,
            timeout=10,
        )
        return completed.returncode == 0 and os.path.exists(output_path)
    except (OSError, subprocess.SubprocessError):
        return False


def hamming_distance(h1, h2):
    """Compute Hamming distance between two PDQ hash vectors."""
    return int(np.count_nonzero(h1 != h2))


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: pdq_check.py <source_file> <output_dir>"}))
        sys.exit(1)

    source_path = sys.argv[1]
    output_dir = sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 100

    if not os.path.exists(source_path):
        print(json.dumps({"error": f"Source file not found: {source_path}"}))
        sys.exit(1)

    if not os.path.isdir(output_dir):
        print(json.dumps({"error": f"Output directory not found: {output_dir}"}))
        sys.exit(1)

    # Determine if source is video or image
    src_ext = os.path.splitext(source_path)[1].lower()
    is_video = src_ext in (".mp4", ".mov", ".webm", ".avi")

    # Get PDQ hash of source
    tmp_dir = os.path.join(output_dir, ".pdq_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    if is_video:
        src_frame = os.path.join(tmp_dir, "source_frame.jpg")
        if not extract_frame(source_path, src_frame):
            print(json.dumps({"error": "Failed to extract frame from source video"}))
            sys.exit(1)
        source_hash, source_quality, err = compute_pdq(src_frame)
    else:
        source_hash, source_quality, err = compute_pdq(source_path)

    if err:
        print(json.dumps({"error": f"Failed to hash source: {err}"}))
        sys.exit(1)

    # Scan output directory
    supported = (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png")
    files = sorted(
        [
            f
            for f in os.listdir(output_dir)
            if os.path.splitext(f)[1].lower() in supported and not f.startswith(".")
        ]
    )[:max_files]

    results = []
    safe_count = 0
    distances = []

    for fname in files:
        fpath = os.path.join(output_dir, fname)
        fext = os.path.splitext(fname)[1].lower()

        if fext in (".mp4", ".mov", ".webm"):
            frame_path = os.path.join(tmp_dir, f"frame_{fname}.jpg")
            if not extract_frame(fpath, frame_path):
                results.append(
                    {
                        "name": fname,
                        "distance": None,
                        "safe": None,
                        "error": "frame extraction failed",
                    }
                )
                continue
            variant_hash, variant_quality, err = compute_pdq(frame_path)
        else:
            variant_hash, variant_quality, err = compute_pdq(fpath)

        if err:
            results.append(
                {"name": fname, "distance": None, "safe": None, "error": err}
            )
            continue

        dist = hamming_distance(source_hash, variant_hash)
        safe = dist > 31  # PDQ threshold: <= 31 = match
        if safe:
            safe_count += 1
        distances.append(dist)

        results.append(
            {
                "name": fname,
                "distance": dist,
                "safe": safe,
                "quality": int(variant_quality),
                "error": None,
            }
        )

    # Compute cross-variant distances (check if variants are unique from each other)
    cross_collisions = 0
    cross_safe_target_violations = 0
    variant_hashes = []
    for fname in files[:50]:  # limit cross-check to 50
        fpath = os.path.join(output_dir, fname)
        fext = os.path.splitext(fname)[1].lower()
        if fext in (".mp4", ".mov", ".webm"):
            frame_path = os.path.join(tmp_dir, f"frame_{fname}.jpg")
            if os.path.exists(frame_path):
                h, q, e = compute_pdq(frame_path)
                if h is not None:
                    variant_hashes.append((fname, h))
        else:
            h, q, e = compute_pdq(fpath)
            if h is not None:
                variant_hashes.append((fname, h))

    for i in range(len(variant_hashes)):
        for j in range(i + 1, len(variant_hashes)):
            d = hamming_distance(variant_hashes[i][1], variant_hashes[j][1])
            if d <= 31:
                cross_collisions += 1
            if d <= 40:
                cross_safe_target_violations += 1

    # Cleanup temp files
    import shutil

    shutil.rmtree(tmp_dir, ignore_errors=True)

    # Stats
    avg_dist = sum(distances) / len(distances) if distances else None
    min_dist = min(distances) if distances else None
    max_dist = max(distances) if distances else None

    output = {
        "results": results,
        "stats": {
            "total": len(results),
            "safeCount": safe_count,
            "safePercent": round((safe_count / len(results)) * 100) if results else 0,
            "avgDistance": round(avg_dist, 1) if avg_dist is not None else None,
            "minDistance": min_dist,
            "maxDistance": max_dist,
            "threshold": 31,
            "safeTarget": 40,
            "crossCollisions": cross_collisions,
            "crossSafeTargetViolations": cross_safe_target_violations,
        },
        "sourceQuality": int(source_quality),
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
