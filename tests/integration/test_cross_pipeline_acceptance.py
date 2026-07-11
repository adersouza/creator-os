from __future__ import annotations

import copy
import json

from pipeline_contracts import (
    load_example,
    schema_path,
    validate_audio_intent,
    validate_generated_asset_lineage,
    validate_higgsfield_soul_image_prompt,
    validate_kling_3_video_prompt,
    validate_repurposing_plan,
    validate_threadsdash_draft_payload_strict,
)


def _caption_context() -> dict:
    return {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "sha256-caption-fit-check",
        "caption_text": "mirror check",
        "caption_bank": "simple_native",
        "caption_banks": ["simple_native"],
        "creator_mix": "Stacey",
        "creator_model": "stacey_soul_v2",
        "frame_type": "mirror_selfie",
        "length_class": "short",
        "format_class": "reel",
        "caption_fit_version": "v1",
        "suitability_decision": "allowed",
        "suitability_reason": "deterministic_acceptance_fixture",
        "render_recipe": "reel_factory.direct_reference_image.v1",
        "source_clip": "fixture://reference/stacey_mirror.jpg",
        "rendered_output": "fixture://render/stacey_mirror_reel",
    }


def _audio_intent() -> dict:
    return {
        "schema": "pipeline.audio_intent.v1",
        "mode": "native_platform_audio",
        "required": True,
        "status": "attached",
        "platform": "instagram",
        "surface": "regular_reel",
        "recommendations": [
            {
                "audio_title": "Fixture Pop",
                "artist_name": "Creator OS",
                "platform_audio_id": "ig_audio_fixture_1",
                "platform_url": "https://instagram.com/audio/fixture-pop",
                "freshness": "stable",
                "confidence": 0.88,
                "vibe_tags": ["fit_check", "mirror"],
                "rationale": "fixture:contract_parity",
                "instruction": "Attach native instagram audio: Fixture Pop",
            }
        ],
        "operator_selection": {
            "audio_title": "Fixture Pop",
            "artist_name": "Creator OS",
            "platform_audio_id": "ig_audio_fixture_1",
            "platform_url": "https://instagram.com/audio/fixture-pop",
            "selected_at": "2026-06-13T12:00:00Z",
            "attached_at": "2026-06-13T12:01:00Z",
            "selection_source": "acceptance_fixture",
        },
        "gates": {
            "allow_draft_export": True,
            "allow_preview_schedule": False,
            "allow_live_schedule": False,
            "allow_publish": False,
        },
    }


def _generated_asset_lineage(caption: dict) -> dict:
    return {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "source": {
            "referenceImage": "fixture://reference/stacey_mirror",
            "sourceReferenceId": "reference_acceptance_1",
            "contentSurface": "reel",
        },
        "generation": {
            "stillPromptId": "still_prompt_acceptance_1",
            "motionPromptId": "motion_prompt_acceptance_1",
            "output": "fixture://render/stacey_mirror_reel",
            "generated": False,
        },
        "review": {
            "approved": True,
            "visualVerificationId": "visual_verify_acceptance_1",
            "captionVerificationId": "caption_verify_acceptance_1",
        },
        "quality": {
            "safeZone": "pass",
            "captionPlacement": "pass",
            "discoverability": "pass",
        },
        "asset_state": "exportable",
        "publishability_failure_reasons": [],
        "blockingReason": None,
        "rootCause": None,
        "captionOutcomeContext": caption,
        "pipelineTraceId": "trace_phase4_acceptance_001",
    }


