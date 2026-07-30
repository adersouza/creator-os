from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from campaign_factory.recreation_lifecycle import (
    explain_recreation_job,
    record_recreation_review,
)
from campaign_test_support import make_factory
from PIL import Image


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
    finally:
        cf.close()
