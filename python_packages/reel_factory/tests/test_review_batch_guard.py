import json
from pathlib import Path

from review_batch_guard import validate_review_batch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _batch(
    tmp_path: Path,
    *,
    font: str = "Instagram Sans Condensed Bold",
    placement: str = "focal-safe",
    contentforge: bool = True,
    contentforge_profile: str = "campaign_factory_v1",
    row_count: int = 1,
    contentforge_variants: int | None = None,
) -> Path:
    root = tmp_path
    clip_dir = root / "02_processed" / "clip_001"
    clip_dir.mkdir(parents=True)
    _write_json(root / "00_source_videos" / "clip_001.generated_asset_lineage.json", {"schema": "lineage"})
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
                "schema": "campaign_factory.generated_asset_lineage.v1",
                "source": {"sourceLineagePath": str(root / "00_source_videos" / "clip_001.generated_asset_lineage.json")},
                "captionPlacementPolicy": placement,
            },
        )
        rows.append(
            {
                "captionText": f"hello {index}",
                "captionHash": f"abc{index}",
                "sourceBanks": ["test"],
                "output": str(output),
                "overlayPng": str(overlay),
                "selectedBand": "top",
                "captionPlacementPolicy": placement,
            }
        )
    _write_json(
        clip_dir / "_readiness.json",
        {
            "schema": "reel_factory.readiness.v1",
            "summary": {"total": row_count, "ready": row_count, "warn": 0, "not_ready": 0},
            "records": [
                {"filename": Path(row["output"]).name, "status": "ready", "warnings": []}
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
                "httpOk": variants,
                "verdictCounts": {"pass": variants},
                "blockingCodes": [],
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
    result = validate_review_batch(_batch(tmp_path, row_count=2, contentforge_variants=1))

    assert result["status"] == "blocked"
    assert "contentforge_audit_count_mismatch" in result["blockingReasons"]


def test_review_batch_guard_blocks_manual_font_and_placement(tmp_path: Path) -> None:
    result = validate_review_batch(_batch(tmp_path, font="Arial", placement="top"))

    assert result["status"] == "blocked"
    assert "font_not_instagram_sans_condensed" in result["blockingReasons"]
    assert "caption_placement_not_focal_safe" in result["blockingReasons"]
