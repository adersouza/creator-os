"""perceptual_hash_check.py — perceptual-hash audit of variation outputs.

Samples N frames evenly across each MP4, computes pHash + dHash for each
frame, and reports the mean Hamming distance between the v01_original
baseline and every other variant. Mirrors the first-line check most copy-
similarity fingerprinting systems run against incoming uploads.

Hamming-distance interpretation (64-bit pHash):
   0..4   → near-duplicate (will likely flag as same content)
   5..10  → modified but recognizably similar
  11..20  → meaningfully different
  21+     → effectively novel content

Usage:
    python3 perceptual_hash_check.py /path/to/02_processed/clip_001
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imagehash
from PIL import Image

_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
FF = (
    str(_FFMPEG_FULL / "ffmpeg")
    if (_FFMPEG_FULL / "ffmpeg").exists()
    else shutil.which("ffmpeg") or "ffmpeg"
)
FFPROBE = (
    str(_FFMPEG_FULL / "ffprobe")
    if (_FFMPEG_FULL / "ffprobe").exists()
    else shutil.which("ffprobe") or "ffprobe"
)
# Sample at ABSOLUTE time-points (not %) — this catches speed differences,
# trims, and reverse properly. The clips are ~6.9s, so these land within
# every recipe variation.
SAMPLE_TIMES = [0.5, 1.0, 1.5, 2.5, 3.5, 5.0]

HASHES = ("phash", "dhash", "whash")


def recipe_from_name(name: str) -> str:
    parts = Path(name).stem.split("_")
    try:
        h_pos = next(
            i for i, p in enumerate(parts) if p.startswith("h") and p[1:].isdigit()
        )
        color_pos = next(i for i, p in enumerate(parts) if p in ("light", "dark"))
        return "_".join(parts[h_pos + 1 : color_pos])
    except StopIteration:
        return Path(name).stem


def probe_duration(mp4: Path) -> float:
    out = (
        subprocess.check_output(
            [
                FFPROBE,
                "-v",
                "0",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(mp4),
            ]
        )
        .decode()
        .strip()
    )
    return float(out)


def sample_hashes(mp4: Path) -> dict[str, list[imagehash.ImageHash]]:
    dur = probe_duration(mp4)
    out: dict[str, list[imagehash.ImageHash]] = {h: [] for h in HASHES}
    with tempfile.TemporaryDirectory() as td:
        for t in SAMPLE_TIMES:
            t = min(max(0.05, t), max(0.05, dur - 0.05))
            png = Path(td) / f"f_{t:.2f}.png"
            subprocess.run(
                [
                    FF,
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{t:.3f}",
                    "-i",
                    str(mp4),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:-1",
                    "-y",
                    str(png),
                ],
                check=True,
            )
            with Image.open(png) as im:
                out["phash"].append(imagehash.phash(im, hash_size=8))
                out["dhash"].append(imagehash.dhash(im, hash_size=8))
                out["whash"].append(imagehash.whash(im, hash_size=8))
    return out


def mean_hamming(a: list, b: list) -> float:
    assert len(a) == len(b)
    return sum(int(x - y) for x, y in zip(a, b)) / len(a)


def audit_clip_dir(clip_dir: str | Path) -> list[dict]:
    d = Path(clip_dir)
    mp4s = sorted(d.glob("*_v0*.mp4")) + sorted(d.glob("*_v1*.mp4"))
    if not mp4s:
        return []

    # baseline = v01_original
    baseline = next(m for m in mp4s if "v01_original" in m.name)
    base = sample_hashes(baseline)

    rows = []
    for mp4 in mp4s:
        recipe = recipe_from_name(mp4.name)
        h = sample_hashes(mp4)
        ph = mean_hamming(base["phash"], h["phash"])
        dh = mean_hamming(base["dhash"], h["dhash"])
        wh = mean_hamming(base["whash"], h["whash"])
        avg = (ph + dh + wh) / 3
        if avg < 5:
            verdict = "NEAR-DUPLICATE (will flag)"
        elif avg < 10:
            verdict = "modified but similar"
        elif avg < 20:
            verdict = "meaningfully different"
        else:
            verdict = "effectively novel"
        novelty = min(100.0, avg / 32.0 * 100.0)
        rows.append(
            {
                "filename": mp4.name,
                "recipe": recipe,
                "phash": round(ph, 3),
                "dhash": round(dh, 3),
                "whash": round(wh, 3),
                "distance": round(avg, 3),
                "verdict": verdict,
                "novelty": round(novelty, 2),
            }
        )
    return rows


def main(clip_dir: str) -> None:
    d = Path(clip_dir)
    rows = audit_clip_dir(d)
    if not rows:
        print(f"no MP4s in {d}")
        return

    baseline = next((r for r in rows if "v01_original" in r["recipe"]), rows[0])
    print(f"baseline: {baseline['filename']}")
    print(f"sampling at absolute t = {SAMPLE_TIMES} seconds\n")
    print(
        f"{'recipe':<18} {'pHash':>8} {'dHash':>8} {'wHash':>8}  "
        f"{'consensus':<28}  {'novelty':>8}"
    )
    print("-" * 86)
    for row in rows:
        print(
            f"{row['recipe']:<18} {row['phash']:>8.2f} {row['dhash']:>8.2f} {row['whash']:>8.2f}  "
            f"{row['verdict']:<28}  {row['novelty']:>7.1f}%"
        )

    print("-" * 86)
    other = [r for r in rows if "v01_original" not in r["recipe"]]
    avgs = [r["distance"] for r in other]
    if not avgs:
        return
    print("\nVARIANTS vs ORIGINAL — mean cross-hash distance:")
    print(
        f"  mean: {sum(avgs) / len(avgs):.2f}   min: {min(avgs):.2f}   max: {max(avgs):.2f}"
    )
    print(f"  near-duplicate (<5):   {sum(1 for a in avgs if a < 5)}/{len(avgs)}")
    print(f"  modified (5..10):      {sum(1 for a in avgs if 5 <= a < 10)}/{len(avgs)}")
    print(
        f"  diff (10..20):         {sum(1 for a in avgs if 10 <= a < 20)}/{len(avgs)}"
    )
    print(f"  novel (>20):           {sum(1 for a in avgs if a >= 20)}/{len(avgs)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: python3 perceptual_hash_check.py /path/to/02_processed/clip_001",
            file=sys.stderr,
        )
        sys.exit(2)
    main(sys.argv[1])
