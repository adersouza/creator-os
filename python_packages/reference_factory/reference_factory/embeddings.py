from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .fileops import atomic_write_text

DEFAULT_EMBEDDING_MODEL = "vit_small_patch14_dinov2.lvd142m"
DEFAULT_EMBEDDING_THRESHOLD = 0.86
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


def build_embedding_clusters(
    conn: Connection | None,
    cards: list[dict[str, Any]],
    output_dir: Path,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    provider: Callable[[Path], list[float]] | None = None,
) -> dict[str, Any]:
    if not cards:
        return {
            "schema": "reference_factory.embedding_clusters.v1",
            "status": "ready",
            "model": model,
            "threshold": threshold,
            "referenceCount": 0,
            "embeddedCount": 0,
            "clusterCount": 0,
            "groups": [],
            "assignments": {},
            "failures": [],
        }
    cache_dir = output_dir / "embedding_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        embed = provider or _timm_provider(model)
    except Exception as exc:
        return _fallback(model, threshold, str(exc), reference_count=len(cards))

    embedded: list[tuple[dict[str, Any], list[float]]] = []
    failures = []
    for card in cards:
        source = _source_image(conn, card, cache_dir)
        if source is None:
            failures.append(
                {"referenceId": card.get("referenceId"), "reason": "no_supported_media"}
            )
            continue
        vector = _cached_vector(card, source, cache_dir, model, embed)
        if vector is None:
            failures.append(
                {"referenceId": card.get("referenceId"), "reason": "embedding_failed"}
            )
            continue
        embedded.append((card, _normalize(vector)))

    if not embedded:
        report = _fallback(
            model, threshold, "no usable embeddings", reference_count=len(cards)
        )
        report["failures"] = failures
        return report

    vectors = [vector for _, vector in embedded]
    components = _components(vectors, threshold)
    assignments: dict[str, dict[str, Any]] = {}
    groups = []
    for component in components:
        refs = [
            str(embedded[i][0].get("referenceId") or embedded[i][0].get("id") or i)
            for i in component
        ]
        cluster_id = (
            "emb_"
            + hashlib.sha1(
                ("|".join(sorted(refs)) + model + str(threshold)).encode()
            ).hexdigest()[:12]
        )
        medoid = _medoid(component, vectors)
        medoid_ref = str(
            embedded[medoid][0].get("referenceId")
            or embedded[medoid][0].get("id")
            or medoid
        )
        noise = len(component) == 1
        groups.append(
            {
                "embeddingClusterId": cluster_id,
                "referenceIds": refs,
                "medoidReferenceId": medoid_ref,
                "noise": noise,
            }
        )
        for i in component:
            ref = str(
                embedded[i][0].get("referenceId") or embedded[i][0].get("id") or i
            )
            assignments[ref] = {
                "embeddingClusterId": cluster_id,
                "embeddingModel": model,
                "embeddingMedoidReferenceId": medoid_ref,
                "embeddingSimilarityThreshold": threshold,
                "embeddingNoise": noise,
            }

    return {
        "schema": "reference_factory.embedding_clusters.v1",
        "status": "ready",
        "model": model,
        "threshold": threshold,
        "referenceCount": len(cards),
        "embeddedCount": len(embedded),
        "clusterCount": len(groups),
        "groups": groups,
        "assignments": assignments,
        "failures": failures,
    }


def _fallback(
    model: str, threshold: float, reason: str, *, reference_count: int = 0
) -> dict[str, Any]:
    return {
        "schema": "reference_factory.embedding_clusters.v1",
        "status": "fallback",
        "model": model,
        "threshold": threshold,
        "referenceCount": reference_count,
        "embeddedCount": 0,
        "clusterCount": 0,
        "fallbackReason": reason,
        "assignments": {},
        "groups": [],
    }


