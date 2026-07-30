from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import campaign_factory.db_migrations as governance_migrations
import pytest
from campaign_asset_test_support import add_schedule_safe_production_asset
from campaign_factory import cli as cli_module
from campaign_factory.creator_governance_schema import CREATOR_GOVERNANCE_SCHEMA
from campaign_factory.db import init_db
from campaign_factory.db_migrations import _apply_creator_governance_backfill
from campaign_test_support import (
    add_rendered_asset,
    authorize_campaign_governance,
    make_factory,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_profile(
    creator: str, soul_id: str, *, source_id: str, source_sha256: str
) -> dict:
    return {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": f"{creator}_higgsfield_{soul_id}",
        "creatorKey": creator,
        "displayName": creator.title(),
        "modelProfile": "higgsfield_soul_v2",
        "identityReferences": [
            {
                "namespace": "higgsfield.soul",
                "externalId": soul_id,
                "fingerprint": "a" * 64,
            }
        ],
        "provenance": {
            "producer": "operator",
            "producedAt": "2026-07-30T12:00:00Z",
            "sourceReferences": [{"recordId": source_id, "fingerprint": source_sha256}],
        },
    }


def test_identity_consent_and_campaign_state_fail_closed(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        cf.domains.models.upsert_campaign("may", "stacey")
        with pytest.raises(
            PermissionError, match="campaign_state_blocks_provider_spend"
        ):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )

        authorized = authorize_campaign_governance(
            cf,
            tmp_path,
            provider="higgsfield",
            soul_id="soul_stacey_v1",
        )
        context = cf.domains.creator_governance.resolve_operation(
            creator="stacey",
            campaign=authorized["campaign"]["id"],
            operation="provider_spend",
            provider="higgsfield",
        )
        assert context["creatorId"] == authorized["model"]["id"]
        assert context["providerIdentityId"] == "soul_stacey_v1"
        assert len(context["authorizationEventIds"]) == 2

        cf.domains.creator_governance.transition_creator(
            "stacey",
            new_status="suspended",
            actor="test",
            reason="fixture suspension",
        )
        with pytest.raises(PermissionError, match="creator_inactive"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )
    finally:
        cf.close()


def test_governance_migration_backfills_only_proven_campaign_owners():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE models (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE campaigns (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL
        );
        INSERT INTO models VALUES ('model_a', 'stacey', 'Stacey');
        INSERT INTO models VALUES ('model_b', 'other', 'Other');
        INSERT INTO campaigns VALUES ('camp_proven', 'proven', 'Proven');
        INSERT INTO campaigns VALUES ('camp_ambiguous', 'ambiguous', 'Ambiguous');
        INSERT INTO campaigns VALUES ('camp_empty', 'empty', 'Empty');
        INSERT INTO source_assets VALUES ('src_1', 'camp_proven', 'model_a');
        INSERT INTO source_assets VALUES ('src_2', 'camp_ambiguous', 'model_a');
        INSERT INTO source_assets VALUES ('src_3', 'camp_ambiguous', 'model_b');
        """
    )
    conn.executescript(CREATOR_GOVERNANCE_SCHEMA)

    _apply_creator_governance_backfill(conn)
    _apply_creator_governance_backfill(conn)

    assert (
        conn.execute("SELECT status FROM schema_migrations").fetchone()["status"]
        == "applied"
    )
    assert (
        conn.execute(
            "SELECT model_id FROM campaign_governance WHERE campaign_id = 'camp_proven'"
        ).fetchone()["model_id"]
        == "model_a"
    )
    assert (
        conn.execute(
            "SELECT 1 FROM campaign_governance WHERE campaign_id = 'camp_ambiguous'"
        ).fetchone()
        is None
    )
    assert (
        conn.execute(
            "SELECT 1 FROM campaign_governance WHERE campaign_id = 'camp_empty'"
        ).fetchone()
        is None
    )
    details = json.loads(
        conn.execute("SELECT details_json FROM schema_migrations").fetchone()[
            "details_json"
        ]
    )
    assert details["unresolvedCampaignIds"] == ["camp_ambiguous", "camp_empty"]
    assert (
        conn.execute("SELECT COUNT(*) FROM creator_lifecycle_state").fetchone()[0] == 2
    )
    conn.close()


def test_governance_migration_checksum_tracks_executable_schema(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE models (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE campaigns (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL
        );
        """
    )
    conn.executescript(CREATOR_GOVERNANCE_SCHEMA)
    _apply_creator_governance_backfill(conn)

    monkeypatch.setattr(
        governance_migrations,
        "CREATOR_GOVERNANCE_SCHEMA",
        CREATOR_GOVERNANCE_SCHEMA + "\n-- executable schema drift",
    )
    with pytest.raises(
        RuntimeError, match="creator_governance_migration_checksum_drift"
    ):
        _apply_creator_governance_backfill(conn)
    conn.close()


def test_governance_migration_postcondition_failure_is_retryable():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE models (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE campaigns (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL
        );
        INSERT INTO models VALUES ('model_a', 'stacey', 'Stacey');
        """
    )
    conn.executescript(CREATOR_GOVERNANCE_SCHEMA)
    conn.execute(
        """
        INSERT INTO creator_lifecycle_state
        (model_id, status, status_reason, effective_at, changed_by, version,
         offboarding_state, retention_state, updated_at)
        VALUES ('model_a', 'active', 'preexisting_state',
                '2026-07-30T12:00:00Z', 'fixture', 2, NULL, 'retain_audit',
                '2026-07-30T12:00:00Z')
        """
    )
    conn.commit()

    with pytest.raises(
        RuntimeError, match="creator_governance_backfill_postcondition_failed"
    ):
        _apply_creator_governance_backfill(conn)
    failed = conn.execute("SELECT status, error FROM schema_migrations").fetchone()
    assert failed["status"] == "failed"
    assert "creator_governance_backfill_postcondition_failed:model_a" in failed["error"]
    assert conn.execute("SELECT COUNT(*) FROM creator_slug_history").fetchone()[0] == 0

    conn.execute(
        """
        INSERT INTO creator_lifecycle_events
        (id, model_id, old_status, new_status, reason, actor, effective_at,
         evidence_json, version, created_at)
        VALUES ('creator_state_recovered', 'model_a', 'suspended', 'active',
                'recovered preexisting event', 'fixture',
                '2026-07-30T12:00:00Z', '{}', 2,
                '2026-07-30T12:00:00Z')
        """
    )
    conn.commit()
    _apply_creator_governance_backfill(conn)
    assert (
        conn.execute("SELECT status FROM schema_migrations").fetchone()["status"]
        == "applied"
    )
    assert conn.execute("SELECT COUNT(*) FROM creator_slug_history").fetchone()[0] == 1
    conn.close()


def test_legacy_source_asset_rebuild_restores_creator_ownership_guards():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          original_path TEXT NOT NULL,
          stored_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          media_type TEXT NOT NULL DEFAULT 'video',
          platform TEXT NOT NULL DEFAULT 'instagram',
          source_prompt TEXT,
          higgsfield_job_id TEXT,
          higgsfield_model TEXT,
          notes TEXT,
          account_ids_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'imported',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    init_db(conn)

    trigger_names = {
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'trigger' AND tbl_name = 'source_assets'
            """
        ).fetchall()
    }
    assert {
        "trg_source_asset_campaign_creator_insert",
        "trg_source_asset_campaign_creator_update",
    } <= trigger_names
    assert "content_surface" in {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(source_assets)")
    }

    now = "2026-07-30T12:00:00Z"
    conn.execute(
        """
        INSERT INTO models (id, slug, name, created_at, updated_at)
        VALUES ('model_a', 'stacey', 'Stacey', ?, ?),
               ('model_b', 'other', 'Other', ?, ?)
        """,
        (now, now, now, now),
    )
    conn.execute(
        """
        INSERT INTO campaigns
        (id, slug, name, platform, root_path, created_at, updated_at)
        VALUES ('camp_a', 'may', 'May', 'instagram', '/tmp/may', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO campaign_governance
        (campaign_id, model_id, lifecycle_status, blocker_codes_json,
         status_reason, changed_by, effective_at, version, updated_at)
        VALUES ('camp_a', 'model_a', 'created', '[]', 'fixture', 'fixture',
                ?, 1, ?)
        """,
        (now, now),
    )
    conn.commit()
    with pytest.raises(
        sqlite3.IntegrityError, match="source asset creator does not own campaign"
    ):
        conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, created_at, updated_at)
            VALUES ('src_wrong', 'camp_a', 'model_b', ?, '/tmp/a', '/tmp/a',
                    'a.jpg', ?, ?)
            """,
            ("a" * 64, now, now),
        )
    conn.close()


def test_governance_history_is_immutable_and_versions_are_unique(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(cf, tmp_path)
        creator_event = cf.conn.execute(
            """
            SELECT * FROM creator_lifecycle_events
            WHERE model_id = ? ORDER BY version LIMIT 1
            """,
            (authorized["model"]["id"],),
        ).fetchone()
        campaign_event = cf.conn.execute(
            """
            SELECT * FROM campaign_lifecycle_events
            WHERE campaign_id = ? ORDER BY version LIMIT 1
            """,
            (authorized["campaign"]["id"],),
        ).fetchone()
        identity = cf.conn.execute(
            "SELECT * FROM creator_identity_profiles WHERE model_id = ?",
            (authorized["model"]["id"],),
        ).fetchone()

        blocked_statements = [
            (
                "UPDATE creator_lifecycle_events SET reason = 'tampered' WHERE id = ?",
                (creator_event["id"],),
                "immutable",
            ),
            (
                "DELETE FROM creator_lifecycle_events WHERE id = ?",
                (creator_event["id"],),
                "immutable",
            ),
            (
                "UPDATE campaign_lifecycle_events SET reason = 'tampered' WHERE id = ?",
                (campaign_event["id"],),
                "immutable",
            ),
            (
                "DELETE FROM campaign_lifecycle_events WHERE id = ?",
                (campaign_event["id"],),
                "immutable",
            ),
            (
                "UPDATE creator_identity_profiles SET operator = 'tampered' WHERE id = ?",
                (identity["id"],),
                "immutable",
            ),
            (
                "DELETE FROM creator_identity_profiles WHERE id = ?",
                (identity["id"],),
                "immutable",
            ),
            (
                "DELETE FROM creator_lifecycle_state WHERE model_id = ?",
                (authorized["model"]["id"],),
                "governed transition",
            ),
            (
                "DELETE FROM campaign_governance WHERE campaign_id = ?",
                (authorized["campaign"]["id"],),
                "governed transition",
            ),
        ]
        for sql, params, message in blocked_statements:
            with pytest.raises(sqlite3.IntegrityError, match=message):
                cf.conn.execute(sql, params)
            cf.conn.rollback()

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            cf.conn.execute(
                """
                INSERT INTO creator_lifecycle_events
                SELECT 'creator_state_duplicate', model_id, old_status, new_status,
                       reason, actor, effective_at, evidence_json, version, created_at
                FROM creator_lifecycle_events WHERE id = ?
                """,
                (creator_event["id"],),
            )
        cf.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            cf.conn.execute(
                """
                INSERT INTO campaign_lifecycle_events
                SELECT 'campaign_state_duplicate', campaign_id, model_id, old_status,
                       new_status, reason, actor, evidence_json, related_ids_json,
                       version, created_at
                FROM campaign_lifecycle_events WHERE id = ?
                """,
                (campaign_event["id"],),
            )
        cf.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            cf.conn.execute(
                """
                INSERT INTO creator_slug_history
                (id, model_id, slug, effective_at, retired_at, actor, reason, created_at)
                SELECT 'creator_slug_duplicate_active', model_id, slug || '_alias',
                       effective_at, NULL, actor, reason, created_at
                FROM creator_slug_history
                WHERE model_id = ? AND retired_at IS NULL
                """,
                (authorized["model"]["id"],),
            )
        cf.conn.rollback()
    finally:
        cf.close()


def test_identity_versions_and_authorization_revocation_are_historical(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(
            cf,
            tmp_path,
            provider="higgsfield",
            soul_id="soul_stacey_v1",
        )
        old = cf.domains.creator_governance.resolve_operation(
            creator="stacey",
            campaign="may",
            operation="provider_spend",
            provider="higgsfield",
        )
        source = cf.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?",
            (authorized["identitySourceId"],),
        ).fetchone()
        replacement = _identity_profile(
            "stacey",
            "soul_stacey_v2",
            source_id=str(source["id"]),
            source_sha256=str(source["content_hash"]),
        )
        manifest = tmp_path / "stacey_higgsfield_identity_v2.json"
        manifest.write_text(json.dumps(replacement, sort_keys=True), encoding="utf-8")
        cf.domains.creator_governance.enroll_identity_profile(
            "stacey",
            provider="higgsfield",
            provider_identity_id="soul_stacey_v2",
            profile=replacement,
            canonical_source_asset_id=str(source["id"]),
            identity_manifest_path=manifest,
            identity_manifest_sha256=_sha(manifest),
            operator="test",
        )
        current = cf.domains.creator_governance.resolve_operation(
            creator="stacey",
            campaign="may",
            operation="provider_spend",
            provider="higgsfield",
        )
        assert current["identityProfileVersion"] == 2
        assert current["governanceFingerprint"] != old["governanceFingerprint"]

        authorization_id = current["authorizationIds"][0]
        evidence = tmp_path / "revocation.txt"
        evidence.write_text("revoked", encoding="utf-8")
        cf.domains.creator_governance.revoke_authorization(
            authorization_id,
            actor="test",
            reason="fixture revocation",
            evidence_path=evidence,
            evidence_sha256=_sha(evidence),
        )
        with pytest.raises(PermissionError, match="creator_authorization_missing"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )
    finally:
        cf.close()


def test_campaign_owner_rename_and_transition_guards(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(cf, tmp_path)
        with pytest.raises(PermissionError, match="campaign_creator_owner_mismatch"):
            cf.domains.models.upsert_campaign("may", "stacey_clone")
        assert (
            cf.domains.campaign_by_slug("may")["root_path"]
            == authorized["campaign"]["root_path"]
        )

        renamed = cf.domains.creator_governance.rename_creator(
            "stacey",
            new_slug="stacey_new",
            actor="test",
            reason="fixture rename",
        )
        assert renamed["creator"]["slug"] == "stacey_new"
        assert (
            cf.domains.creator_governance.creator_status("stacey")["creator"]["id"]
            == authorized["model"]["id"]
        )

        cf.domains.creator_governance.transition_campaign(
            "may",
            new_status="paused",
            actor="test",
            reason="fixture pause",
        )
        with pytest.raises(PermissionError, match="campaign_state_blocks_still_edit"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey_new",
                campaign="may",
                operation="still_edit",
                provider="openai",
            )
        with pytest.raises(ValueError, match="illegal_campaign_transition"):
            cf.domains.creator_governance.transition_campaign(
                "may",
                new_status="archived",
                actor="test",
                reason="illegal fixture transition",
            )
    finally:
        cf.close()


def test_expired_consent_and_cross_creator_inputs_are_blocked(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(cf, tmp_path)
        expired = tmp_path / "expired.txt"
        expired.write_text("expired", encoding="utf-8")
        cf.domains.creator_governance.grant_authorization(
            "stacey",
            scope="reference_video_use",
            provider="openai",
            evidence_path=expired,
            evidence_sha256=_sha(expired),
            actor="test",
            reason="expired fixture",
            effective_at="2020-01-01T00:00:00Z",
            expires_at="2020-01-02T00:00:00Z",
            reference_video_use=True,
        )
        with pytest.raises(PermissionError, match="creator_authorization_missing"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="reference_analysis",
                provider="openai",
            )

        other = cf.domains.models.upsert_campaign("other", "other_creator")
        other_source = tmp_path / "other.mp4"
        other_source.write_bytes(b"other")
        source_id = "src_other_creator"
        now = "2026-07-30T12:00:00Z"
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, platform, account_ids_json, status,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'other.mp4', 'video', 'instagram', '[]',
                    'imported', ?, ?)
            """,
            (
                source_id,
                other["id"],
                cf.domains.creator_governance._model("other_creator")["id"],
                _sha(other_source),
                str(other_source),
                str(other_source),
                now,
                now,
            ),
        )
        cf.conn.commit()
        with pytest.raises(PermissionError, match="cross_creator_source_blocked"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign=authorized["campaign"]["id"],
                operation="still_edit",
                provider="openai",
                source_asset_id=source_id,
            )
    finally:
        cf.close()


