"""Register a completed motion render as a reviewable campaign asset.

Extracted from the retired local-MLX/WaveSpeed motion stage; this is the one
piece the live Higgsfield production lane still uses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import payload_fingerprint

from pipeline_contracts import (
    ContentIntentV1,
    CreatorIdentityProfileV1,
    IdentityReferenceV1,
    ProvenanceV1,
    SourceReferenceV1,
)

from .audio_policy import build_motion_audio_intent
from .core import (
    new_id,
    sanitize_for_storage,
    sha256_file,
)
from .persistence import utc_now
from .production_quality_policy import initial_motion_blockers, production_asset_policy


def _canonical_fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def register_review_asset(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source_asset_id: str,
    model_slug: str,
    model_id: str,
    source_path: Path,
    source_hash: str,
    output_path: Path,
    worker_result: dict[str, Any],
    paid: bool,
    motion_task: str = "image_to_video",
    request_fingerprint: str | None = None,
    production_motion_recipe: Mapping[str, Any] | None = None,
    prompt: str | None = None,
    audio_policy: str | None = None,
    audio_track_id: str | None = None,
    audio_track_name: str | None = None,
    audio_source: str | None = None,
    audio_start_offset: float | None = None,
    audio_volume: float | None = None,
    audio_selected_reason: str | None = None,
    pipeline_job_id: str | None = None,
    paid_authorization: Mapping[str, Any] | None = None,
    paid_authorization_path: Path | None = None,
) -> dict[str, Any]:
    if motion_task == "text_to_video":
        # Retired with the local-MLX stack; the Higgsfield lane never emits it.
        raise ValueError("text_to_video_motion_task_retired")
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise FileNotFoundError(f"motion output missing: {output_path}")
    digest = sha256_file(output_path)
    existing = factory.conn.execute(
        """SELECT * FROM rendered_assets
        WHERE campaign_id = ? AND content_hash = ? ORDER BY created_at, id LIMIT 1""",
        (campaign["id"], digest),
    ).fetchone()
    rendered_id = str(existing["id"]) if existing else new_id("asset")
    now = utc_now()
    caption_hash = factory.domains.publishability.text_hash("")
    generation = worker_result.get("result")
    generation = generation if isinstance(generation, dict) else {}
    audio = generation.get("audio")
    audio = audio if isinstance(audio, dict) else {"mode": "none"}
    audio_mode = str(audio.get("mode") or "none")
    embedded_audio = audio_mode in {"source", "generated", "preserved"}
    audio_intent = build_motion_audio_intent(
        policy=audio_policy,
        audio=audio,
        output_sha256=digest,
        selected_at=now,
        track_id=audio_track_id,
        track_name=audio_track_name,
        source=audio_source,
        start_offset_seconds=audio_start_offset,
        volume=audio_volume,
        selected_reason=audio_selected_reason,
    )
    blocking_issues = initial_motion_blockers(production_motion_recipe)
    if motion_task == "text_to_video":
        blocking_issues.append("text_to_video_identity_assignment_forbidden")
    if embedded_audio:
        blocking_issues.append("audio_video_alignment_qc_required")
    if motion_task in {"audio_image_to_video", "video_lipsync"} or any(
        marker in model_id for marker in ("longcat", "infinitetalk", "lipsync")
    ):
        blocking_issues.append("lip_sync_qc_required")
    if embedded_audio:
        blocking_issues.append("local_audio_policy_review_required")
    elif audio_intent["policy"] == "embedded_trending_required":
        blocking_issues.append("NEEDS_EMBEDDED_AUDIO")
    elif audio_intent["policy"] == "native_trending_required":
        blocking_issues.append("NEEDS_NATIVE_AUDIO")
    if generation.get("aiDisclosureRequired") is True:
        blocking_issues.append("ai_generated_media_disclosure_required")
    source_binding = {"path": str(source_path), "sha256": source_hash}
    video_edit = motion_task in {"video_retake", "video_extend", "video_lipsync"}
    prompt_only = motion_task == "text_to_video"
    static_fallback_source = None if video_edit or prompt_only else source_binding
    generation_source = None if motion_task == "text_to_video" else source_binding
    paid_generation_evidence = (
        _paid_generation_evidence(
            factory,
            campaign=campaign,
            model_slug=model_slug,
            model_id=model_id,
            motion_task=motion_task,
            source_asset_id=source_asset_id,
            source_path=source_path,
            source_hash=source_hash,
            output_path=output_path,
            output_hash=digest,
            request_fingerprint=request_fingerprint,
            prompt=prompt,
            worker_result=worker_result,
            authorization=paid_authorization,
            authorization_path=paid_authorization_path,
            produced_at=now,
        )
        if paid
        else None
    )
    local_routing_lineage = None
    metadata = {
        "schema": "campaign_factory.motion_generation_asset.v1",
        "asset_state": "approved_but_not_publishable",
        **production_asset_policy(production_motion_recipe),
        "contentforgeAuditRequired": True,
        "captionBurned": False,
        "audioBurned": embedded_audio,
        "embeddedAudioMode": audio_mode,
        "embeddedAudio": audio,
        "audioIntent": audio_intent,
        "nativeAudioResolved": False,
        "source": generation_source,
        "generationInput": generation_source,
        "staticFallbackSource": static_fallback_source,
        "promptSource": source_binding if prompt_only else None,
        "sourceAssetRole": (
            "prompt_provenance_only"
            if prompt_only
            else (
                "generation_input_only"
                if video_edit
                else "generation_input_and_static_fallback"
            )
        ),
        "identityRole": (
            "non_creator_broll"
            if motion_task == "text_to_video"
            else "creator_conditioned"
        ),
        "output": {"path": str(output_path), "sha256": digest},
        "modelId": model_id,
        "requestFingerprint": request_fingerprint,
        "localMotionAdmission": None,
        "localMotionRoutingLineage": local_routing_lineage,
        "paidGeneration": paid,
        "paidGenerationEvidence": paid_generation_evidence,
        "worker": worker_result,
        "publishability": {
            "status": "blocked",
            "asset_state": "approved_but_not_publishable",
            "blockingIssues": blocking_issues,
        },
    }
    source_clip = "text_prompt_only" if prompt_only else source_path.name
    outcome_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_bank": "none",
        "caption_banks": [],
        "creator_mix": model_slug,
        "creator_model": model_slug,
        "frame_type": "generated_motion",
        "length_class": "short",
        "format_class": "video",
        "caption_fit_version": "none",
        "suitability_decision": "review_required",
        "suitability_reason": "generated motion requires ContentForge and human review",
        "source_clip": source_clip,
    }
    blob_id = f"blob_{digest.lower()}"
    attempt_id = new_id("generation_attempt")
    lineage_edge_id = new_id("generation_edge")
    attempted_output_path = str(output_path)
    duplicate_disposition = "canonical_output"
    remove_duplicate = False
    if existing:
        canonical_path = Path(str(existing["output_path"])).expanduser().resolve()
        if not canonical_path.is_file():
            raise FileNotFoundError(
                f"canonical generation output missing for digest {digest}: "
                f"{canonical_path}"
            )
        if sha256_file(canonical_path) != digest:
            raise RuntimeError(
                f"canonical generation output hash mismatch for digest {digest}: "
                f"{canonical_path}"
            )
        if output_path.resolve() == canonical_path:
            duplicate_disposition = "reused_canonical_path"
        else:
            duplicate_disposition = "removed_unreferenced_duplicate"
            remove_duplicate = True
    normalized_prompt = " ".join(str(prompt or "").split())
    prompt_sha256 = (
        hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()
        if normalized_prompt
        else None
    )
    admission_fingerprint = None
    lineage = {
        "schema": "campaign_factory.generation_lineage_edge.v1",
        "modelId": model_id,
        "motionTask": motion_task,
        "requestFingerprint": request_fingerprint,
        "promptSha256": prompt_sha256,
        "source": {
            "assetId": source_asset_id,
            "sha256": source_hash,
            "role": ("prompt_provenance_only" if prompt_only else "generation_input"),
            "promptTaskFingerprint": None,
        },
        "output": {"blobId": blob_id, "sha256": digest},
        "admissionFingerprint": admission_fingerprint,
        "localMotionRouting": local_routing_lineage,
    }
    with factory.conn:
        factory.conn.execute(
            """
            INSERT OR IGNORE INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES (?, ?, ?, 'video', ?)
            """,
            (blob_id, digest.lower(), output_path.stat().st_size, now),
        )
        if not existing:
            factory.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
                 filename, media_type, content_surface, caption, caption_hash, caption_bank,
                 caption_banks_json, creator_mix, creator_model, frame_type, length_class,
                 format_class, caption_fit_version, suitability_decision, suitability_reason,
                 source_clip, caption_outcome_context_json, caption_generation_json, recipe,
                 target_ratio, metadata_json, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', '', ?, 'none', '[]', ?, ?,
                        'generated_motion', 'short', 'video', 'none', 'review_required', ?, ?,
                        ?, ?, ?, '9:16', ?, 'pending', 'review_ready', ?, ?)
                """,
                (
                    rendered_id,
                    campaign["id"],
                    source_asset_id,
                    digest,
                    str(output_path),
                    str(output_path),
                    output_path.name,
                    caption_hash,
                    model_slug,
                    model_slug,
                    outcome_context["suitability_reason"],
                    source_clip,
                    json.dumps(outcome_context, sort_keys=True),
                    json.dumps(sanitize_for_storage(metadata), sort_keys=True),
                    model_id,
                    json.dumps(sanitize_for_storage(metadata), sort_keys=True),
                    now,
                    now,
                ),
            )
        factory.conn.execute(
            """
            INSERT INTO generation_attempts
            (id, campaign_id, pipeline_job_id, source_asset_id, rendered_asset_id,
             output_blob_id, request_fingerprint, model_id, motion_task, prompt_sha256,
             source_sha256, admission_fingerprint, input_json, worker_result_json,
             attempted_output_path, duplicate_disposition, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                campaign["id"],
                pipeline_job_id,
                source_asset_id,
                rendered_id,
                blob_id,
                request_fingerprint,
                model_id,
                motion_task,
                prompt_sha256,
                None if prompt_only else source_hash,
                admission_fingerprint,
                json.dumps(
                    sanitize_for_storage(
                        {
                            "sourcePath": (None if prompt_only else str(source_path)),
                            "sourceSha256": None if prompt_only else source_hash,
                            "promptSource": (
                                {
                                    "assetId": source_asset_id,
                                    "path": str(source_path),
                                    "sha256": source_hash,
                                    "promptTaskFingerprint": None,
                                }
                                if prompt_only
                                else None
                            ),
                            "motionTask": motion_task,
                        }
                    ),
                    sort_keys=True,
                ),
                json.dumps(sanitize_for_storage(worker_result), sort_keys=True),
                attempted_output_path,
                duplicate_disposition,
                now,
            ),
        )
        factory.conn.execute(
            """
            INSERT INTO generation_lineage_edges
            (id, generation_attempt_id, source_asset_id, rendered_asset_id,
             output_blob_id, relation, lineage_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'generated_output', ?, ?)
            """,
            (
                lineage_edge_id,
                attempt_id,
                source_asset_id,
                rendered_id,
                blob_id,
                json.dumps(sanitize_for_storage(lineage), sort_keys=True),
                now,
            ),
        )
        if remove_duplicate:
            output_path.unlink()
    return dict(
        factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_id,)
        ).fetchone()
    )


def _paid_generation_evidence(
    factory: Any,
    *,
    campaign: Mapping[str, Any],
    model_slug: str,
    model_id: str,
    motion_task: str,
    source_asset_id: str,
    source_path: Path,
    source_hash: str,
    output_path: Path,
    output_hash: str,
    request_fingerprint: str | None,
    prompt: str | None,
    worker_result: Mapping[str, Any],
    authorization: Mapping[str, Any] | None,
    authorization_path: Path | None,
    produced_at: str,
) -> dict[str, Any]:
    if isinstance(override := worker_result.get("paidGenerationEvidence"), Mapping):
        return dict(override)
    if authorization is None or authorization_path is None:
        raise RuntimeError("paid_generation_authorization_evidence_missing")
    auth_path = Path(authorization_path).expanduser().resolve()
    if not auth_path.is_file() or auth_path.is_symlink():
        raise RuntimeError("paid_generation_authorization_evidence_unsafe")
    try:
        stored_authorization = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_generation_authorization_evidence_invalid") from exc
    if stored_authorization != dict(authorization):
        raise RuntimeError("paid_generation_authorization_evidence_mismatch")
    scope = authorization.get("scope")
    generation = worker_result.get("result")
    if not isinstance(scope, Mapping) or not isinstance(generation, Mapping):
        raise RuntimeError("paid_generation_execution_evidence_missing")
    provider_request_fingerprint = str(scope.get("requestFingerprint") or "")
    provider_model = str(scope.get("providerModel") or "")
    prediction_id = str(generation.get("predictionId") or "")
    evidence_path = Path(str(generation.get("evidencePath") or "")).expanduser()
    if evidence_path.is_symlink():
        raise RuntimeError("paid_generation_provider_evidence_unsafe")
    evidence_path = evidence_path.resolve()
    if not evidence_path.is_file():
        raise RuntimeError("paid_generation_provider_evidence_missing")
    try:
        provider_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("paid_generation_provider_evidence_invalid") from exc
    if (
        not request_fingerprint
        or len(request_fingerprint) != 64
        or scope.get("provider") != "wavespeed"
        or not provider_model
        or not prediction_id
        or generation.get("status") != "completed"
        or generation.get("authorizationId") != authorization.get("authorizationId")
        or generation.get("requestFingerprint") != provider_request_fingerprint
        or generation.get("providerModel") != provider_model
        or generation.get("outputSha256") != output_hash
        or any(
            provider_evidence.get(key) != generation.get(key)
            for key in (
                "schema",
                "requestFingerprint",
                "authorizationId",
                "providerModel",
                "status",
                "predictionId",
                "outputSha256",
            )
        )
    ):
        raise RuntimeError("paid_generation_provider_evidence_mismatch")
    cost_event_id = str(worker_result.get("campaignCostEventId") or "")
    cost_row = factory.conn.execute(
        "SELECT * FROM ai_cost_events WHERE id = ?", (cost_event_id,)
    ).fetchone()
    if cost_row is None:
        raise RuntimeError("paid_generation_spend_record_missing")
    cost_record = dict(cost_row)
    metadata = json.loads(cost_record.get("metadata_json") or "{}")
    if (
        cost_record.get("provider") != "wavespeed"
        or metadata.get("authorizationId") != authorization.get("authorizationId")
        or metadata.get("predictionId") != prediction_id
        or metadata.get("requestFingerprint") != provider_request_fingerprint
    ):
        raise RuntimeError("paid_generation_spend_record_mismatch")
    execution_receipt = worker_result.get("paidExecutionReceipt")
    if not isinstance(execution_receipt, Mapping):
        raise RuntimeError("paid_generation_execution_receipt_missing")
    receipt_path = Path(str(execution_receipt.get("path") or "")).expanduser()
    if receipt_path.is_symlink():
        raise RuntimeError("paid_generation_execution_receipt_unsafe")
    receipt_path = receipt_path.resolve()
    if not receipt_path.is_file() or sha256_file(receipt_path) != execution_receipt.get(
        "sha256"
    ):
        raise RuntimeError("paid_generation_execution_receipt_mismatch")

    campaign_record = {
        "id": str(campaign.get("id") or ""),
        "slug": str(campaign.get("slug") or ""),
        "modelSlug": model_slug,
    }
    campaign_fingerprint = _canonical_fingerprint(campaign_record)
    identity = CreatorIdentityProfileV1(
        profile_id=f"campaign-creator-{model_slug}",
        creator_key=model_slug,
        display_name=model_slug,
        model_profile=model_slug,
        identity_references=(
            IdentityReferenceV1(
                namespace="campaign_source_still",
                external_id=source_asset_id,
                fingerprint=source_hash,
            ),
        ),
        provenance=ProvenanceV1(
            producer="campaign_factory.motion_generation_stage",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=str(campaign["id"]),
                    fingerprint=campaign_fingerprint,
                ),
                SourceReferenceV1(
                    record_id=source_asset_id,
                    fingerprint=source_hash,
                ),
            ),
        ),
    ).to_dict()
    intent = ContentIntentV1(
        intent_id=f"paid-motion-intent-{request_fingerprint[:24]}",
        creator_identity_profile_id=str(identity["profileId"]),
        goal="create one creator-conditioned motion asset for human review",
        content_surface="reel",
        media_kind="video",
        style_lanes=("creator_conditioned_motion",),
        concept_tags=tuple(sorted({motion_task, model_id})),
        source_asset_fingerprints=(source_hash,),
        provenance=ProvenanceV1(
            producer="campaign_factory.motion_generation_stage",
            produced_at=produced_at,
            source_references=(
                SourceReferenceV1(
                    record_id=source_asset_id,
                    fingerprint=source_hash,
                ),
                SourceReferenceV1(
                    record_id=f"provider-request-{provider_request_fingerprint[:24]}",
                    fingerprint=provider_request_fingerprint,
                ),
            ),
        ),
    ).to_dict()
    normalized_prompt = " ".join(str(prompt or "").split())
    recipe = {
        "schema": "campaign_factory.paid_motion_recipe.v1",
        "recipeId": f"paid-motion-recipe-{request_fingerprint[:24]}",
        "motionTask": motion_task,
        "creatorOsModelId": model_id,
        "providerModel": provider_model,
        "campaignRequestFingerprint": request_fingerprint,
        "providerRequestFingerprint": provider_request_fingerprint,
        "sourceSha256": source_hash,
        "promptSha256": hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
    }
    prediction_fingerprint = _canonical_fingerprint(
        {
            "provider": "wavespeed",
            "providerModel": provider_model,
            "predictionId": prediction_id,
            "requestFingerprint": provider_request_fingerprint,
            "inputSha256": source_hash,
            "outputSha256": output_hash,
        }
    )
    execution_evidence = {
        "class": "paid_provider",
        "provider": "wavespeed",
        "providerModel": provider_model,
        "requestFingerprint": provider_request_fingerprint,
        "authorization": {
            "id": str(authorization["authorizationId"]),
            "fingerprint": payload_fingerprint(authorization),
        },
        "authorizationEvidence": {
            "path": str(auth_path),
            "sha256": sha256_file(auth_path),
        },
        "prediction": {
            "id": prediction_id,
            "fingerprint": prediction_fingerprint,
        },
        "providerEvidence": {
            "path": str(evidence_path),
            "sha256": sha256_file(evidence_path),
        },
        "spendRecord": {
            "id": cost_event_id,
            "fingerprint": payload_fingerprint(cost_record),
        },
        "executionReceipt": {
            "id": str(execution_receipt.get("id") or ""),
            "fingerprint": str(execution_receipt.get("fingerprint") or ""),
        },
        "executionReceiptEvidence": {
            "path": str(receipt_path),
            "sha256": str(execution_receipt.get("sha256") or ""),
        },
    }
    return {
        "creatorIdentityProfile": identity,
        "contentIntent": intent,
        "generationRecipe": recipe,
        "modelFingerprint": _canonical_fingerprint(
            {
                "provider": "wavespeed",
                "providerModel": provider_model,
                "creatorOsModelId": model_id,
            }
        ),
        "executionEvidence": execution_evidence,
        "spendRecord": cost_record,
        "campaignRequestFingerprint": request_fingerprint,
        "input": {"path": str(source_path), "sha256": source_hash},
        "output": {"path": str(output_path), "sha256": output_hash},
    }
