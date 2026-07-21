import json
from pathlib import Path

from reel_factory.review_batch_guard import promote_review_batch, validate_review_batch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _batch(
    tmp_path: Path,
    *,
    font: str = "Instagram Sans Condensed Bold",
    placement: str = "focal-safe",
    placement_decision: dict | None = None,
    selected_band: str = "top",
    contentforge: bool = True,
    contentforge_profile: str = "campaign_factory_v1",
    row_count: int = 1,
    contentforge_variants: int | None = None,
    contentforge_variant_files: list[str] | None = None,
    readiness_records: list[dict] | None = None,
) -> Path:
    root = tmp_path
    clip_dir = root / "02_processed" / "clip_001"
    clip_dir.mkdir(parents=True)
    _write_json(
        root / "00_source_videos" / "clip_001.generated_asset_lineage.json",
        {"schema": "lineage"},
    )
    rows = []
    for index in range(row_count):
        output = clip_dir / f"clip_001_v{index + 1:03d}.mp4"
        output.write_bytes(b"not a real mp4; guard only checks package evidence")
        overlay = clip_dir / f"clip_001_v{index + 1:03d}.png"
        overlay.write_bytes(b"png")
        _write_json(
            output.with_suffix(output.suffix + ".audio_intent.json"),
            {"schema": "reel_factory.audio_intent.v1", "mode": "platform_auto_music"},
        )
        _write_json(
            output.with_suffix(output.suffix + ".generated_asset_lineage.json"),
            {
                "schema": "reel_factory.generated_asset_lineage.v1",
                "source": {
                    "sourceLineagePath": str(
                        root
                        / "00_source_videos"
                        / "clip_001.generated_asset_lineage.json"
                    )
                },
                "captionPlacementPolicy": placement,
                "captionPlacementDecision": placement_decision
                if placement_decision is not None
                else {
                    "status": "passed",
                    "selectedLane": selected_band,
                    "rejectedLanes": [],
                    "reason": "top lane lowest (top=1.0, center=9.0, bottom=12.0)",
                    "scores": {"top": 1.0, "center": 9.0, "bottom": 12.0},
                    "components": {
                        "top": {
                            "busyness": 1.0,
                            "face": 0.0,
                            "focal": 0.0,
                            "motion": 0.0,
                            "pose": 0.0,
                            "safe_area": 0.0,
                        },
                        "center": {
                            "busyness": 1.0,
                            "face": 0.0,
                            "focal": 0.0,
                            "motion": 0.0,
                            "pose": 0.0,
                            "safe_area": 8.0,
                        },
                        "bottom": {
                            "busyness": 12.0,
                            "face": 0.0,
                            "focal": 0.0,
                            "motion": 0.0,
                            "pose": 0.0,
                            "safe_area": 0.0,
                        },
                    },
                    "sampleCount": 3,
                },
            },
        )
        rows.append(
            {
                "captionText": f"hello {index}",
                "captionHash": f"abc{index}",
                "sourceBanks": ["test"],
                "output": str(output),
                "overlayPng": str(overlay),
                "selectedBand": selected_band,
                "captionPlacementPolicy": placement,
            }
        )
    _write_json(
        clip_dir / "_readiness.json",
        {
            "schema": "reel_factory.readiness.v1",
            "summary": {
                "total": row_count,
                "ready": row_count,
                "warn": 0,
                "not_ready": 0,
            },
            "records": readiness_records
            if readiness_records is not None
            else [
                {
                    "filename": Path(row["output"]).name,
                    "status": "ready",
                    "warnings": [],
                }
                for row in rows
            ],
        },
    )
    contentforge_path = root / "contentforge_audit.json"
    if contentforge:
        variants = row_count if contentforge_variants is None else contentforge_variants
        _write_json(
            contentforge_path,
            {
                "schema": "creator_os.local_contentforge_full_batch_audit.v1",
                "profile": contentforge_profile,
                "variants": variants,
                "auditedFileCount": variants,
                "verdictCounts": {"pass": variants},
                "blockingCodes": [],
                "variantFiles": contentforge_variant_files
                if contentforge_variant_files is not None
                else [row["output"] for row in rows],
            },
        )
    manifest = root / "review_manifest.json"
    _write_json(
        manifest,
        {
            "schema": "creator_os.reel_review_batch.v1",
            "actualCount": 1,
            "captionSelection": {"source": "Reel Factory caption bank"},
            "font": font,
            "renderer": "reel_factory.caption_render",
            "style": "ig",
            "backgroundPlate": False,
            "captionPlacementPolicy": placement,
            "contentForgeAuditPath": str(contentforge_path) if contentforge else "",
            "outputDir": str(clip_dir),
            "rows": rows,
        },
    )
    return manifest


