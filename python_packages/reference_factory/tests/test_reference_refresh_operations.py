from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OPERATIONS_DOC = REPO_ROOT / "docs" / "operations" / "reference_refresh.md"


def test_reference_refresh_local_schedule_is_documented() -> None:
    doc = OPERATIONS_DOC.read_text(encoding="utf-8")

    assert "com.creator-os.reference-refresh" in doc
    assert "/Users/aderdesouza/.creator-os/run-job.sh" in doc
    assert "import-tiktok-archive --source ~/Downloads/tiktok" in doc
    assert "refresh-tiktok-audio --source ~/Downloads/tiktok" in doc
    assert "analyze-audio-patterns" in doc
    assert "audio-health" in doc
    assert "list-audio --export ~/Developer/reference_reels/audio_catalog.json" in doc
    assert "campaign_factory.cli import-audio-catalog --path" in doc
    assert "Do not install this from CI" in doc
