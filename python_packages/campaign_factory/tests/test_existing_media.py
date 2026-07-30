from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.db import init_db
from campaign_factory.existing_media import (
    apply_intake,
    attach_existing_to_plan,
    inspect_intake,
    review_existing_asset,
    summarize_existing_reviews,
)
from campaign_factory.existing_media_caption import freeze_existing_caption

SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value), encoding="utf-8")
    return _sha(path)


def _probe(_: Path) -> dict[str, object]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "24/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {"duration": "5.0"},
    }


def _fixture(tmp_path: Path) -> tuple[sqlite3.Connection, Path, dict[str, Path]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    source = tmp_path / "source.png"
    visual = tmp_path / "visual.mp4"
    final = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    visual.write_bytes(b"visual")
    final.write_bytes(b"final")
    now = "2026-07-28T00:00:00Z"
    conn.execute(
        "INSERT INTO models (id,slug,name,created_at,updated_at) VALUES ('model','stacey','Stacey',?,?)",
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaigns (id,slug,name,root_path,created_at,updated_at)
        VALUES ('campaign','cohort','Cohort',?, ?, ?)
        """,
        (str(tmp_path), now, now),
    )
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state
        (model_id,status,status_reason,effective_at,changed_by,version,
         retention_state,updated_at)
        VALUES ('model','active','fixture',?,'test',1,'retain_audit',?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance
        (campaign_id,model_id,lifecycle_status,blocker_codes_json,status_reason,
         changed_by,effective_at,version,updated_at)
        VALUES ('campaign','model','production_ready','[]','fixture','test',?,1,?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO source_assets (
          id,campaign_id,model_id,content_hash,original_path,stored_path,
          filename,media_type,status,created_at,updated_at
        ) VALUES ('source','campaign','model',?,?,?,?, 'image','approved',?,?)
        """,
        (_sha(source), str(source), str(source), source.name, now, now),
    )
    conn.execute(
        """
        INSERT INTO rendered_assets (
          id,campaign_id,source_asset_id,content_hash,output_path,campaign_path,
          filename,recipe,created_at,updated_at
        ) VALUES ('raw','campaign','source',?,?,?,?, 'higgsfield_kling3_i2v',?,?)
        """,
        (_sha(visual), str(visual), str(tmp_path), visual.name, now, now),
    )
    conn.execute(
        """
        INSERT INTO generation_output_blobs
        (id,content_sha256,byte_size,media_type,created_at)
        VALUES ('blob',?,6,'video',?)
        """,
        (_sha(visual), now),
    )
    provider_receipt = tmp_path / "provider.json"
    provider_sha = _write_json(
        provider_receipt,
        {"status": "completed", "predictionId": "generation"},
    )
    worker = {
        "paidGenerationEvidence": {
            "generationId": "generation",
            "provider": "higgsfield",
            "providerModel": "kling3_0",
            "creditsConsumed": 15,
            "quote": {"amount": 8.75, "unit": "higgsfield_credits"},
            "costEventIds": ["cost"],
        }
    }
    conn.execute(
        """
        INSERT INTO generation_attempts (
          id,campaign_id,source_asset_id,rendered_asset_id,output_blob_id,
          model_id,motion_task,prompt_sha256,source_sha256,input_json,
          worker_result_json,attempted_output_path,duplicate_disposition,created_at
        ) VALUES ('attempt','campaign','source','raw','blob','higgsfield_kling3_i2v',
                  'image_to_video','prompt',?,'{}',?,?,'canonical_output',?)
        """,
        (_sha(source), json.dumps(worker), str(visual), now),
    )
    audio_receipt = tmp_path / "audio.json"
    audio_sha = _write_json(
        audio_receipt,
        {
            "finalVideo": {"path": str(final), "sha256": _sha(final)},
            "originalVideo": {"path": str(visual), "sha256": _sha(visual)},
            "audioIntent": {
                "fulfillment": {
                    "output_sha256": _sha(final),
                    "status": "verified",
                    "audio_present": True,
                    "proof_type": "embedded_output_audio_stream",
                }
            },
            "selection": {
                "platformSoundIds": [{"platform": "tiktok", "soundId": "music-1"}],
                "advisoryLabels": {"acousticFingerprint": "a" * 64},
            },
            "selectedTrack": {"acquiredAudioSha256": "b" * 64},
            "selectedSegment": {
                "start_offset_seconds": 1.0,
                "duration_seconds": 5.0,
                "processed_segment_sha256": "d" * 64,
                "decoded_audio_fingerprint": "c" * 64,
            },
            "verification": {"durationSeconds": 5.0},
        },
    )
    qc_receipt = tmp_path / "qc.json"
    qc_sha = _write_json(
        qc_receipt,
        {"status": "passed", "passed": True, "subjectSha256": _sha(final)},
    )
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "schema": "creator_os.existing_video_intake.v1",
            "creator": "stacey",
            "campaign": "cohort",
            "intendedAccount": "bennett_s33",
            "contentIntent": "passive_selfie",
            "identityProfile": SOUL_ID,
            "derivationKind": "embedded_audio_final",
            "source": {"id": "source", "sha256": _sha(source)},
            "visualInput": {"path": str(visual), "sha256": _sha(visual)},
            "finalMedia": {"path": str(final), "sha256": _sha(final)},
            "generation": {
                "attemptId": "attempt",
                "generationId": "generation",
                "model": "kling3_0",
                "recipe": "higgsfield_kling3_i2v",
                "prompt": "casual motion",
                "seed": 42,
                "receipt": {"path": str(provider_receipt), "sha256": provider_sha},
            },
            "audioReceipt": {"path": str(audio_receipt), "sha256": audio_sha},
            "technicalQcReceipt": {"path": str(qc_receipt), "sha256": qc_sha},
        },
    )
    conn.commit()
    return (
        conn,
        manifest,
        {
            "source": source,
            "visual": visual,
            "final": final,
            "audio": audio_receipt,
            "qc": qc_receipt,
        },
    )


