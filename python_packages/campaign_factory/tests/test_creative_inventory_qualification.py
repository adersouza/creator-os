from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.creative_inventory_qualification import (
    REVIEW_MANIFEST_SCHEMA,
    build_operator_review_queue,
    product_mode_lineage,
    qualify_creative_inventory_asset,
)
from campaign_test_support import make_factory


def _rights() -> dict:
    return {
        "usageRightsStatus": "licensed",
        "commercialUseAllowed": True,
        "rightsSource": "operator_license",
        "territory": "US",
        "accountScope": "creator_accounts",
        "evidenceReceipt": {"id": "rights-1", "sha256": "e" * 64},
    }


def _audio(subject_sha: str) -> tuple[dict, dict]:
    intent = {
        "rights": _rights(),
        "fulfillment": {
            "status": "verified",
            "audio_present": True,
            "output_sha256": subject_sha,
        },
    }
    receipt = {
        "audioIntent": intent,
        "finalVideo": {"sha256": subject_sha},
        "verification": {"status": "verified", "audioPresent": True},
    }
    return intent, receipt


def _timed_caption(subject_sha: str) -> tuple[dict, dict]:
    placement = {
        "status": "passed",
        "selectedLane": "lower_center",
        "sampleCount": 6,
        "subjectSha256": subject_sha,
    }
    lineage = {
        "variantType": "timed",
        "approvalId": "approval-1",
        "approvalFileSha": "a" * 64,
        "approvalReviewer": "operator-1",
        "approvalDecidedAt": "2026-08-03T12:00:00Z",
        "contentMatch": {
            "family": "self_validation",
            "scene_tags": ["mirror"],
            "action_tags": ["pose"],
            "visual_intensity": "cute",
            "delivery": "timed_setup_payoff",
            "timing_anchor": None,
            "required_context_tags": [],
        },
    }
    return lineage, placement


def _static_caption(subject_sha: str) -> tuple[dict, dict]:
    caption_hash = "1" * 64
    lineage = {
        "schema": "reel_factory.caption_lineage.v1",
        "variantType": "static",
        "captionHash": caption_hash,
        "staticTextHash": caption_hash,
        "captionPayloadHash": "2" * 64,
        "rawCaptionText": "unique static caption",
        "selectedBanks": ["shared_girl_next_door"],
        "captionBankVersion": "caption_banks_v2",
        "captionBankSourceHash": "3" * 64,
    }
    placement = {
        "status": "passed",
        "selectedLane": "lower_center",
        "sampleCount": 6,
        "subjectSha256": subject_sha,
    }
    return lineage, placement


def _mode_evidence(
    tmp_path: Path, name: str = "mode-evidence.json"
) -> tuple[Path, str]:
    path = tmp_path / name
    path.write_text('{"productMode":"static_reel"}', encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_product_mode_lineage_requires_exact_explicit_evidence(tmp_path: Path) -> None:
    assert product_mode_lineage(product_mode=None)["status"] == "unclassified"
    missing = product_mode_lineage(product_mode="static_reel", evidence_sha256="a" * 64)
    assert missing["status"] == "unverified"
    assert missing["reason"] == "product_mode_evidence_source_missing"
    missing_artifact = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(tmp_path / "missing-evidence.json"),
        evidence_sha256="a" * 64,
    )
    assert missing_artifact["status"] == "unverified"
    assert missing_artifact["reason"] == "product_mode_evidence_artifact_unreadable"
    evidence, evidence_sha = _mode_evidence(tmp_path)
    lineage = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(evidence),
        evidence_sha256=evidence_sha,
    )
    assert lineage["status"] == "verified"
    assert lineage["productMode"] == "static_reel"
    assert lineage["verifiedEvidenceSha256"] == evidence_sha

    evidence.write_text('{"productMode":"calm_animation"}', encoding="utf-8")
    tampered = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(evidence),
        evidence_sha256=evidence_sha,
    )
    assert tampered["status"] == "unverified"
    assert tampered["reason"] == "product_mode_evidence_sha256_mismatch"

    symlink = tmp_path / "mode-evidence-link.json"
    symlink.symlink_to(evidence)
    linked = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(symlink),
        evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
    )
    assert linked["status"] == "unverified"
    assert linked["reason"] == "product_mode_evidence_artifact_unreadable"


