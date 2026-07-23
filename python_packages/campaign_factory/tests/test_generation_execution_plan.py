from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from campaign_factory.generation_execution_plan import (
    GenerationExecutionPlan,
    build_generation_execution_plan,
    generation_execution_mode_ids,
)

from pipeline_contracts import validate_generation_execution_plan


def test_generation_execution_plans_cover_exactly_five_modes() -> None:
    assert generation_execution_mode_ids() == (
        "library_reuse",
        "soul_static",
        "local_wan",
        "best_motion",
        "reference_video_remix",
    )

    plans = {
        mode: build_generation_execution_plan(mode)
        for mode in generation_execution_mode_ids()
    }
    for plan in plans.values():
        validate_generation_execution_plan(plan.to_contract())
        assert plan.allowed_output_surface == "campaign_review"

    assert plans["library_reuse"].provider_authorization == "forbidden"
    assert plans["local_wan"].provider_authorization == "forbidden"
    assert plans["soul_static"].motion_strategy == "static_mp4_only"
    assert plans["best_motion"].motion_strategy == "best_paid_motion"
    assert "creative_approval_v2" in plans["local_wan"].required_approvals
    assert "creative_approval_v2" in plans["best_motion"].required_approvals
    assert plans["reference_video_remix"].motion_strategy == "seedance_or_kling_remix"
    assert all(
        plan.static_fallback_required
        for mode, plan in plans.items()
        if mode != "library_reuse"
    )


def test_generation_execution_plan_is_deeply_immutable() -> None:
    plan = build_generation_execution_plan("best-only-kling")

    with pytest.raises(FrozenInstanceError):
        plan.motion_strategy = "local_motion_edit"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.required_approvals[0] = "bypass"  # type: ignore[index]


def test_only_front_worker_modes_expose_front_animation_mode() -> None:
    assert (
        build_generation_execution_plan("soul_static").front_animation_mode == "static"
    )
    assert (
        build_generation_execution_plan("best_only_kling").front_animation_mode
        == "kling"
    )

    with pytest.raises(ValueError, match="does not use the front-generation worker"):
        _ = build_generation_execution_plan("motion_edit").front_animation_mode


def test_generation_execution_plan_contract_rejects_cross_mode_policy_drift() -> None:
    payload = build_generation_execution_plan("best_motion").to_contract()
    payload["motionStrategy"] = "local_motion_edit"

    with pytest.raises(ValueError, match="motionStrategy"):
        validate_generation_execution_plan(payload)


def test_plan_has_no_mutable_collection_fields() -> None:
    plan = build_generation_execution_plan("reference_video_remix")

    assert isinstance(plan, GenerationExecutionPlan)
    assert isinstance(plan.providers, tuple)
    assert isinstance(plan.models, tuple)
    assert isinstance(plan.required_approvals, tuple)
    assert isinstance(plan.required_lineage, tuple)
    assert isinstance(plan.qc_requirements, tuple)
