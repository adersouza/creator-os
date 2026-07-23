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
import importlib.metadata
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from creator_os_core.evidence_attestation import (
    load_evidence_secret,
    sign_evidence_attestation,
)

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

SCHEMA = "reel_factory.identity_verification.v1"
IDENTITY_ANALYZER_ID = "reel_factory.identity_preservation"
IDENTITY_ANALYZER_VERSION = "2.0.0"
FACE_STABILITY_THRESHOLD = 0.80
REFERENCE_SET_SCHEMA = "reel_factory.identity_reference_set.v2"
REFERENCE_QUALITY_POLICY_ID = "reel_factory.identity_reference_consensus"
REFERENCE_QUALITY_POLICY_VERSION = "1.0.0"
MINIMUM_REFERENCE_SOURCES = 2
REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE = 0.35
IDENTITY_VIDEO_SAMPLE_COUNT = 11
IDENTITY_VIDEO_SAMPLE_FRACTIONS = (
    0.03,
    0.10,
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    0.97,
)
HEALTH_SCHEMA = "reel_factory.identity_health.v1"
DEFAULT_THRESHOLD = 0.42
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
PACKAGE_IDENTITY_MODEL_ROOT = Path(__file__).resolve().parent / "models" / "insightface"


class IdentityProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def embedding(self, image_path: Path) -> list[float] | None: ...


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

        model_root = identity_model_root()
        model_dir = model_root / "models" / "buffalo_l"
        if not any(model_dir.glob("*.onnx")):
            raise FileNotFoundError(f"identity_model_missing:{model_dir}")
        self._app = FaceAnalysis(
            name="buffalo_l",
            root=str(model_root),
            allowed_modules=("detection", "recognition"),
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=(640, 640))

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def face_embeddings(self, image_path: Path) -> list[list[float]]:
        import cv2  # type: ignore

        image = cv2.imread(str(image_path))
        if image is None:
            return []
        faces = self._app.get(image)
        return [
            [float(value) for value in face.normed_embedding]
            for face in sorted(
                faces,
                key=lambda item: float(
                    (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])
                ),
                reverse=True,
            )
        ]

    def embedding(self, image_path: Path) -> list[float] | None:
        embeddings = self.face_embeddings(image_path)
        return embeddings[0] if embeddings else None