def _campaign_draft_payload() -> dict:
    caption = _caption_context()
    audio = _audio_intent()
    lineage = _generated_asset_lineage(caption)
    campaign_factory = {
        "graph_id": "cg_rendered_asset_acceptance_reel_1",
        "campaign_graph_id": "cg_campaign_acceptance",
        "source_asset_graph_id": "cg_source_asset_reference_1",
        "rendered_asset_graph_id": "cg_rendered_asset_acceptance_reel_1",
        "audit_graph_id": "cg_audit_acceptance_1",
        "campaign_id": "acceptance_phase4",
        "rendered_asset_id": "asset_acceptance_reel_1",
        "asset_id": "asset_acceptance_reel_1",
        "content_surface": "reel",
        "ig_media_type": "REELS",
        "asset_state": "exportable",
        "approved": True,
        "captioned_render_present": True,
        "visible_caption_verification": "pass",
        "expected_visual_verification": "pass",
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "content_fingerprint": "sha256-content-acceptance-reel-1",
        "caption_hash": caption["caption_hash"],
        "instagram_post_caption": "mirror check",
        "instagram_post_caption_hash": "sha256-post-caption",
        "readiness_checks_pass": True,
        "publishability_failure_reasons": [],
        "concept_id": "concept_acceptance_mirror",
        "parent_asset_id": "parent_acceptance_1",
        "parent_reel_id": "parent_reel_acceptance_1",
        "variant_family_id": "vfam_acceptance_contentforge_1",
        "variant_id": "variant_acceptance_001",
        "variant_index": 1,
        "variant_operations": ["caption_safe_v2", "cover_frame"],
        "captionOutcomeContext": caption,
        "caption_outcome_context": caption,
        "generated_asset_lineage": lineage,
        "audio_intent": audio,
    }
    campaign_factory["handoff_manifest"] = {
        "manifest_version": 1,
        "asset_id": campaign_factory["asset_id"],
        "render_file_id": "render_file_acceptance_1",
        "content_fingerprint": campaign_factory["content_fingerprint"],
        "caption_hash": campaign_factory["caption_hash"],
        "captionOutcomeContext": caption,
        "visual_verification_id": "visual_verify_acceptance_1",
        "caption_verification_id": "caption_verify_acceptance_1",
        "audio_id": "ig_audio_fixture_1",
        "distribution_plan_id": "dist_acceptance_1",
        "exported_by_system": "campaign_factory",
        "exported_at": "2026-06-13T12:05:00Z",
        "concept_id": campaign_factory["concept_id"],
        "parent_asset_id": campaign_factory["parent_asset_id"],
        "parent_reel_id": campaign_factory["parent_reel_id"],
        "variant_family_id": campaign_factory["variant_family_id"],
        "variant_id": campaign_factory["variant_id"],
        "variant_index": campaign_factory["variant_index"],
        "variant_operations": campaign_factory["variant_operations"],
        "instagram_post_caption": campaign_factory["instagram_post_caption"],
        "instagram_post_caption_hash": campaign_factory["instagram_post_caption_hash"],
        "content_surface": "reel",
        "ig_media_type": "REELS",
        "visualQcStatus": "passed",
        "identityVerificationStatus": "passed",
        "visualQc": {"visualQcStatus": "passed", "status": "passed"},
        "identityVerification": {
            "schema": "reel_factory.identity_verification.v1",
            "status": "passed",
            "score": 0.91,
        },
    }
    return {
        "schema": "campaign_factory.threadsdash_drafts.v1",
        "campaign": "acceptance_phase4",
        "userId": "user_acceptance",
        "drafts": [
            {
                "platform": "instagram",
                "status": "draft",
                "distributionSurface": "regular_reel",
                "content": campaign_factory["instagram_post_caption"],
                "captionOutcomeContext": caption,
                "metadata": {"campaign_factory": campaign_factory},
            }
        ],
        "pipelineTraceId": "trace_phase4_acceptance_001",
    }


