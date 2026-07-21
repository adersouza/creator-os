from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_story_quality_asset,
    add_surface_asset_fixture,
)
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters import (
    threadsdash_draft_payload as threadsdash_payload_adapter,
)
from campaign_factory.adapters.threadsdash_account_projection import (
    sync_threadsdash_account_assignments,
)
from campaign_factory.adapters.threadsdash_draft_delivery import export_threadsdash
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
from campaign_factory.adapters.threadsdash_draft_readiness import (
    evaluate_export_readiness,
)
from campaign_factory.variation_stage import run_variation_stage
from campaign_generation_test_support import FakeVariationPipeline
from campaign_learning_test_support import (
    _approve_asset_for_lifecycle,
    _lifecycle_state,
    _threadsdash_lifecycle_post,
)
from campaign_test_support import (
    add_rendered_asset,
    isolate_account_groups,
    make_factory,
    set_test_source_prompt,
)


def test_audio_catalog_recommendations_feed_threadsdash_audio_intent(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("THREADSDASH_WORKSPACE_ID", "workspace_1")
    catalog_path = tmp_path / "audio_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.audio_catalog_export.v1",
                "items": [
                    {
                        "id": "aud_1",
                        "title": "Runway Pop",
                        "artistName": "DJ A",
                        "platform": "instagram",
                        "nativeAudioId": "ig_1",
                        "nativeAudioUrl": "https://instagram.com/audio/1",
                        "moodTags": ["fit_check"],
                        "bestContentTypes": ["v01_original"],
                        "trendStatus": "rising",
                        "safeUsageNotes": "native only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_catalog(catalog_path)
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (json.dumps({}),),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        assert payload["drafts"][0]["workspaceId"] == "workspace_1"
        intent = payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]

        assert intent["status"] == "recommended"
        assert intent["decision"]["primaryAudio"]["audio_title"] == "Runway Pop"
        assert intent["decision"]["decisionConfidence"] in {"usable", "strong"}
        assert intent["recommendations"][0]["audio_title"] == "Runway Pop"
        assert intent["recommendations"][0]["platform_audio_id"] == "ig_1"
        assert (
            intent["recommendations"][0]["platform_url"]
            == "https://instagram.com/audio/1"
        )
        assert intent["recommendations"][0]["freshness"] == "rising"
        assert source["id"]
    finally:
        cf.close()


def test_threadsdash_audio_intent_uses_destination_account_fit(tmp_path: Path):
    catalog_path = tmp_path / "account_audio_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.audio_catalog_export.v1",
                "items": [
                    {
                        "id": "aud_a",
                        "title": "Account A Sound",
                        "artistName": "DJ A",
                        "platform": "instagram",
                        "nativeAudioId": "ig_audio_a",
                        "moodTags": ["fit_check"],
                        "bestContentTypes": ["v01_original"],
                        "accountFit": ["ig_a"],
                        "trendStatus": "rising",
                    },
                    {
                        "id": "aud_b",
                        "title": "Account B Sound",
                        "artistName": "DJ B",
                        "platform": "instagram",
                        "nativeAudioId": "ig_audio_b",
                        "moodTags": ["fit_check"],
                        "bestContentTypes": ["v01_original"],
                        "accountFit": ["ig_b"],
                        "trendStatus": "rising",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    cf = make_factory(tmp_path)
    try:
        cf.domains.audio_recommendations.import_audio_catalog(catalog_path)
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = '{}' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        isolate_account_groups(cf, ["ig_a", "ig_b"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", surface="regular_reel", instagram_account_id="ig_a"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", surface="regular_reel", instagram_account_id="ig_b"
        )

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        by_account = {
            draft["instagramAccountId"]: draft["metadata"]["campaign_factory"][
                "audio_intent"
            ]
            for draft in payload["drafts"]
        }

        assert (
            by_account["ig_a"]["decision"]["primaryAudio"]["audio_title"]
            == "Account A Sound"
        )
        assert (
            by_account["ig_b"]["decision"]["primaryAudio"]["audio_title"]
            == "Account B Sound"
        )
        assert by_account["ig_a"]["recommendations"][0]["account_fit"] == ["ig_a"]
        assert by_account["ig_b"]["recommendations"][0]["account_fit"] == ["ig_b"]
    finally:
        cf.close()


def test_threadsdash_export_disabled_variation_preserves_master_media(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _, rendered_path = add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        draft = payload["drafts"][0]

        assert draft["_localFilePath"] == str(rendered_path)
        assert draft["media"][0]["fileName"] == rendered_path.name
        assert draft["metadata"]["campaign_factory"]["variant_assignment"] is None
        lineage = draft["metadata"]["campaign_factory"]["generated_asset_lineage"]
        assert payload["schema"] == "campaign_factory.threadsdash_drafts.v2"
        assert lineage["schema"] == "reel_factory.generated_asset_lineage.v2"
        assert lineage["variationApplied"] is False
        assert lineage["variantId"] is None
        assert lineage["audioId"] is None
        assert len(lineage["audioIntentFingerprint"]) == 64
    finally:
        cf.close()


def test_threadsdash_export_blocks_incomplete_burned_overlay_regression(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        caption = "men, stop doing this:"
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": threadsdash_client_adapter._text_hash(caption),
            "caption_text": caption,
        }
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?, caption_hash = ?, caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                caption,
                threadsdash_client_adapter._text_hash(caption),
                json.dumps(context),
            ),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(
            ValueError,
            match=(
                "burned_overlay_semantic_incomplete:"
                "missing_overlay_payoff_after_setup:asset_1"
            ),
        ):
            build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
    finally:
        cf.close()


def test_overlay_semantic_gate_does_not_treat_clean_media_as_burned_caption():
    asset = {
        "caption": "men, stop doing this:",
        "generatedAssetLineage": {"captionBurnedIn": False},
    }

    assert threadsdash_payload_adapter._asset_caption_is_burned(asset) is False


def test_threadsdash_export_preserves_real_timed_overlay_payoff_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        caption = json.dumps(
            {
                "segments": [
                    {"text": "men, stop doing this:", "end": 3.0},
                    {"text": "sending one-word replies", "start": 3.0},
                ]
            },
            sort_keys=True,
        )
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": threadsdash_client_adapter._text_hash(caption),
            "caption_text": caption,
        }
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?, caption_hash = ?, caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                caption,
                threadsdash_client_adapter._text_hash(caption),
                json.dumps(context),
            ),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        qc = payload["drafts"][0]["metadata"]["campaign_factory"]["overlay_semantic_qc"]

        assert qc["passed"] is True
        assert qc["decision"] == "timed_payoff_present"
        assert qc["distinct_segment_count"] == 2
    finally:
        cf.close()


def test_threadsdash_selected_batch_prunes_manifest_and_fails_on_missing_ids(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        second_path = tmp_path / "second.mp4"
        second_path.write_bytes(b"second")
        second = dict(
            cf.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()
        )
        second.update(
            id="asset_2",
            content_hash="hash_2",
            output_path=str(second_path),
            campaign_path=str(second_path),
            filename=second_path.name,
            caption_hash="caption_hash_2",
        )
        columns = list(second)
        cf.conn.execute(
            f"INSERT INTO rendered_assets ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [second[column] for column in columns],
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.finished_video.review_rendered_asset("asset_2", decision="approved")

        payload = build_draft_payloads(
            cf,
            campaign_slug="may",
            user_id="user_1",
            rendered_asset_ids=["asset_2"],
        )

        assert [
            asset["renderedAssetId"] for asset in payload["manifest"]["assets"]
        ] == ["asset_2"]
        assert [draft["renderedAssetId"] for draft in payload["drafts"]] == ["asset_2"]
        with pytest.raises(
            ValueError,
            match="selected rendered assets are not exportable.*missing_asset",
        ):
            build_draft_payloads(
                cf,
                campaign_slug="may",
                user_id="user_1",
                rendered_asset_ids=["missing_asset"],
            )
    finally:
        cf.close()


def test_threadsdash_export_enabled_variation_maps_account_media(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        _, rendered_path = add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_2"
        )
        monkeypatch.setattr(
            "campaign_factory.variation_stage.VariantPipeline", FakeVariationPipeline
        )
        monkeypatch.setattr(
            "campaign_factory.variation_stage.audit_variation_batch",
            lambda **kwargs: {
                "contractVersion": "campaign_factory_audit.v1.7",
                "overallVerdict": "pass",
                "verdicts": {"pdq": "pass", "sscd": "pass"},
                "readinessSummary": {"uploadReady": True, "blockingCodes": []},
                "reportPath": str(kwargs["report_path"]),
            },
        )
        run_variation_stage(
            cf,
            campaign_slug="may",
            dry_run=False,
            contentforge_base_url="http://contentforge.test",
        )

        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", enable_variation=True
        )

        drafts_by_ig = {
            draft["instagramAccountId"]: draft for draft in payload["drafts"]
        }
        assert set(drafts_by_ig) == {"ig_1", "ig_2"}
        assert drafts_by_ig["ig_1"]["_localFilePath"] != str(rendered_path)
        assert (
            drafts_by_ig["ig_1"]["_localFilePath"]
            != drafts_by_ig["ig_2"]["_localFilePath"]
        )
        meta = drafts_by_ig["ig_1"]["metadata"]["campaign_factory"]
        assert meta["parent_master_asset_id"] == "asset_1"
        assert meta["variant_asset_id"].startswith("asset_1_")
        assert meta["variant_assignment"]["lineage"]["paid_generation"] is False
        assert meta["generated_asset_lineage"]["variationApplied"] is True
        assert (
            meta["generated_asset_lineage"]["variantId"]
            == meta["variant_assignment"]["variant_asset_id"]
        )
    finally:
        cf.close()


def test_threadsdash_export_enabled_variation_blocks_missing_assignment(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        with pytest.raises(ValueError, match="variation assignment missing"):
            build_draft_payloads(
                cf, campaign_slug="may", user_id="user_1", enable_variation=True
            )
    finally:
        cf.close()


def test_export_manifest_hard_blocks_missing_lineage_v2_prompt_id(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = '{}' WHERE id = ?",
            (source["id"],),
        )
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        with pytest.raises(
            ValueError, match="generated asset lineage v2 missing promptId"
        ):
            cf.domains.export_summary.export_manifest(campaign_slug="may")
    finally:
        cf.close()


def test_threadsdash_export_dry_run_creates_draft_payload_only(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model", account_handles=["ig_a"]
        )
        source = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )[0]
        set_test_source_prompt(cf, source["id"])
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, caption_generation_json, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps(
                    {
                        "audioRecommendations": {
                            "primaryStrategy": "current_native_trending_sound",
                            "nativeAudioPreferred": True,
                            "recommendations": [{"audioVibe": "clean_fitcheck"}],
                        }
                    }
                ),
                now,
                now,
            ),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_1")
        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        assert payload["drafts"][0]["status"] == "draft"
        assert payload["drafts"][0]["platform"] == "instagram"
        assert payload["drafts"][0]["instagramAccountId"] is None
        assert payload["drafts"][0]["contentHash"] == "hash_1"
        assert payload["drafts"][0]["sourceContentHash"] == source["content_hash"]
        assert payload["drafts"][0]["captionHash"]
        assert payload["drafts"][0]["recipe"] == "v01_original"
        assert payload["drafts"][0]["publishMode"] == "notify"
        assert (
            payload["drafts"][0]["audioRecommendations"]["primaryStrategy"]
            == "current_native_trending_sound"
        )
        auto_payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", publish_mode="auto"
        )
        assert auto_payload["drafts"][0]["publishMode"] == "auto"
        assert (
            auto_payload["drafts"][0]["metadata"]["campaign_factory"]["publish_mode"]
            == "auto"
        )
        with pytest.raises(ValueError, match="invalid publish_mode"):
            build_draft_payloads(
                cf, campaign_slug="may", user_id="user_1", publish_mode="bogus"
            )
        metadata = payload["drafts"][0]["metadata"]["campaign_factory"]
        assert metadata["campaign_id"] == "may"
        assert metadata["graph_id"].startswith("cg_rendered_asset_")
        assert metadata["campaign_graph_id"].startswith("cg_campaign_")
        assert metadata["source_asset_graph_id"].startswith("cg_source_asset_")
        assert metadata["rendered_asset_graph_id"] == metadata["graph_id"]
        assert metadata["source_asset_id"] == source["id"]
        assert metadata["rendered_asset_id"] == "asset_1"
        assert metadata["content_hash"] == "hash_1"
        assert metadata["source_content_hash"] == source["content_hash"]
        assert metadata["caption_hash"] == payload["drafts"][0]["captionHash"]
        assert metadata["recipe"] == "v01_original"
        assert (
            metadata["audio_recommendations"]["primaryStrategy"]
            == "current_native_trending_sound"
        )
        assert metadata["audio_intent"]["schema"] == "pipeline.audio_intent.v1"
        assert metadata["audio_intent"]["required"] is True
        assert metadata["audio_intent"]["status"] == "recommended"
        assert metadata["audio_intent"]["task"]["schema"] == "pipeline.audio_task.v1"
        assert metadata["audio_intent"]["task"]["status"] == "open"
        assert metadata["audio_intent"]["task"]["proof_required"] is False
        assert metadata["audio_intent"]["gates"]["allow_draft_export"] is True
        assert metadata["audio_intent"]["gates"]["allow_publish"] is False
        assert metadata["publish_mode"] == "notify"
        assert metadata["audio_strategy"] == "current_native_trending_sound"
        assert metadata["native_audio_preferred"] is True
        exports_before = cf.conn.execute(
            "SELECT COUNT(*) FROM threadsdash_exports"
        ).fetchone()[0]
        jobs_before = cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[
            0
        ]
        events_before = cf.conn.execute(
            "SELECT COUNT(*) FROM activity_events"
        ).fetchone()[0]
        result = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="user_1",
            dry_run=True,
            content_pillar="fit_check",
            cta_type="profile_visit",
            language="en",
        )
        assert result["dryRun"] is True
        assert result["path"] is None
        assert result["pipelineJobId"] is None
        assert not Path(result["wouldWritePath"]).exists()
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == exports_before
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
            == jobs_before
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0]
            == events_before
        )
        assert result["payload"]["drafts"][0]["contentPillar"] == "fit_check"
        assert result["payload"]["drafts"][0]["ctaType"] == "profile_visit"
        assert result["payload"]["drafts"][0]["language"] == "en"
        preview_meta = result["payload"]["drafts"][0]["metadata"]["campaign_factory"]
        assert preview_meta["graph_id"] == metadata["graph_id"]
        assert preview_meta["content_pillar"] == "fit_check"
        assert preview_meta["cta_type"] == "profile_visit"
        assert preview_meta["language"] == "en"
        with pytest.raises(
            ValueError, match="read-only draft preview cannot generate variation"
        ):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=True,
                enable_variation=True,
            )
    finally:
        cf.close()


