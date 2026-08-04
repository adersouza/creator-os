from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
import reference_factory.url_intake as intake
from reference_factory.cli import main as reference_factory_cli
from reference_factory.db import connect
from reference_factory.ocr import promote_url_overlay_candidate
from reference_factory.review import label_reference, reference_query
from reference_factory.url_intake import (
    analyze_url_reference,
    repair_url_intake_video_probes,
    resolve_url_intake_reference,
    select_anchor,
)


def _video(path: Path) -> None:
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=360x640:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def test_anchor_hard_block_and_earliest_tie_break() -> None:
    def candidate(stamp: float, blockers: list[str] | None = None):
        return {
            "timeSec": stamp,
            "hardBlockers": blockers or [],
            "measurements": {
                "sharpness": 1,
                "faceVisibility": 1,
                "bodyExtent": 1,
                "singlePersonLowOcclusion": 1,
                "overlayClear": 1,
                "poseRepresentativeness": 1,
            },
        }

    blocked = candidate(0.0, ["black_frame"])
    early = candidate(0.5)
    later = candidate(0.8)
    assert select_anchor([blocked, later, early])["timeSec"] == 0.5
    assert blocked["score"] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_dry_run_is_write_free_and_apply_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    data_root = tmp_path / "reference-data"
    db_path = tmp_path / "reference.sqlite"
    metadata = {
        "platform": "instagram",
        "nativeMediaId": "reel123",
        "originalUrl": "https://www.instagram.com/reel/reel123/?tracking=x",
        "canonicalUrl": "https://www.instagram.com/reel/reel123/",
        "extractor": "Instagram",
        "extractorVersion": "test",
        "declaredNonTalking": True,
        "operatorClassification": "simple_pose_motion",
        "description": "Close selfie with a curiosity-first reveal.",
        "operatorWarnings": ["Keep the timing payoff intact."],
    }
    monkeypatch.setattr(
        intake,
        "_apple_vision",
        lambda _path: {
            "available": True,
            "provider": "apple_vision",
            "requests": [],
            "frames": [
                {
                    "identifier": index,
                    "available": True,
                    "faces": [{"width": 0.2, "height": 0.2, "confidence": 1.0}],
                    "bodies": [],
                    "handCount": 0,
                    "text": [],
                }
                for index in range(7)
            ],
        },
    )
    monkeypatch.setattr(
        intake,
        "_mediapipe",
        lambda _path: {
            "available": False,
            "provenance": {"available": False, "reason": "test_missing"},
            "frames": [],
        },
    )
    monkeypatch.setattr(
        intake,
        "run_selected_ocr",
        lambda _path, requested_engine: {
            "available": True,
            "engine": requested_engine,
            "boxes": [
                {
                    "ocrText": "Original hook text",
                    "confidence": 0.98,
                    "box": {"x": 10, "y": 20, "w": 100, "h": 30},
                }
            ],
        },
    )
    dry = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=False
    )
    assert dry["apply"] is False
    assert not data_root.exists()
    assert not db_path.exists()
    assert dry["frameDerivatives"]["literal_first"]["path"] is None
    assert dry["frameDerivatives"]["last_clean"]["path"] is None
    assert dry["overlayTextInventory"]["status"] == "observed"
    assert {row["text"] for row in dry["overlayTextInventory"]["observations"]} == {
        "Original hook text"
    }
    assert (
        dry["overlayTextInventory"]["generationPromptPolicy"]
        == "retain_as_evidence_exclude_from_prompt"
    )
    first = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=True
    )
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    existing_dry = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=False
    )
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    second = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=True
    )
    assert first["duplicateResult"] == "created"
    assert existing_dry["duplicateResult"] == "reused_platform_media_id"
    assert existing_dry["apply"] is False
    assert existing_dry["media"]["durationSeconds"] == pytest.approx(1.0)
    assert existing_dry["media"]["width"] == 360
    assert existing_dry["media"]["height"] == 640
    assert existing_dry["sourceSpeakingClassification"] == "DECLARED_NON_TALKING"
    assert existing_dry["operatorClassification"] == "simple_pose_motion"
    assert existing_dry["overlayTextInventory"] == first["overlayTextInventory"]
    assert len(existing_dry["anchorCandidates"]) == len(first["anchorCandidates"])
    assert (
        existing_dry["frameDerivatives"]["best_anchor"]["sha256"]
        == first["frameDerivatives"]["best_anchor"]["sha256"]
    )
    assert before == after
    assert second["duplicateResult"] == "reused_platform_media_id"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM frame_samples").fetchone()[0] == 8
        assert (
            conn.execute("SELECT COUNT(*) FROM reference_anchor_receipts").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT valid FROM video_probes").fetchone()[0] == 1

    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM video_probes")
        conn.commit()
        dry_repair = repair_url_intake_video_probes(conn)
        assert dry_repair["candidates"] == 1
        assert dry_repair["wouldRepair"] == 1
        assert conn.execute("SELECT COUNT(*) FROM video_probes").fetchone()[0] == 0
        applied_repair = repair_url_intake_video_probes(conn, apply=True)
        assert applied_repair["repaired"] == 1
        assert conn.execute("SELECT valid FROM video_probes").fetchone()[0] == 1
        repeated_repair = repair_url_intake_video_probes(conn, apply=True)
        assert repeated_repair["candidates"] == 0
        resolved = resolve_url_intake_reference(conn, first["referenceId"])
        assert resolved["source"]["sha256"] == first["source"]["sha256"]
        assert resolved["source"]["exactBytesVerified"] is True
        assert resolved["intakeMetadata"]["description"] == metadata["description"]
        assert (
            resolved["anchorReceipt"]["selectedFrame"]["sha256"]
            == (first["selectedAnchor"]["sha256"])
        )
        assert len(resolved["frameSamples"]) == 8

        with pytest.raises(PermissionError, match="semantic approval"):
            promote_url_overlay_candidate(
                conn,
                reference_id=first["referenceId"],
                observation_index=0,
                operator="operator@example.com",
                human_semantic_approval=False,
                human_timing_approval=True,
            )
        promoted = promote_url_overlay_candidate(
            conn,
            reference_id=first["referenceId"],
            observation_index=0,
            operator="operator@example.com",
            human_semantic_approval=True,
            human_timing_approval=True,
            notes="Approved as a reusable hook candidate.",
        )
        promoted_again = promote_url_overlay_candidate(
            conn,
            reference_id=first["referenceId"],
            observation_index=0,
            operator="operator@example.com",
            human_semantic_approval=True,
            human_timing_approval=True,
            notes="Approved as a reusable hook candidate.",
        )
        assert promoted["captionHash"] == promoted_again["captionHash"]
        assert promoted["publishOrRender"] is False
        assert conn.execute("SELECT COUNT(*) FROM ocr_results").fetchone()[0] == 1
        placement = json.loads(
            conn.execute("SELECT placement_json FROM caption_patterns").fetchone()[0]
        )
        assert placement["candidateReview"]["humanSemanticApproval"] is True
        assert placement["candidateReview"]["humanTimingApproval"] is True
        assert placement["candidateReview"]["timingScope"] == (
            "source_observation_only"
        )
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM video_probes")
        conn.commit()
    finally:
        conn.close()
    auto_repaired = analyze_url_reference(
        source, metadata=metadata, data_root=data_root, db_path=db_path, apply=True
    )
    assert auto_repaired["probeRepair"]["repaired"] == 1

    with sqlite3.connect(db_path) as readonly_check:
        cli_before = "\n".join(readonly_check.iterdump())
    assert (
        reference_factory_cli(
            [
                "--db",
                str(db_path),
                "--data-root",
                str(data_root),
                "resolve-url-intake",
                "--reference-id",
                first["referenceId"],
            ]
        )
        == 0
    )
    with sqlite3.connect(db_path) as readonly_check:
        cli_after = "\n".join(readonly_check.iterdump())
    assert cli_after == cli_before
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["referenceId"] == first["referenceId"]
    assert cli_payload["source"]["sha256"] == first["source"]["sha256"]
    assert cli_payload["videoProbe"]["valid"] == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_apply_upgrades_legacy_row_that_owns_canonical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "incoming.mp4"
    _video(source)
    data_root = tmp_path / "reference-data"
    canonical = data_root / "url_intake" / "instagram" / "legacy123" / "reference.mp4"
    canonical.parent.mkdir(parents=True)
    shutil.copy2(source, canonical)
    db_path = tmp_path / "reference.sqlite"
    conn = connect(db_path)
    try:
        now = "2026-08-03T00:00:00Z"
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id,path,file_name,extension,kind,size_bytes,mtime,path_hash,
              content_hash,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "ref_legacy",
                str(canonical),
                canonical.name,
                ".mp4",
                "video",
                canonical.stat().st_size,
                now,
                hashlib.sha256(str(canonical).encode()).hexdigest(),
                hashlib.sha256(canonical.read_bytes()).hexdigest(),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        intake,
        "_enrich_visual_evidence",
        lambda _candidates, _frames: {
            "appleVision": {"available": False},
            "mediaPipe": {"available": False},
            "overlayTextInventory": {"status": "observed", "observations": []},
        },
    )

    result = analyze_url_reference(
        source,
        metadata={
            "platform": "instagram",
            "nativeMediaId": "legacy123",
            "canonicalUrl": "https://www.instagram.com/reel/legacy123/",
            "description": "Preserve the existing analysis identity.",
        },
        data_root=data_root,
        db_path=db_path,
        apply=True,
    )

    assert result["referenceId"] == "ref_legacy"
    assert result["duplicateResult"] == "upgraded_legacy_path"
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 1
        resolved = resolve_url_intake_reference(conn, "ref_legacy")
        assert resolved["source"]["nativeMediaId"] == "legacy123"
        assert resolved["source"]["exactBytesVerified"] is True
        assert (
            resolved["intakeMetadata"]["description"]
            == "Preserve the existing analysis identity."
        )
    finally:
        conn.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_anchor_failure_preserves_structural_source_and_blocks_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    data_root = tmp_path / "reference-data"
    db_path = tmp_path / "reference.sqlite"
    metadata = {
        "platform": "instagram",
        "nativeMediaId": "no-compatible-anchor",
        "description": "Useful cut structure even though no anchor is safe.",
    }
    monkeypatch.setattr(
        intake,
        "_apple_vision",
        lambda _path: {
            "available": True,
            "provider": "apple_vision",
            "requests": [],
            "frames": [
                {
                    "identifier": index,
                    "available": True,
                    "faces": [],
                    "bodies": [],
                    "handCount": 0,
                    "text": [],
                }
                for index in range(7)
            ],
        },
    )
    monkeypatch.setattr(
        intake,
        "_mediapipe",
        lambda _path: {
            "available": False,
            "provenance": {"available": False, "reason": "test_missing"},
            "frames": [],
        },
    )
    monkeypatch.setattr(
        intake,
        "run_selected_ocr",
        lambda _path, requested_engine: {
            "available": True,
            "engine": requested_engine,
            "boxes": [],
        },
    )

    result = analyze_url_reference(
        source,
        metadata=metadata,
        data_root=data_root,
        db_path=db_path,
        apply=True,
    )

    assert result["ok"] is True
    assert result["selectedAnchor"] is None
    assert result["anchorSelection"]["status"] == "unavailable"
    assert result["anchorSelection"]["reviewEligibility"] == "blocked"
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0] == 1
        assert conn.execute("SELECT valid FROM video_probes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM frame_samples").fetchone()[0] == 3
        assert (
            conn.execute("SELECT COUNT(*) FROM reference_anchor_receipts").fetchone()[0]
            == 0
        )
        item = reference_query(conn)["items"][0]
        assert item["reviewEligible"] is False
        assert item["anchorSelection"]["status"] == "unavailable"
        with pytest.raises(ValueError, match="review-blocked"):
            label_reference(conn, result["referenceId"], "gold")
        ignored = label_reference(conn, result["referenceId"], "ignore")
        assert ignored["label"] == "ignore"
    finally:
        conn.close()
