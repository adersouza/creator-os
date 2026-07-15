from __future__ import annotations

import pytest

from pipeline_contracts import (
    ContractValidationError,
    example_names,
    load_example,
    validate_account_eligibility_decision,
    validate_assignment_eligibility,
    validate_audio_catalog_export,
    validate_audio_intent,
    validate_campaign_draft_payload,
    validate_campaign_draft_payload_strict,
    validate_caption_outcome_context,
    validate_creative_plan,
    validate_front_generation_plan,
    validate_generated_asset_lineage,
    validate_generated_asset_lineage_v2,
    validate_generation_execution_plan,
    validate_generation_worker_lineage,
    validate_higgsfield_soul_image_prompt,
    validate_kling_3_video_prompt,
    validate_motion_edit_render,
    validate_pattern_card,
    validate_performance_sync,
    validate_post_metric_history_read,
    validate_recommendation_accuracy_report,
    validate_recommendation_next_batch,
    validate_reference_factory_knowledge_pack,
    validate_reference_video_motion_analysis,
    validate_reference_video_remix_plan,
    validate_repurposing_plan,
    validate_schema_examples,
    validate_threadsdash_handshake,
    validate_variant_assignment,
    validate_video_analysis,
)


def test_all_schema_examples_validate():
    checks = validate_schema_examples()

    assert {check["name"] for check in checks} == set(example_names())


def test_named_validators_accept_examples():
    validate_audio_intent(load_example("audio_intent"))
    validate_account_eligibility_decision(load_example("account_eligibility_decision"))
    validate_assignment_eligibility(load_example("assignment_eligibility"))
    validate_campaign_draft_payload(load_example("campaign_draft_payload"))
    validate_caption_outcome_context(load_example("caption_outcome_context"))
    validate_audio_catalog_export(load_example("audio_catalog_export"))
    validate_performance_sync(load_example("performance_sync"))
    validate_post_metric_history_read(load_example("post_metric_history.read"))
    validate_repurposing_plan(load_example("repurposing_plan"))
    validate_recommendation_next_batch(load_example("recommendation_next_batch"))
    validate_reference_factory_knowledge_pack(
        load_example("reference_factory_knowledge_pack")
    )
    validate_pattern_card(load_example("pattern_card"))
    validate_video_analysis(load_example("video_analysis"))
    validate_reference_video_motion_analysis(
        load_example("reference_video_motion_analysis")
    )
    validate_reference_video_remix_plan(load_example("reference_video_remix_plan"))
    validate_higgsfield_soul_image_prompt(load_example("higgsfield_soul_image_prompt"))
    validate_kling_3_video_prompt(load_example("kling_3_video_prompt"))
    validate_generated_asset_lineage(load_example("generated_asset_lineage"))
    validate_generated_asset_lineage_v2(
        load_example("generated_asset_lineage.v2.example.json")
    )
    validate_generation_worker_lineage(load_example("generation_worker_lineage"))
    validate_generation_execution_plan(load_example("generation_execution_plan"))
    validate_campaign_draft_payload(
        load_example("campaign_draft_payload.v2.example.json")
    )
    validate_creative_plan(load_example("creative_plan"))
    validate_variant_assignment(load_example("variant_assignment"))
    validate_motion_edit_render(load_example("motion_edit_render"))
    validate_front_generation_plan(load_example("front_generation_plan"))
    validate_recommendation_accuracy_report(
        load_example("recommendation_accuracy_report")
    )
    validate_threadsdash_handshake(load_example("threadsdash_handshake"))


def test_generation_execution_plan_rejects_policy_drift() -> None:
    payload = load_example("generation_execution_plan")
    payload["motionStrategy"] = "local_motion_edit"

    with pytest.raises(ContractValidationError, match="motionStrategy"):
        validate_generation_execution_plan(payload)


def test_threadsdash_handshake_rejects_publish_authority() -> None:
    payload = load_example("threadsdash_handshake")
    payload["capabilities"]["publishingAllowed"] = True

    with pytest.raises(ContractValidationError, match="publishingAllowed"):
        validate_threadsdash_handshake(payload)


def test_validator_reports_nested_required_field():
    payload = load_example("campaign_draft_payload")
    del payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]["gates"][
        "allow_publish"
    ]

    with pytest.raises(ContractValidationError, match="allow_publish"):
        validate_campaign_draft_payload(payload)


def test_knowledge_pack_requires_measured_outcome_provenance():
    payload = load_example("reference_factory_knowledge_pack")
    del payload["promptCards"][0]["measuredOutcomeProvenance"]

    with pytest.raises(ContractValidationError, match="measuredOutcomeProvenance"):
        validate_reference_factory_knowledge_pack(payload)


def test_reference_video_motion_analysis_rejects_multishot_source():
    payload = load_example("reference_video_motion_analysis")
    payload["source"]["shotCount"] = 2

    with pytest.raises(ContractValidationError, match="shotCount"):
        validate_reference_video_motion_analysis(payload)