def test_threadsdash_audio_intent_defaults_to_needs_operator_selection_without_recommendations(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        folder = tmp_path / "inputs"
        folder.mkdir()
        (folder / "a.mp4").write_bytes(b"source")
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        source = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )[0]
        set_test_source_prompt(cf, source["id"])
        rendered_path = tmp_path / "needs_audio.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_audio', ?, ?, 'hash_audio', ?, ?, 'needs_audio.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                now,
                now,
            ),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_audio")

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        intent = payload["drafts"][0]["metadata"]["campaign_factory"]["audio_intent"]
        readiness = evaluate_export_readiness(cf, campaign_slug="may", user_id="user_1")

        assert intent["required"] is True
        assert intent["status"] == "needs_operator_selection"
        assert intent["task"]["status"] == "open"
        assert (
            "campaign_audio_unresolved: select audio before ThreadsDashboard export"
            in readiness["assets"][0]["blockingReasons"]
        )
        assert any(
            reason.endswith(
                "campaign_audio_unresolved: select audio before ThreadsDashboard export"
            )
            for reason in readiness["blockingReasons"]
        )
        assert not any(
            "native_audio_unresolved" in reason
            for reason in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_threadsdash_audio_intent_safe_statuses_pass_live_gate(
    tmp_path: Path, monkeypatch
):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    for status in ("attached", "verified", "skipped", "not_required"):
        cf = make_factory(tmp_path / status)
        try:
            source, _ = add_rendered_asset(cf, tmp_path / status)
            cf.domains.finished_video.review_rendered_asset(
                "asset_1", decision="approved"
            )
            add_audit_report(cf)
            required = status != "not_required"
            cf.conn.execute(
                "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
                (
                    json.dumps(
                        {
                            "instagram_post_caption": "new post",
                            "audioIntent": {
                                "schema": "pipeline.audio_intent.v1",
                                "mode": "native_platform_audio",
                                "required": required,
                                "status": status,
                                "platform": "instagram",
                                "recommendations": [],
                                "gates": {
                                    "allow_draft_export": True,
                                    "allow_preview_schedule": status
                                    in {
                                        "attached",
                                        "verified",
                                        "skipped",
                                        "not_required",
                                    },
                                    "allow_live_schedule": status
                                    in {
                                        "attached",
                                        "verified",
                                        "skipped",
                                        "not_required",
                                    },
                                    "allow_publish": status
                                    in {
                                        "attached",
                                        "verified",
                                        "skipped",
                                        "not_required",
                                    },
                                },
                                **(
                                    {
                                        "operator_selection": {
                                            "platform_audio_id": "ig_audio_1",
                                            "selected_at": "2026-05-22T12:00:00+00:00",
                                            **(
                                                {
                                                    "attached_at": "2026-05-22T12:05:00+00:00"
                                                }
                                                if status == "attached"
                                                else {
                                                    "verified_at": "2026-05-22T12:10:00+00:00"
                                                }
                                            ),
                                        }
                                    }
                                    if status in {"attached", "verified"}
                                    else {}
                                ),
                            },
                        }
                    ),
                ),
            )
            cf.conn.commit()

            readiness = evaluate_export_readiness(
                cf,
                campaign_slug="may",
                user_id="user_1",
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )

            assert readiness["liveExportAllowed"] is True
            assert not any(
                "campaign_audio_unresolved" in reason
                for reason in readiness["blockingReasons"]
            )
            assert source["id"]
        finally:
            cf.close()


def test_threadsdash_audio_intent_attached_requires_native_proof(
    tmp_path: Path, monkeypatch
):
    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return []

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "attached",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()

        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert readiness["liveExportAllowed"] is False
        assert any(
            "campaign_audio_unresolved: select audio before ThreadsDashboard export"
            in reason
            for reason in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_distribution_plan_exports_trial_and_story_surfaces(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.models.upsert_model_account_profile(
            "model",
            allowed_instagram_account_ids=["ig_good"],
            default_smart_link="https://example.com/stacey",
            story_cta_text="new post is up",
        )
        projected_at = datetime.now(UTC).isoformat()
        account = cf.domains.models.upsert_account(
            "fixture_ig_good", external_id="ig_good"
        )
        cf.domains.models.project_instagram_account_evidence(
            account["id"],
            capability="eligible",
            oauth_granted_scopes=[
                "instagram_business_basic",
                "instagram_business_content_publish",
            ],
            oauth_scopes_verified_at=projected_at,
            checked_at=projected_at,
            reason="meta_trial_reel_publish_succeeded",
            is_active=True,
            status="active",
            needs_reauth=False,
            projection_observed_at=projected_at,
        )
        trial = cf.domains.distribution.create_distribution_plan(
            "asset_1",
            surface="trial_reel",
            instagram_account_id="ig_good",
            planned_window_start="2026-01-02T10:00:00+00:00",
            reason_code="test_uncertain_winner",
            instagram_trial_reels=True,
            trial_graduation_strategy="MANUAL",
        )
        story = cf.domains.distribution.create_distribution_plan(
            "asset_1",
            surface="story_cta",
            instagram_account_id="ig_good",
            paired_rendered_asset_id="asset_1",
            reason_code="cta_followup",
            smart_link="https://example.com/stacey",
            cta_text="new post is up",
        )

        payload = build_draft_payloads(
            cf, campaign_slug="may", user_id="user_1", schedule_mode="preview"
        )
        by_surface = {
            draft["distributionSurface"]: draft for draft in payload["drafts"]
        }
        assert set(by_surface) == {"trial_reel", "story_cta"}
        assert by_surface["trial_reel"]["status"] == "draft"
        assert by_surface["trial_reel"]["instagramTrialReels"] is True
        assert by_surface["trial_reel"]["trialGraduationStrategy"] == "MANUAL"
        assert by_surface["trial_reel"]["shareToFeed"] is False
        assert by_surface["trial_reel"]["collaborators"] == []
        assert by_surface["trial_reel"]["scheduledFor"] == "2026-01-02T10:00:00+00:00"
        assert (
            by_surface["trial_reel"]["metadata"]["campaign_factory"][
                "preview_schedule_only"
            ]
            is True
        )
        assert by_surface["trial_reel"]["metadata"]["trialReels"] is True
        assert by_surface["trial_reel"]["metadata"]["shareToFeed"] is False
        assert (
            by_surface["trial_reel"]["metadata"]["trialGraduationStrategy"] == "MANUAL"
        )
        assert (
            by_surface["trial_reel"]["metadata"]["campaign_factory"][
                "instagram_trial_reels"
            ]
            is True
        )
        assert (
            by_surface["trial_reel"]["metadata"]["campaign_factory"]["trial_reel"]
            is True
        )
        assert (
            by_surface["trial_reel"]["metadata"]["campaign_factory"][
                "distribution_plan_id"
            ]
            == trial["id"]
        )
        assert by_surface["story_cta"]["content"] == "new post is up"
        assert (
            by_surface["story_cta"]["metadata"]["campaign_factory"][
                "distribution_plan_id"
            ]
            == story["id"]
        )
        assert (
            by_surface["story_cta"]["metadata"]["campaign_factory"]["smart_link"]
            == "https://example.com/stacey"
        )
        assert (
            by_surface["story_cta"]["metadata"]["campaign_factory"][
                "paired_rendered_asset_id"
            ]
            == "asset_1"
        )
        assert (
            by_surface["trial_reel"]["metadata"]["campaign_factory"]["account_profile"][
                "modelSlug"
            ]
            == "model"
        )
        assert by_surface["trial_reel"]["campaignId"] == "may"
    finally:
        cf.close()


def test_trial_draft_metadata_rejects_missing_graduation_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        monkeypatch.setattr(
            threadsdash_payload_adapter,
            "_draft_destinations_for_asset",
            lambda *_args, **_kwargs: [
                {
                    "accountId": "account_1",
                    "instagramAccountId": "ig_1",
                    "distributionSurface": "trial_reel",
                    "contentSurface": "reel",
                    "instagramTrialReels": True,
                    "trialGraduationStrategy": None,
                    "accountEligibility": {"allowed": True},
                }
            ],
        )

        with pytest.raises(
            ValueError,
            match="trial_graduation_strategy is required",
        ):
            build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
    finally:
        cf.close()


def test_export_rejects_legacy_unflagged_trial_distribution_plan(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        campaign = cf.domains.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO distribution_plans
            (id, campaign_id, rendered_asset_id, surface, content_surface,
             instagram_trial_reels, created_at, updated_at)
            VALUES ('dist_legacy_unflagged_trial', ?, 'asset_1', 'trial_reel',
                    'reel', 0, '2026-07-16T00:00:00+00:00',
                    '2026-07-16T00:00:00+00:00')
            """,
            (campaign["id"],),
        )
        cf.conn.commit()

        with pytest.raises(
            ValueError, match="trial_reel surface requires instagram_trial_reels=true"
        ):
            build_draft_payloads(
                cf,
                campaign_slug="may",
                user_id="user_1",
                surface="trial_reel",
            )
    finally:
        cf.close()


def test_handoff_manifest_preserves_distinct_instagram_post_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post is up",
                        "caption_cta": "go watch",
                        "hashtags": ["#stacey", "mirror fit", "#reels"],
                        "post_caption_style": "short_natural",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )
        manifest = explanation["handoff_manifest"]

        assert explanation["publishableCandidate"] is True
        assert manifest["burned_caption_text"] == "caption"
        assert (
            manifest["instagram_post_caption"]
            == "new post is up\ngo watch\n#stacey #mirrorfit #reels"
        )
        assert manifest[
            "instagram_post_caption_hash"
        ] == threadsdash_client_adapter._text_hash(manifest["instagram_post_caption"])
        assert manifest["post_caption_style"] == "short_natural"
    finally:
        cf.close()


def test_handoff_manifest_does_not_fallback_burned_caption_to_instagram_post_caption(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ?, caption_outcome_context_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
                json.dumps(
                    {
                        "schema": "campaign_factory.caption_outcome_context.v1",
                        "caption_hash": "caption_hash_1",
                        "caption_text": "caption",
                        "caption_bank": "test_bank",
                        "caption_banks": ["test_bank"],
                        "captionPlacementDecision": {"status": "passed"},
                    }
                ),
            ),
        )
        cf.conn.commit()
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )
        manifest = explanation["handoff_manifest"]

        assert explanation["burned_caption_text"] == "caption"
        assert explanation["instagram_post_caption"] == ""
        assert manifest is None
        assert (
            "missing_instagram_post_caption"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["publishableCandidate"] is False
    finally:
        cf.close()


def test_threadsdash_draft_metadata_does_not_fallback_content_to_instagram_caption():
    metadata = threadsdash_payload_adapter._draft_metadata(
        {
            "campaignId": "campaign_1",
            "renderedAssetId": "asset_1",
            "sourceAssetId": "source_1",
            "content": "visible overlay text should stay separate",
            "captionHash": "caption_hash_1",
            "burnedCaptionText": "visible overlay text should stay separate",
            "publishability": {
                "asset_state": "approved_but_not_publishable",
                "publishability_failure_reasons": ["missing_instagram_post_caption"],
                "visualQcStatus": "passed",
                "identityVerificationStatus": "passed",
            },
            "audioIntent": {
                "schema": "pipeline.audio_intent.v1",
                "mode": "native_platform_audio",
                "required": False,
                "status": "not_required",
                "platform": "instagram",
                "recommendations": [],
                "gates": {"allow_draft_export": False, "allow_publish": False},
            },
        }
    )

    campaign_meta = metadata["campaign_factory"]
    assert campaign_meta["instagram_post_caption"] == ""
    assert (
        campaign_meta["burned_caption_text"]
        == "visible overlay text should stay separate"
    )


def test_variant_lineage_is_added_to_publishability_and_handoff_manifest(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        parent = cf.domains.variant_lineage.register_parent_reel(
            "asset_1", operator="tester"
        )
        variant = cf.domains.variant_lineage.register_variant_asset(
            parent_asset_id="asset_1",
            variant_asset_id="asset_1",
            variant_family_id="vfam_test",
            variant_index=1,
            operations=[{"type": "caption_safe", "preset": "caption_safe"}],
            contentforge_run_id="cf_run_1",
        )
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )

        publishability = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )

        assert variant["variantId"].startswith("var_")
        assert publishability["conceptId"] == parent["conceptId"]
        assert publishability["variantFamilyId"] == "vfam_test"
        assert publishability["variantId"] == variant["variantId"]
        manifest = publishability["handoff_manifest"]
        assert manifest["concept_id"] == parent["conceptId"]
        assert manifest["variant_family_id"] == "vfam_test"
        assert manifest["variant_id"] == variant["variantId"]
        context = publishability["captionOutcomeContext"]
        assert context["concept_id"] == parent["conceptId"]
        assert context["variant_family_id"] == "vfam_test"
    finally:
        cf.close()


def test_surface_draft_proof_feed_single_image_does_not_collapse_to_reel(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_single_proof",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="new fit today",
        )

        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_feed_single_proof",
        )

        draft = proof["drafts"][0]
        manifest = draft["handoffManifestV2"]
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "feed_single"
        assert draft["igMediaType"] == "IMAGE"
        assert draft["mediaType"] == "image"
        assert draft["contentSurface"] != "reel"
        assert manifest["contentSurface"] == "feed_single"
        assert manifest["igMediaType"] == "IMAGE"
        assert manifest["mediaItems"][0]["mediaType"] == "image"
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_draft_proof_story_does_not_require_post_caption_by_default(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_proof",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
            target_ratio="9:16",
        )
        quality = cf.domains.story_management.story_quality_gate_v1("asset_story_proof")

        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_story_proof",
        )

        draft = proof["drafts"][0]
        assert quality["story_quality_gate_passed"] is True
        assert quality["geometry"]["width"] == 1080
        assert quality["geometry"]["height"] == 1920
        assert quality["storyBlackBarCheck"]["blackBarsDetected"] is False
        assert quality["story_safe_zone_score"] >= 95
        assert quality["story_focal_safety_score"] >= 95
        assert quality["story_text_readability_score"] >= 95
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "story"
        assert draft["igMediaType"] == "STORIES"
        assert draft["instagramPostCaption"] == ""
        assert draft["handoffManifestV2"]["instagramPostCaption"] == ""
        assert draft["handoffManifestV2"]["surfaceReadiness"]["canHandoff"] is True
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_surface_draft_proof_carousel_manifest_has_ordered_media_items(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        carousel = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_carousel_proof",
            content_surface="feed_carousel",
            media_type="image",
            instagram_post_caption="which one wins?",
        )
        for index in range(3):
            component_path = tmp_path / f"proof_carousel_{index}.jpg"
            component_path.write_bytes(f"carousel-{index}".encode())
            cf.conn.execute(
                """
                INSERT INTO asset_components
                (id, asset_id, component_index, media_path, media_hash, media_type, aspect_ratio,
                 alt_text, publishability_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'image', '1:1', ?, 'passed',
                        '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
                """,
                (
                    f"proof_comp_{index}",
                    carousel["id"],
                    index,
                    str(component_path),
                    f"hash_proof_{index}",
                    f"slide {index}",
                ),
            )
        cf.conn.commit()

        proof = cf.domains.surface_handoff.surface_draft_proof(
            creator="Stacey",
            campaign="stacey_surface_inventory_20260606",
            rendered_asset_id="asset_carousel_proof",
        )

        draft = proof["drafts"][0]
        media_items = draft["handoffManifestV2"]["mediaItems"]
        assert proof["canProduceDraftPayload"] is True
        assert draft["contentSurface"] == "feed_carousel"
        assert draft["igMediaType"] == "CAROUSEL"
        assert [item["componentIndex"] for item in media_items] == [0, 1, 2]
        assert all(item["mediaHash"] for item in media_items)
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_story_handoff_manifest_v2_includes_story_quality_proof_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(
            cf,
            tmp_path,
            asset_id="asset_story_manifest_quality",
            quality_metadata={"storyNoTextRequired": True, "storyNoTextPassed": True},
        )

        readiness = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id="asset_story_manifest_quality"
        )
        manifest = readiness["assets"][0]["handoffManifestV2"]

        assert readiness["assets"][0]["canHandoff"] is True
        assert manifest["storyQualityGatePassed"] is True
        assert manifest["storySourceNative"] is True
        assert manifest["storyNoTextRequired"] is True
        assert manifest["storyNoTextPassed"] is True
        assert manifest["storyStyleApproved"] is True
        assert manifest["sourceLineageBlockers"] == []
        assert manifest["visualQualityStatus"] == "passed"
    finally:
        cf.close()


def test_sync_threadsdash_account_assignments_imports_calendar_accounts(
    tmp_path: Path, monkeypatch
):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            assert table == "posts"
            return [
                {
                    "id": "post_1",
                    "status": "scheduled",
                    "platform": "instagram",
                    "media_type": "reel",
                    "ig_media_type": "REELS",
                    "account_id": "remote_account_1",
                    "instagram_account_id": "ig_1",
                    "scheduled_for": "2026-05-20T14:00:00+00:00",
                    "metadata": {
                        "campaign_factory": {
                            "campaign_id": "may",
                            "source_asset_id": "src_1",
                            "rendered_asset_id": "asset_1",
                        }
                    },
                },
            ]

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        imported = cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        source = imported["imported"][0]
        cf.conn.execute(
            "UPDATE source_assets SET id = 'src_1' WHERE id = ?", (source["id"],)
        )
        rendered_path = tmp_path / "ok.mp4"
        rendered_path.write_bytes(b"rendered")
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, 'src_1', 'hash_1', ?, ?, 'ok.mp4', 'caption', 'v01_original', 'approved_candidate', 'approved', ?, ?)
            """,
            (source["campaign_id"], str(rendered_path), str(rendered_path), now, now),
        )
        cf.conn.commit()

        first = sync_threadsdash_account_assignments(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )
        second = sync_threadsdash_account_assignments(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assignments = cf.domains.campaign_overview.assignments_for_campaign("may")
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert assignments[0]["rendered_asset_id"] == "asset_1"
        assert assignments[0]["account_id"] is None
        assert assignments[0]["instagram_account_id"] == "ig_1"
        assert assignments[0]["planned_window_start"] == "2026-05-20T14:00:00+00:00"
    finally:
        cf.close()


def test_lifecycle_report_marks_invalid_export_payload_as_failed(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        report = cf.domains.lifecycle_reporting.lifecycle_report(
            "may",
            threadsdash_posts=[
                _threadsdash_lifecycle_post(
                    post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
                    status="draft",
                    plan_id=plan["id"],
                    metadata_extra={
                        "invalid_export_payload": True,
                        "invalid_reason": "threadsdash_draft_media_invalid_missing_burned_captions",
                        "invalidated_at": "2026-06-05T00:00:00Z",
                    },
                )
            ],
        )
        assert _lifecycle_state(report) == "failed"
        assert (
            report["rows"][0]["blockingReason"]
            == "threadsdash_draft_media_invalid_missing_burned_captions"
        )
        assert (
            report["rows"][0]["nextOperatorAction"]
            == "replace_draft_with_verified_captioned_asset"
        )
        assert (
            report["rows"][0]["evidence"]["mediaValidation"]["source"]
            == "threadsdash_metadata"
        )
    finally:
        cf.close()


def test_instagram_distribution_plan_does_not_export_internal_account_id(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            """INSERT INTO accounts
            (id, handle, platform, created_at, updated_at)
            VALUES ('acct_campaign_factory_internal', 'stacey_internal', 'instagram', ?, ?)""",
            ("2026-07-11T00:00:00+00:00", "2026-07-11T00:00:00+00:00"),
        )
        cf.conn.commit()
        cf.domains.distribution.create_distribution_plan(
            "asset_1",
            account_id="acct_campaign_factory_internal",
            instagram_account_id="ig_dashboard_canonical",
        )

        payload = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")
        draft = payload["drafts"][0]

        assert draft["accountId"] is None
        assert draft["instagramAccountId"] == "ig_dashboard_canonical"
    finally:
        cf.close()


def test_content_graph_stays_local_until_threadsdash_draft_handoff(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        node_types = {
            row["entity_type"]
            for row in cf.conn.execute(
                "SELECT entity_type FROM content_graph_nodes"
            ).fetchall()
        }
        assert {
            "campaign",
            "source_asset",
            "rendered_asset",
            "approval_decision",
        } <= node_types
        assert "threadsdash_post" not in node_types
    finally:
        cf.close()


def test_account_assignment_is_preserved_in_draft_payload_without_direct_write(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        assignment = cf.domains.campaign_overview.assign_asset_account(
            "asset_1",
            instagram_account_id="ig_acc_1",
            planned_window_start="2026-05-15T10:00:00-04:00",
            planned_window_end="2026-05-15T12:00:00-04:00",
            notes="morning test",
        )
        assert assignment["instagram_account_id"] == "ig_acc_1"

        draft = build_draft_payloads(cf, campaign_slug="may", user_id="user_1")[
            "drafts"
        ][0]
        metadata = draft["metadata"]["campaign_factory"]
        assert draft["instagramAccountId"] == "ig_acc_1"
        assert metadata["planned_window_start"] == "2026-05-15T10:00:00-04:00"
        assert metadata["planned_window_end"] == "2026-05-15T12:00:00-04:00"
        assert metadata["assignment_notes"] == "morning test"
    finally:
        cf.close()
