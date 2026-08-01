from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from campaign_factory.content_director_operations import design_experiment
from campaign_factory.creative_approval import asset_requires_creative_approval
from campaign_factory.observed_experiment_reporting import (
    OBSERVED_MEASUREMENT_PLAN,
    _bootstrap_interval,
    _interpretation,
    _snapshot_exclusion_reasons,
    observed_experiment_report,
    record_observed_experiment_decision,
    select_observed_profile,
)
from campaign_test_support import make_factory
from reel_factory.observed_profiles import (
    CONTENTFORGE_QC_POLICY_FILES,
    render_observed_profile,
)

TEST_PROFILE = "mirror_crop_tone@1"


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _silent_video(path: Path, *, color: str) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:r=30:d=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _mux_audio(source: Path, output: Path, *, frequency: int = 440) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=44100:duration=1.2",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ],
        check=True,
    )
    return output


def _insert_plan(
    cf,
    *,
    source_id: str,
    account_ids: tuple[str, str],
    profile: str,
) -> tuple[str, tuple[str, str]]:
    now = "2026-07-29T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO creative_plans
        (id, name, target_account, status, created_at, updated_at)
        VALUES ('observed_root', 'observed_root', ?, 'approved', ?, ?)
        """,
        (account_ids[0], now, now),
    )
    cf.conn.execute(
        """
        INSERT INTO creative_plan_versions
        (id, creative_plan_id, version, creator, identity_profile, horizon_start,
         horizon_end, account_scope_json, timezone, objective,
         requested_output_count, autonomy_mode, status, input_fingerprint,
         created_at, updated_at)
        VALUES ('observed_plan', 'observed_root', 1, 'stacey', 'stacey',
                '2026-07-29', '2026-08-05', ?, 'America/New_York', 'GROWTH',
                2, 'SUPERVISED', 'APPROVED', 'observed-plan-fingerprint', ?, ?)
        """,
        (json.dumps(account_ids), now, now),
    )
    item_ids = ("observed_item_a", "observed_item_b")
    for index, (item_id, account_id) in enumerate(
        zip(item_ids, account_ids, strict=True)
    ):
        cf.conn.execute(
            """
            INSERT INTO creative_plan_items
            (id, plan_version_id, item_index, creator, identity_profile,
             target_account, content_intent, source_asset_id, pattern_family,
             prompt_text, desired_duration_seconds, audio_policy,
             exploration_class, priority, execution_state, created_at, updated_at)
            VALUES (?, 'observed_plan', ?, 'stacey', 'stacey', ?,
                    'passive_selfie', ?, 'passive', 'existing approved asset',
                    1.2, 'embedded_trending_required', 'EXPLORE', ?,
                    'CREATIVE_APPROVED', ?, ?)
            """,
            (item_id, index, account_id, source_id, index + 1, now, now),
        )
    cf.conn.commit()
    experiment = design_experiment(
        cf.conn,
        plan_id="observed_plan",
        changed_variable="observed_profile",
        variants=("control", profile),
        hypothesis="profile changes normalized reach",
        apply=True,
        assignment_method="cross_account_blocked_rotation.v1",
    )
    assert experiment["measurementPlan"] == OBSERVED_MEASUREMENT_PLAN
    return experiment["experimentId"], item_ids


def _insert_asset(
    cf,
    *,
    asset_id: str,
    source_id: str,
    path: Path,
    parent_asset_id: str | None,
    metadata: dict,
) -> None:
    now = "2026-07-29T00:00:00+00:00"
    campaign_id = cf.domains.campaign_by_slug("observed")["id"]
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, parent_asset_id, content_hash,
         output_path, campaign_path, filename, media_type, content_surface,
         caption_banks_json, caption_outcome_context_json, caption_generation_json,
         metadata_json, recipe, audit_status, review_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'video', 'reel', '[]', '{}', '{}', ?,
                'observed_test', 'passed', 'approved', ?, ?)
        """,
        (
            asset_id,
            campaign_id,
            source_id,
            parent_asset_id,
            _sha(path),
            str(path),
            str(path),
            path.name,
            json.dumps(metadata, sort_keys=True),
            now,
            now,
        ),
    )
    cf.conn.commit()


def _audio_receipt(original: Path, final: Path) -> dict:
    return {
        "originalVideo": {"path": str(original), "sha256": _sha(original)},
        "finalVideo": {
            "path": str(final),
            "sha256": _sha(final),
            "audioFingerprint": "3" * 64,
        },
        "selectedTrack": {
            "musicId": "track_1",
            "sourceTrackSha256": "1" * 64,
        },
        "selectedSegment": {
            "startSeconds": 0,
            "durationSeconds": 1.2,
            "processedSegmentSha256": "2" * 64,
        },
        "mixSettings": {"gainDb": -8.0},
        "ffmpeg": {"audioCodec": "aac"},
        "verification": {
            "status": "verified",
            "audioPresent": True,
            "audioStreamCount": 1,
            "audioCodec": "aac",
            "durationSeconds": 1.2,
        },
    }