def test_reference_video_analysis_requires_identity_transformation():
    payload = load_example("reference_video_motion_analysis")
    payload["distinctness"]["transformElements"] = [
        "wardrobe",
        "setting",
        "surface_text",
    ]

    with pytest.raises(ContractValidationError, match="transformElements"):
        validate_reference_video_motion_analysis(payload)


def test_reference_video_remix_plan_cannot_authorize_paid_generation():
    payload = load_example("reference_video_remix_plan")
    payload["animation"]["paidGenerationAuthorized"] = True

    with pytest.raises(ContractValidationError, match="paidGenerationAuthorized"):
        validate_reference_video_remix_plan(payload)


def test_reference_video_remix_plan_cannot_allow_publishing():
    payload = load_example("reference_video_remix_plan")
    payload["approval"]["publishingAllowed"] = True

    with pytest.raises(ContractValidationError, match="publishingAllowed"):
        validate_reference_video_remix_plan(payload)


def test_reference_video_remix_plan_requires_correct_endpoint_roles():
    payload = load_example("reference_video_remix_plan")
    payload["framePair"]["first"]["role"] = "last"

    with pytest.raises(ContractValidationError, match="role"):
        validate_reference_video_remix_plan(payload)


def test_reference_video_remix_plan_requires_matching_provider_model():
    payload = load_example("reference_video_remix_plan")
    payload["animation"]["model"] = "kling3_0"

    with pytest.raises(ContractValidationError, match="seedance_2_0"):
        validate_reference_video_remix_plan(payload)


def test_reference_video_remix_plan_blocks_command_before_endpoint_approval():
    payload = load_example("reference_video_remix_plan")
    payload["animation"]["command"] = ["higgsfield", "generate"]

    with pytest.raises(ContractValidationError, match="command"):
        validate_reference_video_remix_plan(payload)


def test_reference_video_remix_plan_requires_integer_provider_duration():
    payload = load_example("reference_video_remix_plan")
    payload["animation"]["inputs"]["durationSeconds"] = 7.5

    with pytest.raises(ContractValidationError, match="durationSeconds"):
        validate_reference_video_remix_plan(payload)


def test_generated_asset_lineage_requires_pipeline_trace_id():
    payload = load_example("generated_asset_lineage")
    del payload["pipelineTraceId"]

    with pytest.raises(ContractValidationError, match="pipelineTraceId"):
        validate_generated_asset_lineage(payload)


def test_v2_lineage_requires_prompt_id():
    payload = load_example("generated_asset_lineage.v2.example.json")
    del payload["source"]["promptId"]

    with pytest.raises(ContractValidationError, match="promptId"):
        validate_generated_asset_lineage_v2(payload)


def test_campaign_draft_payload_requires_generated_asset_lineage():
    payload = load_example("campaign_draft_payload")
    payload["drafts"][0]["metadata"]["campaign_factory"].pop(
        "generated_asset_lineage", None
    )

    with pytest.raises(ContractValidationError, match="generated_asset_lineage"):
        validate_campaign_draft_payload(payload)


def test_recommendation_accuracy_report_requires_causal_graph_ids():
    payload = load_example("recommendation_accuracy_report")
    del payload["reportGraphId"]

    with pytest.raises(ContractValidationError, match="reportGraphId"):
        validate_recommendation_accuracy_report(payload)


def test_performance_sync_requires_pipeline_causal_ids():
    payload = load_example("performance_sync")
    del payload["pipelineJobId"]

    with pytest.raises(ContractValidationError, match="pipelineJobId"):
        validate_performance_sync(payload)


def test_post_metric_history_read_requires_selected_source_columns():
    payload = load_example("post_metric_history.read")
    del payload["rows"][0]["views_count"]

    with pytest.raises(ContractValidationError, match="views_count"):
        validate_post_metric_history_read(payload)


@pytest.mark.parametrize("snapshot_at", [None, "not-a-date"])
def test_post_metric_history_read_requires_valid_snapshot_at(snapshot_at):
    payload = load_example("post_metric_history.read")
    payload["rows"][0]["snapshot_at"] = snapshot_at

    with pytest.raises(ContractValidationError, match="snapshot_at"):
        validate_post_metric_history_read(payload)


def test_campaign_draft_payload_keeps_graph_ids_optional_for_legacy_metadata():
    payload = load_example("campaign_draft_payload")
    meta = payload["drafts"][0]["metadata"]["campaign_factory"]
    for key in [
        "graph_id",
        "campaign_graph_id",
        "source_asset_graph_id",
        "rendered_asset_graph_id",
        "audit_graph_id",
    ]:
        meta.pop(key, None)

    validate_campaign_draft_payload(payload)


def test_campaign_draft_payload_accepts_optional_caption_outcome_context():
    payload = load_example("campaign_draft_payload")
    context = load_example("caption_outcome_context")
    meta = payload["drafts"][0]["metadata"]["campaign_factory"]
    meta["captionOutcomeContext"] = context
    meta["caption_outcome_context"] = context

    validate_campaign_draft_payload(payload)


def test_campaign_draft_payload_accepts_content_trust_blockers():
    payload = load_example("campaign_draft_payload")
    meta = payload["drafts"][0]["metadata"]["campaign_factory"]
    meta["publishability_failure_reasons"] = [
        "visual_qc_unavailable",
        "visual_qc_failed",
        "identity_verification_unavailable",
        "identity_verification_failed",
        "embedded_audio_missing",
    ]

    validate_campaign_draft_payload_strict(payload)


