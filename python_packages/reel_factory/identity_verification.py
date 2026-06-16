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
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


SCHEMA = "reel_factory.identity_verification.v1"
REFERENCE_SET_SCHEMA = "reel_factory.identity_reference_set.v1"
HEALTH_SCHEMA = "reel_factory.identity_health.v1"
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def build_reference_set(
    *,
    creator: str,
    input_dir: str | Path,
    root: str | Path = ".",
    output: str | Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    provider: IdentityProvider | None = None,
) -> dict[str, Any]:
    """Build a local approved identity reference set from image files.

    This writes only the reference JSON requested by the operator. It does not
    alter generated assets, schedules, inventory, or Campaign Factory state.
    """
    root_path = Path(root).resolve()
    input_path = Path(input_dir).expanduser().resolve()
    provider = provider or get_identity_provider()
    output_path = Path(output).expanduser().resolve() if output else _reference_set_path(root_path, creator)
    base = {
        "schema": REFERENCE_SET_SCHEMA,
        "creator": creator,
        "provider": provider.name,
        "threshold": threshold,
        "inputDir": str(input_path),
        "outputPath": str(output_path),
        "status": "failed",
        "referenceSetId": "",
        "sourceImages": [],
        "embeddings": [],
        "failureReason": "",
    }
    if not input_path.exists() or not input_path.is_dir():
        return {**base, "failureReason": "input_dir_missing"}
    ok, reason = provider.available()
    if not ok:
        return {**base, "failureReason": reason}
    image_paths = sorted(path for path in input_path.rglob("*") if path.suffix.lower() in IMAGE_EXTS and path.is_file())
    if not image_paths:
        return {**base, "failureReason": "no_reference_images_found"}

    embeddings: list[list[float]] = []
    sources: list[dict[str, Any]] = []
    for image_path in image_paths:
        item = {
            "path": str(image_path),
            "sha256": _sha256_file(image_path),
            "status": "failed",
            "failureReason": "",
        }
        embedding = provider.embedding(image_path)
        if embedding:
            item["status"] = "embedded"
            embeddings.append([float(value) for value in embedding])
        else:
            item["failureReason"] = "face_embedding_missing"
        sources.append(item)

    if not embeddings:
        return {**base, "sourceImages": sources, "failureReason": "no_usable_reference_embeddings"}

    reference_material = f"{creator}:{provider.name}:{','.join(item['sha256'] for item in sources if item['status'] == 'embedded')}"
    reference_set_id = hashlib.sha256(reference_material.encode("utf-8")).hexdigest()[:16]
    payload = {
        **base,
        "status": "ready",
        "createdAt": datetime.now(UTC).isoformat(),
        "referenceSetId": reference_set_id,
        "sourceImages": sources,
        "embeddings": embeddings,
        "failureReason": "",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def identity_health(
    *,
    creator: str,
    root: str | Path = ".",
    provider: IdentityProvider | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    provider = provider or get_identity_provider()
    ok, reason = provider.available()
    reference_path = _reference_set_path(root_path, creator)
    reference_set_id, embeddings, reference_error = _load_reference_embeddings(reference_path)
    status = "ready" if ok and not reference_error else "unavailable"
    blocking_reasons: list[str] = []
    if not ok:
        blocking_reasons.append(reason)
    if reference_error:
        blocking_reasons.append(reference_error)
    return {
        "schema": HEALTH_SCHEMA,
        "creator": creator,
        "status": status,
        "provider": provider.name,
        "providerAvailable": ok,
        "providerReason": reason,
        "referenceSetPath": str(reference_path),
        "referenceSetId": reference_set_id,
        "referenceEmbeddings": len(embeddings),
        "blockingReasons": blocking_reasons,
    }


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command")

    verify = sub.add_parser("verify", help="verify one generated media file against a creator reference set")
    verify.add_argument("media_path")
    verify.add_argument("--creator", required=True)
    verify.add_argument("--root", default=".")
    verify.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    build = sub.add_parser("identity-reference-build", help="build approved local identity reference embeddings")
    build.add_argument("--creator", required=True)
    build.add_argument("--input-dir", required=True)
    build.add_argument("--root", default=".")
    build.add_argument("--output")
    build.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    health = sub.add_parser("identity-health", help="report identity provider and reference-set availability")
    health.add_argument("--creator", required=True)
    health.add_argument("--root", default=".")

    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] not in {"verify", "identity-reference-build", "identity-health", "-h", "--help"}:
        raw_args.insert(0, "verify")
    args = ap.parse_args(raw_args)
    if args.command == "identity-reference-build":
        result = build_reference_set(
            creator=args.creator,
            input_dir=args.input_dir,
            root=args.root,
            output=args.output,
            threshold=args.threshold,
        )
    elif args.command == "identity-health":
        result = identity_health(creator=args.creator, root=args.root)
    elif args.command == "verify":
        result = verify_identity(args.media_path, creator=args.creator, root=args.root, threshold=args.threshold)
    else:
        ap.print_help()
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