def _fixture(tmp_path: Path, monkeypatch):
    contentforge_root = tmp_path / "contentforge"
    for relative in CONTENTFORGE_QC_POLICY_FILES:
        policy_file = contentforge_root / relative
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        policy_file.write_text("fixture-policy", encoding="utf-8")
    cf = make_factory(tmp_path)

    def audit_variation_batch(*, report_path: Path, **_kwargs):
        report = {
            "contractVersion": "campaign_factory_audit.v1.10",
            "runId": "fixture-contentforge-run",
            "overallVerdict": "fail",
            "verdicts": {"pdq": "fail", "sscd": "fail"},
            "readinessSummary": {
                "uploadReady": False,
                "blockingCodes": ["pdq_failed", "sscd_failed"],
            },
            "ocr": {"available": True, "results": []},
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        return report

    monkeypatch.setattr(
        "campaign_factory.adapters.contentforge.audit_variation_batch",
        audit_variation_batch,
    )
    source_folder = tmp_path / "sources"
    source_folder.mkdir()
    visual_control = _silent_video(source_folder / "control_visual.mp4", color="blue")
    cf.domains.asset_import.import_folder(
        source_folder, campaign_slug="observed", model_slug="stacey"
    )
    campaign_id = cf.domains.campaign_by_slug("observed")["id"]
    source = cf.domains.asset_import.assets_for_campaign(campaign_id)[0]
    derivative = render_observed_profile(
        source_path=visual_control,
        output_dir=tmp_path / "derivatives",
        parent_asset_id="control_asset",
        expected_source_sha256=_sha(visual_control),
        profile=TEST_PROFILE,
        target_accepted_count=1,
        caption_state="uncaptioned_verified",
        audio_state="none",
        passive_content=True,
        synchronized_content=False,
        visible_text=False,
        qc_callback=lambda *_: {
            "status": "passed",
            "blockingCodes": [],
            "sourceQc": True,
            "siblingQc": True,
            "ocrReadabilityQc": True,
            "focalSafetyQc": True,
            "watchabilityQc": True,
            "mediaIntegrityQc": True,
        },
    )
    treatment_visual = Path(derivative["accepted"][0]["output"]["path"])
    receipt_path = next(
        (tmp_path / "derivatives").glob("*.visual_derivative_receipt.json")
    )
    control_final = _mux_audio(visual_control, tmp_path / "control_final.mp4")
    treatment_final = _mux_audio(treatment_visual, tmp_path / "treatment_final.mp4")
    family = "control_asset"
    shared = {
        "sourceFamilyId": family,
        "visualQc": {"status": "passed"},
        "identityVerification": {"status": "passed"},
    }
    _insert_asset(
        cf,
        asset_id=family,
        source_id=source["id"],
        path=control_final,
        parent_asset_id=None,
        metadata={
            **shared,
            "perceptualFingerprint": "control-fingerprint",
            "perceptualClusterId": family,
            "audioBurned": True,
            "audioEmbeddingReceipt": _audio_receipt(visual_control, control_final),
        },
    )
    _insert_asset(
        cf,
        asset_id="treatment_asset",
        source_id=source["id"],
        path=treatment_final,
        parent_asset_id=family,
        metadata={
            **shared,
            "perceptualFingerprint": "treatment-fingerprint",
            "perceptualClusterId": family,
            "audioBurned": True,
            "observedProfile": TEST_PROFILE,
            "visualDerivativeReceipt": {
                "path": str(receipt_path),
                "sha256": _sha(receipt_path),
                "toolchainFingerprint": derivative["toolchain"]["fingerprint"],
                "sourceSha256": _sha(visual_control),
                "outputSha256": _sha(treatment_visual),
                "acceptedIndex": 1,
            },
            "audioEmbeddingReceipt": _audio_receipt(treatment_visual, treatment_final),
        },
    )
    qualification = cf.domains.variant_lineage.qualify_observed_renderer_control(
        rendered_asset_id=family
    )
    assert qualification["qcRegression"] is False
    accounts = tuple(
        cf.domains.models.upsert_account(
            handle,
            external_id=handle,
            account_group_id=f"isolated:{handle}",
        )["id"]
        for handle in ("account_a", "account_b")
    )
    experiment_id, items = _insert_plan(
        cf,
        source_id=source["id"],
        account_ids=accounts,
        profile=TEST_PROFILE,
    )
    slots = (
        {
            "slotId": "slot_a",
            "windowStart": "2026-07-30T12:00:00+00:00",
            "windowEnd": "2026-07-30T13:00:00+00:00",
        },
        {
            "slotId": "slot_b",
            "windowStart": "2026-07-30T12:00:00+00:00",
            "windowEnd": "2026-07-30T13:00:00+00:00",
        },
    )
    return cf, experiment_id, items, accounts, slots


def _caption_binding_fixture(tmp_path: Path):
    cf = make_factory(tmp_path)
    source_folder = tmp_path / "caption_sources"
    source_folder.mkdir()
    visual = source_folder / "visual.mp4"
    visual.write_bytes(b"observed visual")
    captioned = tmp_path / "captioned.mp4"
    captioned.write_bytes(b"captioned observed visual")
    cf.domains.asset_import.import_folder(
        source_folder, campaign_slug="observed", model_slug="stacey"
    )
    campaign_id = cf.domains.campaign_by_slug("observed")["id"]
    source = cf.domains.asset_import.assets_for_campaign(campaign_id)[0]
    _insert_asset(
        cf,
        asset_id="caption_treatment",
        source_id=source["id"],
        path=visual,
        parent_asset_id=None,
        metadata={
            "visualDerivativeReceipt": {"outputSha256": _sha(visual)},
            "publishability": {
                "status": "blocked",
                "blockingIssues": [
                    "exact_final_sha_approval_required",
                    "parent_audio_rebinding_required",
                ],
            },
        },
    )
    now = "2026-07-29T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO generation_output_blobs
        (id, content_sha256, byte_size, media_type, created_at)
        VALUES ('caption_visual_blob', ?, ?, 'video', ?)
        """,
        (_sha(visual), visual.stat().st_size, now),
    )
    cf.conn.execute(
        """
        INSERT INTO generation_attempts
        (id, campaign_id, source_asset_id, rendered_asset_id, output_blob_id,
         model_id, motion_task, input_json, worker_result_json,
         attempted_output_path, duplicate_disposition, created_at)
        VALUES ('caption_visual_attempt', ?, ?, 'caption_treatment',
                'caption_visual_blob', 'observed', 'visual_derivative', '{}', '{}',
                ?, 'unique_output', ?)
        """,
        (campaign_id, source["id"], str(visual), now),
    )
    cf.conn.execute(
        """
        UPDATE rendered_assets
        SET review_state = 'review_ready'
        WHERE id = 'caption_treatment'
        """
    )
    context = {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": "caption-hash",
        "caption_text": "be honest",
        "caption_banks": ["winner_bank"],
        "creator_mix": "Stacey",
    }
    caption_lineage = {
        "captionBurnedIn": True,
        "rawCaptionText": "be honest",
        "captionHash": "caption-hash",
        "selectedBanks": ["winner_bank"],
        "selectedMix": "Stacey",
        "overlaySemanticQc": {"passed": True},
        "captionTimingQc": {"passed": True},
        "captionPlacementDecision": {"status": "passed"},
        "captionPixelRenderEvidence": {
            "rendered": True,
            "outputPath": str(captioned),
        },
        "captionOutcomeContext": context,
    }
    generated_lineage = {
        "source": {"sourceVideoHash": _sha(visual)},
        "render": {"outputPath": str(captioned)},
        "contentFingerprint": _sha(captioned),
    }
    Path(str(captioned) + ".caption_lineage.json").write_text(
        json.dumps(caption_lineage), encoding="utf-8"
    )
    Path(str(captioned) + ".generated_asset_lineage.json").write_text(
        json.dumps(generated_lineage), encoding="utf-8"
    )
    cf.conn.commit()
    return cf, captioned


def test_observed_caption_binding_preserves_exact_lineage(tmp_path: Path):
    cf, captioned = _caption_binding_fixture(tmp_path)
    try:
        result = cf.domains.variant_lineage.bind_observed_caption(
            rendered_asset_id="caption_treatment",
            output_path=captioned,
        )
        row = cf.conn.execute(
            """
            SELECT content_hash, caption, review_state, metadata_json
            FROM rendered_assets WHERE id = 'caption_treatment'
            """
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        assert result["outputSha256"] == _sha(captioned) == row["content_hash"]
        assert row["caption"] == "be honest"
        assert row["review_state"] == "review_ready"
        assert metadata["burnedCaption"] is True
        invalidation = metadata["evidenceInvalidations"][-1]
        assert invalidation["previousSha256"] == result["replacesSha256"]
        assert invalidation["newSha256"] == result["outputSha256"]
        assert invalidation["mutationType"] == "caption_render"
        assert invalidation["mutationReceipt"] == metadata["captionRenderReceipt"]
        assert invalidation["changedAt"] == result["boundAt"]
        assert (
            cf.conn.execute(
                """
                SELECT relation FROM generation_lineage_edges
                WHERE rendered_asset_id = 'caption_treatment'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """
            ).fetchone()[0]
            == "caption_render"
        )
    finally:
        cf.close()


def test_observed_passive_derivative_does_not_inherit_generated_motion_gate(
    tmp_path: Path,
) -> None:
    cf, _captioned = _caption_binding_fixture(tmp_path)
    try:
        row = cf.conn.execute(
            "SELECT metadata_json FROM rendered_assets WHERE id = 'caption_treatment'"
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        metadata["observedProfile"] = TEST_PROFILE
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET frame_type = 'generated_motion',
                recipe = 'reel_factory_observed_profile',
                metadata_json = ?
            WHERE id = 'caption_treatment'
            """,
            (json.dumps(metadata),),
        )
        asset = cf.domains.publishability.rendered_asset("caption_treatment")

        assert cf.domains.publishability.motion_qc_requirements(asset) == {
            "motion": False,
            "audioAlignment": False,
            "lipSync": False,
        }
        assert asset_requires_creative_approval(asset) is False
    finally:
        cf.close()


