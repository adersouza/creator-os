from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

SCHEMA: Final = "campaign_factory.production_quality_policy.v1"

HARD_BLOCKERS: Final[tuple[str, ...]] = (
    "wrong_creator",
    "severe_face_or_body_corruption",
    "unreadable_or_corrupt_media",
    "missing_required_audio",
    "source_substitution",
    "duplicate_output",
    "invalid_duration_or_codec",
    "prohibited_publishing_state",
    "missing_account_authorization",
)

SOFT_RANKING_SIGNALS: Final[tuple[str, ...]] = (
    "attractiveness",
    "motion_naturalness",
    "motion_amount",
    "hook_strength",
    "visual_quality",
    "predicted_engagement",
    "minor_artifacts",
    "aesthetic_preference",
)


def production_quality_policy() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "hardBlockers": list(HARD_BLOCKERS),
        "softRankingSignals": list(SOFT_RANKING_SIGNALS),
        "softScoresBlockPublication": False,
        "calibrationEscalationAllowed": True,
    }


def production_asset_policy(
    recipe: Mapping[str, Any] | None,
) -> dict[str, Any]:
    autonomous = recipe is not None
    return {
        "humanReviewRequired": not autonomous,
        "creativeApprovalRequired": not autonomous,
        "productionMotionRecipe": dict(recipe) if recipe is not None else None,
        "qualityPolicy": production_quality_policy(),
    }


def initial_motion_blockers(
    recipe: Mapping[str, Any] | None,
) -> list[str]:
    blockers = ["contentforge_audit_required", "motion_specific_qc_required"]
    if recipe is None:
        blockers += ["human_final_review_required", "creative_approval_v2_required"]
    return blockers
