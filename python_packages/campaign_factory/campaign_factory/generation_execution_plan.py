from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .contracts import validate_generation_execution_plan

SCHEMA = "campaign_factory.generation_execution_plan.v1"

CreativeMode = Literal[
    "library_reuse",
    "soul_static",
    "local_wan",
    "best_motion",
    "motion_edit",
    "best_only_kling",
    "reference_video_remix",
]


@dataclass(frozen=True, slots=True)
class GenerationExecutionPlan:
    """Immutable Campaign policy consumed by generation workers.

    The plan deliberately contains policy, not run state. Provider quotes,
    paths, approval receipts, and execution results remain on the individual
    stage/run records.
    """

    creative_mode: CreativeMode
    still_strategy: str
    motion_strategy: str
    cost_classification: str
    providers: tuple[str, ...]
    models: tuple[str, ...]
    required_approvals: tuple[str, ...]
    provider_authorization: str
    required_lineage: tuple[str, ...]
    qc_requirements: tuple[str, ...]
    static_fallback_behavior: str
    allowed_output_surface: str
    paid_image_generation: bool
    paid_video_generation: bool

    @property
    def static_fallback_required(self) -> bool:
        return self.static_fallback_behavior != "not_required"

    @property
    def front_animation_mode(self) -> Literal["static", "kling"]:
        """Translate worker strategy without reinterpreting creative mode."""
        modes = {
            "static_mp4_only": "static",
            "kling_best_only": "kling",
        }
        try:
            return modes[self.motion_strategy]  # type: ignore[return-value]
        except KeyError as exc:
            raise ValueError(
                f"{self.creative_mode} does not use the front-generation worker"
            ) from exc

    def to_contract(self) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA,
            "creativeMode": self.creative_mode,
            "stillStrategy": self.still_strategy,
            "motionStrategy": self.motion_strategy,
            "costClassification": self.cost_classification,
            "providers": list(self.providers),
            "models": list(self.models),
            "requiredApprovals": list(self.required_approvals),
            "providerAuthorization": self.provider_authorization,
            "requiredLineage": list(self.required_lineage),
            "qcRequirements": list(self.qc_requirements),
            "staticFallbackBehavior": self.static_fallback_behavior,
            "allowedOutputSurface": self.allowed_output_surface,
            "paidImageGeneration": self.paid_image_generation,
            "paidVideoGeneration": self.paid_video_generation,
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
        validate_generation_execution_plan(payload)
        return payload


_PLANS: dict[str, GenerationExecutionPlan] = {
    "library_reuse": GenerationExecutionPlan(
        creative_mode="library_reuse",
        still_strategy="owned_library_asset",
        motion_strategy="library_existing_media",
        cost_classification="free",
        providers=(),
        models=(),
        required_approvals=("human_asset_approval",),
        provider_authorization="forbidden",
        required_lineage=("campaign_factory.owned_library_lineage.v1",),
        qc_requirements=("contentforge_quality", "human_asset_review"),
        static_fallback_behavior="not_required",
        allowed_output_surface="campaign_review",
        paid_image_generation=False,
        paid_video_generation=False,
    ),
    "soul_static": GenerationExecutionPlan(
        creative_mode="soul_static",
        still_strategy="soul_reference_pair",
        motion_strategy="static_mp4_only",
        cost_classification="paid_still_free_video",
        providers=("higgsfield",),
        models=("soul_2", "static_mp4"),
        required_approvals=("paid_generation", "human_still_approval"),
        provider_authorization="required_per_paid_call",
        required_lineage=(
            "reel_factory.generation_worker_lineage.v1",
            "reel_factory.generated_asset_lineage.v2",
        ),
        qc_requirements=(
            "generated_image_qc",
            "contentforge_quality",
            "human_still_review",
        ),
        static_fallback_behavior="required_for_every_accepted_still",
        allowed_output_surface="campaign_review",
        paid_image_generation=True,
        paid_video_generation=False,
    ),
    "local_wan": GenerationExecutionPlan(
        creative_mode="local_wan",
        still_strategy="accepted_still",
        motion_strategy="local_mlx_video",
        cost_classification="free",
        providers=("local",),
        models=(
            "local_wan22_ti2v_5b_mlx",
            "local_wan22_i2v_a14b_q4_mlx",
            "local_ltx23_distilled_mlx",
            "local_ltx23_dev_hq_mlx",
            "local_longcat_avatar15_q4_mlx",
            "static_mp4",
        ),
        required_approvals=("human_still_approval", "creative_approval_v2"),
        provider_authorization="forbidden",
        required_lineage=(
            "reel_factory.local_video_generation.v1",
            "reel_factory.local_model_router_decision.v1",
            "campaign_factory.local_motion_admission.v1",
            "campaign_factory.motion_generation_asset.v1",
        ),
        qc_requirements=(
            "arena_promotion_evidence",
            "contentforge_quality",
            "human_final_review",
        ),
        static_fallback_behavior="required_before_motion",
        allowed_output_surface="campaign_review",
        paid_image_generation=False,
        paid_video_generation=False,
    ),
    "best_motion": GenerationExecutionPlan(
        creative_mode="best_motion",
        still_strategy="accepted_still",
        motion_strategy="best_paid_motion",
        cost_classification="paid_video",
        providers=("wavespeed",),
        models=(
            "wavespeed_wan27_i2v_pro",
            "wavespeed_wan27_i2v",
            "wavespeed_wan27_reference",
            "wavespeed_wan22_s2v",
            "static_mp4",
        ),
        required_approvals=(
            "human_still_approval",
            "paid_generation",
            "creative_approval_v2",
        ),
        provider_authorization="required_per_paid_call",
        required_lineage=(
            "reel_factory.wavespeed_submission.v1",
            "campaign_factory.motion_generation_asset.v1",
        ),
        qc_requirements=("contentforge_quality", "human_final_review"),
        static_fallback_behavior="required_before_paid_motion",
        allowed_output_surface="campaign_review",
        paid_image_generation=False,
        paid_video_generation=True,
    ),
    "motion_edit": GenerationExecutionPlan(
        creative_mode="motion_edit",
        still_strategy="accepted_still",
        motion_strategy="local_motion_edit",
        cost_classification="free",
        providers=("local",),
        models=("ffmpeg", "static_mp4"),
        required_approvals=("human_still_approval",),
        provider_authorization="forbidden",
        required_lineage=(
            "reel_factory.motion_edit_render.v1",
            "reel_factory.generated_asset_lineage.v2",
        ),
        qc_requirements=(
            "caption_placement",
            "contentforge_quality",
            "human_final_review",
        ),
        static_fallback_behavior="required_before_motion",
        allowed_output_surface="campaign_review",
        paid_image_generation=False,
        paid_video_generation=False,
    ),
    "best_only_kling": GenerationExecutionPlan(
        creative_mode="best_only_kling",
        still_strategy="accepted_rank_one_still",
        motion_strategy="kling_best_only",
        cost_classification="paid_video",
        providers=("higgsfield", "kling"),
        models=("kling3_0", "static_mp4"),
        required_approvals=(
            "human_still_approval",
            "contentforge_approval",
            "rank_one_selection_receipt",
            "paid_generation",
        ),
        provider_authorization="required_per_paid_call",
        required_lineage=(
            "reel_factory.generation_worker_lineage.v1",
            "reel_factory.generated_asset_lineage.v2",
        ),
        qc_requirements=(
            "contentforge_quality",
            "rank_one_selection",
            "human_final_review",
        ),
        static_fallback_behavior="required_before_paid_motion",
        allowed_output_surface="campaign_review",
        paid_image_generation=False,
        paid_video_generation=True,
    ),
    "reference_video_remix": GenerationExecutionPlan(
        creative_mode="reference_video_remix",
        still_strategy="soul_endpoint_pair",
        motion_strategy="seedance_or_kling_remix",
        cost_classification="paid_still_and_video",
        providers=("higgsfield", "seedance", "kling"),
        models=("soul_2", "seedance_2_0", "kling3_0", "static_mp4"),
        required_approvals=(
            "reference_rights",
            "both_endpoint_frames",
            "paid_generation",
            "contentforge_approval",
            "final_human_review",
        ),
        provider_authorization="required_per_paid_call",
        required_lineage=(
            "reel_factory.reference_video_motion_analysis.v1",
            "reel_factory.reference_video_remix_plan.v1",
            "reel_factory.generation_worker_lineage.v1",
            "reel_factory.generated_asset_lineage.v2",
        ),
        qc_requirements=(
            "single_shot_scene_detection",
            "endpoint_frame_review",
            "contentforge_quality",
            "human_final_review",
        ),
        static_fallback_behavior="required_for_endpoint_candidates",
        allowed_output_surface="campaign_review",
        paid_image_generation=True,
        paid_video_generation=True,
    ),
}