def test_authorization_account_and_territory_scope_fail_closed(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey")
        allowed = cf.domains.models.upsert_account("allowed", model_id=model["id"])
        other = cf.domains.models.upsert_account("other", model_id=model["id"])
        authorize_campaign_governance(
            cf,
            tmp_path,
            provider="higgsfield",
            account_scope=[allowed["id"]],
            territories=["US"],
        )

        context = cf.domains.creator_governance.resolve_operation(
            creator="stacey",
            campaign="may",
            operation="provider_spend",
            provider="higgsfield",
            account_id=allowed["id"],
            territory="us",
        )
        assert context["accountId"] == allowed["id"]
        assert context["territory"] == "us"
        assert (
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
                account_id=allowed["handle"],
                territory="US",
            )["accountId"]
            == allowed["id"]
        )

        with pytest.raises(
            PermissionError, match="creator_authorization_account_scope"
        ):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
                account_id=other["id"],
                territory="US",
            )
        with pytest.raises(PermissionError, match="creator_authorization_territory"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
                account_id=allowed["id"],
                territory="CA",
            )
    finally:
        cf.close()


def test_reactivation_requires_fresh_identity_and_authorization(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(
            cf, tmp_path, provider="higgsfield", soul_id="soul_stacey_v1"
        )
        cf.domains.creator_governance.transition_creator(
            "stacey",
            new_status="suspended",
            actor="test",
            reason="fixture suspension",
        )
        cf.domains.creator_governance.transition_creator(
            "stacey",
            new_status="active",
            actor="test",
            reason="fixture reactivation",
        )

        with pytest.raises(PermissionError, match="creator_identity_profile_missing"):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )
    finally:
        cf.close()


