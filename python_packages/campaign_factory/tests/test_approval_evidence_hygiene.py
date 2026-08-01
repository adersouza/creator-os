from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from campaign_factory.approval_evidence_hygiene import approval_evidence_hygiene


def test_hygiene_dry_run_and_apply_quarantine_without_deletion(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rendered_assets (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO rendered_assets VALUES ('asset-live')")
    root = tmp_path / "operational" / "creative_approvals"
    root.mkdir(parents=True)
    test_audit = root / "registered_final_artifact_audit" / "test.json"
    test_audit.parent.mkdir()
    test_audit.write_text(
        json.dumps(
            {
                "schema": "campaign_factory.final_artifact_audit.v1",
                "analyzerEvidence": {"analyzerVersion": "test"},
            }
        ),
        encoding="utf-8",
    )
    orphan_review = root / "operator_media_reviews" / "orphan.json"
    orphan_review.parent.mkdir()
    orphan_review.write_text(
        json.dumps(
            {
                "schema": "creator_os.operator_media_review.v1",
                "reviewId": "media-review-real-shape",
                "renderedAssetId": "asset-missing",
                "reviewedBy": "operator",
            }
        ),
        encoding="utf-8",
    )
    valid_review = root / "operator_media_reviews" / "valid.json"
    valid_review.write_text(
        json.dumps(
            {
                "schema": "creator_os.operator_media_review.v1",
                "reviewId": "media-review-live",
                "renderedAssetId": "asset-live",
                "reviewedBy": "operator",
            }
        ),
        encoding="utf-8",
    )

    preview = approval_evidence_hygiene(conn, root=root, apply=False)
    assert preview["candidateCount"] == 2
    assert preview["movedCount"] == 0
    assert test_audit.exists() and orphan_review.exists() and valid_review.exists()

    applied = approval_evidence_hygiene(conn, root=root, apply=True)
    assert applied["movedCount"] == 2
    assert applied["deleted"] == 0
    assert not test_audit.exists() and not orphan_review.exists()
    assert valid_review.exists()
    receipt = Path(str(applied["receiptPath"]))
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["deleted"] == 0
    assert len(payload["moved"]) == 2


def test_hygiene_limit_is_bounded(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rendered_assets (id TEXT PRIMARY KEY)")
    root = tmp_path / "creative_approvals"
    root.mkdir()
    try:
        approval_evidence_hygiene(conn, root=root, limit=1001)
    except ValueError as exc:
        assert str(exc) == "limit must be between 1 and 1000"
    else:
        raise AssertionError("unbounded approval evidence scan was accepted")