def test_dry_run_has_no_writes_and_filename_is_not_identity(tmp_path: Path) -> None:
    conn, manifest, files = _fixture(tmp_path)
    before = conn.total_changes
    preview = inspect_intake(conn, manifest, probe=_probe)
    assert conn.total_changes == before
    assert preview["persistentWrites"] == 0
    assert preview["registrationAllowed"] is True
    assert preview["eligibility"] == "BLOCKED"
    assert preview["blockers"] == ["creative_review_missing"]
    renamed = files["final"].with_name("looks_like_creator_os.mp4")
    files["final"].rename(renamed)
    assert (
        "final_media_missing"
        in inspect_intake(conn, manifest, probe=_probe)["blockers"]
    )


def test_apply_registers_exact_bytes_without_provider_and_reconciles(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    preview = inspect_intake(conn, manifest, probe=_probe)
    first = apply_intake(conn, preview)
    second = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))
    assert first["providerCalls"] == 0
    assert first["mediaWrites"] == 0
    assert second["reconciled"] is True
    assert (
        conn.execute(
            "SELECT count(*) FROM rendered_assets WHERE content_hash = ?",
            (_sha(files["final"]),),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT count(*) FROM existing_media_intakes").fetchone()[0] == 1
    )
    assert files["final"].read_bytes() == b"final"


def test_reapply_refreshes_eligibility_after_exact_asset_review(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    preview = inspect_intake(conn, manifest, probe=_probe)
    asset_id = apply_intake(conn, preview)["renderedAssetId"]
    blocked = conn.execute(
        """
        SELECT eligibility_state, receipt_json
        FROM existing_media_intakes
        WHERE rendered_asset_id = ?
        """,
        (asset_id,),
    ).fetchone()
    assert blocked["eligibility_state"] == "BLOCKED"
    assert json.loads(blocked["receipt_json"])["blockers"] == [
        "creative_review_missing"
    ]

    review_existing_asset(
        conn,
        rendered_asset_id=asset_id,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={"identity": "PASS"},
        notes=None,
        apply=True,
    )
    refreshed = inspect_intake(conn, manifest, probe=_probe)
    assert refreshed["eligibility"] == "ELIGIBLE"
    apply_intake(conn, refreshed)
    apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))

    eligible = conn.execute(
        """
        SELECT eligibility_state, receipt_json
        FROM existing_media_intakes
        WHERE rendered_asset_id = ?
        """,
        (asset_id,),
    ).fetchone()
    assert eligible["eligibility_state"] == "ELIGIBLE"
    assert json.loads(eligible["receipt_json"])["blockers"] == []
    assert (
        conn.execute("SELECT count(*) FROM existing_media_intakes").fetchone()[0] == 1
    )


