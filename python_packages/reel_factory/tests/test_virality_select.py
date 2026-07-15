from __future__ import annotations

from pathlib import Path

import pytest
from reel_factory.virality_select import (
    predict_engagement,
    rank_candidates,
    rank_kling_candidate_manifest,
)


def _candidate(candidate_id: str, score: float | None) -> dict:
    candidate = {
        "id": candidate_id,
        "features": {"scene": "mirror"},
        "generatedAssetLineage": {"features": {"scene": "mirror"}},
    }
    if score is not None:
        candidate["knowledgeAdvisory"] = {
            "sourcePackId": "kp_test",
            "score": score,
            "measuredExampleCount": 2,
            "recommendationStatus": "advisory",
            "matchedPatternCount": 1,
        }
    return candidate


def test_missing_campaign_knowledge_is_honest() -> None:
    result = predict_engagement({"scene": "mirror"})

    assert result == {
        "score": 0.0,
        "matched": 0,
        "weight": 0.0,
        "source": "missing_campaign_knowledge",
        "recommendationStatus": "not_run",
        "measuredExampleCount": 0,
    }


def test_ranking_uses_only_explicit_campaign_advisory(tmp_path: Path) -> None:
    ranked = rank_candidates(
        [_candidate("low", 21.0), _candidate("high", 91.0)], tmp_path
    )

    assert [row["id"] for row in ranked] == ["high", "low"]
    assert ranked[0]["predictedEngagement"]["source"] == (
        "campaign_factory.explicit_knowledge_advisory"
    )
    assert ranked[0]["predictedEngagement"]["decisionAuthority"] is False
    assert not (tmp_path / "manifest.sqlite").exists()


def test_kling_ranking_fails_closed_without_advisory(tmp_path: Path) -> None:
    result = rank_kling_candidate_manifest(
        {
            "schema": "campaign_factory.kling_candidate_manifest.v1",
            "batchId": "batch_1",
            "candidates": [_candidate("one", None), _candidate("two", None)],
        },
        tmp_path,
    )

    assert result["status"] == "insufficient_signal"
    assert result["selectedCandidateId"] is None
    assert result["rankingOwnership"] == "campaign_factory.explicit_advisory"
    assert result["paidGenerationAuthorized"] is False


def test_invalid_advisory_never_fabricates_score() -> None:
    with pytest.raises(ValueError, match="finite number"):
        predict_engagement(
            {},
            knowledge_advisory={
                "score": float("nan"),
                "measuredExampleCount": 3,
                "recommendationStatus": "eligible",
            },
        )