def test_cancel_releases_pending_and_preserves_committed_and_ambiguous_work(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_schedule_safe_production_asset(
            cf, tmp_path, asset_id="asset_2", source=source
        )
        campaign = cf.domains.campaign_by_slug("may")
        now = "2026-07-30T12:00:00Z"
        for suffix, status in (("pending", "pending"), ("committed", "committed")):
            cf.conn.execute(
                """
                INSERT INTO asset_inventory_reservations
                (id, asset_id, campaign_id, surface, reservation_id, reserved_by,
                 reserved_at, status, created_at, updated_at)
                VALUES (?, ?, ?, 'reel', ?, 'test', ?, ?, ?, ?)
                """,
                (
                    f"reservation_{suffix}",
                    "asset_1" if suffix == "pending" else "asset_2",
                    campaign["id"],
                    f"reservation_{suffix}",
                    now,
                    status,
                    now,
                    now,
                ),
            )
        cf.conn.commit()
        job = cf.domains.events.create_pipeline_job(
            "higgsfield_motion_generation", campaign["id"], {}
        )
        cf.domains.events.start_pipeline_job(job["id"])
        cf.domains.events.mark_pipeline_effect_state(
            job["id"], "AUTHORIZATION_CONSUMED"
        )
        cf.domains.events.mark_pipeline_effect_state(job["id"], "SUBMISSION_STARTED")
        cf.domains.events.fail_pipeline_job(job["id"], "provider timeout")

        result = cf.domains.creator_governance.transition_campaign(
            "may",
            new_status="cancelled",
            actor="test",
            reason="fixture cancellation",
        )

        statuses = dict(
            cf.conn.execute(
                """
                SELECT reservation_id, status
                FROM asset_inventory_reservations
                ORDER BY reservation_id
                """
            ).fetchall()
        )
        assert statuses == {
            "reservation_committed": "committed",
            "reservation_pending": "released",
        }
        assert (
            cf.domains.events.pipeline_job(job["id"])["recovery"]["effectState"]
            == "AMBIGUOUS"
        )
        event = cf.conn.execute(
            """
            SELECT evidence_json, related_ids_json FROM campaign_lifecycle_events
            WHERE campaign_id = ? AND new_status = 'cancelled'
            """,
            (campaign["id"],),
        ).fetchone()
        evidence = json.loads(event["evidence_json"])
        assert evidence["releasedPendingReservationIds"] == ["reservation_pending"]
        assert evidence["committedReservationCancellationObligations"] == [
            "reservation_committed"
        ]
        assert evidence["ambiguousExternalEffectJobIds"] == [job["id"]]
        assert job["id"] in json.loads(event["related_ids_json"])
        assert result["lifecycle_status"] == "cancelled"
    finally:
        cf.close()


def test_archived_campaign_rejects_new_operations(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(cf, tmp_path, provider="higgsfield")
        for status in ("producing", "completed", "archived"):
            cf.domains.creator_governance.transition_campaign(
                "may",
                new_status=status,
                actor="test",
                reason="fixture archival",
            )
        with pytest.raises(
            PermissionError, match="campaign_state_blocks_provider_spend"
        ):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )
    finally:
        cf.close()


def test_transition_preview_is_validation_equivalent_and_write_free(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        campaign = cf.domains.campaign_by_slug("may")
        cf.conn.execute(
            """
            INSERT INTO asset_inventory_reservations
            (id, asset_id, campaign_id, surface, reservation_id, reserved_by,
             reserved_at, status, created_at, updated_at)
            VALUES ('preview_reservation', 'asset_1', ?, 'reel',
                    'preview_reservation', 'test', '2026-07-30T12:00:00Z',
                    'pending', '2026-07-30T12:00:00Z', '2026-07-30T12:00:00Z')
            """,
            (campaign["id"],),
        )
        cf.conn.commit()
        before_events = cf.conn.execute(
            "SELECT COUNT(*) FROM campaign_lifecycle_events"
        ).fetchone()[0]

        plan = cf.domains.creator_governance.transition_campaign(
            "may",
            new_status="paused",
            actor="operator",
            reason="preview",
            validate_only=True,
        )

        assert plan["oldStatus"] == "approved"
        assert plan["pendingReservationsToRelease"] == ["preview_reservation"]
        assert (
            cf.domains.creator_governance.campaign_status("may")["lifecycle_status"]
            == "approved"
        )
        assert (
            cf.conn.execute(
                "SELECT status FROM asset_inventory_reservations "
                "WHERE id = 'preview_reservation'"
            ).fetchone()[0]
            == "pending"
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM campaign_lifecycle_events"
            ).fetchone()[0]
            == before_events
        )

        with pytest.raises(ValueError, match="illegal_campaign_transition"):
            cf.domains.creator_governance.transition_campaign(
                "may",
                new_status="archived",
                actor="operator",
                reason="invalid preview",
                validate_only=True,
            )
    finally:
        cf.close()


def test_governance_cli_preview_opens_database_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        authorize_campaign_governance(cf, tmp_path)
    finally:
        cf.close()
    before = _sha(settings.db_path)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "campaign-factory",
            "campaign-governance-transition",
            "--campaign",
            "may",
            "--status",
            "paused",
            "--actor",
            "operator",
            "--reason",
            "read-only preview",
        ],
    )

    assert cli_module.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["apply"] is False
    assert output["oldStatus"] == "production_ready"
    assert _sha(settings.db_path) == before