def _feed_single_draft_payload() -> dict:
    payload = copy.deepcopy(_campaign_draft_payload())
    draft = payload["drafts"][0]
    cf = draft["metadata"]["campaign_factory"]
    draft["distributionSurface"] = "feed_single"
    draft["media_urls"] = ["https://cdn.example/acceptance-feed.jpg"]
    cf["content_surface"] = "feed_single"
    cf["ig_media_type"] = "IMAGE"
    cf["audio_intent"]["required"] = False
    cf["audio_intent"]["status"] = "not_required"
    cf["handoff_manifest"].update(
        {
            "manifest_version": 2,
            "content_surface": "feed_single",
            "contentSurface": "feed_single",
            "ig_media_type": "IMAGE",
            "igMediaType": "IMAGE",
            "mediaItems": [
                {"type": "image", "url": "https://cdn.example/acceptance-feed.jpg"}
            ],
            "audio_id": "not_required",
            "surfaceReadiness": {"canHandoff": True, "blockers": []},
        }
    )
    return payload


def test_reel_factory_reference_still_and_motion_contracts_validate_for_campaign_handoff() -> (
    None
):
    still_prompt = {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": "ready_for_human_review",
        "sourceReferenceId": "reference_acceptance_1",
        "sourcePatternId": "pattern_mirror_selfie",
        "modelProfile": "stacey_soul_v2",
        "mainPrompt": "Use the reference-image pose and room setting with Stacey Soul ID. Keep head and face fully visible.",
        "negativePrompt": "no text, no logos, no cropped head, no outfit change",
        "closenessControls": {"pose": "high", "wardrobe": "high", "setting": "high"},
        "formatCard": {"aspectRatio": "9:16", "surface": "reel"},
        "aspectRatio": "9:16",
        "reviewNotes": ["deterministic acceptance fixture; no generation invoked"],
    }
    motion_prompt = {
        "schema": "reference_factory.kling_3_video_prompt.v1",
        "tool": "kling_3_video",
        "status": "ready_for_human_review",
        "sourceReferenceId": still_prompt["sourceReferenceId"],
        "sourcePatternId": still_prompt["sourcePatternId"],
        "modelProfile": still_prompt["modelProfile"],
        "firstFrameInstruction": "Use accepted still fixture://render/stacey_mirror_still.png as the first frame.",
        "mainPrompt": "Five second 9:16 mirror selfie motion: tiny phone sway, breathing, slight posture shift. No new text or pose change.",
        "negativePrompt": "no text, no logos, no face crop, no outfit change, no location change",
        "closenessControls": {
            "pose": "locked",
            "wardrobe": "locked",
            "setting": "locked",
        },
        "scenes": [{"durationSeconds": 5, "motion": "subtle_handheld_sway"}],
        "aspectRatio": "9:16",
        "reviewNotes": ["deterministic acceptance fixture; no animation invoked"],
    }
    lineage = {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "source": {
            "referenceImage": "fixture://reference/stacey_mirror.jpg",
            "sourceReferenceId": still_prompt["sourceReferenceId"],
            "contentSurface": "reel",
        },
        "generation": {
            "stillPrompt": still_prompt,
            "motionPrompt": motion_prompt,
            "output": "fixture://render/stacey_mirror_reel.mp4",
            "generated": False,
        },
        "review": {
            "approved": True,
            "visualVerificationId": "visual_verify_acceptance_1",
            "captionVerificationId": "caption_verify_acceptance_1",
        },
        "quality": {
            "safeZone": "pass",
            "captionPlacement": "pass",
            "discoverability": "pass",
        },
        "asset_state": "exportable",
        "publishability_failure_reasons": [],
        "blockingReason": None,
        "rootCause": None,
        "captionOutcomeContext": _caption_context(),
        "pipelineTraceId": "trace_phase4_acceptance_001",
    }

    validate_higgsfield_soul_image_prompt(still_prompt)
    validate_kling_3_video_prompt(motion_prompt)
    validate_generated_asset_lineage(lineage)

    payload = _campaign_draft_payload()
    cf = payload["drafts"][0]["metadata"]["campaign_factory"]
    assert cf["handoff_manifest"]["asset_id"] == cf["asset_id"]
    assert cf["captionOutcomeContext"] == lineage["captionOutcomeContext"]
    validate_audio_intent(cf["audio_intent"])
    validate_threadsdash_draft_payload_strict(payload)


