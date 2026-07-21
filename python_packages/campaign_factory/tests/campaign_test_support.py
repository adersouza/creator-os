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
