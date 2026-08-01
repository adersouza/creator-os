from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import campaign_factory.daily_library_production as daily_library
from campaign_test_support import make_factory
from reel_factory.caption_bank import CaptionBankStore
from reel_factory.caption_intake import promote
from reel_factory.reel_pipeline_support import CaptionSet, timed_caption_band

from pipeline_contracts import (
    evaluate_overlay_semantic_completeness,
    evaluate_overlay_timing,
)


def test_recent_unassigned_review_inventory_blocks_overlay_reuse() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE rendered_assets (
          id TEXT, caption_hash TEXT, caption_generation_json TEXT,
          metadata_json TEXT, review_state TEXT, created_at TEXT
        );
        CREATE TABLE asset_account_assignments (rendered_asset_id TEXT, created_at TEXT);
        CREATE TABLE distribution_plans (rendered_asset_id TEXT, planned_window_start TEXT, created_at TEXT);
        CREATE TABLE asset_inventory_reservations (asset_id TEXT, status TEXT, reserved_at TEXT);
        INSERT INTO rendered_assets VALUES (
          'asset-1', 'caption-hash', '{}', '{}', 'draft',
          strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        );
        """
    )

    assert "caption-hash" in daily_library._recent_used_caption_keys(conn)


def test_approved_timed_payload_survives_bank_selection_sidecar_and_render_plan(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "clip.mp4").write_bytes(b"fixture-video")
        cf.domains.asset_import.import_folder(
            source_dir,
            campaign_slug="may",
            model_slug="stacey",
            storage_mode="reference",
        )
        source = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )[0]

        approval = tmp_path / "approved.json"
        segments = [
            {"text": "wife material"},
            {"text": "or heartbreak material?"},
        ]
        approval.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_swipe_approved.v1",
                    "candidates": [
                        {
                            "id": "candidate-e2e-1",
                            "text": "wife material\nor heartbreak material?",
                            "status": "approved",
                            "approvedUse": ["timed"],
                            "placementIntent": {
                                "creatorStylePreset": "stacey_static_center",
                                "timedPlacementMode": "segment",
                                "timedBandFamily": [
                                    "lower_center",
                                    "lower_center_alt",
                                ],
                                "finalPlacement": "placement.py",
                            },
                            "hookVariants": {"timed": {"segments": segments}},
                            "reviewer": "operator-1",
                            "decidedAt": "2026-07-29T12:00:00Z",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        promoted = promote(cf.settings.reel_factory_root, approval)
        assert promoted["promoted"] == 1
        store = CaptionBankStore.from_root(cf.settings.reel_factory_root)
        bank_item = next(
            item for item in store.all_items() if item["variant_type"] == "timed"
        )
        payload_hash = bank_item["caption_payload_hash"]

        import reel_factory.worker_api as worker_api

        monkeypatch.setattr(
            worker_api, "load_or_build_caption_bank_store", lambda _root: store
        )
        monkeypatch.setattr(
            cf.domains.reference,
            "reference_hook_is_schedule_safe",
            lambda _text: True,
        )
        monkeypatch.setattr(
            daily_library, "_recent_used_caption_keys", lambda _conn: set()
        )

        hooks = daily_library._daily_hooks(cf, count=1, seed_key="e2e")
        hook = hooks[0]
        assert hook["captionPayloadHash"] == payload_hash
        assert hook["segments"] == segments
        assert hook["captionLineage"]["captionPayloadHash"] == payload_hash
        assert hook["captionLineage"]["approvalReviewer"] == "operator-1"
        assert hook["captionLineage"]["timedPreferred"] is True
        assert hook["captionLineage"]["timedEligible"] is True
        assert hook["captionLineage"]["fallbackReason"] is None

        prepared = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=hooks,
            recipes=["v01_original"],
            source_asset_ids=[source["id"]],
        )
        job = prepared["prepared"][0]
        sidecar = json.loads(
            (
                cf.settings.reel_factory_root
                / "01_captions"
                / f"{job['reel_clip_stem']}.json"
            ).read_text(encoding="utf-8")
        )
        assert sidecar["hooks"][0]["segments"] == segments
        assert sidecar["hook_metadata"][0]["captionPayloadHash"] == payload_hash
        assert (
            sidecar["hook_metadata"][0]["captionLineage"]["captionPayloadHash"]
            == payload_hash
        )
        loaded = CaptionSet.from_path(
            cf.settings.reel_factory_root
            / "01_captions"
            / f"{job['reel_clip_stem']}.json"
        )
        assert loaded.hooks[0]["segments"] == segments
        assert loaded.hook_lineage[0]["captionPayloadHash"] == payload_hash
        assert loaded.hook_lineage[0]["approvalReviewer"] == "operator-1"

        timing = evaluate_overlay_timing(segments, duration_seconds=4.0)
        render_plan = timing["resolved_render_plan"]
        semantic = evaluate_overlay_semantic_completeness(
            render_plan,
            require_overlay=True,
            duration_seconds=4.0,
        )
        bands = [
            timed_caption_band("lower_center", index, None)  # type: ignore[arg-type]
            for index in range(len(segments))
        ]
        assert timing["passed"] is True
        assert semantic["passed"] is True
        assert bands == ["lower_center", "lower_center_alt"]
        assert [item["text"] for item in render_plan["segments"]] == [
            item["text"] for item in segments
        ]
    finally:
        cf.close()


def test_unapproved_historical_timed_item_falls_back_to_static(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)

    class Store:
        def resolve_mix(self, *_args, **_kwargs):
            return [
                {
                    "caption_hash": "unproven_text",
                    "static_text_hash": "unproven_text",
                    "caption_payload_hash": "unproven_payload",
                    "variant_type": "timed",
                    "text": "unproven first\nunproven payoff",
                    "segments": [
                        {"text": "unproven first"},
                        {"text": "unproven payoff"},
                    ],
                    "approval_id": None,
                    "banks": ["comment_bait"],
                    "selected_banks": ["comment_bait"],
                },
                {
                    "caption_hash": "static_text",
                    "static_text_hash": "static_text",
                    "caption_payload_hash": "static_payload",
                    "variant_type": "static",
                    "text": "pick one",
                    "line_count": 1,
                    "word_count": 2,
                    "char_count": 8,
                    "banks": ["choice_poll"],
                    "selected_banks": ["choice_poll"],
                },
            ]

        def lineage_for(self, item, **_kwargs):
            return {"captionHash": item["caption_hash"]}

    import reel_factory.worker_api as worker_api

    monkeypatch.setattr(
        worker_api, "load_or_build_caption_bank_store", lambda _root: Store()
    )
    monkeypatch.setattr(
        cf.domains.reference, "reference_hook_is_schedule_safe", lambda _text: True
    )
    monkeypatch.setattr(daily_library, "_recent_used_caption_keys", lambda _conn: set())
    try:
        selected = daily_library._daily_hooks(cf, count=1, seed_key="fallback")[0]
        assert selected["variantType"] == "static"
        assert selected["captionLineage"]["eligibilityDecision"] == "static_fallback"
        assert selected["captionLineage"]["timedEligible"] is False
        assert (
            selected["captionLineage"]["fallbackReason"]
            == "no_remaining_eligible_approved_timed_hook"
        )
    finally:
        cf.close()


def test_daily_hook_uses_source_scene_fit_before_static_fallback(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "gym_selfie.mp4").write_bytes(b"fixture-video")
    cf.domains.asset_import.import_folder(
        source_dir,
        campaign_slug="may",
        model_slug="stacey",
        storage_mode="reference",
    )
    source = cf.domains.asset_import.assets_for_campaign(
        cf.domains.campaign_by_slug("may")["id"]
    )[0]

    class Store:
        def resolve_mix(self, *_args, **_kwargs):
            return [
                {
                    "caption_hash": "timed_text",
                    "static_text_hash": "timed_text",
                    "caption_payload_hash": "timed_payload",
                    "variant_type": "timed",
                    "text": "come to my bedroom\nor stay lonely",
                    "segments": [
                        {"text": "come to my bedroom"},
                        {"text": "or stay lonely"},
                    ],
                    "approval_id": "approval-1",
                    "approval_file_sha": "a" * 64,
                    "approval_reviewer": "operator",
                    "approval_decided_at": "2026-07-31T12:00:00Z",
                    "banks": ["bedroom_mirror"],
                    "selected_banks": ["bedroom_mirror"],
                },
                {
                    "caption_hash": "static_text",
                    "static_text_hash": "static_text",
                    "caption_payload_hash": "static_payload",
                    "variant_type": "static",
                    "text": "gym or dinner?",
                    "line_count": 1,
                    "word_count": 3,
                    "char_count": 14,
                    "banks": ["gym_body"],
                    "selected_banks": ["gym_body"],
                },
            ]

        def lineage_for(self, item, **_kwargs):
            return {
                "captionHash": item["caption_hash"],
                "captionPayloadHash": item["caption_payload_hash"],
                "selectedBanks": item["selected_banks"],
                "approvalId": item.get("approval_id"),
                "approvalFileSha": item.get("approval_file_sha"),
            }

    import reel_factory.worker_api as worker_api

    monkeypatch.setattr(
        worker_api, "load_or_build_caption_bank_store", lambda _root: Store()
    )
    monkeypatch.setattr(
        cf.domains.reference, "reference_hook_is_schedule_safe", lambda _text: True
    )
    monkeypatch.setattr(daily_library, "_recent_used_caption_keys", lambda _conn: set())
    try:
        selected = daily_library._daily_hooks(
            cf,
            count=1,
            seed_key="gym-context",
            selections=[{"sourceAssetId": source["id"]}],
        )[0]
        lineage = selected["captionLineage"]
        assert selected["text"] == "gym or dinner?"
        assert lineage["fallbackReason"] == "no_source_compatible_approved_timed_hook"
        assert lineage["captionSelectionContext"]["frameType"] == "gym_body"
        assert lineage["sceneCompatibilityDecision"] == "allowed"
    finally:
        cf.close()
