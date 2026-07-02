"""sscd_video.py — multi-frame SSCD copy-detection over a directory of videos.

Improvement over contentforge/lib/sscd_check.py: extracts N frames per video
(absolute-time sampling), embeds each, and reports both:
  - mean similarity across all source-vs-variant frame pairs
  - max similarity (worst-case match — what Meta actually flags on)

This catches temporal transforms (reverse, speed, time-warp) that single-frame
SSCD misses. Uses the same sscd_disc_mixup.torchscript.pt model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

MODEL_PATH = os.environ.get(
    "SSCD_MODEL_PATH",
    os.environ.get(
        "CONTENTFORGE_SSCD_MODEL_PATH",
        str(
            Path(__file__).resolve().parent
            / "models"
            / "sscd_disc_mixup.torchscript.pt"
        ),
    ),
)
_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
FFMPEG = (
    str(_FFMPEG_FULL / "ffmpeg")
    if (_FFMPEG_FULL / "ffmpeg").exists()
    else shutil.which("ffmpeg") or "ffmpeg"
)
FFPROBE = (
    str(_FFMPEG_FULL / "ffprobe")
    if (_FFMPEG_FULL / "ffprobe").exists()
    else shutil.which("ffprobe") or "ffprobe"
)
SAMPLE_PCTS = [0.10, 0.30, 0.50, 0.70, 0.90]  # 5 frames per video

TRANSFORM = transforms.Compose(
    [
        transforms.Resize(288),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ]
)

_model = None


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


def model():
    global _model
    if _model is None:
        if not Path(MODEL_PATH).exists():
            raise FileNotFoundError(
                f"SSCD model not found at {MODEL_PATH}. Set SSCD_MODEL_PATH or CONTENTFORGE_SSCD_MODEL_PATH to the torchscript model."
            )
        _model = torch.jit.load(MODEL_PATH)
        _model.eval()
    return _model


def probe_dur(p: Path) -> float:
    return float(
        subprocess.check_output(
            [
                FFPROBE,
                "-v",
                "0",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(p),
            ]
        )
        .decode()
        .strip()
    )


def extract_frames(video: Path, td: Path) -> list[Path]:
    dur = probe_dur(video)
    out = []
    for i, pct in enumerate(SAMPLE_PCTS):
        t = max(0.05, dur * pct)
        png = td / f"{video.stem}_f{i}.jpg"
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(png),
            ],
            check=True,
        )
        out.append(png)
    return out


def embed_many(paths: list[Path]) -> np.ndarray:
    """Stack-batch all images, return (N, 512) embeddings."""
    tensors = []
    for p in paths:
        with Image.open(p) as im:
            tensors.append(TRANSFORM(im.convert("RGB")))
    batch = torch.stack(tensors)
    with torch.no_grad():
        emb = model()(batch).numpy()  # (N, 512), L2-normalized
    return emb


def cross_similarity(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """All-pairs cosine similarity. a,b are (Na,512), (Nb,512), L2-normalized.
    Returns (mean, max) of the cross-similarity matrix."""
    sims = a @ b.T  # (Na, Nb)
    return float(sims.mean()), float(sims.max())


def audit_video_dir(source: str | Path, out_dir: str | Path) -> list[dict]:
    src = Path(source)
    od = Path(out_dir)
    if not src.exists() or not od.is_dir():
        raise FileNotFoundError("missing source video or output dir")

    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)
        src_frames = extract_frames(src, td)
        src_emb = embed_many(src_frames)

        videos = sorted(od.glob("*.mp4"))
        rows = []
        for v in videos:
            v_frames = extract_frames(v, td)
            v_emb = embed_many(v_frames)
            mean_s, max_s = cross_similarity(src_emb, v_emb)
            # Verdict based on MAX cosine similarity — Meta flags on the
            # closest-matching frame pair, not the average.
            if max_s >= 0.75:
                status = "fail"
                verdict = "FAIL (copy detected)"
            elif max_s >= 0.50:
                status = "warn"
                verdict = "WARN (modified copy)"
            else:
                status = "pass"
                verdict = "PASS (distinct content)"
            recipe = recipe_from_name(v.name)
            rows.append(
                {
                    "schema": "reel_factory.sscd_similarity_row.v1",
                    "filename": v.name,
                    "recipe": recipe,
                    "mean_similarity": round(mean_s, 6),
                    "max_similarity": round(max_s, 6),
                    "status": status,
                    "verdict": verdict,
                }
            )
        return rows


def main(source: str, out_dir: str) -> None:
    src = Path(source)
    od = Path(out_dir)
    try:
        rows = audit_video_dir(src, od)
    except FileNotFoundError:
        print("missing src or dir")
        sys.exit(1)

    print(f"\nbaseline source: {src.name}  ({len(SAMPLE_PCTS)} frames)")
    print(f"variant dir: {od}\n")
    print(f"{'recipe':<22} {'mean':>7}  {'max':>7}  {'verdict':<26}")
    print("-" * 70)
    for row in rows:
        print(
            f"{row['recipe']:<22} {row['mean_similarity']:>7.4f}  "
            f"{row['max_similarity']:>7.4f}  {row['verdict']:<26}"
        )

    print("-" * 70)
    passes = sum(1 for r in rows if r["status"] == "pass")
    warns = sum(1 for r in rows if r["status"] == "warn")
    fails = sum(1 for r in rows if r["status"] == "fail")
    avgs = [r["max_similarity"] for r in rows]
    print("\nResults vs source:")
    print(f"  PASS (distinct):   {passes}/{len(rows)}")
    print(f"  WARN (modified):   {warns}/{len(rows)}")
    print(f"  FAIL (copy):       {fails}/{len(rows)}")
    if avgs:
        print(
            f"  max-sim summary:   mean={sum(avgs) / len(avgs):.4f}  "
            f"min={min(avgs):.4f}  max={max(avgs):.4f}"
        )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "usage: python3 sscd_video.py /path/to/source.mp4 /path/to/02_processed/clip_001",
            file=sys.stderr,
        )
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
