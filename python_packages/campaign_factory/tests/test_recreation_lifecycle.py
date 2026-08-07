from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from campaign_factory import recreation_lifecycle, recreation_prompting
from campaign_factory.recreation_lifecycle import (
    _campaign_for_soul_identity,
    _register_anchor_candidate,
    explain_recreation_job,
    record_recreation_review,
)
from campaign_test_support import authorize_campaign_governance, make_factory
from PIL import Image


def test_structural_image_anchor_conditions_soul_on_the_reference_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        soul_id = "soul-stacey-verified"
        governance = authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="stacey-structural-image",
            provider="higgsfield",
            soul_id=soul_id,
            reference_video_use=True,
        )
        active = dict(
            cf.domains.creator_governance.active_identity_profile(
                "stacey", provider="higgsfield"
            )
        )
        binding_core = {
            "schema": "campaign_factory.verified_soul_identity_binding.v1",
            "creatorSlug": "stacey",
            "provider": "higgsfield",
            "soulId": soul_id,
            "identityProfileId": active["id"],
            "identityProfileVersion": active["version"],
            "identityProfileFingerprint": active["profile_fingerprint"],
        }
        soul_identity = {
            **binding_core,
            "bindingFingerprint": recreation_prompting._fingerprint(binding_core),
        }
        reference = tmp_path / "reference.png"
        Image.new("RGB", (360, 640), "purple").save(reference)
        reference_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
        pack_core = {
            "schema": "campaign_factory.recreation_prompt_pack.v1",
            "creator": "stacey",
            "promptPlanning": {
                "builderVersion": recreation_prompting.PROMPT_BUILDER_VERSION,
                "requestFingerprint": "a" * 64,
            },
            "creatorImage": {"path": str(reference), "sha256": reference_sha},
            "referenceImageRole": "structural_reference",
            "soulIdentity": soul_identity,
            "referenceVideo": None,
            "promptScope": "soul_image_only",
            "anchorPrompt": (
                "Adult woman, age 19, with dark hair, wearing a fitted black top "
                "in soft bedroom light."
            ),
        }
        prompt_pack = {
            **pack_core,
            "promptPackFingerprint": recreation_prompting._fingerprint(pack_core),
        }
        prompt_path = tmp_path / "prompt.json"
        prompt_path.write_text(json.dumps(prompt_pack), encoding="utf-8")
        plan_core = {
            "schema": "campaign_factory.structural_image_plan.v1",
            "creator": "stacey",
            "creatorGovernance": {"campaignId": governance["campaign"]["id"]},
            "referenceImageSha256": reference_sha,
            "referenceAuthorized": True,
            "promptPack": {
                "promptPackFingerprint": prompt_pack["promptPackFingerprint"]
            },
        }
        plan = {
            **plan_core,
            "planFingerprint": recreation_lifecycle._fingerprint(plan_core),
        }
        generated = tmp_path / "generated.png"
        Image.new("RGB", (720, 1280), "gold").save(generated)
        lineage = tmp_path / "lineage.json"
        lineage.write_text("{}", encoding="utf-8")
        observed: dict[str, object] = {}

        def fake_generate(_factory, args):
            observed["args"] = list(args)
            return {
                "ok": True,
                "path": str(lineage),
                "lineage": {
                    "assets": {"localPaths": {"image": str(generated)}},
                    "generation": {"imageJobId": "soul-generation-1"},
                },
                "campaignSpendReceipt": None,
            }

        monkeypatch.setattr(
            recreation_lifecycle, "_invoke_generate_assets", fake_generate
        )
        result = recreation_lifecycle.generate_recreation_anchor(
            cf,
            creator="stacey",
            prompt_pack_path=prompt_path,
            attempt_id="structural-image-attempt",
            max_credits=10.0,
            recreation_plan=plan,
        )

        args = observed["args"]
        assert isinstance(args, list)
        # A structural reference is shown to Soul, not described in prose: the
        # reference-image worker action passes both the trained identity and the
        # reference image, which is what held identity and pose in one call.
        assert args[0] == "reference-image"
        assert args[args.index("--reference") + 1] == str(reference)
        assert args[args.index("--soul-id") + 1] == soul_id
        assert args[args.index("--image-aspect-ratio") + 1] == "9:16"
        assert "--prompt-json" not in args
        assert result["status"] == "completed"
        assert result["sourceAsset"]["status"] == "imported"
    finally:
        cf.close()