def test_caption_freeze_requires_eligible_exact_bytes_and_is_idempotent(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset_id = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    with pytest.raises(ValueError, match="QC is not eligible"):
        freeze_existing_caption(
            conn,
            rendered_asset_id=asset_id,
            final_sha256=_sha(files["final"]),
            caption="should i post more like this?",
            hashtags=[],
            overlay_state="NONE_FROZEN",
            pattern_source="caption_bank:comment_bait",
            reviewer="operator",
            apply=False,
        )
    review_existing_asset(
        conn,
        rendered_asset_id=asset_id,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={"identity": "PASS"},
        notes=None,
        apply=True,
    )
    apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))
    before = conn.total_changes
    dry = freeze_existing_caption(
        conn,
        rendered_asset_id=asset_id,
        final_sha256=_sha(files["final"]),
        caption="should i post more like this?",
        hashtags=[],
        overlay_state="NONE_FROZEN",
        pattern_source="caption_bank:comment_bait",
        reviewer="operator",
        apply=False,
    )
    assert dry["dryRun"] is True
    assert dry["persistentWrites"] == 0
    assert conn.total_changes == before
    first = freeze_existing_caption(
        conn,
        rendered_asset_id=asset_id,
        final_sha256=_sha(files["final"]),
        caption="should i post more like this?",
        hashtags=[],
        overlay_state="NONE_FROZEN",
        pattern_source="caption_bank:comment_bait",
        reviewer="operator",
        apply=True,
    )
    second = freeze_existing_caption(
        conn,
        rendered_asset_id=asset_id,
        final_sha256=_sha(files["final"]),
        caption="should i post more like this?",
        hashtags=[],
        overlay_state="NONE_FROZEN",
        pattern_source="caption_bank:comment_bait",
        reviewer="operator",
        apply=True,
    )
    assert first["freezeFingerprint"] == second["freezeFingerprint"]
    assert (
        conn.execute("SELECT count(*) FROM existing_media_caption_freezes").fetchone()[
            0
        ]
        == 1
    )
    row = conn.execute(
        "SELECT caption, caption_hash FROM rendered_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    assert row["caption"] == "should i post more like this?"
    assert row["caption_hash"] == first["captionHash"]
    with pytest.raises(ValueError, match="caption freeze conflict"):
        freeze_existing_caption(
            conn,
            rendered_asset_id=asset_id,
            final_sha256=_sha(files["final"]),
            caption="different caption",
            hashtags=[],
            overlay_state="NONE_FROZEN",
            pattern_source="caption_bank:comment_bait",
            reviewer="operator",
            apply=True,
        )


@pytest.mark.parametrize(
    ("mutate", "blocker"),
    [
        ("final", "final_sha_mismatch"),
        ("source", "source_sha_mismatch"),
        ("creator", "source_creator_mismatch"),
        ("generation", "generation_attempt_missing"),
        ("provider_receipt", "generation_receipt_missing"),
        ("audio_receipt", "audio_receipt_missing"),
        ("audio_binding", "audio_final_sha_mismatch"),
        ("qc", "technical_qc_receipt_missing"),
    ],
)
def test_fail_closed_lineage(tmp_path: Path, mutate: str, blocker: str) -> None:
    conn, manifest_path, files = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    if mutate == "final":
        files["final"].write_bytes(b"changed")
    elif mutate == "source":
        files["source"].write_bytes(b"changed")
    elif mutate == "creator":
        manifest["creator"] = "larissa"
    elif mutate == "generation":
        manifest["generation"]["attemptId"] = "missing"
    elif mutate == "provider_receipt":
        manifest["generation"]["receipt"]["path"] = str(tmp_path / "missing.json")
    elif mutate == "audio_receipt":
        manifest["audioReceipt"]["path"] = str(tmp_path / "missing.json")
    elif mutate == "audio_binding":
        receipt = json.loads(files["audio"].read_text())
        receipt["finalVideo"]["sha256"] = "0" * 64
        manifest["audioReceipt"]["sha256"] = _write_json(files["audio"], receipt)
    else:
        manifest.pop("technicalQcReceipt")
    _write_json(manifest_path, manifest)
    result = inspect_intake(conn, manifest_path, probe=_probe)
    assert blocker in result["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("generationId", "", "generation_id_missing"),
        ("generationId", "different", "generation_id_mismatch"),
        ("recipe", "", "generation_recipe_missing"),
        ("prompt", "", "generation_prompt_missing"),
        ("seed", None, "generation_seed_missing"),
    ],
)
def test_generation_contract_is_exact(
    tmp_path: Path, field: str, value: object, blocker: str
) -> None:
    conn, manifest_path, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["generation"][field] = value
    _write_json(manifest_path, manifest)
    assert blocker in inspect_intake(conn, manifest_path, probe=_probe)["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("generationId", "different", "generation_receipt_id_mismatch"),
        ("status", "failed", "generation_receipt_not_completed"),
        ("status", "refunded", "generation_receipt_not_completed"),
    ],
)
def test_provider_receipt_cannot_be_substituted(
    tmp_path: Path, field: str, value: str, blocker: str
) -> None:
    conn, manifest_path, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    receipt_path = Path(manifest["generation"]["receipt"]["path"])
    receipt = json.loads(receipt_path.read_text())
    if field == "generationId":
        receipt.pop("predictionId")
    receipt[field] = value
    manifest["generation"]["receipt"]["sha256"] = _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    result = inspect_intake(conn, manifest_path, probe=_probe)
    assert blocker in result["blockers"]
    assert result["registrationAllowed"] is False


