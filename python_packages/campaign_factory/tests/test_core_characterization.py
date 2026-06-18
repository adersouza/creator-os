from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from campaign_factory.adapters import threadsdash as threadsdash_adapter
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory


def make_factory(tmp_path: Path) -> CampaignFactory:
    reel_root = tmp_path / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True, exist_ok=True)
    (reel_root / "01_captions").mkdir(parents=True, exist_ok=True)
    return CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))


def normalize(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {child_key: normalize(item, key=child_key) for child_key, item in value.items() if not _dynamic_key(child_key)}
    if isinstance(value, list):
        return [normalize(item, key=key) for item in value]
    if isinstance(value, str):
        if value.startswith("cg_") and len(value) > 18:
            return "<graph_id>"
        if value.startswith("cfam_") and len(value) > 12:
            return "<caption_family_id>"
        if value.startswith("cver_") and len(value) > 12:
            return "<caption_version_id>"
        for prefix in (
            "acct_", "camp_", "cpevt_", "cplan_", "dist_", "edge_", "evt_", "ex_",
            "job_", "model_", "node_", "profile_",
        ):
            if value.startswith(prefix) and len(value) > len(prefix) + 6:
                return f"<{prefix[:-1]}_id>"
        if key in {"startedAt", "finishedAt", "timestamp"} and value.startswith("202") and "T" in value:
            return "<timestamp>"
    return value


def _dynamic_key(key: str) -> bool:
    return key in {"id", "created_at", "updated_at", "createdAt", "updatedAt", "generatedAt"}


def table_counts(cf: CampaignFactory, *tables: str) -> dict[str, int]:
    return {
        table: int(cf.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def add_rendered_asset(cf: CampaignFactory, tmp_path: Path, *, campaign_slug: str = "may") -> dict[str, Any]:
    folder = tmp_path / f"{campaign_slug}_inputs"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"source")
    cf.import_folder(folder, campaign_slug=campaign_slug, model_slug="model")
    source = cf.assets_for_campaign(cf.campaign_by_slug(campaign_slug)["id"])[0]
    rendered_path = tmp_path / f"{campaign_slug}_rendered.mp4"
    rendered_path.write_bytes(b"rendered")
    caption_context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "caption_hash_1",
        "caption_text": "caption",
        "instagram_post_caption": "new post",
        "instagram_post_caption_hash": threadsdash_adapter._text_hash("new post"),
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
    now = "2026-01-01T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
         caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
         caption_generation_json, metadata_json, created_at, updated_at)
        VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'rendered.mp4',
                'caption', 'caption_hash_1', ?, 'v01_original', 'pending', 'draft', ?, ?, ?, ?)
        """,
        (
            source["campaign_id"],
            source["id"],
            str(rendered_path),
            str(rendered_path),
            json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
            json.dumps({"instagram_post_caption": "new post"}, ensure_ascii=False, sort_keys=True),
            json.dumps({
                "visualQc": {"visualQcStatus": "passed", "status": "passed"},
                "identityVerification": {"status": "passed", "score": 0.9},
            }, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    cf.conn.commit()
    return cf.rendered_asset("asset_1")


def test_tier1_graph_events_models_and_asset_import_characterization(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        model = cf.upsert_model("Model A", name="Model A", notes="first")
        campaign = cf.upsert_campaign("Launch Campaign", model["slug"], platform="threads")
        account = cf.upsert_account("@creator_a", platform="instagram", external_id="ig_1", model_id=model["id"])
        profile = cf.upsert_model_account_profile(
            model["slug"],
            label="Model A Profile",
            allowed_instagram_account_ids=["ig_1"],
            allowed_account_group_names=["warm"],
            allowed_handle_patterns=["creator_*"],
            default_smart_link="https://example.test",
            story_cta_text="new post",
        )
        campaign_graph = cf.graph_id_for("campaigns", campaign["id"], entity_type="campaign", payload={"slug": campaign["slug"]})
        account_graph = cf.graph_id_for("accounts", account["id"], entity_type="account", payload={"handle": account["handle"]})
        edge_id = cf.ensure_graph_edge(campaign_graph, account_graph, "assigned_account", evidence={"source": "characterization"}, commit=True)
        event = cf.record_event(
            "characterization_event",
            campaign_id=campaign["id"],
            status="success",
            metadata={"account": account["handle"], "nested": {"ok": True}},
        )
        job = cf.create_pipeline_job("characterization_job", campaign["id"], {"step": "queued"})
        running = cf.start_pipeline_job(job["id"])
        finished = cf.finish_pipeline_job(job["id"], {"ok": True})
        inputs = tmp_path / "import_inputs"
        inputs.mkdir()
        (inputs / "clip.mp4").write_bytes(b"clip")
        (inputs / "notes.txt").write_text("ignore me", encoding="utf-8")
        imported = cf.import_folder(
            inputs,
            campaign_slug="Launch Campaign",
            model_slug="Model A",
            platform="instagram",
            account_handles=["creator_a"],
            source_prompt="prompt",
            notes="notes",
        )

        assert normalize({
            "model": model,
            "campaign": campaign,
            "account": account,
            "profile": profile,
            "event": event,
            "job": job,
            "running": running,
            "finished": finished,
            "importedSummary": {
                "imported": len(imported["imported"]),
                "duplicates": imported["duplicates"],
                "ignoredSuffixes": [Path(path).suffix for path in imported["ignored"]],
                "pipelineJobId": imported["pipelineJobId"],
            },
            "edgeId": edge_id,
            "counts": table_counts(
                cf,
                "models",
                "campaigns",
                "accounts",
                "model_account_profiles",
                "content_graph_nodes",
                "content_graph_edges",
                "activity_events",
                "pipeline_jobs",
                "source_assets",
            ),
        }) == {
            "model": {
                "slug": "model_a",
                "name": "Model A",
                "notes": "first",
            },
            "campaign": {
                "slug": "launch_campaign",
                "name": "Launch Campaign",
                "platform": "threads",
                "root_path": str(tmp_path / "campaigns" / "model_a" / "launch_campaign"),
            },
            "account": {
                "handle": "creator_a",
                "platform": "instagram",
                "external_id": "ig_1",
                "model_id": "<model_id>",
            },
            "profile": {
                "modelId": "<model_id>",
                "modelSlug": "model_a",
                "label": "Model A Profile",
                "allowedInstagramAccountIds": ["ig_1"],
                "allowedAccountGroupNames": ["warm"],
                "allowedHandlePatterns": ["creator_*"],
                "defaultSmartLink": "https://example.test",
                "storyCtaText": "new post",
            },
            "event": {
                "event_type": "characterization_event",
                "campaign_id": "<camp_id>",
                "source_asset_id": None,
                "rendered_asset_id": None,
                "render_job_id": None,
                "audit_report_id": None,
                "threadsdash_export_id": None,
                "pipeline_job_id": None,
                "status": "success",
                "message": "characterization event",
                "metadata_json": "{\"account\": \"creator_a\", \"nested\": {\"ok\": true}}",
            },
            "job": {
                "jobType": "characterization_job",
                "campaignId": "<camp_id>",
                "status": "queued",
                "input": {"step": "queued"},
                "result": {},
                "error": None,
                "attemptCount": 0,
                "startedAt": None,
                "finishedAt": None,
            },
            "running": {
                "jobType": "characterization_job",
                "campaignId": "<camp_id>",
                "status": "running",
                "input": {"step": "queued"},
                "result": {},
                "error": None,
                "attemptCount": 1,
                "startedAt": "<timestamp>",
                "finishedAt": None,
            },
            "finished": {
                "jobType": "characterization_job",
                "campaignId": "<camp_id>",
                "status": "succeeded",
                "input": {"step": "queued"},
                "result": {"ok": True},
                "error": None,
                "attemptCount": 1,
                "startedAt": "<timestamp>",
                "finishedAt": "<timestamp>",
            },
            "importedSummary": {
                "imported": 1,
                "duplicates": [],
                "ignoredSuffixes": [".txt"],
                "pipelineJobId": "<job_id>",
            },
            "edgeId": "<edge_id>",
            "counts": {
                "models": 1,
                "campaigns": 1,
                "accounts": 1,
                "model_account_profiles": 1,
                "content_graph_nodes": 4,
                "content_graph_edges": 2,
                "activity_events": 5,
                "pipeline_jobs": 2,
                "source_assets": 1,
            },
        }
    finally:
        cf.close()


def test_tier2_planning_distribution_exceptions_discoverability_and_decision_characterization(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        rendered = add_rendered_asset(cf, tmp_path, campaign_slug="tier2")
        campaign = cf.campaign_by_slug("tier2")
        plan = cf.create_creative_plan(
            name="Daily Plan",
            platform="instagram",
            target_account="@creator_a",
            daily_base_video_target=2,
            style_lanes=["Mirror Selfie", "GRWM"],
            source_accounts=["@source_a"],
            linked_campaign="tier2",
        )
        prompt_export = tmp_path / "prompt_export.json"
        prompt_export.write_text(json.dumps({
            "items": [
                {
                    "creativePlanId": plan["id"],
                    "referenceId": "ref_1",
                    "sourcePatternId": "pattern_1",
                    "imagePrompt": {"id": "img_1", "targetTool": "higgsfield"},
                    "klingPrompt": {"id": "vid_1", "targetTool": "kling"},
                }
            ]
        }), encoding="utf-8")
        progress = cf.sync_creative_plan_progress(name="Daily Plan", prompt_export_path=prompt_export)
        status = cf.update_creative_plan_status(name="Daily Plan", status="prompts_ready")
        distribution = cf.create_distribution_plan(
            rendered["id"],
            surface="trial_reel",
            instagram_account_id="ig_1",
            planned_window_start="2026-01-02T10:00:00+00:00",
            reason_code="test_characterization",
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
        )
        exception = cf.create_exception(
            reason_code="caption_needs_review",
            severity="high",
            campaign_id=campaign["id"],
            entity_graph_id=cf.graph_id_for("campaigns", campaign["id"], entity_type="campaign"),
            payload={"field": "caption"},
        )
        exception_report = cf.exception_queue_report(
            daily_plan={"accounts": [{"accountId": "ig_1", "state": "blocked", "blockedReason": "account_reauth"}]},
            execution_readiness={"blockers": ["caption_contract_invalid"]},
            publishability_report={"assets": [{"assetId": "asset_1", "blockingReasons": ["metadata_missing"]}]},
        )
        discoverability = cf.discoverability_generation_gate({
            "prompt": "clean morning outfit check",
            "caption_text": "DM me for more",
        })
        decision = cf.decision_ledger_by_creator(
            creator="Stacey",
            generated_at="2026-01-01T00:00:00+00:00",
        )
        caption_plan = cf.caption_family_plan(
            creator="Stacey",
            parent_asset_id=rendered["id"],
            requested_caption_versions=2,
            dry_run=True,
        )

        assert normalize({
            "plan": plan,
            "progress": progress,
            "status": status,
            "distribution": distribution,
            "exception": exception,
            "exceptionReport": exception_report,
            "discoverability": discoverability,
            "decision": decision,
            "captionPlan": caption_plan,
            "counts": table_counts(
                cf,
                "creative_plans",
                "creative_plan_events",
                "distribution_plans",
                "trust_exceptions",
                "caption_families",
                "caption_versions",
            ),
        }) == {
            "plan": {
                "schema": "campaign_factory.creative_plan.v1",
                "name": "daily_plan",
                "platform": "instagram",
                "goal": "views_reach",
                "target_account": "creator_a",
                "daily_base_video_target": 2,
                "style_lanes": ["mirror_selfie", "grwm"],
                "model_profile": "",
                "source_accounts": ["source_a"],
                "status": "planned",
                "counts": {
                    "references": 0,
                    "analyses": 0,
                    "image_prompts": 0,
                    "video_prompts": 0,
                    "generated_videos": 0,
                    "ingested_videos": 0,
                    "rendered_outputs": 0,
                    "reviewed_outputs": 0,
                    "exported_drafts": 0,
                    "posted_items": 0,
                    "measured_items": 0,
                },
                "next_actions": [
                    "Select 2 more references",
                    "Analyze 2 more references",
                    "Generate 2 more Higgsfield image prompts",
                    "Generate 2 more Kling video prompts",
                    "Generate 2 more finished videos",
                ],
                "linked_campaign": "tier2",
            },
            "progress": {
                "schema": "campaign_factory.creative_plan_progress_sync.v1",
                "plan": {
                    "schema": "campaign_factory.creative_plan.v1",
                    "name": "daily_plan",
                    "platform": "instagram",
                    "goal": "views_reach",
                    "target_account": "creator_a",
                    "daily_base_video_target": 2,
                    "style_lanes": ["mirror_selfie", "grwm"],
                    "model_profile": "",
                    "source_accounts": ["source_a"],
                    "status": "prompts_ready",
                    "counts": {
                        "references": 1,
                        "analyses": 1,
                        "image_prompts": 1,
                        "video_prompts": 1,
                        "generated_videos": 0,
                        "ingested_videos": 0,
                        "rendered_outputs": 0,
                        "reviewed_outputs": 0,
                        "exported_drafts": 0,
                        "posted_items": 0,
                        "measured_items": 0,
                    },
                    "next_actions": [
                        "Select 1 more references",
                        "Analyze 1 more references",
                        "Generate 1 more Higgsfield image prompts",
                        "Generate 1 more Kling video prompts",
                        "Generate 2 more finished videos",
                    ],
                    "linked_campaign": "tier2",
                },
                "sourcePath": str(prompt_export),
                "counts": {
                    "references": 1,
                    "analyses": 1,
                    "image_prompts": 1,
                    "video_prompts": 1,
                },
            },
            "status": {
                "schema": "campaign_factory.creative_plan.v1",
                "name": "daily_plan",
                "platform": "instagram",
                "goal": "views_reach",
                "target_account": "creator_a",
                "daily_base_video_target": 2,
                "style_lanes": ["mirror_selfie", "grwm"],
                "model_profile": "",
                "source_accounts": ["source_a"],
                "status": "prompts_ready",
                "counts": {
                    "references": 1,
                    "analyses": 1,
                    "image_prompts": 1,
                    "video_prompts": 1,
                    "generated_videos": 0,
                    "ingested_videos": 0,
                    "rendered_outputs": 0,
                    "reviewed_outputs": 0,
                    "exported_drafts": 0,
                    "posted_items": 0,
                    "measured_items": 0,
                },
                "next_actions": [
                    "Select 1 more references",
                    "Analyze 1 more references",
                    "Generate 1 more Higgsfield image prompts",
                    "Generate 1 more Kling video prompts",
                    "Generate 2 more finished videos",
                ],
                "linked_campaign": "tier2",
            },
            "distribution": {
                "campaignId": "<camp_id>",
                "renderedAssetId": "asset_1",
                "accountId": None,
                "instagramAccountId": "ig_1",
                "surface": "trial_reel",
                "contentSurface": "reel",
                "plannedWindowStart": "2026-01-02T10:00:00+00:00",
                "plannedWindowEnd": None,
                "pairedRenderedAssetId": None,
                "reasonCode": "test_characterization",
                "smartLink": None,
                "ctaText": None,
                "instagramTrialReels": True,
                "instagram_trial_reels": True,
                "trialGraduationStrategy": "MANUAL",
                "trial_graduation_strategy": "MANUAL",
                "conceptId": None,
                "parentReelId": None,
                "variantFamilyId": None,
                "variantId": None,
                "variantIndex": None,
                "variantOperations": [],
                "captionOutcomeContext": {
                    "captionPlacementDecision": {
                        "reason": "test fixture placement passed",
                        "selectedLane": "top",
                        "status": "passed",
                    },
                    "captionPlacementPolicy": "focal_safe_v1",
                    "caption_bank": "test_bank",
                    "caption_banks": ["test_bank"],
                    "caption_hash": "caption_hash_1",
                    "caption_text": "caption",
                    "creator_mix": "Test",
                    "instagram_post_caption": "new post",
                    "instagram_post_caption_hash": "b09962951983294e7200e86a5cb802cf2e01a35d80c7e34b389e15b4d194733c",
                    "render_recipe": "v01_original",
                    "rendered_output": str(tmp_path / "tier2_rendered.mp4"),
                    "schema": "campaign_factory.caption_outcome_context.v1",
                },
            },
            "exception": {
                "status": "open",
                "severity": "high",
                "reasonCode": "caption_needs_review",
                "entityGraphId": "<graph_id>",
                "graphId": "<graph_id>",
                "recommendationItemId": None,
                "campaignId": "<camp_id>",
                "accountId": None,
                "payload": {"field": "caption"},
                "resolution": {},
                "resolvedAt": None,
                "snoozedUntil": None,
            },
            "exceptionReport": {
                "schema": "creator_os.exception_queue_report.v1",
                "exceptionCount": 3,
                "exceptions": [
                    {
                        "exceptionId": "exception_3663c12eaf22ed82",
                        "severity": "high",
                        "owner": "threadsdashboard_operator",
                        "system": "account_health",
                        "category": "account_health",
                        "account": "ig_1",
                        "accountId": "ig_1",
                        "asset": "",
                        "assetId": "",
                        "reason": "account_reauth",
                        "nextAction": "resolve_account_blocker",
                        "repairable": True,
                        "estimatedResolutionMinutes": 15,
                        "blockingAccounts": 1,
                        "blockingInventory": 0,
                        "wouldWrite": False,
                    },
                    {
                        "exceptionId": "exception_7155a638af418b58",
                        "severity": "high",
                        "owner": "campaign_factory_operator",
                        "system": "execution_readiness",
                        "category": "discoverability",
                        "account": "",
                        "accountId": "",
                        "asset": "",
                        "assetId": "",
                        "reason": "caption_contract_invalid",
                        "nextAction": "repair_caption_contract",
                        "repairable": True,
                        "estimatedResolutionMinutes": 12,
                        "blockingAccounts": 0,
                        "blockingInventory": 0,
                        "wouldWrite": False,
                    },
                    {
                        "exceptionId": "exception_de8fdad1e0ee32d1",
                        "severity": "low",
                        "owner": "campaign_factory_operator",
                        "system": "publishability",
                        "category": "publishability",
                        "account": "",
                        "accountId": "",
                        "asset": "asset_1",
                        "assetId": "asset_1",
                        "reason": "metadata_missing",
                        "nextAction": "inspect_and_route_exception",
                        "repairable": True,
                        "estimatedResolutionMinutes": 8,
                        "blockingAccounts": 0,
                        "blockingInventory": 0,
                        "wouldWrite": False,
                    },
                ],
                "wouldWrite": False,
            },
            "discoverability": {
                "schema": "campaign_factory.discoverability_generation_gate.v1",
                "gate": "generation",
                "canProceed": False,
                "violations": [
                    {
                        "failedStage": "discoverability_safety_pass",
                        "failureCategory": "dm_language",
                        "sourceField": "caption_text",
                        "matchedText": "DM",
                        "policyVersion": "discoverability_safe_v1",
                        "preventableAt": "caption_creation",
                        "reason": "dm_reference",
                        "repairable": True,
                        "wouldWrite": False,
                    }
                ],
                "policyVersion": "discoverability_safe_v1",
                "nextAction": "reject_before_render",
                "wouldWrite": False,
            },
            "decision": {
                "schema": "creator_os.decision_ledger_by_creator.v1",
                "creator": "Stacey",
                "date": "2026-01-01",
                "decisionCount": 1,
                "decisions": [
                    {
                        "decisionId": "mdec_preview_a2464d73d100678d",
                        "decisionType": "story_intent_recommended",
                        "reason": "creator_story_mix_plan",
                        "timestamp": "<timestamp>",
                        "creator": "Stacey",
                        "accountId": "",
                        "surface": "story",
                        "renderedAssetId": "",
                        "parentAssetId": "",
                        "variantId": "",
                        "sourceSystem": "story_mix_plan",
                        "explanation": "Creator OS recommends a reel_teaser Story using raw_phone styling based on the current Story mix/calendar plan.",
                        "contextSnapshot": {
                            "recommendedStoryIntent": "reel_teaser",
                            "recommendedStoryStyle": "raw_phone",
                            "storyCalendarPlan": {
                                "Friday": "snapchat_promo",
                                "Monday": "reel_teaser",
                                "Saturday": "lifestyle",
                                "Sunday": "casual_selfie",
                                "Thursday": "reel_teaser",
                                "Tuesday": "snapchat_promo",
                                "Wednesday": "casual_selfie",
                            },
                            "storyMixPlan": {
                                "casual_selfie": 30,
                                "engagement": 10,
                                "lifestyle": 10,
                                "reel_teaser": 25,
                                "snapchat_promo": 25,
                            },
                        },
                        "storyGoal": "reel_support",
                        "storyIntent": "reel_teaser",
                        "storyStyle": "raw_phone",
                        "wouldWrite": False,
                    }
                ],
                "wouldWrite": False,
            },
            "captionPlan": {
                "schema": "campaign_factory.caption_family_plan.v1",
                "creator": "Stacey",
                "parentAssetId": "asset_1",
                "parentReelId": None,
                "conceptId": None,
                "captionFamilyId": "<caption_family_id>",
                "requestedCaptionVersions": 2,
                "style": "ig_short",
                "plannedVersions": [
                    {
                        "captionVersionId": "<caption_version_id>",
                        "captionFamilyId": "<caption_family_id>",
                        "captionFamilyIndex": 1,
                        "burnedCaptionText": "caption?",
                        "burnedCaptionHash": "aa9b47f6e9514befd2dd96f27f277425d600c43fe559eeb418dc35009a307029",
                        "instagramPostCaption": "quick question: caption\ntell me yes or no",
                        "instagramPostCaptionHash": "694dfc850571e912db5150bf40dcba4d8aed05f39017de148e2bb4c3c2c40953",
                        "captionAngle": "question_bait",
                        "captionCta": "tell me yes or no",
                        "captionSource": "existing_caption_bank:test_bank",
                        "hashtags": [],
                        "parentAssetId": "asset_1",
                        "parentReelId": None,
                        "postCaptionStyle": "ig_short",
                        "wouldWrite": False,
                    },
                    {
                        "captionVersionId": "<caption_version_id>",
                        "captionFamilyId": "<caption_family_id>",
                        "captionFamilyIndex": 2,
                        "burnedCaptionText": "caption but softer",
                        "burnedCaptionHash": "7114ddf8d234aabe1e62ea17f25b38b91aba0272e7f5e6bbcd0d0e88ea84adfd",
                        "instagramPostCaption": "this one felt too good not to post\nsave this for later",
                        "instagramPostCaptionHash": "cb29d2c1cc67f009205baeb5594e20f3ff36c813baa3acd592d188ec5bb80117",
                        "captionAngle": "flirty_tease",
                        "captionCta": "save this for later",
                        "captionSource": "existing_caption_bank:test_bank",
                        "hashtags": [],
                        "parentAssetId": "asset_1",
                        "parentReelId": None,
                        "postCaptionStyle": "ig_short",
                        "wouldWrite": False,
                    },
                ],
                "canProceed": False,
                "blockingReason": "parent_reel_not_registered",
                "blockingReasons": ["parent_reel_not_registered", "missing_audio"],
                "wouldWrite": False,
                "dryRun": True,
            },
            "counts": {
                "creative_plans": 1,
                "creative_plan_events": 3,
                "distribution_plans": 1,
                "trust_exceptions": 1,
                "caption_families": 0,
                "caption_versions": 0,
            },
        }
    finally:
        cf.close()