def _cached_vector(
    card: dict[str, Any],
    source: Path,
    cache_dir: Path,
    model: str,
    provider: Callable[[Path], list[float]],
) -> list[float] | None:
    stat = source.stat()
    cache_key = hashlib.sha1(
        str(card.get("referenceId") or card.get("id") or source).encode()
    ).hexdigest()[:16]
    cache_path = cache_dir / f"{cache_key}.json"
    metadata = {
        "model": model,
        "sourcePath": str(source),
        "sourceSize": stat.st_size,
        "sourceMtimeNs": stat.st_mtime_ns,
    }
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if all(cached.get(key) == value for key, value in metadata.items()):
                vector = cached.get("vector")
                if isinstance(vector, list):
                    return [float(value) for value in vector]
        except Exception:
            pass
    try:
        vector = [float(value) for value in provider(source)]
    except Exception:
        return None
    atomic_write_text(cache_path, 
        json.dumps({**metadata, "dim": len(vector), "vector": vector}, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return vector


def _source_image(
    conn: Connection | None, card: dict[str, Any], cache_dir: Path
) -> Path | None:
    path_value = card.get("localPath")
    if not path_value:
        return None
    path = Path(str(path_value)).expanduser()
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS and path.exists():
        return path
    if ext not in VIDEO_EXTS:
        return None
    frame = _existing_frame(conn, str(card.get("referenceId") or ""))
    if frame:
        return frame
    return _extract_preview(path, cache_dir) if path.exists() else None


def _existing_frame(conn: Connection | None, reference_id: str) -> Path | None:
    if conn is None or not reference_id:
        return None
    try:
        row = conn.execute(
            """
            SELECT frame_path FROM frame_samples
            WHERE reference_id = ? AND role IN ('contact', 'hook_1s', 'middle')
            ORDER BY CASE role WHEN 'contact' THEN 0 WHEN 'hook_1s' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (reference_id,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    path = Path(str(row["frame_path"] if hasattr(row, "keys") else row[0])).expanduser()
    return path if path.exists() else None


def _extract_preview(video_path: Path, cache_dir: Path) -> Path | None:
    frame_dir = cache_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    target = (
        frame_dir / f"{hashlib.sha1(str(video_path).encode()).hexdigest()[:16]}.jpg"
    )
    if target.exists():
        return target
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "1",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(target),
        ],
        capture_output=True,
        timeout=20,
        text=True,
    )
    return target if result.returncode == 0 and target.exists() else None


def _components(vectors: list[list[float]], threshold: float) -> list[list[int]]:
    neighbors = {idx: set([idx]) for idx in range(len(vectors))}
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            if _cosine(vectors[i], vectors[j]) >= threshold:
                neighbors[i].add(j)
                neighbors[j].add(i)
    seen: set[int] = set()
    components = []
    for start in range(len(vectors)):
        if start in seen:
            continue
        stack = [start]
        group = []
        while stack:
            idx = stack.pop()
            if idx in seen:
                continue
            seen.add(idx)
            group.append(idx)
            stack.extend(neighbors[idx] - seen)
        components.append(sorted(group))
    return components


def _medoid(component: list[int], vectors: list[list[float]]) -> int:
    return max(
        component,
        key=lambda idx: (
            sum(_cosine(vectors[idx], vectors[other]) for other in component)
            / max(1, len(component))
        ),
    )


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _timm_provider(model_name: str) -> Callable[[Path], list[float]]:
    import timm
    import torch
    from PIL import Image
    from timm.data import create_transform, resolve_model_data_config

    device = (
        "mps"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        else "cpu"
    )
    model = (
        timm.create_model(model_name, pretrained=True, num_classes=0).to(device).eval()
    )
    transform = create_transform(**resolve_model_data_config(model))

    def embed(path: Path) -> list[float]:
        image = Image.open(path).convert("RGB")
        tensor = transform(image).unsqueeze(0).to(device)
        with torch.inference_mode():
            output = model(tensor)
        return output.squeeze(0).detach().cpu().float().tolist()

    return embed
