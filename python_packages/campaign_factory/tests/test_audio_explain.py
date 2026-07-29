from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from campaign_factory.audio_radar.cli import _explain_audio


def test_audio_explain_binds_final_sha_to_track_segment_and_publication(
    tmp_path: Path,
) -> None:
    database = tmp_path / "campaign.db"
    digest = "a" * 64
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE rendered_assets (
            id TEXT, campaign_id TEXT, content_hash TEXT, output_path TEXT,
            audit_status TEXT, review_state TEXT, metadata_json TEXT,
            updated_at TEXT
        );
        CREATE TABLE approval_decisions (
            id TEXT, rendered_asset_id TEXT, decision TEXT, notes TEXT,
            created_at TEXT
        );
        CREATE TABLE performance_snapshots (
            rendered_asset_id TEXT, content_hash TEXT, post_id TEXT,
            platform TEXT, status TEXT, account_id TEXT,
            instagram_account_id TEXT, permalink TEXT, published_at TEXT
        );
        """
    )
    receipt = {
        "selection": {
            "canonicalTrackId": "track-1",
            "canonicalTitle": "Track One",
            "advisoryLabels": {"trendScore": 0.9},
        },
        "selectedTrack": {
            "provider": "fixture",
            "acquiredAudioSha256": "b" * 64,
        },
        "selectedSegment": {"startSeconds": 4, "endSeconds": 12},
        "finalVideo": {"audioFingerprint": "c" * 64},
        "audioIntent": {
            "rights": {"usageRightsStatus": "licensed"},
            "lineage": {"embeddingReceiptSha256": "d" * 64},
        },
    }
    conn.execute(
        "INSERT INTO rendered_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "asset-1",
            "campaign-1",
            digest,
            "/tmp/final.mp4",
            "approved",
            "approved",
            json.dumps({"audioEmbeddingReceipt": receipt}),
            "2026-07-29T12:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO approval_decisions VALUES (?, ?, ?, ?, ?)",
        ("approval-1", "asset-1", "approved", "reviewed", "2026-07-29T12:01:00Z"),
    )
    conn.execute(
        "INSERT INTO performance_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "asset-1",
            digest,
            "post-1",
            "instagram",
            "published",
            None,
            "account-1",
            "https://instagram.test/p/post-1",
            "2026-07-29T12:02:00Z",
        ),
    )
    conn.commit()
    conn.close()

    result = _explain_audio(database, digest)

    assert result["matches"][0]["track"]["canonicalTrackId"] == "track-1"
    assert result["matches"][0]["selectedSegment"] == {
        "startSeconds": 4,
        "endSeconds": 12,
    }
    assert result["matches"][0]["publicationLinkage"][0]["post_id"] == "post-1"