def test_observed_caption_binding_rejects_source_sha_mismatch(tmp_path: Path):
    cf, captioned = _caption_binding_fixture(tmp_path)
    try:
        generated_path = Path(str(captioned) + ".generated_asset_lineage.json")
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        generated["source"]["sourceVideoHash"] = "0" * 64
        generated_path.write_text(json.dumps(generated), encoding="utf-8")
        with pytest.raises(ValueError, match="source SHA"):
            cf.domains.variant_lineage.bind_observed_caption(
                rendered_asset_id="caption_treatment",
                output_path=captioned,
            )
    finally:
        cf.close()


def test_observed_caption_binding_allows_verified_final_qc_retry(tmp_path: Path):
    cf, captioned = _caption_binding_fixture(tmp_path)
    try:
        first = cf.domains.variant_lineage.bind_observed_caption(
            rendered_asset_id="caption_treatment",
            output_path=captioned,
        )
        final = tmp_path / "failed_final.mp4"
        final.write_bytes(b"verified audio final")
        row = cf.conn.execute(
            "SELECT metadata_json FROM rendered_assets WHERE id = 'caption_treatment'"
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        metadata["audioEmbeddingReceipt"] = {
            "finalVideo": {"path": str(final), "sha256": _sha(final)}
        }
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET content_hash = ?, output_path = ?, campaign_path = ?, metadata_json = ?
            WHERE id = 'caption_treatment'
            """,
            (_sha(final), str(final), str(final), json.dumps(metadata)),
        )
        retry = tmp_path / "captioned_retry.mp4"
        retry.write_bytes(b"larger accepted caption")
        caption_lineage = json.loads(
            Path(str(captioned) + ".caption_lineage.json").read_text(encoding="utf-8")
        )
        caption_lineage["captionPixelRenderEvidence"]["outputPath"] = str(retry)
        generated_lineage = json.loads(
            Path(str(captioned) + ".generated_asset_lineage.json").read_text(
                encoding="utf-8"
            )
        )
        generated_lineage["render"]["outputPath"] = str(retry)
        generated_lineage["contentFingerprint"] = _sha(retry)
        Path(str(retry) + ".caption_lineage.json").write_text(
            json.dumps(caption_lineage), encoding="utf-8"
        )
        Path(str(retry) + ".generated_asset_lineage.json").write_text(
            json.dumps(generated_lineage), encoding="utf-8"
        )
        result = cf.domains.variant_lineage.bind_observed_caption(
            rendered_asset_id="caption_treatment",
            output_path=retry,
        )
        assert result["inputSha256"] == first["inputSha256"]
        assert result["replacesSha256"] == _sha(final)
        assert result["outputSha256"] == _sha(retry)
    finally:
        cf.close()


def test_atomic_pair_assignment_is_idempotent_immutable_and_retained(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        first = cf.domains.inventory_reservations.reserve_experiment_pair(
            experiment_id=experiment_id,
            parent_family_id="control_asset",
            pair_index=0,
            control_asset_id="control_asset",
            treatment_asset_id="treatment_asset",
            account_ids=accounts,
            eligible_slots=slots,
            plan_item_ids=items,
            treatment_profile=TEST_PROFILE,
        )
        assert first["idempotent"] is False
        assert {row["role"] for row in first["assignments"]} == {
            "control",
            "treatment",
        }
        assert all(
            row["cooldownException"]["thirdReuseAllowed"] is False
            for row in first["assignments"]
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM asset_inventory_reservations"
            ).fetchone()[0]
            == 2
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM creative_plan_metric_cohorts"
            ).fetchone()[0]
            == 6
        )
        reservations = cf.conn.execute(
            "SELECT expires_at FROM asset_inventory_reservations"
        ).fetchall()
        assert all(
            datetime.fromisoformat(row["expires_at"])
            >= datetime.fromisoformat(slots[0]["windowEnd"]) + timedelta(hours=72)
            for row in reservations
        )
        identities = [
            json.loads(row["generation_identity_json"])
            for row in cf.conn.execute(
                """
                SELECT generation_identity_json FROM creative_plan_items
                WHERE id IN (?, ?)
                """,
                items,
            ).fetchall()
        ]
        assert all(identity["generatedDuringPlan"] is False for identity in identities)
        assert {identity["renderedAssetId"] for identity in identities} == {
            "control_asset",
            "treatment_asset",
        }
        second = cf.domains.inventory_reservations.reserve_experiment_pair(
            experiment_id=experiment_id,
            parent_family_id="control_asset",
            pair_index=0,
            control_asset_id="control_asset",
            treatment_asset_id="treatment_asset",
            account_ids=accounts,
            eligible_slots=slots,
            plan_item_ids=items,
            treatment_profile=TEST_PROFILE,
        )
        assert second["idempotent"] is True
        event = cf.conn.execute(
            """
            SELECT id FROM creative_plan_item_events
            WHERE event_type = 'experiment_assignment'
            LIMIT 1
            """
        ).fetchone()
        with pytest.raises(Exception, match="immutable"):
            cf.conn.execute(
                "UPDATE creative_plan_item_events SET reason = 'changed' WHERE id = ?",
                (event["id"],),
            )
        cf.conn.rollback()
        with pytest.raises(Exception, match="immutable"):
            cf.conn.execute(
                """
                UPDATE creative_plan_items
                SET experiment_variant = 'changed'
                WHERE id = ?
                """,
                (items[0],),
            )
        cf.conn.rollback()
        metadata = json.loads(
            cf.conn.execute(
                "SELECT metadata_json FROM rendered_assets WHERE id = 'control_asset'"
            ).fetchone()[0]
        )
        assert metadata["experimentRetention"][0]["protectedThroughDecision"] is True
    finally:
        cf.close()


def test_observed_source_follows_parent_audio_receipt(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source_folder = tmp_path / "sources"
        source_folder.mkdir()
        visual = _silent_video(source_folder / "visual.mp4", color="blue")
        final = _mux_audio(visual, tmp_path / "final.mp4")
        child_final = _mux_audio(visual, tmp_path / "child_final.mp4", frequency=660)
        cf.domains.asset_import.import_folder(
            source_folder, campaign_slug="observed", model_slug="stacey"
        )
        campaign_id = cf.domains.campaign_by_slug("observed")["id"]
        source = cf.domains.asset_import.assets_for_campaign(campaign_id)[0]
        _insert_asset(
            cf,
            asset_id="audio_parent",
            source_id=source["id"],
            path=final,
            parent_asset_id=None,
            metadata={
                "audioEmbeddingReceipt": _audio_receipt(visual, final),
                "productionMotionRecipe": {"intent": "passive_selfie"},
            },
        )
        _insert_asset(
            cf,
            asset_id="approved_child",
            source_id=source["id"],
            path=child_final,
            parent_asset_id="audio_parent",
            metadata={},
        )

        child = cf.domains.variant_lineage.rendered_asset("approved_child")
        selected, digest, provenance = cf.domains.variant_lineage._observed_source(
            child, source_media_path=None
        )

        assert selected == visual.resolve()
        assert digest == _sha(visual)
        assert provenance == "audio_receipt_original_visual"
    finally:
        cf.close()


def test_eligible_existing_media_can_register_as_parent(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source_folder = tmp_path / "sources"
        source_folder.mkdir()
        visual = _silent_video(source_folder / "visual.mp4", color="blue")
        final = _mux_audio(visual, tmp_path / "final.mp4")
        cf.domains.asset_import.import_folder(
            source_folder, campaign_slug="observed", model_slug="stacey"
        )
        campaign_id = cf.domains.campaign_by_slug("observed")["id"]
        source = cf.domains.asset_import.assets_for_campaign(campaign_id)[0]
        _insert_asset(
            cf,
            asset_id="existing_control",
            source_id=source["id"],
            path=final,
            parent_asset_id=None,
            metadata={"audioEmbeddingReceipt": _audio_receipt(visual, final)},
        )
        now = "2026-07-29T00:00:00+00:00"
        receipt_paths = []
        for name in ("manifest", "audio", "qc"):
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            receipt_paths.append(path)
        final_sha = _sha(final)
        cf.conn.execute(
            """
            INSERT INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES ('blob_existing_control', ?, ?, 'video', ?)
            """,
            (final_sha, final.stat().st_size, now),
        )
        cf.conn.execute(
            """
            INSERT INTO generation_attempts
            (id, campaign_id, source_asset_id, rendered_asset_id, output_blob_id,
             model_id, motion_task, input_json, worker_result_json,
             attempted_output_path, duplicate_disposition, created_at)
            VALUES ('attempt_existing_control', ?, ?, 'existing_control',
                    'blob_existing_control', 'stacey', 'image_to_video', '{}', '{}',
                    ?, 'canonical_output', ?)
            """,
            (campaign_id, source["id"], str(final), now),
        )
        cf.conn.execute(
            """
            INSERT INTO existing_media_intakes
            (id, intake_identity, campaign_id, source_asset_id, rendered_asset_id,
             generation_attempt_id, final_sha256, manifest_path, manifest_sha256,
             audio_receipt_path, audio_receipt_sha256, qc_receipt_path,
             qc_receipt_sha256, eligibility_state, receipt_json, created_at, updated_at)
            VALUES ('intake_existing_control', 'identity_existing_control', ?, ?,
                    'existing_control', 'attempt_existing_control', ?, ?, ?, ?, ?, ?,
                    ?, 'ELIGIBLE', '{}', ?, ?)
            """,
            (
                campaign_id,
                source["id"],
                final_sha,
                str(receipt_paths[0]),
                _sha(receipt_paths[0]),
                str(receipt_paths[1]),
                _sha(receipt_paths[1]),
                str(receipt_paths[2]),
                _sha(receipt_paths[2]),
                now,
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO existing_media_asset_reviews
            (id, rendered_asset_id, final_sha256, creator, reviewer, verdict,
             contract_version, created_at)
            VALUES ('review_existing_control', 'existing_control', ?, 'stacey',
                    'operator', 'WOULD_POST', 'test.v1', ?)
            """,
            (final_sha, now),
        )
        cf.conn.execute(
            """
            INSERT INTO existing_media_caption_freezes
            (id, rendered_asset_id, final_sha256, caption, caption_hash,
             overlay_state, pattern_source, reviewer, contract_version,
             freeze_fingerprint, created_at)
            VALUES ('freeze_existing_control', 'existing_control', ?, 'caption',
                    'caption_hash', 'NONE_FROZEN', 'test', 'operator', 'test.v1',
                    'freeze_fingerprint', ?)
            """,
            (final_sha, now),
        )
        cf.conn.commit()

        parent = cf.domains.variant_lineage.register_parent_reel(
            "existing_control", operator="tester"
        )
        plan = cf.domains.variant_lineage.variant_plan(
            parent_asset_id="existing_control", count=1, profile=TEST_PROFILE
        )

        assert parent["parentAssetId"] == "existing_control"
        assert plan["canGenerate"] is True
        metadata = json.loads(
            cf.conn.execute(
                "SELECT metadata_json FROM concepts WHERE id = ?",
                (parent["conceptId"],),
            ).fetchone()[0]
        )
        assert metadata["controlAdmission"] == "eligible_existing_media"
    finally:
        cf.close()


