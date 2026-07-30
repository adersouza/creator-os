from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.adapters.threadsdash_draft_delivery import (
    _commit_payload_inventory_reservations,
    _release_payload_inventory_reservations,
)
from campaign_factory.asset_inventory import explain_asset, inventory_report
from campaign_test_support import make_factory


def _approved_asset(cf, tmp_path: Path) -> tuple[str, str]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.jpg").write_bytes(b"source")
    cf.domains.asset_import.import_folder(
        source_dir,
        campaign_slug="asset-lineage",
        model_slug="stacey",
    )
    campaign = cf.domains.campaign_by_slug("asset-lineage")
    source = cf.domains.asset_import.assets_for_campaign(campaign["id"])[0]
    output = tmp_path / "final.mp4"
    output.write_bytes(b"final mp4 bytes")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    caption = {
        "variantCooldownCheck": "clear",
        "captionPlacementDecision": {"status": "passed", "lane": "lower_center"},
        "generatedAssetLineage": {
            "schema": "reel_factory.generated_asset_lineage.v2",
            "source": {"assetId": source["id"]},
        },
    }
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path,
         campaign_path, filename, media_type, content_surface,
         caption_generation_json, metadata_json, recipe, audit_status,
         review_state, created_at, updated_at)
        VALUES ('asset-final', ?, ?, ?, ?, ?, 'final.mp4', 'video', 'reel',
                ?, ?, 'static_mp4', 'approved_candidate', 'approved',
                '2026-07-29T12:00:00+00:00', '2026-07-29T12:00:00+00:00')
        """,
        (
            campaign["id"],
            source["id"],
            digest,
            str(output),
            str(output),
            json.dumps(caption),
            json.dumps(
                {
                    "audioEmbeddingReceipt": {
                        "verification": {"status": "verified"},
                        "finalVideo": {"sha256": digest},
                    }
                }
            ),
        ),
    )
    cf.conn.execute(
        """
        INSERT INTO approval_decisions
        (id, campaign_id, rendered_asset_id, decision, notes, created_at)
        VALUES ('approval-final', ?, 'asset-final', 'approved', 'would post',
                '2026-07-29T12:01:00+00:00')
        """,
        (campaign["id"],),
    )
    cf.conn.commit()
    return digest, source["id"]


def test_asset_explain_and_inventory_reservation_lifecycle(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        digest, source_id = _approved_asset(cf, tmp_path)
        account = cf.domains.models.upsert_account("destination")
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset-final",
            account_id=account["id"],
            surface="reel",
        )
        payload = {
            "drafts": [
                {
                    "renderedAssetId": "asset-final",
                    "inventoryReservationId": reservation["reservation_id"],
                }
            ]
        }

        explanation = explain_asset(cf, digest)
        inventory = inventory_report(
            cf, campaign_slug="asset-lineage", content_surface="reel"
        )
        _commit_payload_inventory_reservations(cf, payload)

        assert explanation["lineageStatus"] == "verified"
        assert explanation["source"]["id"] == source_id
        assert explanation["final"]["bytesStatus"] == "verified"
        assert explanation["overlay"]["captionPlacementDecision"]["status"] == "passed"
        assert explanation["audio"]["verification"]["status"] == "verified"
        assert explanation["reuse"]["variantCooldownCheck"] == "clear"
        assert inventory == {
            "schema": "campaign_factory.inventory_report.v1",
            "campaign": "asset_lineage",
            "contentSurface": "reel",
            "grossInventory": 1,
            "reservedInventory": 1,
            "assignedInventory": 0,
            "usedInventory": 0,
            "cooldownBlockedInventory": 0,
            "netInventory": 0,
        }
        committed = cf.conn.execute(
            "SELECT status FROM asset_inventory_reservations WHERE reservation_id = ?",
            (reservation["reservation_id"],),
        ).fetchone()
        assert committed["status"] == "committed"
        _release_payload_inventory_reservations(cf, payload)
        still_committed = cf.conn.execute(
            "SELECT status FROM asset_inventory_reservations WHERE reservation_id = ?",
            (reservation["reservation_id"],),
        ).fetchone()
        assert still_committed["status"] == "committed"
    finally:
        cf.close()


def test_reconciliation_reports_and_expires_stranded_reservations(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        _approved_asset(cf, tmp_path)
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset-final",
            surface="reel",
            expires_at="2026-07-28T00:00:00+00:00",
        )

        preview = cf.domains.inventory_reservations.reservation_reconciliation_report(
            now="2026-07-29T00:00:00+00:00"
        )
        applied = cf.domains.inventory_reservations.reservation_reconciliation_report(
            now="2026-07-29T00:00:00+00:00",
            apply=True,
        )

        assert preview["strandedCount"] == 1
        assert (
            preview["strandedReservations"][0]["reservation_id"]
            == (reservation["reservation_id"])
        )
        assert applied["expiredNow"] == 1
        assert applied["expiredReservations"][0]["status"] == "expired"
    finally:
        cf.close()


def test_missing_variant_cooldown_evidence_fails_closed(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        reason = cf.domains.creator_os_drafts.creator_os_draft_exclusion_reason(
            {
                "instagramPostCaption": "caption",
                "handoffManifestOk": True,
                "platformDraftValidated": True,
                "publishabilityState": "exportable",
            }
        )
        assert reason == "variantCooldownBlocked"
        assert (
            cf.domains.creator_os_drafts.creator_os_gap_blocking_reason(reason, [], {})
            == "unproven"
        )
    finally:
        cf.close()


def test_publication_terminalizes_reservation_and_persists_assignment_event(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        digest, _ = _approved_asset(cf, tmp_path)
        account = cf.domains.models.upsert_account("destination")
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset-final",
            account_id=account["id"],
            surface="reel",
        )
        cf.domains.inventory_reservations.commit_inventory_reservation(
            reservation["reservation_id"]
        )

        published = cf.domains.inventory_reservations.publish_inventory_reservation(
            reservation["reservation_id"],
            post_id="post-1",
            instagram_media_id="ig-media-1",
            instagram_account_id="ig-destination",
            published_at="2026-07-29T15:00:00+00:00",
        )

        assert published["status"] == "published"
        assignment = cf.conn.execute(
            """
            SELECT * FROM asset_account_assignments
            WHERE rendered_asset_id = 'asset-final'
            """
        ).fetchone()
        assert assignment["account_id"] == account["id"]
        assert assignment["instagram_account_id"] == "ig-destination"
        events = cf.conn.execute(
            """
            SELECT * FROM asset_inventory_reservation_events
            WHERE reservation_id = ? ORDER BY occurred_at
            """,
            (reservation["reservation_id"],),
        ).fetchall()
        assert {event["event_type"] for event in events} == {
            "draft_ingest_accepted",
            "publication_confirmed",
        }
        publication_event = next(
            event for event in events if event["event_type"] == "publication_confirmed"
        )
        evidence = json.loads(publication_event["evidence_json"])
        assert evidence["finalMediaSha256"] == digest
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            cf.conn.execute(
                """
                UPDATE asset_inventory_reservation_events
                SET event_type = 'changed'
                WHERE id = ?
                """,
                (publication_event["id"],),
            )
    finally:
        cf.close()


def test_draft_cancellation_terminalizes_committed_reservation(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        _approved_asset(cf, tmp_path)
        reservation = cf.domains.inventory_reservations.reserve_inventory_asset(
            "asset-final",
            surface="reel",
        )
        cf.domains.inventory_reservations.commit_inventory_reservation(
            reservation["reservation_id"]
        )

        cancelled = cf.domains.inventory_reservations.cancel_inventory_reservation(
            reservation["reservation_id"],
            post_id="post-cancelled",
            reason="operator_deleted_draft",
        )

        assert cancelled["status"] == "cancelled"
        event = cf.conn.execute(
            """
            SELECT * FROM asset_inventory_reservation_events
            WHERE reservation_id = ? AND event_type = 'draft_cancelled'
            """,
            (reservation["reservation_id"],),
        ).fetchone()
        assert event["post_id"] == "post-cancelled"
        assert json.loads(event["evidence_json"])["reason"] == "operator_deleted_draft"
    finally:
        cf.close()