def build_generation_execution_plan(mode: str) -> GenerationExecutionPlan:
    normalized = str(mode or "").strip().lower().replace("-", "_")
    try:
        plan = _PLANS[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown creative workflow mode: {mode}") from exc
    plan.to_contract()
    return plan


def require_generation_execution_mode(
    plan: GenerationExecutionPlan, expected_mode: CreativeMode
) -> dict[str, Any]:
    """Validate the exact immutable plan before a mode handler does any work."""
    if not isinstance(plan, GenerationExecutionPlan):
        raise TypeError("generation handler requires a GenerationExecutionPlan")
    contract = plan.to_contract()
    if plan.creative_mode != expected_mode:
        raise PermissionError(
            f"{plan.creative_mode} execution plan does not authorize "
            f"{expected_mode} handler"
        )
    return contract


def authorize_paid_generation(
    plan: GenerationExecutionPlan,
    *,
    expected_mode: CreativeMode,
    media_kind: Literal["image", "video"],
    required_approvals: tuple[str, ...],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Fail closed unless Campaign policy authorizes one paid provider action."""
    contract = require_generation_execution_mode(plan, expected_mode)
    paid_field = (
        plan.paid_image_generation
        if media_kind == "image"
        else plan.paid_video_generation
    )
    if not paid_field:
        raise PermissionError(
            f"{plan.creative_mode} execution plan does not authorize paid "
            f"{media_kind} generation"
        )
    if plan.provider_authorization != "required_per_paid_call":
        raise PermissionError(
            f"{plan.creative_mode} execution plan lacks paid provider authorization"
        )
    if not plan.providers or not plan.models:
        raise PermissionError(
            f"{plan.creative_mode} execution plan lacks provider/model authorization"
        )
    if provider is not None and provider not in plan.providers:
        raise PermissionError(
            f"{plan.creative_mode} execution plan does not authorize provider {provider}"
        )
    if model is not None and model not in plan.models:
        raise PermissionError(
            f"{plan.creative_mode} execution plan does not authorize model {model}"
        )
    missing = sorted(set(required_approvals).difference(plan.required_approvals))
    if missing:
        raise PermissionError(
            f"{plan.creative_mode} execution plan lacks required approvals: "
            + ", ".join(missing)
        )
    return contract


def generation_execution_mode_ids() -> tuple[str, ...]:
    return (
        "library_reuse",
        "soul_static",
        "local_wan",
        "best_motion",
        "reference_video_remix",
    )
