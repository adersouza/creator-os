from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from campaign_factory import creation_modes
from campaign_test_support import authorize_campaign_governance, make_factory


@pytest.fixture(autouse=True)
def _approved_v2_reuse_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        creation_modes,
        "_creative_approval_for_asset",
        lambda _factory, asset_id: {
            "schema": "creator_os.creative_approval_state.v2",
            "assetId": asset_id,
            "state": "approved",
        },
    )


def test_anchor_approval_is_only_valid_for_recreate_reel(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only valid for recreate_reel"):
        creation_modes.run_creation_batch(
            object(),
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
            recreation_anchor_approval_path=tmp_path / "approval.json",
        )


def _approved_reusable_asset(
    cf,
    tmp_path: Path,
    *,
    asset_id: str,
    intent: str,
    recipe: str,
    updated_at: str,
) -> tuple[dict[str, object], str]:
    campaign = cf.domains.campaign_by_slug("stacey-library")
    source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
    video = tmp_path / f"{asset_id}.mp4"
    video.write_bytes(asset_id.encode())
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    metadata = {
        "contentIntent": intent,
        "audioBurned": True,
        "output": {"path": str(video), "sha256": digest},
        "audioEmbeddingReceipt": {
            "verification": {
                "status": "verified",
                "audioPresent": True,
                "audioCodec": "aac",
            },
            "finalVideo": {"path": str(video), "sha256": digest},
        },
    }
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path,
         campaign_path, filename, media_type, content_surface,
         caption_generation_json, metadata_json, recipe, audit_status,
         review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', '{}', ?, ?,
                'approved_candidate', 'approved', ?, ?)
        """,
        (
            asset_id,
            campaign["id"],
            source["id"],
            digest,
            str(video),
            str(video),
            video.name,
            json.dumps(metadata),
            recipe,
            updated_at,
            updated_at,
        ),
    )
    cf.conn.execute(
        """
        INSERT INTO approval_decisions
        (id, campaign_id, rendered_asset_id, decision, notes, created_at)
        VALUES (?, ?, ?, 'approved', 'exact creative approval', ?)
        """,
        (f"approval-{asset_id}", campaign["id"], asset_id, updated_at),
    )
    cf.conn.commit()
    return dict(source), digest


def _seed_stacey_source(cf, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.mp4").write_bytes(b"source")
    cf.domains.asset_import.import_folder(
        source_dir,
        campaign_slug="stacey-library",
        model_slug="stacey",
    )
    authorize_campaign_governance(
        cf,
        tmp_path,
        creator="stacey",
        campaign="stacey-library",
        provider="higgsfield",
        soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
    )


def test_calm_animation_reuses_exact_approved_asset_before_prompt_or_provider(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "source.mp4").write_bytes(b"source")
        cf.domains.asset_import.import_folder(
            source_dir,
            campaign_slug="stacey-library",
            model_slug="stacey",
        )
        authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="stacey-library",
            provider="higgsfield",
            soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        )
        campaign = cf.domains.campaign_by_slug("stacey-library")
        source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
        video = tmp_path / "approved.mp4"
        video.write_bytes(b"approved-calm-animation")
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        now = "2026-07-29T12:00:00Z"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, media_type, content_surface,
             caption_generation_json, metadata_json, recipe, audit_status,
             review_state, created_at, updated_at)
            VALUES ('approved-calm', ?, ?, ?, ?, ?, 'approved.mp4', 'video',
                    'reel', '{}', ?, 'higgsfield_kling3_turbo_i2v',
                    'approved_candidate', 'approved', ?, ?)
            """,
            (
                campaign["id"],
                source["id"],
                digest,
                str(video),
                str(video),
                json.dumps(
                    {
                        "contentIntent": "passive_selfie",
                        "audioBurned": True,
                        "output": {"path": str(video), "sha256": digest},
                        "audioEmbeddingReceipt": {
                            "verification": {
                                "status": "verified",
                                "audioPresent": True,
                                "audioCodec": "aac",
                            },
                            "finalVideo": {
                                "path": str(video),
                                "sha256": digest,
                            },
                        },
                    }
                ),
                now,
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO approval_decisions
            (id, campaign_id, rendered_asset_id, decision, notes, created_at)
            VALUES ('approval-approved-calm', ?, 'approved-calm', 'approved',
                    'exact creative approval', ?)
            """,
            (campaign["id"], now),
        )
        cf.conn.commit()

        def forbidden_prompt(**_kwargs):
            raise AssertionError("reuse must happen before OpenAI prompting")

        result = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
            prompt_pack_provider=forbidden_prompt,
        )

        assert result["execution"] == "library_reuse"
        assert result["route"] == "exact_final_reuse"
        assert result["reusePolicy"] == "prefer_exact"
        assert result["summary"]["reused"] == 1
        assert result["summary"]["totalProviderCredits"] == 0
        assert result["results"][0]["renderedAssetId"] == "approved-calm"
        assert result["results"][0]["outputSha256"] == digest
        assert result["schedulingAllowed"] is False
        assert result["publishingAllowed"] is False

        monkeypatch.setattr(
            creation_modes,
            "run_production_batch",
            lambda _factory, **kwargs: {
                "route": "fresh_generation",
            },
        )
        fresh = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
            reuse_policy="require_fresh",
        )
        assert fresh["route"] == "fresh_generation"
        assert fresh["reusePolicy"] == "require_fresh"
        assert fresh["fallbackDecision"] == "require_fresh"
        assert fresh["destinationReady"] is False
    finally:
        cf.close()


def test_static_reel_reuse_requires_exact_content_intent(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        _seed_stacey_source(cf, tmp_path)
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="approved-static-outfit",
            intent="outfit",
            recipe="static_mp4",
            updated_at="2026-07-29T12:00:00Z",
        )
        calls: list[int] = []
        monkeypatch.setattr(
            creation_modes,
            "_run_static_reel_batch",
            lambda _factory, **kwargs: (
                calls.append(int(kwargs["count"]))
                or {"route": "fresh_generation", "results": [], "summary": {}}
            ),
        )

        result = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="static_reel",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
        )

        assert calls == [1]
        assert result["route"] == "fresh_generation"
        assert result["reuseCandidatesFound"] == 0
        assert result["fallbackDecision"] == "fresh_full_batch_no_qualified_reuse"
    finally:
        cf.close()


def test_reuse_fails_closed_without_exact_creative_approval_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        _seed_stacey_source(cf, tmp_path)
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="legacy-approved-only",
            intent="passive_selfie",
            recipe="higgsfield_kling3_turbo_i2v",
            updated_at="2026-07-29T12:00:00Z",
        )
        monkeypatch.setattr(
            creation_modes,
            "_creative_approval_for_asset",
            lambda _factory, _asset_id: {
                "schema": "creator_os.creative_approval_state.v2",
                "state": "missing",
            },
        )
        monkeypatch.setattr(
            creation_modes,
            "run_production_batch",
            lambda _factory, **_kwargs: {
                "route": "fresh_generation",
                "results": [],
                "summary": {},
            },
        )

        result = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
        )

        assert result["route"] == "fresh_generation"
        assert result["reuseCandidatesFound"] == 0
    finally:
        cf.close()


def test_reuse_skips_conflicting_reservation_and_reserves_next_candidate(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        _seed_stacey_source(cf, tmp_path)
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="approved-available",
            intent="passive_selfie",
            recipe="higgsfield_kling3_turbo_i2v",
            updated_at="2026-07-29T12:00:00Z",
        )
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="approved-conflicting",
            intent="passive_selfie",
            recipe="higgsfield_kling3_turbo_i2v",
            updated_at="2026-07-29T13:00:00Z",
        )
        model_id = cf.domains.models.upsert_model("stacey")["id"]
        destination = cf.domains.models.upsert_account("destination", model_id=model_id)
        other = cf.domains.models.upsert_account("other", model_id=model_id)
        cf.domains.inventory_reservations.reserve_inventory_asset(
            "approved-conflicting",
            account_id=other["id"],
            surface="reel",
        )

        result = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts="destination",
            audio_preference="embedded_trending_required",
            apply=True,
        )

        assert result["route"] == "exact_final_reuse"
        assert result["destinationReady"] is True
        assert result["results"][0]["renderedAssetId"] == "approved-available"
        assert result["results"][0]["reservationId"]
        reservation = cf.conn.execute(
            """
            SELECT *
            FROM asset_inventory_reservations
            WHERE asset_id = 'approved-available'
            """
        ).fetchone()
        assert reservation is not None
        assert reservation["account_id"] == destination["id"]
        assert reservation["status"] == "pending"
        assert result["reuseBlockers"] == [
            {
                "assetId": "approved-conflicting",
                "reason": "active_reservation_for_other_destination",
            }
        ]
    finally:
        cf.close()


def test_destination_reuse_generates_only_the_exact_shortfall(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        _seed_stacey_source(cf, tmp_path)
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="approved-one",
            intent="passive_selfie",
            recipe="higgsfield_kling3_turbo_i2v",
            updated_at="2026-07-29T12:00:00Z",
        )
        model_id = cf.domains.models.upsert_model("stacey")["id"]
        cf.domains.models.upsert_account("destination", model_id=model_id)
        fresh_counts: list[int] = []

        def fresh(_factory, **kwargs):
            fresh_counts.append(int(kwargs["count"]))
            return {
                "schema": "campaign_factory.production_batch.v1",
                "requested": kwargs["count"],
                "route": "fresh_generation",
                "results": [{"jobId": "fresh-0", "index": 0, "status": "created"}],
                "summary": {
                    "requested": kwargs["count"],
                    "created": kwargs["count"],
                    "completed": 0,
                    "approved": 0,
                    "blocked": 0,
                    "failed": 0,
                    "totalProviderCredits": 0,
                },
            }

        monkeypatch.setattr(creation_modes, "run_production_batch", fresh)
        result = creation_modes.run_creation_batch(
            cf,
            creator="stacey",
            mode="calm_animation",
            style="passive_selfie",
            count=2,
            execution="cloud",
            accounts="destination",
            audio_preference="embedded_trending_required",
            apply=False,
        )

        assert fresh_counts == [1]
        assert result["route"] == "partial_exact_reuse_fresh_fill"
        assert result["summary"]["requested"] == 2
        assert result["summary"]["reused"] == 1
        assert result["reuseShortfall"] == 1
        assert result["fallbackDecision"] == "generate_fresh_shortfall"
        assert [item["index"] for item in result["results"]] == [0, 1]
        assert result["reservationStatus"] == "partial_preview"
        assert result["destinationReady"] is False
    finally:
        cf.close()


def test_partial_reuse_releases_new_reservations_when_fresh_fill_aborts(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        _seed_stacey_source(cf, tmp_path)
        _approved_reusable_asset(
            cf,
            tmp_path,
            asset_id="approved-one",
            intent="passive_selfie",
            recipe="higgsfield_kling3_turbo_i2v",
            updated_at="2026-07-29T12:00:00Z",
        )
        model_id = cf.domains.models.upsert_model("stacey")["id"]
        cf.domains.models.upsert_account("destination", model_id=model_id)
        monkeypatch.setattr(
            creation_modes,
            "run_production_batch",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("fresh fill aborted")
            ),
        )

        with pytest.raises(RuntimeError, match="fresh fill aborted"):
            creation_modes.run_creation_batch(
                cf,
                creator="stacey",
                mode="calm_animation",
                style="passive_selfie",
                count=2,
                execution="cloud",
                accounts="destination",
                audio_preference="embedded_trending_required",
                apply=True,
            )

        reservation = cf.conn.execute(
            """
            SELECT status
            FROM asset_inventory_reservations
            WHERE asset_id = 'approved-one'
            """
        ).fetchone()
        assert reservation is not None
        assert reservation["status"] == "released"
    finally:
        cf.close()