def test_soul_bound_anchor_candidate_has_no_creator_image_lineage(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        soul_id = "soul-stacey-verified"
        governance = authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="stacey-recreation",
            provider="higgsfield",
            soul_id=soul_id,
            reference_video_use=True,
        )
        active = dict(
            cf.domains.creator_governance.active_identity_profile(
                "stacey", provider="higgsfield"
            )
        )
        binding_core = {
            "schema": "campaign_factory.verified_soul_identity_binding.v1",
            "creatorSlug": "stacey",
            "provider": "higgsfield",
            "soulId": soul_id,
            "identityProfileId": active["id"],
            "identityProfileVersion": active["version"],
            "identityProfileFingerprint": active["profile_fingerprint"],
        }
        soul_identity = {
            **binding_core,
            "bindingFingerprint": hashlib.sha256(
                json.dumps(binding_core, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        campaign, model_id = _campaign_for_soul_identity(
            cf,
            creator="stacey",
            campaign_id=governance["campaign"]["id"],
            soul_id=soul_id,
            soul_identity=soul_identity,
        )
        anchor = tmp_path / "soul-anchor.png"
        Image.new("RGB", (360, 640), "gold").save(anchor)
        anchor_sha = hashlib.sha256(anchor.read_bytes()).hexdigest()
        lineage_path = tmp_path / "provider-lineage.json"
        lineage_path.write_text("{}", encoding="utf-8")
        registered = _register_anchor_candidate(
            cf,
            campaign=campaign,
            source=None,
            model_id=model_id,
            anchor=anchor,
            digest=anchor_sha,
            attempt_id="soul-attempt-1",
            generation_id="soul-generation-1",
            prompt_pack={
                "promptPackFingerprint": "a" * 64,
                "soulIdentity": soul_identity,
                "referenceVideo": {"sha256": "b" * 64},
            },
            execution_binding={
                "referenceId": "reference-1",
                "recreationPlanFingerprint": "c" * 64,
                "selectedRecreationMode": "structural",
                "referenceClassification": "simple_pose_motion",
                "referenceProviderRights": {"eligible": True},
            },
            lineage_path=lineage_path,
            spend_receipt=None,
        )
        lineage = json.loads(str(registered["source_prompt"]))
        assert lineage["derivedFromSourceAssetId"] is None
        assert lineage["creatorImageSha256"] is None
        assert lineage["soulIdentity"] == soul_identity
        assert lineage["referenceVideoSha256"] == "b" * 64
    finally:
        cf.close()


def test_recreation_explain_and_retry_branches_keep_provider_success(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    cf.settings = replace(
        cf.settings,
        reference_reels_root=tmp_path / "reference_reels",
        reference_factory_db=tmp_path / "reference_reels" / "reference_factory.sqlite",
    )
    try:
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        creator_image = source_dir / "creator.png"
        Image.new("RGB", (360, 640), "purple").save(creator_image)
        cf.domains.asset_import.import_folder(
            source_dir,
            campaign_slug="stacey-library",
            model_slug="stacey",
        )
        campaign = cf.domains.campaign_by_slug("stacey-library")
        source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
        cf.conn.execute(
            "UPDATE source_assets SET status = 'approved' WHERE id = ?",
            (source["id"],),
        )
        final = tmp_path / "final.mp4"
        final.write_bytes(b"final-video")
        final_sha = hashlib.sha256(final.read_bytes()).hexdigest()
        anchor_sha = "a" * 64
        reference_sha = "b" * 64
        now = "2026-07-29T12:00:00Z"
        asset_id = "asset_recreation_test"
        metadata = {
            "compiledPrompt": {"text": "Recreate the motion."},
            "audioEmbeddingReceipt": {"status": "verified"},
        }
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, media_type, content_surface, metadata_json,
             audit_status, review_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', ?, 'pending', 'draft', ?, ?)
            """,
            (
                asset_id,
                campaign["id"],
                source["id"],
                final_sha,
                str(final),
                str(final),
                final.name,
                json.dumps(metadata),
                now,
                now,
            ),
        )
        cf.conn.commit()
        job = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation",
            campaign["id"],
            {
                "jobId": "create_recreation_test",
                "sourceAssetId": source["id"],
                "sourceSha256": source["content_hash"],
                "referenceVideo": {
                    "referenceVideoId": "reference-1",
                    "originalLocalFile": {
                        "sha256": reference_sha,
                        "path": str(tmp_path / "reference.mp4"),
                    },
                },
                "recreationAnchorApproval": {
                    "anchorFileSha256": anchor_sha,
                    "anchorFilePath": str(tmp_path / "anchor.png"),
                    "anchorGenerationId": "soul-generation-1",
                    "anchorModel": "soul_2",
                    "selectedCompositionFrameSha256": "c" * 64,
                    "promptPackFingerprint": "d" * 64,
                    "anchorPromptPackId": "prompt-pack-1",
                },
            },
        )
        cf.domains.events.start_pipeline_job(job["id"])
        cf.domains.events.finish_pipeline_job(
            job["id"],
            {
                "registeredAsset": {
                    "id": asset_id,
                    "content_hash": final_sha,
                    "output_path": str(final),
                    "metadata_json": json.dumps(metadata),
                },
                "worker": {
                    "result": {"status": "completed"},
                    "paidGenerationEvidence": {
                        "providerModel": "seedance_2_0",
                        "authorizationId": "auth-1",
                        "reservationId": "reservation-1",
                        "providerPlanFingerprint": "e" * 64,
                        "generationId": "seedance-generation-1",
                        "referenceElement": {
                            "kind": "prompt_token",
                            "id": "soul-token",
                            "creator": "stacey",
                            "fileSha256": anchor_sha,
                        },
                        "providerReceipt": {},
                    },
                },
            },
        )

        explained = explain_recreation_job(cf, job["id"])
        assert explained["reference"]["sha256"] == reference_sha
        assert explained["identityComparison"]["approvedAnchorSha256"] == anchor_sha
        assert explained["providerExecutionStatus"] == "completed"
        assert explained["learningEligible"] is False

        anchor_job = cf.domains.events.create_pipeline_job(
            "recreation_anchor_generation",
            campaign["id"],
            {
                "attemptId": "anchor-attempt-1",
                "sourceAssetId": source["id"],
                "creatorImageSha256": source["content_hash"],
                "referenceVideoSha256": reference_sha,
                "promptPackFingerprint": "d" * 64,
            },
        )
        anchor_source_id = "source_recreation_anchor_test"
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, content_surface, platform, account_ids_json,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'anchor.png', 'image', 'reel', 'instagram',
                    '[]', 'imported', ?, ?)
            """,
            (
                anchor_source_id,
                campaign["id"],
                source["model_id"],
                anchor_sha,
                str(tmp_path / "anchor.png"),
                str(tmp_path / "anchor.png"),
                now,
                now,
            ),
        )
        cf.conn.commit()
        cf.domains.events.start_pipeline_job(anchor_job["id"])
        cf.domains.events.finish_pipeline_job(
            anchor_job["id"],
            {
                "generationId": "soul-generation-1",
                "attemptId": "anchor-attempt-1",
                "anchorPath": str(tmp_path / "anchor.png"),
                "anchorSha256": anchor_sha,
                "providerExecutionStatus": "completed",
                "technicalArtifactStatus": "completed",
                "sourceAsset": {"id": anchor_source_id},
            },
        )
        anchor_rejected = record_recreation_review(
            cf,
            job_id=anchor_job["id"],
            stage="anchor",
            decision="rejected",
            reviewed_by="operator@test",
        )
        assert anchor_rejected["retry"]["branch"] == "new_soul_anchor"
        assert anchor_rejected["retry"]["freshSpendAuthorizationRequired"] is True
        anchor_row = cf.conn.execute(
            "SELECT status FROM source_assets WHERE id = ?", (anchor_source_id,)
        ).fetchone()
        assert anchor_row["status"] == "rejected"

        rejected = record_recreation_review(
            cf,
            job_id=job["id"],
            stage="final_video",
            decision="rejected",
            reviewed_by="operator@test",
        )
        assert rejected["retry"] == {
            "branch": "retain_anchor_new_seedance",
            "automatic": False,
            "freshSpendAuthorizationRequired": True,
        }
        assert rejected["providerExecutionStatus"] == "completed"
        row = cf.conn.execute(
            "SELECT review_state FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        assert row["review_state"] == "rejected"

        with pytest.raises(PermissionError, match="muted_watchability_review_required"):
            record_recreation_review(
                cf,
                job_id=job["id"],
                stage="final_video",
                decision="approved",
                reviewed_by="operator@test",
            )
        approved = record_recreation_review(
            cf,
            job_id=job["id"],
            stage="final_video",
            decision="approved",
            reviewed_by="operator@test",
            notes=json.dumps(
                {
                    "mutedWatchability": {
                        "setupPayoff": True,
                        "meaningfulSilentMotion": True,
                        "anticipation": True,
                        "shotContinuity": True,
                    }
                }
            ),
        )
        muted = approved["mutedWatchabilityReview"]
        assert approved["wouldPost"] is True
        assert approved["publishability"] == "eligible_for_normal_approval_flow"
        assert muted["status"] == "passed"
        assert muted["finalSha256"] == final_sha
        assert Path(muted["receiptPath"]).is_file()
    finally:
        cf.close()