def test_pair_reservation_rejects_tampered_renderer_qc_evidence(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        control = cf.domains.rendered_asset("control_asset")
        metadata = json.loads(control["metadata_json"])
        baseline = Path(
            metadata["rendererEquivalenceReceipt"]["qcEvidence"]["baselineReport"][
                "path"
            ]
        )
        baseline.write_text('{"tampered":true}', encoding="utf-8")

        with pytest.raises(ValueError, match="baselineReport evidence SHA mismatch"):
            cf.domains.inventory_reservations.reserve_experiment_pair(
                experiment_id=experiment_id,
                parent_family_id="control_asset",
                pair_index=0,
                control_asset_id="control_asset",
                treatment_asset_id="treatment_asset",
                account_ids=accounts,
                eligible_slots=slots,
                plan_item_ids=items,
                treatment_profile=TEST_PROFILE,
            )
    finally:
        cf.close()


def test_pair_reservation_rejects_missing_renderer_identity_output(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        control = cf.domains.rendered_asset("control_asset")
        metadata = json.loads(control["metadata_json"])
        identity_output = Path(
            metadata["rendererEquivalenceReceipt"]["identityOutputPath"]
        )
        identity_output.unlink()

        with pytest.raises(ValueError, match="renderer identity output is missing"):
            cf.domains.inventory_reservations.reserve_experiment_pair(
                experiment_id=experiment_id,
                parent_family_id="control_asset",
                pair_index=0,
                control_asset_id="control_asset",
                treatment_asset_id="treatment_asset",
                account_ids=accounts,
                eligible_slots=slots,
                plan_item_ids=items,
                treatment_profile=TEST_PROFILE,
            )
    finally:
        cf.close()


def test_pair_reservation_rejects_tampered_renderer_identity_output(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        control = cf.domains.rendered_asset("control_asset")
        metadata = json.loads(control["metadata_json"])
        identity_output = Path(
            metadata["rendererEquivalenceReceipt"]["identityOutputPath"]
        )
        identity_output.write_bytes(identity_output.read_bytes() + b"tampered")

        with pytest.raises(ValueError, match="renderer identity output SHA mismatch"):
            cf.domains.inventory_reservations.reserve_experiment_pair(
                experiment_id=experiment_id,
                parent_family_id="control_asset",
                pair_index=0,
                control_asset_id="control_asset",
                treatment_asset_id="treatment_asset",
                account_ids=accounts,
                eligible_slots=slots,
                plan_item_ids=items,
                treatment_profile=TEST_PROFILE,
            )
    finally:
        cf.close()


def test_pair_reservation_rolls_back_both_arms_when_second_fails(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        cf.conn.execute("DELETE FROM accounts WHERE id = ?", (accounts[1],))
        cf.conn.commit()
        with pytest.raises(ValueError, match="account not found"):
            cf.domains.inventory_reservations.reserve_experiment_pair(
                experiment_id=experiment_id,
                parent_family_id="control_asset",
                pair_index=0,
                control_asset_id="control_asset",
                treatment_asset_id="treatment_asset",
                account_ids=accounts,
                eligible_slots=slots,
                plan_item_ids=items,
                treatment_profile=TEST_PROFILE,
            )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM asset_inventory_reservations"
            ).fetchone()[0]
            == 0
        )
        assert (
            cf.conn.execute(
                """
                SELECT COUNT(*) FROM creative_plan_item_events
                WHERE event_type = 'experiment_assignment'
                """
            ).fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_observed_profiles_require_sequential_operator_decisions(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, _, _, _ = _fixture(tmp_path, monkeypatch)
    try:
        with pytest.raises(
            ValueError,
            match="previous observed-profile experiment is not decided",
        ):
            design_experiment(
                cf.conn,
                plan_id="observed_plan",
                changed_variable="observed_profile",
                variants=("control", "tilt_crop_dark@1"),
                hypothesis="profile changes normalized reach",
                apply=True,
                assignment_method="cross_account_blocked_rotation.v1",
            )
        cf.conn.execute(
            "UPDATE creative_plan_experiments SET status = 'DECIDED' WHERE id = ?",
            (experiment_id,),
        )
        cf.conn.commit()
        next_experiment = design_experiment(
            cf.conn,
            plan_id="observed_plan",
            changed_variable="observed_profile",
            variants=("control", "auto"),
            hypothesis="profile changes normalized reach",
            apply=True,
            assignment_method="cross_account_blocked_rotation.v1",
        )
        assert next_experiment["status"] == "PROPOSED"
        assert next_experiment["variants"] == ["control", "tilt_crop_dark@1"]
        assert next_experiment["profileDecision"]["mode"] == "next_unmeasured"
    finally:
        cf.close()


def test_pair_reservation_blocks_preexisting_third_audio_reuse(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        visual = _silent_video(tmp_path / "third_visual.mp4", color="red")
        final = _mux_audio(visual, tmp_path / "third_final.mp4")
        source = cf.conn.execute(
            "SELECT id FROM source_assets ORDER BY created_at LIMIT 1"
        ).fetchone()
        _insert_asset(
            cf,
            asset_id="third_asset",
            source_id=source["id"],
            path=final,
            parent_asset_id=None,
            metadata={
                "sourceFamilyId": "third_family",
                "perceptualFingerprint": "third_fingerprint",
                "perceptualClusterId": "third_cluster",
                "visualQc": {"status": "passed"},
                "identityVerification": {"status": "passed"},
                "audioEmbeddingReceipt": _audio_receipt(visual, final),
            },
        )
        third_account = cf.domains.models.upsert_account(
            "account_c",
            external_id="account_c",
            account_group_id="isolated:account_c",
        )["id"]
        cf.domains.inventory_reservations.reserve_inventory_asset(
            "third_asset", account_id=third_account
        )
        with pytest.raises(ValueError, match="audio reuse cooldown conflict"):
            cf.domains.inventory_reservations.reserve_experiment_pair(
                experiment_id=experiment_id,
                parent_family_id="control_asset",
                pair_index=0,
                control_asset_id="control_asset",
                treatment_asset_id="treatment_asset",
                account_ids=accounts,
                eligible_slots=slots,
                plan_item_ids=items,
                treatment_profile=TEST_PROFILE,
            )
        assert (
            cf.conn.execute(
                """
                SELECT COUNT(*) FROM creative_plan_item_events
                WHERE event_type = 'experiment_assignment'
                """
            ).fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_primary_fallback_requires_reach_missing_on_both_arms(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        pair = cf.domains.inventory_reservations.reserve_experiment_pair(
            experiment_id=experiment_id,
            parent_family_id="control_asset",
            pair_index=0,
            control_asset_id="control_asset",
            treatment_asset_id="treatment_asset",
            account_ids=accounts,
            eligible_slots=slots,
            plan_item_ids=items,
            treatment_profile=TEST_PROFILE,
        )
        _insert_metrics(cf, assignments=pair["assignments"], items=items)
        cf.conn.execute(
            "UPDATE performance_snapshots SET reach = NULL WHERE id LIKE 'experiment_%_72h'"
        )
        cf.conn.commit()
        views_report = observed_experiment_report(cf.conn, experiment_id=experiment_id)
        assert views_report["pairs"][0]["primaryMetric"] == "views"
        cf.conn.execute(
            "UPDATE performance_snapshots SET reach = 800 WHERE id = 'experiment_0_72h'"
        )
        cf.conn.commit()
        excluded = observed_experiment_report(cf.conn, experiment_id=experiment_id)
        assert excluded["includedPairCount"] == 0
        assert excluded["exclusions"][0]["reasons"] == [
            "same_primary_metric_unavailable"
        ]
    finally:
        cf.close()


def test_snapshot_exclusions_cover_lineage_fixtures_and_metric_revisions():
    receipt = {
        "assignedAssetId": "asset",
        "assignedAssetSha256": "a" * 64,
    }
    reasons = _snapshot_exclusion_reasons(
        {
            "metrics_eligible": 0,
            "history_source": "fallback",
            "lineage_v2_valid": 0,
            "rendered_asset_id": "other",
            "content_hash": "b" * 64,
            "published_at": None,
            "post_id": None,
            "raw_json": json.dumps({"fixture": True, "revision_status": "pending"}),
        },
        receipt,
    )
    assert {
        "metrics_ineligible",
        "fallback_history",
        "lineage_invalid",
        "assigned_asset_mismatch",
        "assigned_sha_mismatch",
        "publication_ambiguity",
        "fixture_or_fallback",
        "metric_revision_unreconciled",
    } <= set(reasons)


def _insert_metrics(
    cf,
    *,
    assignments: list[dict],
    items: tuple[str, str],
) -> None:
    publication = datetime(2026, 7, 30, 12, tzinfo=UTC)
    campaign_id = cf.domains.campaign_by_slug("observed")["id"]
    for index, (assignment, item) in enumerate(zip(assignments, items, strict=True)):
        account = assignment["accountId"]
        baseline_id = f"baseline_{index}"
        baseline_published = publication - timedelta(days=7)
        baseline_snapshot = baseline_published + timedelta(hours=72)
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, post_id, account_id, published_at, snapshot_at,
             views, likes, comments, shares, saves, impressions, reach,
             watch_time_seconds,
             metrics_eligible, history_source, lineage_v2_valid, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1000, 50, 10, 5, 5, 1100, 800, 5000,
                    1, 'metric_history', 1, ?, ?)
            """,
            (
                baseline_id,
                campaign_id,
                f"baseline_post_{index}",
                account,
                baseline_published.isoformat(),
                baseline_snapshot.isoformat(),
                json.dumps(
                    {
                        "engagement_rate": 0.0875,
                        "ig_reels_avg_watch_time": 5000,
                        "completion_rate": 0.40,
                        "retention_rate": 0.55,
                    }
                ),
                baseline_snapshot.isoformat(),
            ),
        )
        for bucket, hours in (("1h", 1), ("24h", 24), ("72h", 72)):
            snapshot_id = f"experiment_{index}_{bucket}"
            is_treatment = assignment["role"] == "treatment"
            reach = 960 if is_treatment else 800
            views = 1200 if is_treatment else 1000
            impressions = 1320 if is_treatment else 1100
            completion_rate = 0.48 if is_treatment else 0.40
            retention_rate = 0.66 if is_treatment else 0.55
            observed = publication + timedelta(hours=hours)
            cf.conn.execute(
                """
                INSERT INTO performance_snapshots
                (id, campaign_id, rendered_asset_id, content_hash, post_id,
                 account_id, published_at, snapshot_at, views, likes, comments,
                 shares, saves, impressions, reach, watch_time_seconds, metrics_eligible,
                 history_source, lineage_v2_valid, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 60, 12, 6, 6, ?, ?, 6000,
                        1, 'metric_history', 1, ?, ?)
                """,
                (
                    snapshot_id,
                    campaign_id,
                    assignment["assignedAssetId"],
                    assignment["assignedAssetSha256"],
                    f"experiment_post_{index}",
                    account,
                    publication.isoformat(),
                    observed.isoformat(),
                    views,
                    impressions,
                    reach,
                    json.dumps(
                        {
                            "engagement_rate": 0.0875,
                            "ig_reels_avg_watch_time": 5000,
                            "completion_rate": completion_rate,
                            "retention_rate": retention_rate,
                        }
                    ),
                    observed.isoformat(),
                ),
            )
            cf.conn.execute(
                """
                UPDATE creative_plan_metric_cohorts
                SET actual_observed_at = ?, post_age_seconds = ?,
                    observation_state = 'OBSERVED', snapshot_id = ?,
                    learning_eligible = 1, updated_at = ?
                WHERE plan_item_id = ? AND observation_bucket = ?
                """,
                (
                    observed.isoformat(),
                    hours * 3600,
                    snapshot_id,
                    observed.isoformat(),
                    item,
                    bucket,
                ),
            )
    cf.conn.commit()


def test_end_to_end_pair_metrics_report_is_deterministic_and_operator_only(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        pair = cf.domains.inventory_reservations.reserve_experiment_pair(
            experiment_id=experiment_id,
            parent_family_id="control_asset",
            pair_index=0,
            control_asset_id="control_asset",
            treatment_asset_id="treatment_asset",
            account_ids=accounts,
            eligible_slots=slots,
            plan_item_ids=items,
            treatment_profile=TEST_PROFILE,
        )
        _insert_metrics(cf, assignments=pair["assignments"], items=items)
        first = observed_experiment_report(cf.conn, experiment_id=experiment_id)
        second = observed_experiment_report(cf.conn, experiment_id=experiment_id)
        assert first["fingerprint"] == second["fingerprint"]
        assert first["includedPairCount"] == 1
        assert first["medianPairedLift"] == 0.2
        assert first["measurementPlan"] == OBSERVED_MEASUREMENT_PLAN
        assert first["pairs"][0]["secondaryLifts"]["impressions"] == 0.2
        assert first["pairs"][0]["secondaryLifts"]["completionRate"] == 0.2
        assert first["interpretation"]["status"] == "insufficient"
        assert first["automaticProductionExpansion"] is False
        active = select_observed_profile(
            cf.conn,
            creator="stacey",
            content_intent="passive_selfie",
            purpose="experiment",
        )
        assert active["selectedProfile"] == TEST_PROFILE
        assert active["mode"] == "continue_active"
        observed_experiment_report(
            cf.conn, experiment_id=experiment_id, record_interpretation=True
        )
        with pytest.raises(ValueError, match="operator-review-eligible"):
            record_observed_experiment_decision(
                cf.conn,
                experiment_id=experiment_id,
                operator="operator",
                decision="adopt",
                reason="not enough evidence",
            )
        decision = record_observed_experiment_decision(
            cf.conn,
            experiment_id=experiment_id,
            operator="operator",
            decision="continue_sequence",
            reason="collect the next profile only",
        )
        assert decision["productionUsageChanged"] is False
        next_profile = select_observed_profile(
            cf.conn,
            creator="stacey",
            content_intent="passive_selfie",
            purpose="experiment",
        )
        assert next_profile["selectedProfile"] == "tilt_crop_dark@1"
        assert next_profile["normalControlRequired"] is True
        production = select_observed_profile(
            cf.conn,
            creator="stacey",
            content_intent="passive_selfie",
            purpose="production",
        )
        assert production["selectedProfile"] is None
        assert production["mode"] == "normal_control"
    finally:
        cf.close()


def test_operator_adopted_profile_changes_auto_production_choice(
    tmp_path: Path, monkeypatch
):
    cf, experiment_id, items, accounts, slots = _fixture(tmp_path, monkeypatch)
    try:
        pair = cf.domains.inventory_reservations.reserve_experiment_pair(
            experiment_id=experiment_id,
            parent_family_id="control_asset",
            pair_index=0,
            control_asset_id="control_asset",
            treatment_asset_id="treatment_asset",
            account_ids=accounts,
            eligible_slots=slots,
            plan_item_ids=items,
            treatment_profile=TEST_PROFILE,
        )
        _insert_metrics(cf, assignments=pair["assignments"], items=items)
        observed_experiment_report(
            cf.conn, experiment_id=experiment_id, record_interpretation=True
        )
        stored = json.loads(
            cf.conn.execute(
                "SELECT interpretation_json FROM creative_plan_experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()[0]
        )
        stored["interpretation"]["status"] = "operator_review_eligible"
        cf.conn.execute(
            "UPDATE creative_plan_experiments SET interpretation_json = ? WHERE id = ?",
            (json.dumps(stored, sort_keys=True), experiment_id),
        )
        cf.conn.commit()

        decision = record_observed_experiment_decision(
            cf.conn,
            experiment_id=experiment_id,
            operator="operator",
            decision="adopt",
            reason="measured winner",
        )
        selected = select_observed_profile(
            cf.conn,
            creator="stacey",
            content_intent="passive_selfie",
            purpose="production",
        )
        assert decision["productionUsageChanged"] is True
        assert selected["selectedProfile"] == TEST_PROFILE
        assert selected["mode"] == "operator_adopted"
    finally:
        cf.close()


def test_sample_tiers_and_bootstrap_are_deterministic():
    values = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert _bootstrap_interval(values, seed="a" * 64) == _bootstrap_interval(
        values, seed="a" * 64
    )
    assert (
        _interpretation(
            pair_count=2,
            account_count=2,
            median_lift=0.5,
            positive_percentage=1,
            interval=(0.1, 0.6),
            guardrails_pass=True,
        )["status"]
        == "insufficient"
    )
    assert (
        _interpretation(
            pair_count=4,
            account_count=2,
            median_lift=0.5,
            positive_percentage=1,
            interval=(0.1, 0.6),
            guardrails_pass=True,
        )["status"]
        == "early_advisory"
    )
    assert (
        _interpretation(
            pair_count=7,
            account_count=2,
            median_lift=0.2,
            positive_percentage=0.71,
            interval=(-0.1, 0.4),
            guardrails_pass=True,
        )["status"]
        == "preliminary"
    )
    assert (
        _interpretation(
            pair_count=10,
            account_count=3,
            median_lift=0.1,
            positive_percentage=0.6,
            interval=(0.01, 0.2),
            guardrails_pass=True,
        )["status"]
        == "operator_review_eligible"
    )


def test_rendered_asset_sha_mutations_use_canonical_invalidation() -> None:
    package = Path(__file__).parents[1] / "campaign_factory"
    mutation = re.compile(
        r"UPDATE\s+rendered_assets\s+SET(?:(?!WHERE).){0,2000}"
        r"\bcontent_hash\s*=",
        re.IGNORECASE | re.DOTALL,
    )
    offenders = [
        source.name
        for source in package.glob("*.py")
        if source.name != "asset_evidence.py"
        and mutation.search(source.read_text(encoding="utf-8"))
    ]
    assert offenders == []