def identity_model_root() -> Path:
    """Resolve existing ArcFace weights without duplicating the model cache."""
    configured = os.environ.get("REEL_FACTORY_IDENTITY_MODEL_ROOT")
    candidates = [
        Path(configured).expanduser() if configured else None,
        PACKAGE_IDENTITY_MODEL_ROOT,
        Path.home() / ".insightface",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if any((candidate / "models" / "buffalo_l").glob("*.onnx")):
            return candidate
    return candidates[0] or PACKAGE_IDENTITY_MODEL_ROOT


def get_identity_provider() -> IdentityProvider:
    try:
        return InsightFaceIdentityProvider()
    except Exception as exc:
        return UnavailableIdentityProvider(
            f"identity_provider_unavailable:{exc.__class__.__name__}"
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    value = float(sum(x * y for x, y in zip(a, b, strict=True)))
    return value if math.isfinite(value) else 0.0


def _reference_set_path(root: Path, creator: str) -> Path:
    env = os.environ.get("REEL_FACTORY_IDENTITY_REFERENCE_SET")
    if env:
        return Path(env)
    slug = (
        "".join(ch.lower() for ch in creator if ch.isalnum() or ch in {"_", "-"}).strip(
            "-_"
        )
        or "creator"
    )
    return root / "identity_references" / f"{slug}.json"


def _identity_reference_root(root: Path) -> Path:
    return (root / "identity_references").resolve()


def _output_allowed(root: Path, output_path: Path) -> bool:
    try:
        output_path.resolve().relative_to(_identity_reference_root(root))
    except ValueError:
        return False
    return True


def _identity_reference_failure_reason(error: str, creator: str) -> str:
    if error == "reference_set_missing":
        return f"no identity reference set for {creator} - run identity-reference-build"
    return error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _reference_path_error(root: Path, path: Path) -> str | None:
    if path.is_symlink():
        return "reference_set_symlink_forbidden"
    try:
        path.resolve().relative_to(_identity_reference_root(root))
    except ValueError:
        return "reference_set_outside_identity_root"
    return None


def _identity_analyzer_evidence(provider: IdentityProvider) -> dict[str, Any]:
    try:
        provider_revision = importlib.metadata.version("insightface")
    except importlib.metadata.PackageNotFoundError:
        provider_revision = None
    implementation_path = Path(__file__).resolve()
    model_fingerprint = getattr(provider, "model_fingerprint", None)
    if not isinstance(model_fingerprint, str) or len(model_fingerprint) != 64:
        if provider.name == "insightface_arcface":
            model_dir = identity_model_root() / "models" / "buffalo_l"
            records = [
                {"path": path.name, "sha256": _sha256_file(path)}
                for path in sorted(model_dir.glob("*.onnx"))
                if path.is_file() and not path.is_symlink()
            ]
            model_fingerprint = (
                hashlib.sha256(
                    json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                if records
                else None
            )
        else:
            model_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "provider": provider.name,
                        "providerRevision": provider_revision,
                        "modelRevision": None,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
    return {
        "analyzerId": IDENTITY_ANALYZER_ID,
        "analyzerVersion": IDENTITY_ANALYZER_VERSION,
        "implementationRef": "python_packages/reel_factory/reel_factory/identity_verification.py",
        "implementationFingerprint": _sha256_file(implementation_path),
        "provider": provider.name,
        "providerRevision": provider_revision,
        "modelRevision": "buffalo_l"
        if provider.name == "insightface_arcface"
        else None,
        "modelFingerprint": model_fingerprint,
    }


def identity_qc_receipt(result: dict[str, Any]) -> dict[str, Any]:
    """Return an exact output-bound QC receipt without inventing availability."""

    subject = result.get("subjectSha256")
    analyzer = result.get("analyzer")
    observations = result.get("observations")
    if (
        not isinstance(subject, str)
        or len(subject) != 64
        or any(character not in "0123456789abcdef" for character in subject)
    ):
        raise ValueError("identity_qc_subject_missing")
    if not isinstance(analyzer, dict) or not isinstance(observations, dict):
        raise ValueError("identity_qc_evidence_missing")
    if (
        analyzer.get("analyzerId") != IDENTITY_ANALYZER_ID
        or analyzer.get("analyzerVersion") != IDENTITY_ANALYZER_VERSION
    ):
        raise ValueError("identity_qc_analyzer_mismatch")
    reference_set_id = result.get("referenceSetId")
    reference_set_fingerprint = result.get("referenceSetFingerprint")
    reference_set_path = result.get("referenceSetPath")
    creator_profile = result.get("creatorIdentityProfile")
    if not isinstance(reference_set_id, str) or not reference_set_id.strip():
        raise ValueError("identity_qc_reference_set_id_missing")
    if (
        not isinstance(reference_set_fingerprint, str)
        or len(reference_set_fingerprint) != 64
        or any(
            character not in "0123456789abcdef"
            for character in reference_set_fingerprint
        )
    ):
        raise ValueError("identity_qc_reference_set_fingerprint_missing")
    if not isinstance(reference_set_path, str) or not reference_set_path.strip():
        raise ValueError("identity_qc_reference_set_path_missing")
    if (
        not isinstance(creator_profile, dict)
        or not str(creator_profile.get("profileId") or "").strip()
        or not _valid_sha256(creator_profile.get("profileFingerprint"))
    ):
        raise ValueError("identity_qc_creator_profile_missing")
    if (
        not _valid_sha256(analyzer.get("implementationFingerprint"))
        or not _valid_sha256(analyzer.get("modelFingerprint"))
        or not str(analyzer.get("implementationRef") or "").strip()
    ):
        raise ValueError("identity_qc_analyzer_evidence_invalid")
    stability = observations.get("faceStabilityScore")
    score = result.get("score")
    score_available = (
        not isinstance(score, bool)
        and isinstance(score, (int, float))
        and math.isfinite(float(score))
    )
    stability_value: float | None = None
    if not isinstance(stability, bool) and isinstance(stability, (int, float)):
        parsed_stability = float(stability)
        if math.isfinite(parsed_stability):
            stability_value = parsed_stability
    stability_available = stability_value is not None
    available = result.get("status") in {"passed", "failed"} and isinstance(
        score, (int, float)
    )
    available = available and score_available
    passed = bool(
        available
        and result.get("status") == "passed"
        and stability_available
        and stability_value is not None
        and stability_value >= FACE_STABILITY_THRESHOLD
    )
    reasons: list[dict[str, str]] = []
    if not available:
        reasons.append(
            {
                "code": str(result.get("failureReason") or "identity_unavailable"),
                "severity": "block",
            }
        )
    elif result.get("status") != "passed":
        reasons.append(
            {
                "code": str(
                    result.get("failureReason") or "identity_similarity_below_threshold"
                ),
                "severity": "block",
            }
        )
    elif not stability_available:
        reasons.append({"code": "face_stability_unavailable", "severity": "block"})
    elif stability_value is not None and stability_value < FACE_STABILITY_THRESHOLD:
        reasons.append({"code": "face_stability_below_threshold", "severity": "block"})
    identity_result_fingerprint = hashlib.sha256(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    receipt = {
        "schema": "reel_factory.identity_qc_receipt.v1",
        "policy": {
            "id": IDENTITY_ANALYZER_ID,
            "version": IDENTITY_ANALYZER_VERSION,
        },
        "subjectSha256": subject,
        "verdict": "pass" if passed else "blocked",
        "passed": passed,
        "evidenceOnly": True,
        "providerCalls": 0,
        "modelCalls": 0,
        "identityResultFingerprint": identity_result_fingerprint,
        "implementationRef": analyzer.get("implementationRef"),
        "implementationFingerprint": analyzer.get("implementationFingerprint"),
        "arcFaceModelFingerprint": analyzer.get("modelFingerprint"),
        "creator": result.get("creator"),
        "creatorIdentityProfile": creator_profile,
        "referenceSetId": reference_set_id,
        "referenceSetFingerprint": reference_set_fingerprint,
        "referenceSetPath": reference_set_path,
        "identityResult": result,
        "score": score,
        "faceStabilityScore": stability,
        "reasons": reasons,
    }
    observed_at = str(result.get("observedAt") or "")
    if not observed_at:
        raise ValueError("identity_qc_observed_at_missing")
    return {
        **receipt,
        "producerAttestation": sign_evidence_attestation(
            receipt,
            issuer="reel_factory.identity_verification",
            issued_at=observed_at,
            secret=load_evidence_secret(),
        ),
    }


def _provider_face_embeddings(
    provider: IdentityProvider, image_path: Path
) -> list[list[float]]:
    method = getattr(provider, "face_embeddings", None)
    if callable(method):
        values = method(image_path)
        return [list(map(float, item)) for item in values if item]
    embedding = provider.embedding(image_path)
    return [list(map(float, embedding))] if embedding else []


def _identity_sample_fractions(samples: int) -> tuple[float, ...]:
    if samples < 1:
        raise ValueError("identity_sample_count_invalid")
    if samples == IDENTITY_VIDEO_SAMPLE_COUNT:
        return IDENTITY_VIDEO_SAMPLE_FRACTIONS
    return tuple((index + 0.5) / samples for index in range(samples))


def _media_frames_for_embedding(
    media_path: Path, *, samples: int = IDENTITY_VIDEO_SAMPLE_COUNT
) -> list[Path]:
    if media_path.suffix.lower() in IMAGE_EXTS:
        return [media_path]
    if media_path.suffix.lower() not in VIDEO_EXTS:
        return [media_path]
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    tmp = Path(tempfile.mkdtemp(prefix="identity_verify_"))
    duration = _probe_duration(media_path)
    pcts = _identity_sample_fractions(samples)
    frames: list[Path] = []
    for idx, pct in enumerate(pcts):
        frame = tmp / f"frame_{idx}.jpg"
        timestamp = max(0.05, duration * pct) if duration else 0.5 + idx
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-y",
                str(frame),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        frames.append(frame)
    return frames


def _probe_duration(media_path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        raw = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "0",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(media_path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return float(raw.decode().strip())
    except ValueError:
        return None


def _load_reference_embeddings(
    path: Path, *, creator: str
) -> tuple[str, list[list[float]], str | None]:
    if path.is_symlink():
        return path.stem, [], "reference_set_symlink_forbidden"
    if not path.exists():
        return path.stem, [], "reference_set_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem, [], "reference_set_invalid_json"
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != REFERENCE_SET_SCHEMA
        or str(payload.get("creator") or "").strip().lower()
        != str(creator).strip().lower()
        or payload.get("status") != "ready"
    ):
        return path.stem, [], "reference_set_schema_or_creator_mismatch"
    quality_policy = payload.get("qualityPolicy")
    if quality_policy != {
        "id": REFERENCE_QUALITY_POLICY_ID,
        "version": REFERENCE_QUALITY_POLICY_VERSION,
        "exactlyOneFacePerSource": True,
        "minimumAcceptedSources": MINIMUM_REFERENCE_SOURCES,
        "outlierMinimumMedianCosine": REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE,
    }:
        return path.stem, [], "reference_set_quality_policy_mismatch"
    sources = payload.get("sourceImages")
    if not isinstance(sources, list) or not sources:
        return path.stem, [], "reference_set_sources_missing"
    accepted_sources = []
    for source in sources:
        if not isinstance(source, dict):
            return path.stem, [], "reference_set_source_record_invalid"
        if source.get("faceCount") != 1:
            return path.stem, [], "reference_set_source_face_count_invalid"
        if source.get("status") != "embedded":
            continue
        accepted_sources.append(source)
        raw_source = Path(str(source.get("path") or "")).expanduser()
        if (
            raw_source.is_symlink()
            or not raw_source.is_file()
            or _sha256_file(raw_source.resolve()) != source.get("sha256")
        ):
            return path.stem, [], "reference_set_source_substituted"
    embeddings = payload.get("embeddings")
    if (
        not isinstance(embeddings, list)
        or len(accepted_sources) < MINIMUM_REFERENCE_SOURCES
        or len(embeddings) != len(accepted_sources)
        or payload.get("acceptedSourceCount") != len(accepted_sources)
        or payload.get("rejectedSourceCount") != len(sources) - len(accepted_sources)
    ):
        return (
            str(payload.get("referenceSetId") or path.stem)
            if isinstance(payload, dict)
            else path.stem,
            [],
            "reference_embeddings_missing",
        )
    rows = [
        [float(value) for value in row]
        for row in embeddings
        if isinstance(row, list) and row
    ]
    return (
        str(payload.get("referenceSetId") or path.stem),
        rows,
        None if rows else "reference_embeddings_missing",
    )


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
    output_path = (
        Path(output).expanduser().resolve()
        if output
        else _reference_set_path(root_path, creator)
    )
    base: dict[str, Any] = {
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
    if not _output_allowed(root_path, output_path):
        return {**base, "failureReason": "output_must_be_under_identity_references"}
    if not input_path.exists() or not input_path.is_dir():
        return {**base, "failureReason": "input_dir_missing"}
    ok, reason = provider.available()
    if not ok:
        return {**base, "failureReason": reason}
    image_paths = sorted(
        path
        for path in input_path.rglob("*")
        if path.suffix.lower() in IMAGE_EXTS and path.is_file()
    )
    if not image_paths:
        return {**base, "failureReason": "no_reference_images_found"}

    candidate_embeddings: list[list[float]] = []
    sources: list[dict[str, Any]] = []
    for image_path in image_paths:
        item: dict[str, Any] = {
            "path": str(image_path),
            "sha256": _sha256_file(image_path),
            "status": "failed",
            "failureReason": "",
        }
        face_embeddings = _provider_face_embeddings(provider, image_path)
        item["faceCount"] = len(face_embeddings)
        item["consensusScore"] = None
        if len(face_embeddings) != 1:
            item["failureReason"] = (
                "face_embedding_missing"
                if not face_embeddings
                else "multiple_faces_detected"
            )
        else:
            item["status"] = "candidate"
            candidate_embeddings.append(face_embeddings[0])
        sources.append(item)

    if any(item["faceCount"] != 1 for item in sources):
        return {
            **base,
            "sourceImages": sources,
            "failureReason": "reference_source_face_count_invalid",
        }
    if len(candidate_embeddings) < MINIMUM_REFERENCE_SOURCES:
        return {
            **base,
            "sourceImages": sources,
            "failureReason": "insufficient_single_face_references",
        }

    accepted_embeddings: list[list[float]] = []
    accepted_sources: list[dict[str, Any]] = []
    for index, (source, embedding) in enumerate(
        zip(sources, candidate_embeddings, strict=True)
    ):
        similarities = [
            cosine_similarity(embedding, other)
            for other_index, other in enumerate(candidate_embeddings)
            if other_index != index
        ]
        consensus_score = float(statistics.median(similarities))
        source["consensusScore"] = consensus_score
        if consensus_score < REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE:
            source["status"] = "rejected"
            source["failureReason"] = "identity_embedding_outlier"
            continue
        source["status"] = "embedded"
        source["failureReason"] = ""
        accepted_sources.append(source)
        accepted_embeddings.append(embedding)
    if len(accepted_embeddings) < MINIMUM_REFERENCE_SOURCES:
        return {
            **base,
            "sourceImages": sources,
            "failureReason": "identity_reference_consensus_insufficient",
        }

    quality_policy = {
        "id": REFERENCE_QUALITY_POLICY_ID,
        "version": REFERENCE_QUALITY_POLICY_VERSION,
        "exactlyOneFacePerSource": True,
        "minimumAcceptedSources": MINIMUM_REFERENCE_SOURCES,
        "outlierMinimumMedianCosine": REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE,
    }
    reference_material = json.dumps(
        {
            "creator": creator,
            "provider": provider.name,
            "qualityPolicy": quality_policy,
            "acceptedSources": [item["sha256"] for item in accepted_sources],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    reference_set_id = hashlib.sha256(reference_material.encode("utf-8")).hexdigest()[
        :16
    ]
    payload = {
        **base,
        "status": "ready",
        "createdAt": datetime.now(UTC).isoformat(),
        "referenceSetId": reference_set_id,
        "qualityPolicy": quality_policy,
        "sourceImages": sources,
        "acceptedSourceCount": len(accepted_sources),
        "rejectedSourceCount": len(sources) - len(accepted_sources),
        "embeddings": accepted_embeddings,
        "failureReason": "",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(output_path.parent, 0o700)
    atomic_write_text(
        output_path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.chmod(output_path, 0o600)
    return payload


def delete_reference_set(*, creator: str, root: str | Path = ".") -> dict[str, Any]:
    path = _reference_set_path(Path(root).resolve(), creator)
    existed = path.exists()
    if existed:
        path.unlink()
    return {
        "schema": REFERENCE_SET_SCHEMA,
        "creator": creator,
        "referenceSetPath": str(path),
        "deleted": existed,
    }


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
    reference_set_id, embeddings, reference_error = _load_reference_embeddings(
        reference_path, creator=creator
    )
    reference_error = (
        _reference_path_error(root_path, reference_path) or reference_error
    )
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
    frame_extractor=None,
    identity_profile_id: str | None = None,
    identity_profile_fingerprint: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    path = Path(media_path).expanduser().resolve()
    provider = provider or get_identity_provider()
    reference_path = _reference_set_path(root_path, creator)
    reference_set_id, references, reference_error = _load_reference_embeddings(
        reference_path, creator=creator
    )
    reference_error = (
        _reference_path_error(root_path, reference_path) or reference_error
    )
    analyzer = _identity_analyzer_evidence(provider)
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "creator": creator,
        "observedAt": datetime.now(UTC).isoformat(),
        "status": "unavailable",
        "score": None,
        "threshold": threshold,
        "provider": provider.name,
        "referenceSetId": reference_set_id,
        "referenceSetPath": str(reference_path),
        "referenceSetFingerprint": (
            _sha256_file(reference_path) if reference_path.is_file() else None
        ),
        "subjectSha256": _sha256_file(path) if path.is_file() else None,
        "analyzer": analyzer,
        "creatorIdentityProfile": (
            {
                "profileId": identity_profile_id,
                "profileFingerprint": identity_profile_fingerprint,
            }
            if identity_profile_id is not None
            and identity_profile_fingerprint is not None
            else None
        ),
        "observations": {
            "frameCount": None,
            "frames": [],
            "faceStabilityScore": None,
        },
        "failureReason": "",
    }
    if not path.exists():
        return {**base, "failureReason": "media_missing"}
    ok, reason = provider.available()
    if not ok:
        return {**base, "failureReason": reason}
    if reference_error:
        return {
            **base,
            "failureReason": _identity_reference_failure_reason(
                reference_error, creator
            ),
        }
    generated_frames = frame_extractor is None and path.suffix.lower() in VIDEO_EXTS
    frames = (
        [Path(frame).expanduser().resolve() for frame in frame_extractor(path)]
        if frame_extractor
        else _media_frames_for_embedding(path)
    )
    cleanup_root = frames[0].parent if generated_frames and frames else None
    try:
        if not frames or any(not frame.exists() for frame in frames):
            return {**base, "failureReason": "frame_extract_failed"}
        frame_scores: list[float] = []
        frame_embeddings: list[list[float]] = []
        frame_observations: list[dict[str, Any]] = []
        duration = _probe_duration(path) if path.suffix.lower() in VIDEO_EXTS else None
        sample_points = (
            _identity_sample_fractions(len(frames)) if generated_frames else ()
        )
        for index, frame in enumerate(frames):
            embeddings = _provider_face_embeddings(provider, frame)
            observation: dict[str, Any] = {
                "index": index,
                "frameSha256": _sha256_file(frame),
                "timestampSeconds": (
                    round(duration * sample_points[index], 6)
                    if duration is not None and index < len(sample_points)
                    else None
                ),
                "facesDetected": len(embeddings),
            }
            frame_observations.append(observation)
            if not embeddings:
                return {
                    **base,
                    "observations": {
                        "frameCount": len(frames),
                        "frames": frame_observations,
                        "faceStabilityScore": None,
                        "samplingPolicy": _identity_sampling_policy(sample_points),
                    },
                    "failureReason": "face_embedding_missing",
                }
            if len(embeddings) != 1:
                return {
                    **base,
                    "status": "failed",
                    "observations": {
                        "frameCount": len(frames),
                        "frames": frame_observations,
                        "faceStabilityScore": None,
                        "samplingPolicy": _identity_sampling_policy(sample_points),
                    },
                    "failureReason": "multiple_faces_detected",
                }
            embedding = embeddings[0]
            frame_embeddings.append(embedding)
            frame_scores.append(
                max(
                    (cosine_similarity(embedding, ref) for ref in references),
                    default=0.0,
                )
            )
        adjacent = [
            cosine_similarity(first, second)
            for first, second in zip(
                frame_embeddings, frame_embeddings[1:], strict=False
            )
        ]
        face_stability = min(adjacent) if adjacent else 1.0
    finally:
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)
    score = min(frame_scores) if frame_scores else 0.0
    status = "passed" if score >= threshold else "failed"
    return {
        **base,
        "status": status,
        "score": round(score, 6),
        "frameCount": len(frame_scores),
        "frameScores": [round(value, 6) for value in frame_scores],
        "faceStabilityScore": round(face_stability, 6),
        "observations": {
            "frameCount": len(frame_scores),
            "frames": frame_observations,
            "faceStabilityScore": round(face_stability, 6),
            "samplingPolicy": _identity_sampling_policy(sample_points),
        },
        "failureReason": ""
        if status == "passed"
        else "identity_similarity_below_threshold",
    }


def _identity_sampling_policy(sample_points: tuple[float, ...]) -> dict[str, Any]:
    return {
        "id": "reel_factory.identity_stratified_full_duration",
        "version": "1.0.0",
        "sampleCount": len(sample_points),
        "fractions": [round(value, 6) for value in sample_points],
        "fullDurationBoundaryCoverage": bool(
            sample_points and sample_points[0] <= 0.05 and sample_points[-1] >= 0.95
        ),
    }


def verification_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command")

    verify = sub.add_parser(
        "verify", help="verify one generated media file against a creator reference set"
    )
    verify.add_argument("media_path")
    verify.add_argument("--creator", required=True)
    verify.add_argument("--root", default=".")
    verify.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    build = sub.add_parser(
        "identity-reference-build",
        help="build approved local identity reference embeddings",
    )
    build.add_argument("--creator", required=True)
    build.add_argument("--input-dir", required=True)
    build.add_argument("--root", default=".")
    build.add_argument("--output")
    build.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    build.add_argument("--json-embeddings", action="store_true")

    delete = sub.add_parser(
        "identity-reference-delete",
        help="delete a local identity reference embedding set",
    )
    delete.add_argument("--creator", required=True)
    delete.add_argument("--root", default=".")

    health = sub.add_parser(
        "identity-health",
        help="report identity provider and reference-set availability",
    )
    health.add_argument("--creator", required=True)
    health.add_argument("--root", default=".")

    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] not in {
        "verify",
        "identity-reference-build",
        "identity-reference-delete",
        "identity-health",
        "-h",
        "--help",
    }:
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
        if not args.json_embeddings:
            result = {
                key: value for key, value in result.items() if key != "embeddings"
            }
    elif args.command == "identity-reference-delete":
        result = delete_reference_set(creator=args.creator, root=args.root)
    elif args.command == "identity-health":
        result = identity_health(creator=args.creator, root=args.root)
    elif args.command == "verify":
        result = verify_identity(
            args.media_path,
            creator=args.creator,
            root=args.root,
            threshold=args.threshold,
        )
    else:
        ap.print_help()
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