def test_qualification_requires_exact_evidence() -> None:
    subject_sha = "b" * 64
    asset = {
        "id": "asset-1",
        "content_hash": subject_sha,
        "campaign_path": "/missing.mp4",
        "recipe": "finished_video_registered",
        "caption": "same caption",
        "metadata_json": json.dumps(
            {"inventoryQualificationScope": "synthetic_nonproduction_fixture"}
        ),
        "caption_outcome_context_json": json.dumps(
            {
                "burned_caption_text": "same caption",
                "captionPlacementDecision": {
                    "status": "passed",
                    "selectedLane": "top",
                    "sampleCount": 0,
                },
            }
        ),
        "caption_generation_json": "{}",
    }
    result = qualify_creative_inventory_asset(
        asset,
        audit={"subjectSha256": subject_sha, "overallVerdict": "pass"},
        final_integrity={"passed": True},
        caption_repeat_count=3,
    )
    assert result["applicable"] is True
    assert result["productionQualified"] is False
    assert set(result["blockingReasons"]) >= {
        "product_mode_lineage_unclassified",
        "embedded_audio_unverified",
        "audio_final_sha_unbound",
        "audio_rights_evidence_unverified",
        "caption_variant_lineage_unclassified",
        "caption_placement_approval_unverified",
        "caption_repeated_in_inventory",
    }


def test_qualification_passes_only_fully_bound_evidence(tmp_path: Path) -> None:
    subject_sha = "c" * 64
    intent, receipt = _audio(subject_sha)
    lineage, placement = _timed_caption(subject_sha)
    evidence, evidence_sha = _mode_evidence(tmp_path)
    mode = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(evidence),
        evidence_sha256=evidence_sha,
    )
    asset = {
        "id": "asset-1",
        "content_hash": subject_sha,
        "campaign_path": "/missing.mp4",
        "recipe": "finished_video_registered",
        "caption": "unique caption",
        "metadata_json": json.dumps(
            {
                "productModeLineage": mode,
                "audioIntent": intent,
                "audioEmbeddingReceipt": receipt,
            }
        ),
        "caption_outcome_context_json": json.dumps(
            {
                "burned_caption_text": "unique caption",
                "captionPlacementDecision": placement,
            }
        ),
        "caption_generation_json": json.dumps({"captionLineage": lineage}),
    }
    result = qualify_creative_inventory_asset(
        asset,
        audit={"subjectSha256": subject_sha, "overallVerdict": "pass"},
        final_integrity={"passed": True},
        caption_repeat_count=1,
    )
    assert result["productionQualified"] is True
    assert result["blockingReasons"] == []


def test_static_burned_caption_uses_static_lineage_not_timed_approval(
    tmp_path: Path,
) -> None:
    subject_sha = "4" * 64
    intent, receipt = _audio(subject_sha)
    lineage, placement = _static_caption(subject_sha)
    evidence, evidence_sha = _mode_evidence(tmp_path)
    mode = product_mode_lineage(
        product_mode="static_reel",
        evidence_source=str(evidence),
        evidence_sha256=evidence_sha,
    )
    asset = {
        "id": "asset-static",
        "content_hash": subject_sha,
        "campaign_path": "/missing.mp4",
        "recipe": "finished_video_registered",
        "caption": "unique static caption",
        "metadata_json": json.dumps(
            {
                "productModeLineage": mode,
                "audioIntent": intent,
                "audioEmbeddingReceipt": receipt,
            }
        ),
        "caption_outcome_context_json": json.dumps(
            {
                "burned_caption_text": "unique static caption",
                "captionPlacementDecision": placement,
            }
        ),
        "caption_generation_json": json.dumps({"captionLineage": lineage}),
    }
    result = qualify_creative_inventory_asset(
        asset,
        audit={"subjectSha256": subject_sha, "overallVerdict": "pass"},
        final_integrity={"passed": True},
        caption_repeat_count=1,
    )
    assert result["captionVariantType"] == "static"
    assert "timed_caption_semantic_approval_unverified" not in result["blockingReasons"]
    assert result["productionQualified"] is True
    assert result["blockingReasons"] == []

    lineage.pop("captionBankSourceHash")
    asset["caption_generation_json"] = json.dumps({"captionLineage": lineage})
    missing_static_approval = qualify_creative_inventory_asset(
        asset,
        audit={"subjectSha256": subject_sha, "overallVerdict": "pass"},
        final_integrity={"passed": True},
        caption_repeat_count=1,
    )
    assert (
        "static_caption_lineage_unverified"
        in missing_static_approval["blockingReasons"]
    )
    assert (
        "timed_caption_semantic_approval_unverified"
        not in missing_static_approval["blockingReasons"]
    )


