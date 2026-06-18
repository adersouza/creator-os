#!/usr/bin/env python3
"""
FAISS-backed reference database for ContentForge.
Stores SSCD embeddings + PDQ hashes of all published/generated content.
New variants are checked against the index for cross-batch and cross-account collisions.

Usage:
  reference_db.py add <file_or_dir>          — Add images/videos to the reference index
  reference_db.py query <file_or_dir>         — Query files against the reference index
  reference_db.py stats                       — Show index statistics
  reference_db.py clear                       — Clear the reference index
"""

import sys
import json
import os
import numpy as np
import subprocess
import shutil

try:
    import faiss
except ImportError:
    print(json.dumps({"error": "faiss-cpu not installed. Run: pip3 install faiss-cpu"}))
    sys.exit(1)

import torch
from PIL import Image
from torchvision import transforms

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
INDEX_DIR = os.path.join(PROJECT_ROOT, "output", "index")
FAISS_INDEX_PATH = os.path.join(INDEX_DIR, "sscd.faiss")
METADATA_PATH = os.path.join(INDEX_DIR, "metadata.json")
PDQ_INDEX_PATH = os.path.join(INDEX_DIR, "pdq_hashes.npy")
MODEL_PATH = os.environ.get(
    "CONTENTFORGE_SSCD_MODEL_PATH",
    os.path.join(PROJECT_ROOT, "models", "sscd_disc_mixup.torchscript.pt"),
)

EMBEDDING_DIM = 512
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".webm"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}