def test_contentforge_variant_pack_output_maps_to_campaign_factory_variant_lineage() -> (
    None
):
    repurposing_plan = {
        "schema": "campaign_factory.repurposing_plan.v1",
        "master_asset_id": "parent_acceptance_1",
        "preset_name": "ig_subtle",
        "target_count": 1,
        "platform": "instagram",
        "custom_config": {
            "contentforgePreset": "caption_safe_v2",
            "preserveBurnedCaptions": True,
        },
    }
    contentforge_variant = {
        "schema": "contentforge.variant_pack.v2",
        "runId": "cf_variant_run_acceptance_1",
        "source": "fixture://render/parent_acceptance_1.mp4",
        "results": [
            {
                "variantId": "variant_acceptance_001",
                "variantFamilyId": "vfam_acceptance_contentforge_1",
                "variantIndex": 1,
                "output": "fixture://contentforge/variant_acceptance_001.mp4",
                "recommendedUploadReady": True,
                "operationSet": "caption_safe_v2",
                "familyName": "cover_frame",
                "operationSignals": {
                    "coverFrameDifferent": True,
                    "horizontalFlip": False,
                    "captionTextChanged": False,
                    "metadataChanged": True,
                },
                "quality": {
                    "visualQcPassed": True,
                    "captionPlacementQcPassed": True,
                    "discoverabilityPassed": True,
                    "publishabilityPassed": True,
                },
            }
        ],
    }

    validate_repurposing_plan(repurposing_plan)
    result = contentforge_variant["results"][0]
    assert result["recommendedUploadReady"] is True
    assert result["quality"] == {
        "visualQcPassed": True,
        "captionPlacementQcPassed": True,
        "discoverabilityPassed": True,
        "publishabilityPassed": True,
    }

    payload = _campaign_draft_payload()
    cf = payload["drafts"][0]["metadata"]["campaign_factory"]
    assert cf["variant_id"] == result["variantId"]
    assert cf["variant_family_id"] == result["variantFamilyId"]
    assert cf["variant_index"] == result["variantIndex"]
    assert result["operationSet"] in cf["variant_operations"]
    validate_threadsdash_draft_payload_strict(payload)


def test_campaign_handoff_manifest_v2_matches_dashboard_surface_draft_expectations() -> (
    None
):
    payload = _feed_single_draft_payload()
    validate_threadsdash_draft_payload_strict(payload)

    cf = payload["drafts"][0]["metadata"]["campaign_factory"]
    manifest = cf["handoff_manifest"]
    assert manifest["manifest_version"] == 2
    assert manifest["exported_by_system"] == "campaign_factory"
    assert manifest["content_surface"] == "feed_single"
    assert manifest["ig_media_type"] == "IMAGE"
    assert manifest["mediaItems"] == [
        {"type": "image", "url": "https://cdn.example/acceptance-feed.jpg"}
    ]
    assert manifest["surfaceReadiness"]["canHandoff"] is True

    assert (
        json.loads(schema_path("campaign_draft_payload").read_text(encoding="utf-8"))[
            "$id"
        ]
        == "campaign_factory.threadsdash_drafts.v1"
    )


def test_integration_fixtures_do_not_require_runtime_artifacts() -> None:
    payload = _campaign_draft_payload()
    serialized = json.dumps(payload)
    forbidden_fragments = [
        "/00_source_videos/",
        "/02_processed/",
        "/output/",
        "/uploads/",
        "/campaigns/",
        "/tmp/",
        ".sqlite",
        '.mp4"',
        '.mov"',
    ]
    assert "fixture://" in serialized
    for fragment in forbidden_fragments:
        assert fragment not in serialized

    example = load_example("campaign_draft_payload")
    validate_threadsdash_draft_payload_strict(example)
