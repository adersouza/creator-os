#!/usr/bin/env python3
"""
SSCD (Self-Supervised Copy Detection) checker for ContentForge.
Uses Meta's exact production copy detection model (sscd_disc_mixup).
Produces 512-dimensional L2-normalized embeddings — cosine similarity directly
measures copy likelihood.

Research-calibrated thresholds:
  >= 0.75: copy detected (90% precision, Meta's own benchmark)
  0.50-0.75: similar / modified copy
  < 0.50: distinct content

This is the same model deployed on Facebook and Instagram via SimSearchNet++.
"""

import sys
import json
import os
import subprocess
import numpy as np

import torch
from PIL import Image
from torchvision import transforms

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "sscd_disc_mixup.torchscript.pt")

# ImageNet normalization (SSCD uses standard ImageNet preprocessing)
TRANSFORM = transforms.Compose([
    transforms.Resize(288),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

# Global model — loaded once per script invocation
_model = None

def get_model():
    global _model
    if _model is None:
        _model = torch.jit.load(MODEL_PATH)
        _model.eval()
    return _model


def compute_embedding(image_path):
    """Compute 512-d SSCD embedding for an image."""
    try:
        img = Image.open(image_path).convert("RGB")
        tensor = TRANSFORM(img).unsqueeze(0)
        with torch.no_grad():
            embedding = get_model()(tensor)
        return embedding.squeeze(0).numpy(), None
    except Exception as e:
        return None, str(e)


def extract_frame(video_path, output_path):
    """Extract first frame from video as JPEG for SSCD embedding."""
    try:
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vframes", "1", "-q:v", "2", "-y", output_path],
            capture_output=True, timeout=10
        )
        return os.path.exists(output_path)
    except Exception:
        return False


def cosine_similarity(a, b):
    """Cosine similarity between two L2-normalized vectors."""
    return float(np.dot(a, b))


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: sscd_check.py <source_file> <output_dir> [max_files]"}))
        sys.exit(1)

    source_path = sys.argv[1]
    output_dir = sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    if not os.path.exists(source_path):
        print(json.dumps({"error": f"Source file not found: {source_path}"}))
        sys.exit(1)

    if not os.path.isdir(output_dir):
        print(json.dumps({"error": f"Output directory not found: {output_dir}"}))
        sys.exit(1)

    if not os.path.exists(MODEL_PATH):
        print(json.dumps({"error": f"SSCD model not found at {MODEL_PATH}. Download from Meta."}))
        sys.exit(1)

    # Determine media type
    src_ext = os.path.splitext(source_path)[1].lower()
    is_video = src_ext in ('.mp4', '.mov', '.webm', '.avi')

    # Temp dir for frame extraction
    tmp_dir = os.path.join(output_dir, ".sscd_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # Get source embedding
    if is_video:
        src_frame = os.path.join(tmp_dir, "source_frame.jpg")
        if not extract_frame(source_path, src_frame):
            print(json.dumps({"error": "Failed to extract frame from source video"}))
            sys.exit(1)
        source_emb, err = compute_embedding(src_frame)
    else:
        source_emb, err = compute_embedding(source_path)

    if err:
        print(json.dumps({"error": f"Failed to embed source: {err}"}))
        sys.exit(1)

    # Scan output directory
    supported = ('.mp4', '.mov', '.webm', '.jpg', '.jpeg', '.png')
    files = sorted([
        f for f in os.listdir(output_dir)
        if os.path.splitext(f)[1].lower() in supported and not f.startswith('.')
    ])[:max_files]

    results = []
    similarities = []

    for fname in files:
        fpath = os.path.join(output_dir, fname)
        fext = os.path.splitext(fname)[1].lower()

        if fext in ('.mp4', '.mov', '.webm'):
            frame_path = os.path.join(tmp_dir, f"frame_{fname}.jpg")
            if not extract_frame(fpath, frame_path):
                results.append({"name": fname, "similarity": None, "verdict": None, "error": "frame extraction failed"})
                continue
            variant_emb, err = compute_embedding(frame_path)
        else:
            variant_emb, err = compute_embedding(fpath)

        if err:
            results.append({"name": fname, "similarity": None, "verdict": None, "error": err})
            continue

        sim = cosine_similarity(source_emb, variant_emb)
        similarities.append(sim)

        # Research-calibrated verdicts
        if sim >= 0.75:
            verdict = "fail"   # Copy detected (90% precision threshold)
        elif sim >= 0.50:
            verdict = "warn"   # Similar / modified copy
        else:
            verdict = "pass"   # Distinct content

        results.append({
            "name": fname,
            "similarity": round(sim, 4),
            "verdict": verdict,
            "error": None,
        })

    # Cross-variant similarity (check variants against each other)
    cross_high = 0
    variant_embeddings = []
    for fname in files[:30]:
        fpath = os.path.join(output_dir, fname)
        fext = os.path.splitext(fname)[1].lower()
        if fext in ('.mp4', '.mov', '.webm'):
            frame_path = os.path.join(tmp_dir, f"frame_{fname}.jpg")
            if os.path.exists(frame_path):
                emb, _ = compute_embedding(frame_path)
                if emb is not None:
                    variant_embeddings.append((fname, emb))
        else:
            emb, _ = compute_embedding(fpath)
            if emb is not None:
                variant_embeddings.append((fname, emb))

    for i in range(len(variant_embeddings)):
        for j in range(i + 1, len(variant_embeddings)):
            sim = cosine_similarity(variant_embeddings[i][1], variant_embeddings[j][1])
            if sim >= 0.75:
                cross_high += 1

    # Cleanup temp
    try:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    # Stats
    avg_sim = float(np.mean(similarities)) if similarities else None
    min_sim = float(np.min(similarities)) if similarities else None
    max_sim = float(np.max(similarities)) if similarities else None
    pass_count = sum(1 for s in similarities if s < 0.50)
    warn_count = sum(1 for s in similarities if 0.50 <= s < 0.75)
    fail_count = sum(1 for s in similarities if s >= 0.75)

    output = {
        "results": results,
        "stats": {
            "total": len(results),
            "passCount": pass_count,
            "warnCount": warn_count,
            "failCount": fail_count,
            "passPercent": round((pass_count / len(results)) * 100) if results else 0,
            "avgSimilarity": round(avg_sim, 4) if avg_sim is not None else None,
            "minSimilarity": round(min_sim, 4) if min_sim is not None else None,
            "maxSimilarity": round(max_sim, 4) if max_sim is not None else None,
            "crossVariantCollisions": cross_high,
            "thresholds": {"pass": 0.50, "warn": 0.75},
        },
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