def test_identity_enrollment_requires_exact_origin_attestation(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorized = authorize_campaign_governance(cf, tmp_path)
        source = cf.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?",
            (authorized["identitySourceId"],),
        ).fetchone()
        cf.conn.execute(
            """
            INSERT INTO activity_events
            (id, event_type, campaign_id, source_asset_id, status, message,
             metadata_json, created_at)
            VALUES ('evt_invalid_origin_attestation',
                    'canonical_identity_origin_attested', ?, ?, 'warning',
                    'invalid newer attestation fixture', '{}',
                    '9999-12-31T23:59:59Z')
            """,
            (source["campaign_id"], source["id"]),
        )
        cf.conn.commit()
        profile = _identity_profile(
            "stacey",
            "soul_stacey_v2",
            source_id=source["id"],
            source_sha256=source["content_hash"],
        )
        manifest = tmp_path / "identity_without_origin.json"
        manifest.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")

        with pytest.raises(
            PermissionError,
            match="canonical_identity_origin_attestation_missing",
        ):
            cf.domains.creator_governance.enroll_identity_profile(
                "stacey",
                provider="higgsfield",
                provider_identity_id="soul_stacey_v2",
                profile=profile,
                canonical_source_asset_id=source["id"],
                identity_manifest_path=manifest,
                identity_manifest_sha256=_sha(manifest),
                operator="test",
            )
    finally:
        cf.close()


def test_authorization_evidence_is_rehashed_at_operation_time(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(cf, tmp_path, provider="higgsfield")
        grant = cf.conn.execute(
            """
            SELECT * FROM creator_authorization_events
            WHERE event_type = 'grant' AND provider = 'higgsfield'
            ORDER BY created_at LIMIT 1
            """
        ).fetchone()
        Path(grant["evidence_path"]).write_text("tampered", encoding="utf-8")

        with pytest.raises(
            PermissionError, match="creator_authorization_evidence_stale"
        ):
            cf.domains.creator_governance.resolve_operation(
                creator="stacey",
                campaign="may",
                operation="provider_spend",
                provider="higgsfield",
            )
    finally:
        cf.close()