@pytest.mark.parametrize(
    ("mutate", "blocker"),
    [
        ("music", "audio_music_id_missing"),
        ("track", "audio_track_sha_missing"),
        ("acoustic", "audio_acoustic_fingerprint_missing"),
        ("segment_bounds", "audio_segment_missing"),
        ("segment_sha", "audio_segment_sha_missing"),
        ("fulfillment", "audio_fulfillment_invalid"),
    ],
)
def test_audio_lineage_is_complete(tmp_path: Path, mutate: str, blocker: str) -> None:
    conn, manifest_path, files = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    receipt = json.loads(files["audio"].read_text())
    if mutate == "music":
        receipt["selection"]["platformSoundIds"] = []
    elif mutate == "track":
        receipt["selectedTrack"].pop("acquiredAudioSha256")
    elif mutate == "acoustic":
        receipt["selection"]["advisoryLabels"].pop("acousticFingerprint")
    elif mutate == "segment_bounds":
        receipt["selectedSegment"].pop("start_offset_seconds")
    elif mutate == "segment_sha":
        receipt["selectedSegment"].pop("processed_segment_sha256")
    else:
        receipt["audioIntent"]["fulfillment"]["status"] = "pending"
    manifest["audioReceipt"]["sha256"] = _write_json(files["audio"], receipt)
    _write_json(manifest_path, manifest)
    assert blocker in inspect_intake(conn, manifest_path, probe=_probe)["blockers"]


def test_unapproved_source_can_register_evidence_but_not_attach(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    conn.execute("UPDATE source_assets SET status='imported' WHERE id='source'")
    preview = inspect_intake(conn, manifest, probe=_probe)
    assert preview["registrationAllowed"] is True
    assert "blocked_unapproved_source" in preview["blockers"]
    asset = apply_intake(conn, preview)["renderedAssetId"]
    review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={},
        notes=None,
        apply=True,
    )
    _plan(conn)
    attached = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert "blocked_unapproved_source" in attached["blockers"]


def test_review_binds_exact_sha_and_does_not_transfer(tmp_path: Path) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    dry = review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={"identity": "PASS"},
        notes=None,
        apply=False,
    )
    assert dry["dryRun"] is True
    assert (
        conn.execute("SELECT count(*) FROM existing_media_asset_reviews").fetchone()[0]
        == 0
    )
    applied = review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={"identity": "PASS"},
        notes="good",
        apply=True,
    )
    assert applied["dryRun"] is False
    with pytest.raises(ValueError, match="exact asset bytes"):
        review_existing_asset(
            conn,
            rendered_asset_id=asset,
            final_sha256="0" * 64,
            reviewer="operator",
            verdict="WOULD_POST",
            results={},
            notes=None,
            apply=False,
        )


