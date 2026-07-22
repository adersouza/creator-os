"""Immutable, output-bound human evidence for local-model Arena review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from .local_generation_queue import AppendOnlyJournal, LocalQueueError, fingerprint

SCHEMA: Final = "reel_factory.human_media_review.v1"
RUBRIC_VERSION: Final = "1.0.0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"human_media_review_{field}_missing")
    return normalized


def _sha256(value: Any, field: str) -> str:
    normalized = _required_text(value, field)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"human_media_review_{field}_invalid")
    return normalized


def _score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"human_media_review_{field}_invalid")
    normalized = float(value)
    if not 0 <= normalized <= 1:
        raise ValueError(f"human_media_review_{field}_invalid")
    return normalized


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"human_media_review_{field}_invalid")
    return value


def _timestamp(value: Any) -> str:
    normalized = _required_text(value, "reviewed_at")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("human_media_review_reviewed_at_timezone_missing")
    return normalized


@dataclass(frozen=True)
class HumanReviewRatings:
    realism: float
    attractiveness: float
    creator_identity_similarity: float
    face_stability: float
    motion_naturalness: float
    face_artifact_score: float
    hands_visible: bool
    hand_artifact_score: float | None
    body_artifact_score: float
    conversion_usefulness: float
    intent_adherence: float
    loop_acceptable: bool

    @classmethod
    def from_dict(cls, payload: Any) -> HumanReviewRatings:
        if not isinstance(payload, dict):
            raise ValueError("human_media_review_ratings_invalid")
        hands_visible = _boolean(payload.get("handsVisible"), "hands_visible")
        hand_score = payload.get("handArtifactScore")
        if hands_visible and hand_score is None:
            raise ValueError("human_media_review_hand_artifact_score_missing")
        if not hands_visible and hand_score is not None:
            raise ValueError(
                "human_media_review_hidden_hands_score_must_be_unavailable"
            )
        return cls(
            realism=_score(payload.get("realism"), "realism"),
            attractiveness=_score(payload.get("attractiveness"), "attractiveness"),
            creator_identity_similarity=_score(
                payload.get("creatorIdentitySimilarity"), "creator_identity_similarity"
            ),
            face_stability=_score(payload.get("faceStability"), "face_stability"),
            motion_naturalness=_score(
                payload.get("motionNaturalness"), "motion_naturalness"
            ),
            face_artifact_score=_score(
                payload.get("faceArtifactScore"), "face_artifact_score"
            ),
            hands_visible=hands_visible,
            hand_artifact_score=(
                _score(hand_score, "hand_artifact_score")
                if hand_score is not None
                else None
            ),
            body_artifact_score=_score(
                payload.get("bodyArtifactScore"), "body_artifact_score"
            ),
            conversion_usefulness=_score(
                payload.get("conversionUsefulness"), "conversion_usefulness"
            ),
            intent_adherence=_score(payload.get("intentAdherence"), "intent_adherence"),
            loop_acceptable=_boolean(payload.get("loopAcceptable"), "loop_acceptable"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "realism": self.realism,
            "attractiveness": self.attractiveness,
            "creatorIdentitySimilarity": self.creator_identity_similarity,
            "faceStability": self.face_stability,
            "motionNaturalness": self.motion_naturalness,
            "faceArtifactScore": self.face_artifact_score,
            "handsVisible": self.hands_visible,
            "handArtifactScore": self.hand_artifact_score,
            "bodyArtifactScore": self.body_artifact_score,
            "conversionUsefulness": self.conversion_usefulness,
            "intentAdherence": self.intent_adherence,
            "loopAcceptable": self.loop_acceptable,
        }


@dataclass(frozen=True)
class HumanReviewDecisions:
    creator_identity_preserved: bool
    anatomy_acceptable: bool
    operator_useful: bool
    approved_for_benchmark: bool

    @classmethod
    def from_dict(cls, payload: Any) -> HumanReviewDecisions:
        if not isinstance(payload, dict):
            raise ValueError("human_media_review_decisions_invalid")
        return cls(
            creator_identity_preserved=_boolean(
                payload.get("creatorIdentityPreserved"), "creator_identity_preserved"
            ),
            anatomy_acceptable=_boolean(
                payload.get("anatomyAcceptable"), "anatomy_acceptable"
            ),
            operator_useful=_boolean(payload.get("operatorUseful"), "operator_useful"),
            approved_for_benchmark=_boolean(
                payload.get("approvedForBenchmark"), "approved_for_benchmark"
            ),
        )

    def as_dict(self) -> dict[str, bool]:
        return {
            "creatorIdentityPreserved": self.creator_identity_preserved,
            "anatomyAcceptable": self.anatomy_acceptable,
            "operatorUseful": self.operator_useful,
            "approvedForBenchmark": self.approved_for_benchmark,
        }


@dataclass(frozen=True)
class HumanReviewProvenance:
    review_mode: str
    unblinding_reason: str | None
    source_references: tuple[tuple[str, str], ...]

    @classmethod
    def from_dict(cls, payload: Any) -> HumanReviewProvenance:
        if not isinstance(payload, dict):
            raise ValueError("human_media_review_provenance_invalid")
        mode = _required_text(payload.get("reviewMode"), "review_mode")
        if mode not in {"blinded", "unblinded"}:
            raise ValueError("human_media_review_review_mode_invalid")
        reason_raw = payload.get("unblindingReason")
        reason = str(reason_raw).strip() if reason_raw is not None else None
        if mode == "blinded" and reason:
            raise ValueError("human_media_review_blinded_reason_forbidden")
        if mode == "unblinded" and not reason:
            raise ValueError("human_media_review_unblinding_reason_missing")
        rows = payload.get("sourceReferences")
        if not isinstance(rows, list) or not rows:
            raise ValueError("human_media_review_source_references_missing")
        references: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("human_media_review_source_reference_invalid")
            references.append(
                (
                    _required_text(row.get("recordId"), "source_reference_id"),
                    _sha256(row.get("fingerprint"), "source_reference_fingerprint"),
                )
            )
        if len(set(references)) != len(references):
            raise ValueError("human_media_review_duplicate_source_reference")
        return cls(mode, reason, tuple(references))

    def as_dict(self) -> dict[str, Any]:
        return {
            "reviewMode": self.review_mode,
            "unblindingReason": self.unblinding_reason,
            "sourceReferences": [
                {"recordId": record_id, "fingerprint": record_fingerprint}
                for record_id, record_fingerprint in self.source_references
            ],
        }


@dataclass(frozen=True)
class HumanMediaReview:
    review_id: str
    arena_plan_id: str
    sample_id: str
    blinded_candidate_id: str
    subject_sha256: str
    source_sha256: str
    reviewer: str
    reviewed_at: str
    rubric_version: str
    ratings: HumanReviewRatings
    decisions: HumanReviewDecisions
    provenance: HumanReviewProvenance

    @classmethod
    def from_dict(cls, payload: Any) -> HumanMediaReview:
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError("human_media_review_schema_invalid")
        review = cls(
            review_id=_required_text(payload.get("reviewId"), "review_id"),
            arena_plan_id=_required_text(payload.get("arenaPlanId"), "arena_plan_id"),
            sample_id=_required_text(payload.get("sampleId"), "sample_id"),
            blinded_candidate_id=_required_text(
                payload.get("blindedCandidateId"), "blinded_candidate_id"
            ),
            subject_sha256=_sha256(payload.get("subjectSha256"), "subject_sha256"),
            source_sha256=_sha256(payload.get("sourceSha256"), "source_sha256"),
            reviewer=_required_text(payload.get("reviewer"), "reviewer"),
            reviewed_at=_timestamp(payload.get("reviewedAt")),
            rubric_version=_required_text(
                payload.get("rubricVersion"), "rubric_version"
            ),
            ratings=HumanReviewRatings.from_dict(payload.get("ratings")),
            decisions=HumanReviewDecisions.from_dict(payload.get("decisions")),
            provenance=HumanReviewProvenance.from_dict(payload.get("provenance")),
        )
        claimed = _sha256(payload.get("reviewFingerprint"), "review_fingerprint")
        if claimed != review.review_fingerprint:
            raise ValueError("human_media_review_fingerprint_mismatch")
        return review

    @property
    def review_fingerprint(self) -> str:
        return fingerprint(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "reviewId": self.review_id,
            "arenaPlanId": self.arena_plan_id,
            "sampleId": self.sample_id,
            "blindedCandidateId": self.blinded_candidate_id,
            "subjectSha256": self.subject_sha256,
            "sourceSha256": self.source_sha256,
            "reviewer": self.reviewer,
            "reviewedAt": self.reviewed_at,
            "rubricVersion": self.rubric_version,
            "ratings": self.ratings.as_dict(),
            "decisions": self.decisions.as_dict(),
            "provenance": self.provenance.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "reviewFingerprint": self.review_fingerprint}

    def qc_receipt(self) -> dict[str, Any]:
        passed = bool(
            self.decisions.creator_identity_preserved
            and self.decisions.anatomy_acceptable
            and self.decisions.operator_useful
            and self.decisions.approved_for_benchmark
        )
        reasons = []
        for field, approved in (
            (
                "creator_identity_not_preserved",
                self.decisions.creator_identity_preserved,
            ),
            ("anatomy_not_acceptable", self.decisions.anatomy_acceptable),
            ("operator_usefulness_rejected", self.decisions.operator_useful),
            ("benchmark_approval_rejected", self.decisions.approved_for_benchmark),
        ):
            if not approved:
                reasons.append({"code": field, "severity": "block"})
        return {
            "schema": "reel_factory.human_media_review_qc.v1",
            "policy": {
                "id": "reel_factory.structured_human_media_review",
                "version": self.rubric_version,
            },
            "subjectSha256": self.subject_sha256,
            "verdict": "pass" if passed else "blocked",
            "passed": passed,
            "evidenceOnly": True,
            "providerCalls": 0,
            "modelCalls": 0,
            "reviewId": self.review_id,
            "reviewFingerprint": self.review_fingerprint,
            "reasons": reasons,
        }


class HumanMediaReviewStore:
    """Append reviews beside benchmark evidence without another state database."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.journal = AppendOnlyJournal(self.root / "human_reviews.jsonl")

    def reviews(self) -> dict[str, HumanMediaReview]:
        result: dict[str, HumanMediaReview] = {}
        samples: set[str] = set()
        for event in self.journal.read().events:
            if event.get("eventType") != "human_media_review_recorded":
                continue
            review = HumanMediaReview.from_dict(event.get("payload"))
            if review.review_id in result:
                raise LocalQueueError("duplicate_human_review_identity")
            if review.sample_id in samples:
                raise LocalQueueError("duplicate_human_review_sample")
            result[review.review_id] = review
            samples.add(review.sample_id)
        return result

    def record(self, review: HumanMediaReview, *, output_path: Path) -> dict[str, Any]:
        resolved = output_path.expanduser().resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise LocalQueueError("human_review_output_missing_or_unsafe")
        if _sha256_file(resolved) != review.subject_sha256:
            raise LocalQueueError("human_review_output_substituted")
        existing = self.reviews()
        if review.review_id in existing:
            raise LocalQueueError("duplicate_human_review_identity")
        if any(item.sample_id == review.sample_id for item in existing.values()):
            raise LocalQueueError("duplicate_human_review_sample")
        return self.journal.append("human_media_review_recorded", review.as_dict())


def load_review(path: Path) -> HumanMediaReview:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    return HumanMediaReview.from_dict(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("--review", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--root", type=Path)
    sub.add_parser("status").add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    root = args.root or os.environ.get("CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT")
    store = HumanMediaReviewStore(
        Path(root).expanduser().resolve()
        if root
        else Path.home() / ".creator-os/state/reel_factory/local_benchmarks"
    )
    try:
        if args.command == "record":
            payload: Any = store.record(
                load_review(args.review), output_path=args.output
            )
        else:
            payload = {
                "schema": "reel_factory.human_media_review_status.v1",
                "root": str(store.root),
                "reviews": [
                    review.as_dict()
                    for review in sorted(
                        store.reviews().values(), key=lambda item: item.review_id
                    )
                ],
            }
    except (LocalQueueError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
