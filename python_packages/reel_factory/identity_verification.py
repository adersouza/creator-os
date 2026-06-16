#!/usr/bin/env python3
"""Identity verification for generated creator media.

The default provider uses InsightFace/ArcFace when it is installed and a local
reference embedding set is available. Tests and local tools can inject a fake
provider so the readiness contract is deterministic without requiring model
weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


SCHEMA = "reel_factory.identity_verification.v1"
DEFAULT_THRESHOLD = 0.42
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


class IdentityProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def embedding(self, image_path: Path) -> list[float] | None:
        ...


@dataclass
class UnavailableIdentityProvider:
    reason: str
    name: str = "unavailable"

    def available(self) -> tuple[bool, str]:
        return False, self.reason

    def embedding(self, image_path: Path) -> list[float] | None:
        return None


class InsightFaceIdentityProvider:
    name = "insightface_arcface"

    def __init__(self) -> None:
        from insightface.app import FaceAnalysis  # type: ignore

        self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=-1, det_size=(640, 640))

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def embedding(self, image_path: Path) -> list[float] | None:
        import cv2  # type: ignore

        image = cv2.imread(str(image_path))
        if image is None:
            return None
        faces = self._app.get(image)
        if not faces:
            return None
        face = max(faces, key=lambda item: float((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])))
        return [float(value) for value in face.normed_embedding]


def get_identity_provider() -> IdentityProvider:
    try:
        return InsightFaceIdentityProvider()
    except Exception as exc:
        return UnavailableIdentityProvider(f"identity_provider_unavailable:{exc.__class__.__name__}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def _reference_set_path(root: Path, creator: str) -> Path:
    env = os.environ.get("REEL_FACTORY_IDENTITY_REFERENCE_SET")
    if env:
        return Path(env)
    slug = "".join(ch.lower() for ch in creator if ch.isalnum() or ch in {"_", "-"}).strip("-_") or "creator"
    return root / "identity_references" / f"{slug}.json"


def _media_frame_for_embedding(media_path: Path) -> Path:
    if media_path.suffix.lower() in IMAGE_EXTS:
        return media_path
    if media_path.suffix.lower() not in VIDEO_EXTS:
        return media_path
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    tmp = Path(tempfile.mkdtemp(prefix="identity_verify_"))
    frame = tmp / "frame.jpg"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", "0.500", "-i", str(media_path), "-frames:v", "1", "-y", str(frame)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    return frame


def _load_reference_embeddings(path: Path) -> tuple[str, list[list[float]], str | None]:
    if not path.exists():
        return path.stem, [], "reference_set_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem, [], "reference_set_invalid_json"
    embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
    if not isinstance(embeddings, list):
        return str(payload.get("referenceSetId") or path.stem) if isinstance(payload, dict) else path.stem, [], "reference_embeddings_missing"
    rows = [
        [float(value) for value in row]
        for row in embeddings
        if isinstance(row, list) and row
    ]
    return str(payload.get("referenceSetId") or path.stem), rows, None if rows else "reference_embeddings_missing"


def verify_identity(
    media_path: str | Path,
    *,
    creator: str,
    root: str | Path = ".",
    threshold: float = DEFAULT_THRESHOLD,
    provider: IdentityProvider | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    path = Path(media_path)
    provider = provider or get_identity_provider()
    reference_set_id, references, reference_error = _load_reference_embeddings(_reference_set_path(root_path, creator))
    base = {
        "schema": SCHEMA,
        "creator": creator,
        "status": "unavailable",
        "score": 0.0,
        "threshold": threshold,
        "provider": provider.name,
        "referenceSetId": reference_set_id,
        "failureReason": "",
    }
    if not path.exists():
        return {**base, "failureReason": "media_missing"}
    ok, reason = provider.available()
    if not ok:
        return {**base, "failureReason": reason}
    if reference_error:
        return {**base, "failureReason": reference_error}
    frame = _media_frame_for_embedding(path)
    if not frame.exists():
        return {**base, "failureReason": "frame_extract_failed"}
    embedding = provider.embedding(frame)
    if not embedding:
        return {**base, "failureReason": "face_embedding_missing"}
    score = max((cosine_similarity(embedding, ref) for ref in references), default=0.0)
    status = "passed" if score >= threshold else "failed"
    return {
        **base,
        "status": status,
        "score": round(score, 6),
        "failureReason": "" if status == "passed" else "identity_similarity_below_threshold",
    }


def verification_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media_path")
    ap.add_argument("--creator", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    print(json.dumps(verify_identity(args.media_path, creator=args.creator, root=args.root, threshold=args.threshold), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