def test_recreate_permission_false_is_a_hard_blocker() -> None:
    subject_sha = "f" * 64
    asset = {
        "id": "asset-recreate",
        "content_hash": subject_sha,
        "campaign_path": "/missing.mp4",
        "recipe": "higgsfield_seedance2_recreate_reel",
        "caption": "",
        "metadata_json": json.dumps(
            {
                "contentIntent": "recreate_reel",
                "recreationCharacterCompatibility": {"permissionGranted": False},
            }
        ),
        "caption_outcome_context_json": "{}",
        "caption_generation_json": "{}",
    }
    result = qualify_creative_inventory_asset(
        asset,
        audit={"subjectSha256": subject_sha, "overallVerdict": "pass"},
        final_integrity={"passed": True},
    )
    assert "recreate_permission_not_granted" in result["blockingReasons"]


def test_operator_queue_is_exact_sha_read_only_and_never_grants_authority(
    tmp_path: Path,
) -> None:
    media = tmp_path / "asset.mp4"
    media.write_bytes(b"review bytes")
    subject_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE source_assets (id TEXT PRIMARY KEY, source_prompt TEXT);
        CREATE TABLE rendered_assets (
          id TEXT PRIMARY KEY, source_asset_id TEXT, content_hash TEXT,
          campaign_path TEXT, output_path TEXT, caption TEXT, recipe TEXT,
          metadata_json TEXT, caption_outcome_context_json TEXT,
          caption_generation_json TEXT
        );
        CREATE TABLE audit_reports (
          rendered_asset_id TEXT, report_path TEXT, subject_sha256 TEXT,
          overall_verdict TEXT, created_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO source_assets VALUES ('source-1', '{}')")
    conn.execute(
        "INSERT INTO rendered_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "asset-1",
            "source-1",
            subject_sha,
            str(media),
            str(media),
            "caption",
            "finished_video_registered",
            "{}",
            "{}",
            "{}",
        ),
    )
    manifest = {
        "schema": REVIEW_MANIFEST_SCHEMA,
        "name": "test-queue",
        "publishAuthority": False,
        "entries": [
            {
                "day": 1,
                "renderedAssetId": "asset-1",
                "expectedSha256": subject_sha,
                "creator": "Larissa",
                "classification": "unclassified",
                "recommendation": "operator_review_candidate",
            }
        ],
    }
    before = conn.total_changes
    queue = build_operator_review_queue(conn, manifest)
    assert conn.total_changes == before
    assert queue["databaseMutation"] is False
    assert queue["approvalAuthority"] is False
    assert queue["publishAuthority"] is False
    assert queue["entries"][0]["queueStatus"] == "ready_for_operator_review"
    assert queue["entries"][0]["productionQualified"] is False
    assert queue["entries"][0]["reviewStateUnchanged"] is True


def test_checked_in_review_manifest_contains_only_the_seven_exact_assets() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "operations"
        / "creative_inventory_supervised_review_queue_2026-08-03.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["publishAuthority"] is False
    assert manifest["approvalAuthority"] is False
    assert [entry["day"] for entry in manifest["entries"]] == list(range(1, 8))
    assert {entry["renderedAssetId"] for entry in manifest["entries"]} == {
        "asset_a1d5edab7bee",
        "asset_existing_cf20127bd8d35604",
        "asset_finished_cdac166510e5",
        "asset_finished_6428e7a86b41",
        "asset_8e6348fd5fb0",
        "asset_finished_19e38a3a0e73",
        "asset_finished_0e1b297ad78c",
    }


def test_finished_video_import_persists_explicit_product_mode_lineage(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        video = tmp_path / "finished.mp4"
        video.write_bytes(b"fake mp4 bytes")
        evidence, evidence_sha = _mode_evidence(tmp_path)
        result = cf.domains.finished_video.register_finished_video(
            input_path=video,
            campaign_slug="larissa_import",
            model_slug="larissa",
            caption="caption text",
            product_mode="static_reel",
            product_mode_evidence_source=str(evidence),
            product_mode_evidence_sha256=evidence_sha,
        )
        row = cf.conn.execute(
            "SELECT metadata_json, caption_outcome_context_json FROM rendered_assets WHERE id = ?",
            (result["renderedAssetId"],),
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        context = json.loads(row["caption_outcome_context_json"])
        assert metadata["productModeLineage"]["status"] == "verified"
        assert context["productModeLineage"]["productMode"] == "static_reel"
        assert result["productModeLineage"] == metadata["productModeLineage"]
    finally:
        cf.close()


def test_synthetic_qualification_writer_rejects_normal_runtime(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="requires proof sandbox"):
            cf.domains.finished_video.add_synthetic_qualification_evidence(
                result={"renderedAssetId": "asset-1", "contentHash": "a" * 64},
                caption="fixture caption",
                caption_hash="b" * 64,
                evidence_sha="c" * 64,
            )
    finally:
        cf.close()