TRANSFORM = transforms.Compose([
    transforms.Resize(288),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

_model = None

def get_model():
    global _model
    if _model is None:
        _model = torch.jit.load(MODEL_PATH)
        _model.eval()
    return _model


def compute_sscd_embedding(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        tensor = TRANSFORM(img).unsqueeze(0)
        with torch.no_grad():
            emb = get_model()(tensor)
        return emb.squeeze(0).numpy(), None
    except Exception as e:
        return None, str(e)


def compute_pdq_hash(image_path):
    try:
        import pdqhash
        img = Image.open(image_path).convert("RGB")
        arr = np.array(img)
        hash_vec, quality = pdqhash.compute(arr)
        return hash_vec.astype(np.bool_), quality, None
    except Exception as e:
        return None, 0, str(e)


def extract_frame(video_path, output_path):
    try:
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vframes", "1", "-q:v", "2", "-y", output_path],
            capture_output=True, timeout=10
        )
        return os.path.exists(output_path)
    except:
        return False


def ensure_index_dir():
    os.makedirs(INDEX_DIR, exist_ok=True)


def load_faiss_index():
    if os.path.exists(FAISS_INDEX_PATH):
        return faiss.read_index(FAISS_INDEX_PATH)
    # Create new flat L2 index (inner product on L2-normalized = cosine similarity)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    return index


def save_faiss_index(index):
    ensure_index_dir()
    faiss.write_index(index, FAISS_INDEX_PATH)


def load_metadata():
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, "r") as f:
            return json.load(f)
    return {"files": [], "count": 0}


def save_metadata(meta):
    ensure_index_dir()
    with open(METADATA_PATH, "w") as f:
        json.dump(meta, f, indent=2)


def load_pdq_hashes():
    if os.path.exists(PDQ_INDEX_PATH):
        return np.load(PDQ_INDEX_PATH)
    return np.empty((0, 256), dtype=np.bool_)


def save_pdq_hashes(hashes):
    ensure_index_dir()
    np.save(PDQ_INDEX_PATH, hashes)


def get_image_for_file(filepath):
    """Get an image path (extract frame from video if needed)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in VIDEO_EXTS:
        tmp = os.path.join(INDEX_DIR, ".tmp_frame.jpg")
        os.makedirs(INDEX_DIR, exist_ok=True)
        if extract_frame(filepath, tmp):
            return tmp, True
        return None, False
    return filepath, False


def cmd_add(target, max_files=500):
    """Add files to the reference index."""
    if os.path.isdir(target):
        files = sorted([
            os.path.join(target, f) for f in os.listdir(target)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS and not f.startswith(".")
        ])[:max_files]
    elif os.path.isfile(target):
        files = [target]
    else:
        return {"error": f"Not found: {target}"}

    index = load_faiss_index()
    meta = load_metadata()
    pdq_hashes = load_pdq_hashes()

    existing_files = set(meta.get("files", []))
    added = 0
    errors = []
    new_embeddings = []
    new_pdq = []

    for filepath in files:
        basename = os.path.basename(filepath)
        if basename in existing_files:
            continue

        img_path, is_tmp = get_image_for_file(filepath)
        if img_path is None:
            errors.append({"file": basename, "error": "Frame extraction failed"})
            continue

        # SSCD embedding
        emb, err = compute_sscd_embedding(img_path)
        if err:
            errors.append({"file": basename, "error": err})
            continue

        # PDQ hash
        pdq, quality, pdq_err = compute_pdq_hash(img_path)

        new_embeddings.append(emb)
        if pdq is not None:
            new_pdq.append(pdq)
        else:
            new_pdq.append(np.zeros(256, dtype=np.bool_))

        meta["files"].append(basename)
        added += 1

    # Add to FAISS index
    if new_embeddings:
        embeddings_array = np.stack(new_embeddings).astype(np.float32)
        faiss.normalize_L2(embeddings_array)
        index.add(embeddings_array)

    # Add to PDQ index
    if new_pdq:
        new_pdq_array = np.stack(new_pdq)
        pdq_hashes = np.vstack([pdq_hashes, new_pdq_array]) if pdq_hashes.size > 0 else new_pdq_array

    meta["count"] = index.ntotal
    save_faiss_index(index)
    save_metadata(meta)
    save_pdq_hashes(pdq_hashes)

    # Cleanup tmp
    tmp_frame = os.path.join(INDEX_DIR, ".tmp_frame.jpg")
    if os.path.exists(tmp_frame):
        os.remove(tmp_frame)

    return {
        "action": "add",
        "added": added,
        "errors": errors,
        "totalInIndex": index.ntotal,
    }


def cmd_query(target, max_files=50):
    """Query files against the reference index."""
    index = load_faiss_index()
    meta = load_metadata()
    pdq_hashes = load_pdq_hashes()

    if index.ntotal == 0:
        return {"error": "Reference index is empty. Add published content first.", "totalInIndex": 0}

    if os.path.isdir(target):
        files = sorted([
            os.path.join(target, f) for f in os.listdir(target)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS and not f.startswith(".")
        ])[:max_files]
    elif os.path.isfile(target):
        files = [target]
    else:
        return {"error": f"Not found: {target}"}

    results = []
    ref_files = meta.get("files", [])

    for filepath in files:
        basename = os.path.basename(filepath)

        img_path, is_tmp = get_image_for_file(filepath)
        if img_path is None:
            results.append({"file": basename, "error": "Frame extraction failed"})
            continue

        # SSCD embedding
        emb, err = compute_sscd_embedding(img_path)
        if err:
            results.append({"file": basename, "error": err})
            continue

        query = emb.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(query)

        # Search top 3 nearest neighbors
        k = min(3, index.ntotal)
        scores, indices = index.search(query, k)

        matches = []
        for j in range(k):
            idx = int(indices[0][j])
            sim = float(scores[0][j])
            ref_name = ref_files[idx] if idx < len(ref_files) else f"index_{idx}"
            matches.append({
                "refFile": ref_name,
                "similarity": round(sim, 4),
                "verdict": "fail" if sim >= 0.75 else "warn" if sim >= 0.50 else "pass",
            })

        # PDQ check against reference
        pdq, quality, pdq_err = compute_pdq_hash(img_path)
        pdq_min_dist = None
        pdq_closest = None
        if pdq is not None and pdq_hashes.size > 0:
            distances = np.count_nonzero(pdq_hashes != pdq, axis=1)
            min_idx = int(np.argmin(distances))
            pdq_min_dist = int(distances[min_idx])
            pdq_closest = ref_files[min_idx] if min_idx < len(ref_files) else f"index_{min_idx}"

        top_sim = matches[0]["similarity"] if matches else None
        overall = "fail" if (top_sim and top_sim >= 0.75) or (pdq_min_dist is not None and pdq_min_dist <= 30) else \
                  "warn" if (top_sim and top_sim >= 0.50) or (pdq_min_dist is not None and pdq_min_dist <= 60) else "pass"

        results.append({
            "file": basename,
            "sscdMatches": matches,
            "pdqMinDistance": pdq_min_dist,
            "pdqClosestRef": pdq_closest,
            "verdict": overall,
            "error": None,
        })

    # Cleanup
    tmp_frame = os.path.join(INDEX_DIR, ".tmp_frame.jpg")
    if os.path.exists(tmp_frame):
        os.remove(tmp_frame)

    # Stats
    pass_count = sum(1 for r in results if r.get("verdict") == "pass")
    warn_count = sum(1 for r in results if r.get("verdict") == "warn")
    fail_count = sum(1 for r in results if r.get("verdict") == "fail")

    return {
        "action": "query",
        "results": results,
        "stats": {
            "total": len(results),
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "passPercent": round((pass_count / len(results)) * 100) if results else 0,
        },
        "totalInIndex": index.ntotal,
    }


def cmd_stats():
    """Show index statistics."""
    index = load_faiss_index()
    meta = load_metadata()
    pdq_hashes = load_pdq_hashes()
    return {
        "action": "stats",
        "totalEmbeddings": index.ntotal,
        "totalPDQHashes": pdq_hashes.shape[0] if pdq_hashes.size > 0 else 0,
        "totalFiles": len(meta.get("files", [])),
        "indexPath": INDEX_DIR,
    }


def cmd_clear():
    """Clear the reference index."""
    if os.path.exists(INDEX_DIR):
        for f in os.listdir(INDEX_DIR):
            fp = os.path.join(INDEX_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
    return {"action": "clear", "cleared": True}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: reference_db.py <add|query|stats|clear> [path] [max_files]"}))
        sys.exit(1)

    command = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else None
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    if command == "add":
        if not target:
            print(json.dumps({"error": "Usage: reference_db.py add <file_or_dir>"}))
            sys.exit(1)
        print(json.dumps(cmd_add(target, max_files)))
    elif command == "query":
        if not target:
            print(json.dumps({"error": "Usage: reference_db.py query <file_or_dir>"}))
            sys.exit(1)
        print(json.dumps(cmd_query(target, max_files)))
    elif command == "stats":
        print(json.dumps(cmd_stats()))
    elif command == "clear":
        print(json.dumps(cmd_clear()))
    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