def test_review_batch_guard_accepts_complete_pipeline_package(tmp_path: Path) -> None:
    result = validate_review_batch(_batch(tmp_path))

    assert result["status"] == "ready"
    assert result["blockingReasons"] == []


def test_review_batch_guard_blocks_missing_contentforge_proof(tmp_path: Path) -> None:
    result = validate_review_batch(_batch(tmp_path, contentforge=False))

    assert result["status"] == "blocked"
    assert "missing_contentforge_audit" in result["blockingReasons"]


def test_review_batch_guard_blocks_default_contentforge_profile(tmp_path: Path) -> None:
    result = validate_review_batch(_batch(tmp_path, contentforge_profile="default"))

    assert result["status"] == "blocked"
    assert "contentforge_audit_not_campaign_profile" in result["blockingReasons"]


def test_review_batch_guard_blocks_stale_contentforge_count(tmp_path: Path) -> None:
    result = validate_review_batch(
        _batch(tmp_path, row_count=2, contentforge_variants=1)
    )

    assert result["status"] == "blocked"
    assert "contentforge_audit_count_mismatch" in result["blockingReasons"]


def test_review_batch_guard_blocks_same_count_contentforge_for_other_files(
    tmp_path: Path,
) -> None:
    result = validate_review_batch(
        _batch(
            tmp_path,
            row_count=2,
            contentforge_variant_files=[
                str(tmp_path / "02_processed" / "clip_001" / "foreign_a.mp4"),
                str(tmp_path / "02_processed" / "clip_001" / "foreign_b.mp4"),
            ],
        )
    )

    assert result["status"] == "blocked"
    assert "contentforge_audit_file_mismatch" in result["blockingReasons"]


def test_review_batch_guard_blocks_same_count_readiness_for_other_files(
    tmp_path: Path,
) -> None:
    result = validate_review_batch(
        _batch(
            tmp_path,
            row_count=2,
            readiness_records=[
                {"filename": "foreign_a.mp4", "status": "ready", "warnings": []},
                {"filename": "foreign_b.mp4", "status": "ready", "warnings": []},
            ],
        )
    )

    assert result["status"] == "blocked"
    assert "readiness_file_mismatch" in result["blockingReasons"]


def test_review_batch_guard_blocks_manual_font_and_placement(tmp_path: Path) -> None:
    result = validate_review_batch(_batch(tmp_path, font="Arial", placement="top"))

    assert result["status"] == "blocked"
    assert "font_not_instagram_sans_condensed" in result["blockingReasons"]
    assert "caption_placement_not_focal_safe" in result["blockingReasons"]


def test_review_batch_guard_blocks_missing_real_placement_decision(
    tmp_path: Path,
) -> None:
    result = validate_review_batch(_batch(tmp_path, placement_decision={}))

    assert result["status"] == "blocked"
    assert (
        "caption_placement_decision_missing_or_mismatched" in result["blockingReasons"]
    )


def test_review_batch_guard_blocks_selected_band_mismatch(tmp_path: Path) -> None:
    result = validate_review_batch(
        _batch(
            tmp_path,
            selected_band="bottom",
            placement_decision={
                "status": "passed",
                "selectedLane": "top",
                "scores": {"top": 1.0, "center": 9.0, "bottom": 12.0},
                "components": {"top": {}, "center": {}, "bottom": {}},
                "sampleCount": 3,
            },
        )
    )

    assert result["status"] == "blocked"
    assert (
        "caption_placement_decision_missing_or_mismatched" in result["blockingReasons"]
    )


def test_promote_review_batch_writes_package_only_after_guard_passes(
    tmp_path: Path,
) -> None:
    manifest = _batch(tmp_path / "ready")
    package_path = tmp_path / "ready" / "review_package.json"

    result = promote_review_batch(manifest, package_path=package_path)

    assert result["status"] == "ready"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["schema"] == "reel_factory.review_batch_package.v1"
    assert package["guard"]["status"] == "ready"
    assert package["count"] == 1
    assert package["fileSha256"][str(manifest.resolve())]


def test_promote_review_batch_refuses_to_emit_blocked_package(tmp_path: Path) -> None:
    manifest = _batch(tmp_path / "blocked", contentforge=False)
    package_path = tmp_path / "blocked" / "review_package.json"

    result = promote_review_batch(manifest, package_path=package_path)

    assert result["status"] == "blocked"
    assert not package_path.exists()