def test_review_reasons_are_exact_sha_bound_and_blanks_stay_unknown(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    reviewed = review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="REJECT",
        results={},
        rejection_reasons=["MOTION_UNNATURAL"],
        notes=None,
        apply=True,
    )
    assert reviewed["sourceSha256"] == _sha(files["source"])
    assert reviewed["rejectionReasons"] == ["MOTION_UNNATURAL"]
    assert reviewed["promptCardFingerprint"] is None
    row = conn.execute(
        "SELECT * FROM existing_media_asset_reviews WHERE id = ?",
        (reviewed["reviewId"],),
    ).fetchone()
    assert json.loads(row["rejection_reasons_json"]) == ["MOTION_UNNATURAL"]
    summary = summarize_existing_reviews(conn)
    assert summary["explicitReasonCount"] == 1
    assert summary["groups"][0]["rejectionReason"] == "MOTION_UNNATURAL"


def test_historical_review_rows_remain_readable_and_not_counted_as_reasons(
    tmp_path: Path,
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    conn.execute(
        """
        INSERT INTO existing_media_asset_reviews (
          id, rendered_asset_id, final_sha256, creator, reviewer, verdict,
          results_json, notes, contract_version, created_at
        ) VALUES ('old', ?, ?, 'stacey', 'operator', 'WOULD_POST',
                  '{}', NULL, 'existing-video-intake.v1', '2026-01-01T00:00:00Z')
        """,
        (asset, _sha(files["final"])),
    )
    summary = summarize_existing_reviews(conn)
    assert summary["reviewCount"] == 1
    assert summary["explicitReasonCount"] == 0
    assert summary["groups"] == []


def test_review_summary_reads_pre_upgrade_table_without_migration() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE existing_media_asset_reviews (
          id TEXT PRIMARY KEY,
          rendered_asset_id TEXT NOT NULL,
          final_sha256 TEXT NOT NULL,
          creator TEXT NOT NULL,
          reviewer TEXT NOT NULL,
          verdict TEXT NOT NULL,
          results_json TEXT NOT NULL DEFAULT '{}',
          notes TEXT,
          contract_version TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        INSERT INTO existing_media_asset_reviews VALUES (
          'old', 'asset', 'abc', 'stacey', 'operator', 'WOULD_POST',
          '{}', NULL, 'existing-video-intake.v1', '2026-01-01T00:00:00Z'
        );
        """
    )
    summary = summarize_existing_reviews(conn)
    assert summary["reviewCount"] == 1
    assert summary["explicitReasonCount"] == 0


def _plan(conn: sqlite3.Connection, *, source_id: str = "source") -> None:
    now = "2026-07-28T00:00:00Z"
    conn.execute(
        """
        INSERT INTO creative_plans (
          id,name,target_account,status,created_at,updated_at
        ) VALUES ('plan-root','plan-root','bennett_s33','approved',?,?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO creative_plan_versions (
          id,creative_plan_id,version,creator,identity_profile,horizon_start,
          horizon_end,timezone,objective,requested_output_count,autonomy_mode,
          status,input_fingerprint,created_at,updated_at
        ) VALUES ('plan','plan-root',1,'stacey',?,'2026-07-28','2026-08-03',
                  'America/New_York','GROWTH',1,'SUPERVISED','APPROVED','fp',?,?)
        """,
        (SOUL_ID, now, now),
    )
    conn.execute(
        """
        INSERT INTO creative_plan_items (
          id,plan_version_id,item_index,creator,identity_profile,target_account,
          content_intent,source_asset_id,pattern_family,prompt_text,
          desired_duration_seconds,audio_policy,exploration_class,priority,
          execution_state,created_at,updated_at
        ) VALUES ('item','plan',0,'stacey',?,'bennett_s33','passive_selfie',?,
                  'passive','prompt',5,'embedded_trending_required','EXPLOIT',1,
                  'GENERATION_READY',?,?)
        """,
        (SOUL_ID, source_id, now, now),
    )
    conn.commit()


def test_plan_attachment_gates_then_is_idempotent(tmp_path: Path) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    _plan(conn)
    blocked = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert "would_post_review_missing" in blocked["blockers"]
    review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={},
        notes=None,
        apply=True,
    )
    dry = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert dry["blockers"] == []
    assert (
        json.loads(
            conn.execute(
                "SELECT generation_identity_json FROM creative_plan_items WHERE id='item'"
            ).fetchone()[0]
        )
        == {}
    )
    applied = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=True,
    )
    assert applied["attachmentCost"]["credits"] == 0
    again = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=True,
    )
    assert again["idempotent"] is True
    assert (
        conn.execute(
            "SELECT count(*) FROM creative_plan_item_events WHERE plan_item_id='item'"
        ).fetchone()[0]
        == 2
    )
    transitions = conn.execute(
        """
        SELECT from_state,to_state FROM creative_plan_item_events
        WHERE plan_item_id='item' ORDER BY rowid
        """
    ).fetchall()
    assert [tuple(row) for row in transitions] == [
        ("GENERATION_READY", "REVIEW_READY"),
        ("REVIEW_READY", "CREATIVE_APPROVED"),
    ]
    generation = json.loads(
        conn.execute(
            "SELECT generation_identity_json FROM creative_plan_items WHERE id='item'"
        ).fetchone()[0]
    )
    decision = json.loads(
        conn.execute(
            "SELECT decision_receipt_json FROM creative_plan_items WHERE id='item'"
        ).fetchone()[0]
    )
    assert generation["generatedDuringPlan"] is False
    assert generation["attachmentCost"] == {"credits": 0, "providerCalls": 0}
    assert generation["originalGeneration"]["originalCost"]["creditsConsumed"] == 15
    assert decision == {
        "applied": False,
        "consulted": True,
        "eligible": False,
        "fallbackReason": "insufficient real eligible outcomes",
        "finalChoiceChanged": False,
    }


def test_conflicting_plan_asset_blocks_replacement(tmp_path: Path) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={},
        notes=None,
        apply=True,
    )
    _plan(conn)
    conn.execute(
        """
        UPDATE creative_plan_items
        SET generation_identity_json='{"renderedAssetId":"another"}'
        WHERE id='item'
        """
    )
    result = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert "plan_item_asset_conflict" in result["blockers"]


def test_published_asset_cannot_enter_unpublished_plan(tmp_path: Path) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={},
        notes=None,
        apply=True,
    )
    _plan(conn)
    now = "2026-07-28T00:00:00Z"
    conn.execute(
        """
        INSERT INTO proof_runs (
          id,campaign_id,rendered_asset_id,threadsdash_post_id,status,current_state,
          started_at,created_at,updated_at
        ) VALUES ('proof','campaign',?,'instagram-1','complete','published',?,?,?)
        """,
        (asset, now, now, now),
    )
    result = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert "asset_already_published" in result["blockers"]


def test_missing_qc_registers_evidence_but_never_export_ready(tmp_path: Path) -> None:
    conn, manifest_path, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("technicalQcReceipt")
    _write_json(manifest_path, manifest)
    preview = inspect_intake(conn, manifest_path, probe=_probe)
    assert preview["registrationAllowed"] is True
    assert "technical_qc_receipt_missing" in preview["blockers"]
    receipt = apply_intake(conn, preview)
    asset = conn.execute(
        "SELECT audit_status,review_state FROM rendered_assets WHERE id=?",
        (receipt["renderedAssetId"],),
    ).fetchone()
    assert dict(asset) == {
        "audit_status": "needs_review",
        "review_state": "review_ready",
    }


@pytest.mark.parametrize(
    ("column", "value", "blocker"),
    [
        ("creator", "larissa", "creator_mismatch"),
        ("target_account", "other", "account_mismatch"),
        ("content_intent", "outfit", "content_intent_mismatch"),
    ],
)
def test_wrong_plan_scope_blocks(
    tmp_path: Path, column: str, value: str, blocker: str
) -> None:
    conn, manifest, files = _fixture(tmp_path)
    asset = apply_intake(conn, inspect_intake(conn, manifest, probe=_probe))[
        "renderedAssetId"
    ]
    review_existing_asset(
        conn,
        rendered_asset_id=asset,
        final_sha256=_sha(files["final"]),
        reviewer="operator",
        verdict="WOULD_POST",
        results={},
        notes=None,
        apply=True,
    )
    _plan(conn)
    conn.execute(
        f"UPDATE creative_plan_items SET {column} = ? WHERE id='item'", (value,)
    )
    result = attach_existing_to_plan(
        conn,
        plan_id="plan",
        plan_item_id="item",
        rendered_asset_id=asset,
        apply=False,
    )
    assert blocker in result["blockers"]
