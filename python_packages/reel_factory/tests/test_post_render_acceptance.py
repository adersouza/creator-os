from pathlib import Path

from post_render_acceptance import acceptance_from_readiness
from readiness_check import run_readiness


def _row(**overrides):
    row = {
        "filename": "clip.mp4",
        "path": "/tmp/clip.mp4",
        "platform": "instagram_reels",
        "status": "ready",
        "score": 92,
        "warnings": [],
        "dimensions": {"width": 1080, "height": 1920},
        "audioIntent": {"status": "recommended"},
        "safeZone": {"safeZoneStatus": "passed"},
        "viralityQc": None,
        "lineagePresent": True,
    }
    row.update(overrides)
    return row


def test_acceptance_marks_ready_record_ready():
    result = acceptance_from_readiness(_row())

    assert result["schema"] == "reel_factory.post_render_acceptance.v1"
    assert result["status"] == "ready"
    assert result["blockingReasons"] == []
    assert result["reviewReasons"] == []


def test_acceptance_reviews_missing_audio_or_lineage_without_rejecting():
    result = acceptance_from_readiness(
        _row(warnings=["missing_audio_intent"], audioIntent=None, lineagePresent=False)
    )

    assert result["status"] == "review"
    assert result["blockingReasons"] == []
    assert result["reviewReasons"] == ["missing_audio_intent", "missing_generated_asset_lineage"]


def test_acceptance_rejects_not_ready_and_required_virality_failure():
    result = acceptance_from_readiness(
        _row(
            status="not_ready",
            warnings=["virality_score_low"],
            viralityQc={"status": "failed", "required": True, "warnings": ["virality_score_low"]},
        )
    )

    assert result["status"] == "reject"
    assert "readiness_not_ready" in result["blockingReasons"]
    assert "virality_score_low" in result["blockingReasons"]


def test_run_readiness_embeds_acceptance_record(tmp_path: Path):
    output = tmp_path / "02_processed" / "clip_001" / "clip_001_h00_v01_original_light_deadbeef.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"fake")

    result = run_readiness(tmp_path, clip="clip_001")

    acceptance = result["records"][0]["postRenderAcceptance"]
    assert acceptance["schema"] == "reel_factory.post_render_acceptance.v1"
    assert acceptance["status"] == "review"
