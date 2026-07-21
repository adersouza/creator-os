#!/usr/bin/env python3
"""
Temporal PDQ video matcher for ContentForge.
Approximates Meta's TMK Level 1 features by extracting frames at fixed intervals
and comparing PDQ hash sequences.

TMK Level 1: slotwise average of per-frame PDQ hashes = compact temporal descriptor.
We extract N frames at 1fps, compute PDQ per frame, then compare:
1. Average hash distance (approximates TMK Level 1 cosine similarity)
2. Sequence alignment (catches temporal reordering)

Research: TMK Level 1 threshold >= 0.7 for filtering, >= 0.9 for exact match.
"""

import json
import os
import shutil
import subprocess
import sys

import numpy as np

try:
    import pdqhash
except ImportError:
    print(json.dumps({"error": "pdqhash not installed"}))
    sys.exit(1)

from PIL import Image


def extract_frames(video_path, output_dir, fps=1, max_frames=15):
    """Extract frames at fixed FPS from video."""
    os.makedirs(output_dir, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-vf",
                f"fps={fps}",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "2",
                "-y",
                os.path.join(output_dir, "frame_%03d.jpg"),
            ],
            capture_output=True,
            timeout=30,
        )

        if completed.returncode != 0:
            return []

        frames = sorted(
            [
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.startswith("frame_") and f.endswith(".jpg")
            ]
        )
        return frames
    except (OSError, subprocess.SubprocessError):
        return []


def compute_frame_hashes(frame_paths):
    """Compute PDQ hashes without silently weakening the audited frame set."""
    hashes = []
    errors = []
    for fp in frame_paths:
        try:
            with Image.open(fp) as image:
                arr = np.array(image.convert("RGB"))
            h, q = pdqhash.compute(arr)
            hashes.append(h)
        except Exception as exc:
            errors.append(
                {
                    "path": fp,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return hashes, errors


def compute_level1_descriptor(hashes):
    """
    Compute TMK Level 1 approximation: average of frame hashes.
    Since PDQ hashes are binary, we compute the mean bit value per position,
    then threshold at 0.5 to get a consensus hash.
    """
    if not hashes:
        return None
    arr = np.stack(hashes).astype(np.float32)
    mean_bits = arr.mean(axis=0)
    return mean_bits  # Keep as float for cosine comparison


def cosine_similarity(a, b):
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def frame_sequence_distance(hashes_a, hashes_b):
    """
    Compare frame hash sequences using aligned Hamming distances.
    Returns average per-frame Hamming distance.
    """
    min_len = min(len(hashes_a), len(hashes_b))
    if min_len == 0:
        return None

    distances = []
    for i in range(min_len):
        d = int(np.count_nonzero(hashes_a[i] != hashes_b[i]))
        distances.append(d)

    return {
        "avgFrameDistance": float(np.mean(distances)),
        "minFrameDistance": int(np.min(distances)),
        "maxFrameDistance": int(np.max(distances)),
        "framesCompared": min_len,
    }


def main():
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "error": "Usage: temporal_pdq.py <source_video> <output_dir> [max_files]"
                }
            )
        )
        sys.exit(1)

    source_path = sys.argv[1]
    output_dir = sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    src_ext = os.path.splitext(source_path)[1].lower()
    if src_ext not in (".mp4", ".mov", ".webm", ".avi"):
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "Image mode — temporal hashing requires video",
                }
            )
        )
        sys.exit(0)

    # Create temp dir for frames
    tmp_base = os.path.join(output_dir, ".temporal_tmp")
    os.makedirs(tmp_base, exist_ok=True)

    # Extract source frames
    src_frame_dir = os.path.join(tmp_base, "source")
    src_frames = extract_frames(source_path, src_frame_dir, fps=1, max_frames=15)
    if len(src_frames) < 3:
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "Source video too short for temporal analysis",
                }
            )
        )
        sys.exit(0)

    src_hashes, src_hash_errors = compute_frame_hashes(src_frames)
    if src_hash_errors:
        shutil.rmtree(tmp_base, ignore_errors=True)
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "Source frame hashing failed",
                    "frameHashErrors": src_hash_errors,
                }
            )
        )
        sys.exit(0)
    src_descriptor = compute_level1_descriptor(src_hashes)
    if src_descriptor is None:
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "Failed to compute source temporal descriptor",
                }
            )
        )
        sys.exit(0)

    # Find video variants
    video_exts = {".mp4", ".mov", ".webm"}
    files = sorted(
        [
            f
            for f in os.listdir(output_dir)
            if os.path.splitext(f)[1].lower() in video_exts and not f.startswith(".")
        ]
    )[:max_files]

    results = []
    similarities = []

    for fname in files:
        fpath = os.path.join(output_dir, fname)
        var_frame_dir = os.path.join(tmp_base, f"var_{fname}")

        var_frames = extract_frames(fpath, var_frame_dir, fps=1, max_frames=15)
        if len(var_frames) < 3:
            results.append(
                {
                    "name": fname,
                    "similarity": None,
                    "verdict": None,
                    "error": "Too short",
                }
            )
            continue

        var_hashes, var_hash_errors = compute_frame_hashes(var_frames)
        if var_hash_errors:
            results.append(
                {
                    "name": fname,
                    "similarity": None,
                    "verdict": None,
                    "error": "Frame hashing failed",
                    "frameHashErrors": var_hash_errors,
                }
            )
            continue
        var_descriptor = compute_level1_descriptor(var_hashes)

        if var_descriptor is None:
            results.append(
                {
                    "name": fname,
                    "similarity": None,
                    "verdict": None,
                    "error": "Hash failed",
                }
            )
            continue

        # Level 1: cosine similarity of temporal descriptors
        sim = cosine_similarity(src_descriptor, var_descriptor)
        similarities.append(sim)

        # Frame sequence analysis
        seq_stats = frame_sequence_distance(src_hashes, var_hashes)

        # TMK-calibrated verdict: >= 0.9 = exact match, >= 0.7 = likely match
        if sim >= 0.90:
            verdict = "fail"
        elif sim >= 0.70:
            verdict = "warn"
        else:
            verdict = "pass"

        results.append(
            {
                "name": fname,
                "similarity": round(sim, 4),
                "sequenceStats": seq_stats,
                "verdict": verdict,
                "error": None,
            }
        )

    # Cleanup
    shutil.rmtree(tmp_base, ignore_errors=True)

    # Stats
    avg_sim = float(np.mean(similarities)) if similarities else None
    pass_count = sum(1 for s in similarities if s < 0.70)
    warn_count = sum(1 for s in similarities if 0.70 <= s < 0.90)
    fail_count = sum(1 for s in similarities if s >= 0.90)
    analysis_error_count = sum(1 for result in results if result.get("error"))

    print(
        json.dumps(
            {
                "available": True,
                "results": results,
                "stats": {
                    "total": len(results),
                    "passCount": pass_count,
                    "warnCount": warn_count,
                    "failCount": fail_count,
                    "analysisErrorCount": analysis_error_count,
                    "avgSimilarity": round(avg_sim, 4) if avg_sim is not None else None,
                    "sourceFrames": len(src_hashes),
                    "thresholds": {"filter": 0.70, "exact": 0.90},
                },
            }
        )
    )


if __name__ == "__main__":
    main()
