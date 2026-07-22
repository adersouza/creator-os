from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from reel_factory.human_media_review import (
    HumanMediaReview,
    HumanMediaReviewStore,
    HumanReviewDecisions,
    HumanReviewProvenance,
    HumanReviewRatings,
)
from reel_factory.local_generation_queue import LocalQueueError, sha256_file


def review_for(
    output: Path, *, review_id: str = "review-1", sample_id: str = "sample-1"
) -> HumanMediaReview:
    return HumanMediaReview(
        review_id=review_id,
        arena_plan_id="arena-1",
        sample_id=sample_id,
        blinded_candidate_id="candidate-A7",
        subject_sha256=sha256_file(output),
        source_sha256="b" * 64,
        reviewer="operator@example.test",
        reviewed_at="2026-07-22T20:00:00Z",
        rubric_version="1.0.0",
        ratings=HumanReviewRatings(
            realism=0.9,
            attractiveness=0.8,
            creator_identity_similarity=0.92,
            face_stability=0.88,
            motion_naturalness=0.84,
            face_artifact_score=0.05,
            hands_visible=False,
            hand_artifact_score=None,
            body_artifact_score=0.08,
            conversion_usefulness=0.86,
            intent_adherence=0.9,
            loop_acceptable=True,
        ),
        decisions=HumanReviewDecisions(
            creator_identity_preserved=True,
            anatomy_acceptable=True,
            operator_useful=True,
            approved_for_benchmark=True,
        ),
        provenance=HumanReviewProvenance(
            review_mode="blinded",
            unblinding_reason=None,
            source_references=(("arena-1:sample-1", "c" * 64),),
        ),
    )


def test_review_round_trip_requires_exact_fingerprint(tmp_path: Path) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"measured output")
    review = review_for(output)

    assert HumanMediaReview.from_dict(review.as_dict()) == review

    tampered = review.as_dict()
    tampered["ratings"]["realism"] = 0.1
    with pytest.raises(ValueError, match="fingerprint_mismatch"):
        HumanMediaReview.from_dict(tampered)


def test_review_rejects_version_provenance_and_unavailable_score_errors(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"measured output")
    review = review_for(output)
    wrong_version = review.as_dict()
    wrong_version["schema"] = "reel_factory.human_media_review.v2"
    with pytest.raises(ValueError, match="schema_invalid"):
        HumanMediaReview.from_dict(wrong_version)

    missing_provenance = review.as_dict()
    missing_provenance["provenance"]["sourceReferences"] = []
    with pytest.raises(ValueError, match="source_references_missing"):
        HumanMediaReview.from_dict(missing_provenance)

    invented_hidden_hand_score = review.as_dict()
    invented_hidden_hand_score["ratings"]["handArtifactScore"] = 0.0
    with pytest.raises(ValueError, match="hidden_hands_score_must_be_unavailable"):
        HumanMediaReview.from_dict(invented_hidden_hand_score)


def test_review_store_binds_output_and_rejects_duplicate_identity(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"measured output")
    store = HumanMediaReviewStore(tmp_path / "evidence")
    review = review_for(output)

    store.record(review, output_path=output)
    assert store.reviews() == {review.review_id: review}
    with pytest.raises(LocalQueueError, match="duplicate_human_review_identity"):
        store.record(review, output_path=output)
    with pytest.raises(LocalQueueError, match="duplicate_human_review_sample"):
        store.record(
            review_for(output, review_id="review-2", sample_id=review.sample_id),
            output_path=output,
        )


def test_review_store_rejects_substituted_output(tmp_path: Path) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"measured output")
    review = review_for(output)
    output.write_bytes(b"substituted output")

    with pytest.raises(LocalQueueError, match="output_substituted"):
        HumanMediaReviewStore(tmp_path / "evidence").record(review, output_path=output)


def test_review_emits_output_bound_qc_receipt(tmp_path: Path) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"measured output")
    review = review_for(output)

    receipt = review.qc_receipt()

    assert receipt["subjectSha256"] == sha256_file(output)
    assert receipt["reviewFingerprint"] == review.review_fingerprint
    assert receipt["passed"] is True
    rejected = replace(
        review,
        decisions=replace(review.decisions, operator_useful=False),
    ).qc_receipt()
    assert rejected["passed"] is False
    assert rejected["reasons"] == [
        {"code": "operator_usefulness_rejected", "severity": "block"}
    ]