def test_caption_outcome_context_rejects_wrong_schema_id():
    context = load_example("caption_outcome_context")
    context["schema"] = "campaign_factory.caption_learning.v1"

    with pytest.raises(ContractValidationError, match="caption_outcome_context"):
        validate_caption_outcome_context(context)


def test_campaign_draft_payload_strict_requires_graph_ids_for_new_metadata():
    payload = load_example("campaign_draft_payload")
    meta = payload["drafts"][0]["metadata"]["campaign_factory"]
    meta.pop("graph_id", None)

    with pytest.raises(ContractValidationError, match="graph_id"):
        validate_campaign_draft_payload_strict(payload)


def test_campaign_draft_payload_strict_allows_explicit_legacy_compat():
    payload = load_example("campaign_draft_payload")
    meta = payload["drafts"][0]["metadata"]["campaign_factory"]
    for key in [
        "graph_id",
        "campaign_graph_id",
        "source_asset_graph_id",
        "rendered_asset_graph_id",
        "audit_graph_id",
    ]:
        meta.pop(key, None)
    meta["legacy_compat"] = True

    validate_campaign_draft_payload_strict(payload)


def test_repurposing_plan_contract_requires_known_preset():
    payload = load_example("repurposing_plan")
    payload["preset_name"] = "unknown"

    with pytest.raises(ContractValidationError, match="preset_name"):
        validate_repurposing_plan(payload)


def test_repurposing_plan_contract_rejects_out_of_range_target_count():
    payload = load_example("repurposing_plan")
    payload["target_count"] = 0

    with pytest.raises(ContractValidationError, match="target_count"):
        validate_repurposing_plan(payload)


def test_repurposing_plan_contract_rejects_extra_top_level_properties():
    payload = load_example("repurposing_plan")
    payload["unexpected"] = True

    with pytest.raises(ContractValidationError, match="unexpected"):
        validate_repurposing_plan(payload)


def test_repurposing_plan_contract_rejects_bad_master_asset_id_pattern():
    payload = load_example("repurposing_plan")
    payload["master_asset_id"] = "asset id with spaces"

    with pytest.raises(ContractValidationError, match="master_asset_id"):
        validate_repurposing_plan(payload)


def test_variant_assignment_contract_requires_account_binding():
    payload = load_example("variant_assignment")
    del payload["assignments"][0]["account_id"]

    with pytest.raises(ContractValidationError, match="account_id"):
        validate_variant_assignment(payload)


def test_variant_assignment_contract_rejects_extra_assignment_properties():
    payload = load_example("variant_assignment")
    payload["assignments"][0]["unexpected"] = True

    with pytest.raises(ContractValidationError, match="unexpected"):
        validate_variant_assignment(payload)


def test_variant_assignment_contract_rejects_bad_scores():
    payload = load_example("variant_assignment")
    payload["assignments"][0]["distinctness_scores"]["master_ssim"] = 1.2

    with pytest.raises(ContractValidationError, match="master_ssim"):
        validate_variant_assignment(payload)


def test_motion_edit_render_contract_requires_zero_paid_cost():
    payload = load_example("motion_edit_render")
    payload["estimatedCostUsd"] = 1

    with pytest.raises(ContractValidationError, match="estimatedCostUsd"):
        validate_motion_edit_render(payload)


def test_motion_edit_render_contract_requires_motion_edit_mode():
    payload = load_example("motion_edit_render")
    payload["animationMode"] = "kling"

    with pytest.raises(ContractValidationError, match="animationMode"):
        validate_motion_edit_render(payload)


def test_motion_edit_render_contract_requires_quality_dimensions():
    payload = load_example("motion_edit_render")
    del payload["quality"]["width"]

    with pytest.raises(ContractValidationError, match="width"):
        validate_motion_edit_render(payload)


def test_front_generation_plan_requires_human_review():
    payload = load_example("front_generation_plan")
    payload["humanReviewRequired"] = False

    with pytest.raises(ContractValidationError, match="humanReviewRequired"):
        validate_front_generation_plan(payload)


def test_front_generation_plan_never_allows_publishing():
    payload = load_example("front_generation_plan")
    payload["publishingAllowed"] = True

    with pytest.raises(ContractValidationError, match="publishingAllowed"):
        validate_front_generation_plan(payload)


def test_front_generation_plan_rejects_missing_budget_status():
    payload = load_example("front_generation_plan")
    del payload["budgetStatus"]

    with pytest.raises(ContractValidationError, match="budgetStatus"):
        validate_front_generation_plan(payload)


def test_campaign_draft_payload_validates_nested_ref_constraints():
    payload = load_example("campaign_draft_payload")
    context = payload["drafts"][0]["metadata"]["campaign_factory"][
        "captionOutcomeContext"
    ]
    context["schema"] = "wrong.schema"

    with pytest.raises(ContractValidationError, match="captionOutcomeContext"):
        validate_campaign_draft_payload(payload)
