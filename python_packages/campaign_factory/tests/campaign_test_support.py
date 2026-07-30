from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True, exist_ok=True)
    (reel_root / "01_captions").mkdir(parents=True, exist_ok=True)
    return CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=reel_root,
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )


def authorize_campaign_governance(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    creator: str = "stacey",
    campaign: str = "may",
    provider: str = "openai",
    soul_id: str = "soul_stacey_v1",
    territories: list[str] | None = None,
    account_scope: list[str] | None = None,
    reference_video_use: bool = False,
) -> dict:
    model = cf.domains.models.upsert_model(creator)
    campaign_row = cf.domains.models.upsert_campaign(campaign, creator)
    identity_campaign = cf.domains.models.upsert_campaign(
        f"{creator}-identity-registry", creator
    )
    source_path = tmp_path / f"{creator}_canonical_original.bin"
    source_path.write_bytes(f"operator-original:{creator}".encode())
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_id = f"src_identity_{creator}"
    now = "2026-07-30T12:00:00Z"
    cf.conn.execute(
        """
        INSERT OR IGNORE INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, media_type, platform, source_prompt, account_ids_json, status,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'instagram', '{}', '[]', 'approved',
                ?, ?)
        """,
        (
            source_id,
            identity_campaign["id"],
            model["id"],
            source_sha,
            str(source_path),
            str(source_path),
            source_path.name,
            now,
            now,
        ),
    )
    approval = {
        "sourceAssetId": source_id,
        "sha256": source_sha,
        "decision": "approved",
        "operator": "test",
        "reason": "canonical identity fixture",
        "decidedAt": now,
    }
    cf.conn.execute(
        """
        INSERT OR IGNORE INTO activity_events
        (id, event_type, campaign_id, source_asset_id, status, message,
         metadata_json, created_at)
        VALUES (?, 'source_approval_decided', ?, ?, 'success',
                'Canonical identity source approved', ?, ?)
        """,
        (
            f"event_identity_{creator}",
            identity_campaign["id"],
            source_id,
            json.dumps(approval, sort_keys=True),
            now,
        ),
    )
    origin_attestation = {
        "sourceAssetId": source_id,
        "sha256": source_sha,
        "originClassification": "human_original",
        "operatorApproved": True,
        "operator": "test",
        "attestedAt": now,
    }
    cf.conn.execute(
        """
        INSERT OR IGNORE INTO activity_events
        (id, event_type, campaign_id, source_asset_id, status, message,
         metadata_json, created_at)
        VALUES (?, 'canonical_identity_origin_attested', ?, ?, 'success',
                'Canonical identity origin attested', ?, ?)
        """,
        (
            f"event_identity_origin_{creator}",
            identity_campaign["id"],
            source_id,
            json.dumps(origin_attestation, sort_keys=True),
            now,
        ),
    )
    cf.conn.commit()
    profile = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": f"{creator}_{provider}_{soul_id}",
        "creatorKey": creator,
        "displayName": creator.title(),
        "modelProfile": "higgsfield_soul_v2",
        "identityReferences": [
            {
                "namespace": f"{provider}.identity",
                "externalId": soul_id,
                "fingerprint": "a" * 64,
            }
        ],
        "provenance": {
            "producer": "operator",
            "producedAt": "2026-07-30T12:00:00Z",
            "sourceReferences": [{"recordId": source_id, "fingerprint": source_sha}],
        },
    }
    manifest = tmp_path / f"{creator}_{provider}_identity.json"
    manifest.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    cf.domains.creator_governance.enroll_identity_profile(
        creator,
        provider=provider,
        provider_identity_id=soul_id,
        profile=profile,
        canonical_source_asset_id=source_id,
        identity_manifest_path=manifest,
        identity_manifest_sha256=manifest_sha,
        operator="test",
    )
    evidence = tmp_path / f"{creator}_{provider}_rights.txt"
    evidence.write_text("operator-approved rights fixture", encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    for authorization_provider in sorted({provider, "internal"}):
        for scope in ("likeness_generation", "commercial_use"):
            cf.domains.creator_governance.grant_authorization(
                creator,
                scope=scope,
                provider=authorization_provider,
                evidence_path=evidence,
                evidence_sha256=evidence_sha,
                actor="test",
                reason="fixture authorization",
                territories=territories,
                account_scope=account_scope,
            )
    if reference_video_use:
        cf.domains.creator_governance.grant_authorization(
            creator,
            scope="reference_video_use",
            provider="internal",
            evidence_path=evidence,
            evidence_sha256=evidence_sha,
            actor="test",
            reason="fixture reference authorization",
            reference_video_use=True,
        )
    for state in ("configured", "source_ready", "production_ready"):
        cf.domains.creator_governance.transition_campaign(
            campaign,
            new_status=state,
            actor="test",
            reason="fixture lifecycle",
        )
    return {"model": model, "campaign": campaign_row, "identitySourceId": source_id}


def authorize_campaign_export(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    creator: str,
    campaign: str,
) -> None:
    state = cf.conn.execute(
        """
        SELECT cg.lifecycle_status
        FROM campaign_governance cg
        JOIN campaigns c ON c.id = cg.campaign_id
        WHERE c.slug = ?
        """,
        (campaign.replace("-", "_"),),
    ).fetchone()
    identities = cf.conn.execute(
        """
        SELECT COUNT(*) FROM creator_identity_profiles cip
        JOIN models m ON m.id = cip.model_id
        WHERE m.slug = ? AND cip.status = 'active'
        """,
        (creator.replace("-", "_"),),
    ).fetchone()[0]
    if not identities:
        authorize_campaign_governance(
            cf,
            tmp_path,
            creator=creator,
            campaign=campaign,
            provider="higgsfield",
            soul_id=f"soul_{creator}_fixture",
        )
        current = "production_ready"
    else:
        current = str(state["lifecycle_status"])
    if current == "production_ready":
        for target in ("producing", "reviewing", "approved"):
            cf.domains.creator_governance.transition_campaign(
                campaign,
                new_status=target,
                actor="test",
                reason="export fixture lifecycle",
                evidence=(
                    {"approvedAssetIds": ["fixture_pending_asset"]}
                    if target == "approved"
                    else None
                ),
            )


def set_test_source_prompt(
    cf: CampaignFactory,
    source_id: str,
    *,
    prompt_id: str = "prompt_test_001",
    reference_id: str = "reference_test_001",
) -> None:
    source_prompt = {
        "promptId": prompt_id,
        "referenceId": reference_id,
        "generationTool": "manual_finished_video",
        "generatedAssetLineage": {
            "schema": "reel_factory.generated_asset_lineage.v1",
            "pipelineTraceId": f"trace_{prompt_id}",
            "source": {
                "promptId": prompt_id,
                "referenceId": reference_id,
            },
            "generation": {"tool": "manual_finished_video"},
            "review": {"humanReviewRequired": True, "status": "draft"},
        },
    }
    cf.conn.execute(
        "UPDATE source_assets SET source_prompt = ? WHERE id = ?",
        (json.dumps(source_prompt, sort_keys=True), source_id),
    )


def add_rendered_asset(
    cf: CampaignFactory,
    tmp_path: Path,
    *,
    campaign_slug: str = "may",
    filename: str = "ok.mp4",
) -> tuple[dict, Path]:
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf.domains.asset_import.import_folder(
        folder, campaign_slug=campaign_slug, model_slug="model"
    )
    source = cf.domains.asset_import.assets_for_campaign(
        cf.domains.campaign_by_slug(campaign_slug)["id"]
    )[0]
    authorize_campaign_export(
        cf,
        tmp_path,
        creator="model",
        campaign=campaign_slug,
    )
    cf.domains.models.upsert_model_account_profile("model")
    set_test_source_prompt(cf, source["id"])
    rendered_path = tmp_path / filename
    rendered_path.write_bytes(b"rendered")
    rendered_hash = hashlib.sha256(rendered_path.read_bytes()).hexdigest()
    now = "2026-01-01T00:00:00+00:00"
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "caption_hash_1",
        "caption_text": "caption",
        "instagram_post_caption": "new post",
        "instagram_post_caption_hash": threadsdash_client_adapter._text_hash(
            "new post"
        ),
        "caption_bank": "test_bank",
        "caption_banks": ["test_bank"],
        "creator_mix": "Test",
        "render_recipe": "v01_original",
        "rendered_output": str(rendered_path),
        "captionPlacementPolicy": "focal_safe_v1",
        "captionPlacementDecision": {
            "status": "passed",
            "selectedLane": "top",
            "reason": "test fixture placement passed",
        },
    }
    content_trust_metadata = {
        "sourceFamilyId": f"fixture-family:{campaign_slug}:{filename}",
        "perceptualFingerprint": f"phash64:fixture:{campaign_slug}:{filename}",
        "perceptualClusterId": f"phash64:fixture:{campaign_slug}:{filename}",
        "visualQc": {"visualQcStatus": "passed", "status": "passed"},
        "identityVerification": {
            "schema": "reel_factory.identity_verification.v1",
            "status": "passed",
            "score": 0.9,
        },
    }
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, metadata_json, created_at, updated_at)
        VALUES ('asset_1', ?, ?, ?, ?, ?, ?, 'caption', 'caption_hash_1', ?, 'v01_original', 'pending', 'draft', ?, ?, ?, ?)
        """,
        (
            source["campaign_id"],
            source["id"],
            rendered_hash,
            str(rendered_path),
            str(rendered_path),
            filename,
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
            json.dumps(
                {
                    "instagram_post_caption": "new post",
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    },
                }
            ),
            json.dumps(content_trust_metadata, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    cf.conn.commit()
    return source, rendered_path


def isolate_account_groups(
    cf: CampaignFactory, instagram_account_ids: list[str]
) -> None:
    for instagram_account_id in instagram_account_ids:
        cf.domains.models.upsert_account(
            instagram_account_id,
            external_id=instagram_account_id,
            account_group_id=f"isolated:{instagram_account_id}",
        )


def add_source_asset(
    cf: CampaignFactory, tmp_path: Path, *, campaign_slug: str = "may"
) -> dict:
    folder = tmp_path / "source_inputs"
    folder.mkdir(exist_ok=True)
    (folder / "source.mp4").write_bytes(b"source")
    cf.domains.asset_import.import_folder(
        folder, campaign_slug=campaign_slug, model_slug="model"
    )
    source = cf.domains.asset_import.assets_for_campaign(
        cf.domains.campaign_by_slug(campaign_slug)["id"]
    )[0]
    set_test_source_prompt(cf, source["id"], prompt_id="prompt_motion_edit_001")
    return source
