from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.reddit_handoff import (
    ORGANIC_AMATEUR_STYLE,
    build_reddit_daily_schedule,
    build_reddit_handoff_review,
    build_reddit_manual_handoff,
    build_reddit_trend_brief,
    record_reddit_reservation_receipt,
    set_reddit_proposed_assignment,
    write_reddit_manual_handoff,
)
from campaign_factory.reddit_library import (
    archive_reddit_assets,
    build_reddit_library_report,
)

from pipeline_contracts import validate_reddit_manual_handoff


def _sha(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _factory(tmp_path: Path) -> SimpleNamespace:
    media = tmp_path / "approved.jpg"
    media.write_bytes(b"approved-reddit-media")
    asset = {
        "id": "asset-1",
        "campaign_id": "campaign-1",
        "output_path": str(media),
        "content_hash": hashlib.sha256(media.read_bytes()).hexdigest(),
        "metadata_json": json.dumps(
            {
                "sourceFamilyId": "family-1",
                "perceptualFingerprint": "pdq:asset-1",
                "perceptualClusterId": "cluster-1",
            }
        ),
        "caption_generation_json": "{}",
    }
    approval = {
        "approvalId": "approval-1",
        "approvalFingerprint": "a" * 64,
        "schema": "campaign_factory.creative_approval.v2",
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE rendered_assets (
          id TEXT PRIMARY KEY, campaign_id TEXT, output_path TEXT, content_hash TEXT,
          metadata_json TEXT, caption_generation_json TEXT, review_state TEXT,
          source_asset_id TEXT, created_at TEXT, updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, output_path, content_hash, metadata_json,
         caption_generation_json, review_state, source_asset_id, created_at, updated_at)
        VALUES (:id, :campaign_id, :output_path, :content_hash, :metadata_json,
                :caption_generation_json, 'approved', 'source-1',
                '2026-07-30T21:00:00Z', '2026-07-30T22:00:00Z')
        """,
        asset,
    )
    events: list[dict] = []
    publishability = SimpleNamespace(
        rendered_asset=lambda asset_id: (
            dict(row)
            if (
                row := conn.execute(
                    "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
                ).fetchone()
            )
            else None
        ),
        creative_approval_for_asset=lambda _asset_id: {
            "state": "approved",
            "approvalId": "approval-1",
            "approvalFingerprint": approval["approvalFingerprint"],
            "approval": approval,
        },
    )
    domains = SimpleNamespace(
        campaign_by_slug=lambda slug: {"id": "campaign-1", "slug": slug},
        publishability=publishability,
        reel_execution=SimpleNamespace(
            model_slug_for_campaign=lambda _campaign_id: "larissa"
        ),
        campaign_dirs=lambda _model, _campaign: {
            "exports": tmp_path / "exports",
            "sources": tmp_path / "sources",
        },
        events=SimpleNamespace(
            record_event=lambda event_type, **kwargs: events.append(
                {"eventType": event_type, **kwargs}
            )
        ),
    )
    return SimpleNamespace(domains=domains, conn=conn, events=events)


def _spec() -> dict:
    rules = {"allowedMediaTypes": ["image"], "minimumSpacingMinutes": 15}
    return {
        "userId": "user-1",
        "renderedAssetId": "asset-1",
        "creator": {"id": "creator-larissa", "name": "Larissa"},
        "account": {
            "id": "reddit-account-1",
            "username": "u/Serious_material571",
        },
        "destination": {
            "subreddit": "r/example",
            "canonicalUrl": "https://www.reddit.com/r/example/",
        },
        "mediaUrl": "https://media.example.com/approved.jpg",
        "mediaType": "image",
        "content": {
            "title": "weekend mood",
            "firstComment": None,
            "nsfw": False,
            "spoiler": False,
            "flair": None,
        },
        "rules": {
            "snapshot": rules,
            "snapshotHash": _sha(rules),
            "reviewedAt": "2026-07-30T22:00:00Z",
            "reviewedBy": "operator",
            "reviewApproved": True,
            "verificationEvidence": {"status": "verified"},
            "accountRestrictionState": "active",
        },
        "scheduling": {
            "scheduledFor": "2026-07-31T13:00:00Z",
            "windowStart": "2026-07-31T13:00:00Z",
            "windowEnd": "2026-07-31T13:30:00Z",
            "spacingMinutes": 15,
            "queuePosition": 1,
            "dailyTarget": 8,
        },
        "trendBrief": None,
        "reuseException": None,
    }


def test_reddit_handoff_binds_exact_task_and_validates_contract(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    spec = _spec()
    review = build_reddit_handoff_review(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    spec["redditApproval"] = {
        "decision": "approved",
        "approvedBy": "operator",
        "approvedAt": "2026-07-30T22:05:00Z",
        "bindingFingerprint": review["approvalFingerprint"],
    }

    payload = build_reddit_manual_handoff(
        factory,
        campaign_slug="reddit-pilot",
        spec=spec,
        exported_at="2026-07-30T22:06:00Z",
    )

    assert validate_reddit_manual_handoff(payload) is None
    assert payload["approval"]["fingerprint"] == review["approvalFingerprint"]
    assert payload["asset"]["sourceFamilyId"] == "family-1"
    assert payload["rules"]["reviewApproved"] is True
    artifact = write_reddit_manual_handoff(
        factory, campaign_slug="reddit-pilot", payload=payload
    )
    assert json.loads(artifact.read_text()) == payload


def test_reddit_handoff_rejects_changed_approval_bound_field(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    spec = _spec()
    review = build_reddit_handoff_review(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    spec["redditApproval"] = {
        "decision": "approved",
        "approvedBy": "operator",
        "approvedAt": "2026-07-30T22:05:00Z",
        "bindingFingerprint": review["approvalFingerprint"],
    }
    spec["content"]["title"] = "changed after approval"

    with pytest.raises(ValueError, match="approval_binding_mismatch"):
        build_reddit_manual_handoff(factory, campaign_slug="reddit-pilot", spec=spec)


def test_reddit_handoff_rejects_claimed_media_type_mismatch(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    spec = _spec()
    spec["mediaType"] = "gif"

    with pytest.raises(ValueError, match="media_type_asset_mismatch"):
        build_reddit_handoff_review(factory, campaign_slug="reddit-pilot", spec=spec)


def test_reddit_reuse_exception_binds_transformed_media_identity(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    asset = factory.domains.publishability.rendered_asset("asset-1")
    exception_core = {
        "approvedBy": "operator",
        "approvedAt": "2026-07-30T22:04:00Z",
        "reason": "Reviewed transformed derivative for controlled reuse.",
        "priorTaskId": "11111111-1111-4111-8111-111111111111",
        "derivedMediaSha256": asset["content_hash"],
        "derivedPerceptualFingerprint": "pdq:asset-1",
        "transformReceiptFingerprint": "d" * 64,
    }
    spec = _spec()
    spec["reuseException"] = {
        **exception_core,
        "approvalFingerprint": _sha(exception_core),
    }

    review = build_reddit_handoff_review(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    assert review["approvalBinding"]["reuseException"]["priorTaskId"] == (
        "11111111-1111-4111-8111-111111111111"
    )

    spec["reuseException"]["derivedMediaSha256"] = "e" * 64
    with pytest.raises(ValueError, match="reuse_exception_media_sha_mismatch"):
        build_reddit_handoff_review(factory, campaign_slug="reddit-pilot", spec=spec)


def test_reddit_handoff_fails_closed_without_lineage(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    original = factory.domains.publishability.rendered_asset("asset-1")
    factory.domains.publishability.rendered_asset = lambda _asset_id: {
        **original,
        "metadata_json": "{}",
    }
    with pytest.raises(ValueError, match="lineage_missing"):
        build_reddit_handoff_review(factory, campaign_slug="reddit-pilot", spec=_spec())


def test_reddit_handoff_rejects_family_owned_by_another_account(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    metadata = {
        "sourceFamilyId": "family-1",
        "perceptualFingerprint": "pdq:variant-2",
        "perceptualClusterId": "cluster-2",
        "redditProposedAssignment": {
            "newAccount": "u/Adventurous-bill-745",
        },
    }
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, output_path, content_hash, metadata_json,
         caption_generation_json, review_state, source_asset_id, created_at, updated_at)
        SELECT 'asset-2', campaign_id, output_path, ?, ?, caption_generation_json,
               review_state, source_asset_id, created_at, updated_at
        FROM rendered_assets WHERE id = 'asset-1'
        """,
        ("b" * 64, json.dumps(metadata)),
    )

    with pytest.raises(ValueError, match="family_account_ownership_conflict"):
        build_reddit_handoff_review(factory, campaign_slug="reddit-pilot", spec=_spec())


def test_reddit_trend_brief_keeps_generation_recipe_organic() -> None:
    brief = build_reddit_trend_brief(
        {
            "subreddit": "r/example",
            "snapshotDate": "2026-07-30",
            "ruleSourceUrl": "https://www.reddit.com/r/example/about/rules",
            "rules": {"allowedMediaTypes": ["image"]},
            "patterns": [{"framing": "selfie", "lighting": "natural"}],
            "concepts": ["bedroom selfie", "hallway candid", "car selfie"],
        },
        created_at="2026-07-30T22:00:00Z",
    )
    assert brief["generationStyle"] == ORGANIC_AMATEUR_STYLE
    assert "compression" not in brief["generationStyle"].lower()
    assert len(brief["concepts"]) == 3


def test_reddit_daily_schedule_has_24_base_and_30_optional_slots() -> None:
    base = build_reddit_daily_schedule("2026-07-31")
    expanded = build_reddit_daily_schedule("2026-07-31", include_optional=True)

    assert len(base["slots"]) == 24
    assert len(expanded["slots"]) == 30
    for username in {
        "u/Serious_material571",
        "u/Adventurous-bill-745",
        "u/staceylazy",
    }:
        account_slots = [
            slot for slot in expanded["slots"] if slot["accountUsername"] == username
        ]
        assert [slot["queuePosition"] for slot in account_slots] == list(range(1, 11))
        assert len({slot["scheduledFor"] for slot in account_slots}) == 10


def test_proposed_account_can_change_only_before_committed_reservation(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    first = set_reddit_proposed_assignment(
        factory,
        campaign_slug="reddit-pilot",
        rendered_asset_id="asset-1",
        account_username="u/Serious_material571",
        operator="operator",
        reason="initial match",
        assigned_at="2026-07-30T22:01:00Z",
        apply=True,
    )
    changed = set_reddit_proposed_assignment(
        factory,
        campaign_slug="reddit-pilot",
        rendered_asset_id="asset-1",
        account_username="u/Adventurous-bill-745",
        operator="operator",
        reason="better subreddit fit",
        assigned_at="2026-07-30T22:02:00Z",
        apply=True,
    )
    assert first["oldAccount"] is None
    assert changed["oldAccount"] == "u/Serious_material571"
    assert changed["newAccount"] == "u/Adventurous-bill-745"
    assert [event["eventType"] for event in factory.events] == [
        "reddit_proposed_assignment_changed",
        "reddit_proposed_assignment_changed",
    ]

    spec = _spec()
    spec["account"]["username"] = "u/Adventurous-bill-745"
    review = build_reddit_handoff_review(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    spec["redditApproval"] = {
        "decision": "approved",
        "approvedBy": "operator",
        "approvedAt": "2026-07-30T22:05:00Z",
        "bindingFingerprint": review["approvalFingerprint"],
    }
    payload = build_reddit_manual_handoff(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    receipt_core = {
        "schema": "threadsdashboard.reddit_reservation_receipt.v1",
        "status": "committed",
        "taskId": "task-1",
        "idempotencyKey": payload["idempotencyKey"],
        "assetId": payload["asset"]["id"],
        "mediaSha256": payload["asset"]["mediaSha256"],
        "sourceFamilyId": payload["asset"]["sourceFamilyId"],
        "perceptualClusterId": payload["asset"]["perceptualClusterId"],
        "accountUsername": payload["account"]["username"],
        "subreddit": payload["destination"]["subreddit"],
        "committedAt": "2026-07-30T22:06:00Z",
    }
    record_reddit_reservation_receipt(
        factory,
        campaign_slug="reddit-pilot",
        payload=payload,
        delivery={
            "reservationReceipt": {
                **receipt_core,
                "receiptFingerprint": _sha(receipt_core),
            }
        },
    )
    with pytest.raises(ValueError, match="ownership_already_committed"):
        set_reddit_proposed_assignment(
            factory,
            campaign_slug="reddit-pilot",
            rendered_asset_id="asset-1",
            account_username="u/Serious_material571",
            operator="operator",
            reason="too late",
            apply=True,
        )


def test_reddit_library_views_and_coverage_are_computed_from_canonical_state(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    spec = _spec()
    review = build_reddit_handoff_review(
        factory, campaign_slug="reddit-pilot", spec=spec
    )
    spec["redditApproval"] = {
        "decision": "approved",
        "approvedBy": "operator",
        "approvedAt": "2026-07-30T22:05:00Z",
        "bindingFingerprint": review["approvalFingerprint"],
    }
    payload = build_reddit_manual_handoff(
        factory,
        campaign_slug="reddit-pilot",
        spec=spec,
        exported_at="2026-07-30T22:06:00Z",
    )
    write_reddit_manual_handoff(factory, campaign_slug="reddit-pilot", payload=payload)
    state = {
        "accounts": [
            {
                "id": "reddit-account-id-1",
                "username": "u/Serious_material571",
                "creator_id": "creator-larissa",
                "daily_target": 8,
                "is_active": True,
                "account_health": "active",
            }
        ],
        "subreddits": [
            {
                "name": "r/example",
                "status": "active",
                "eligible_creators": ["creator-larissa"],
                "eligible_accounts": ["u/Serious_material571"],
                "allowed_media_types": ["image"],
                "rule_review_approved": True,
                "account_restriction_state": "active",
                "verification_evidence": {"status": "verified"},
                "rule_snapshot_hash": payload["rules"]["snapshotHash"],
            }
        ],
        "contentOwners": [
            {
                "identity_type": "source_family",
                "identity_value": "family-1",
                "reddit_account_id": "reddit-account-id-1",
            }
        ],
        "tasks": [],
    }
    ready = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert [card["assetId"] for card in ready["views"]["Ready"]] == ["asset-1"]
    assert ready["views"]["Ready"][0]["accountUsername"] == ("u/Serious_material571")
    assert ready["coverage"]["u/Serious_material571"] == {
        "targetSlots": 56,
        "scheduledSlots": 0,
        "readySlots": 1,
        "totalSchedulableSlots": 1,
        "healthy": False,
        "uncoveredSlots": 55,
    }
    row = factory.domains.publishability.rendered_asset("asset-1")
    metadata = json.loads(row["metadata_json"])
    second_export = {
        **metadata["redditReadyExports"][0],
        "subreddit": "r/example2",
        "exportFingerprint": "b" * 64,
        "idempotencyKey": "second-ready-export",
    }
    metadata["redditReadyExports"].append(second_export)
    factory.conn.execute(
        "UPDATE rendered_assets SET metadata_json = ? WHERE id = ?",
        (json.dumps(metadata), "asset-1"),
    )
    state["subreddits"].append(
        {
            **state["subreddits"][0],
            "name": "r/example2",
        }
    )
    overlapping = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert overlapping["coverage"]["u/Serious_material571"]["readySlots"] == 1
    state["accounts"].append(
        {
            **state["accounts"][0],
            "id": "reddit-account-id-2",
            "username": "u/Adventurous-bill-745",
        }
    )
    state["contentOwners"].append(
        {
            "identity_type": "perceptual_cluster",
            "identity_value": "cluster-1",
            "reddit_account_id": "reddit-account-id-2",
        }
    )
    conflicted = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert conflicted["views"]["Exhausted"][0]["ownershipConflict"] is True
    state["accounts"].pop()
    state["contentOwners"].pop()
    task = {
        "id": "task-1",
        "account_username": "u/Serious_material571",
        "subreddit_name": "r/example",
        "source_family_id": "family-1",
        "perceptual_cluster_id": "cluster-1",
        "media_sha256": payload["asset"]["mediaSha256"],
        "handoff_status": "scheduled",
        "publication_status": "pending",
        "moderation_status": "unknown",
        "scheduled_for": "2026-07-31T13:00:00Z",
    }
    state["tasks"] = [task]
    reserved = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert [card["assetId"] for card in reserved["views"]["Reserved"]] == ["asset-1"]
    assert reserved["coverage"]["u/Serious_material571"]["scheduledSlots"] == 1
    task.update(
        {
            "handoff_status": "completed",
            "publication_status": "operator_reported",
        }
    )
    held = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert [card["assetId"] for card in held["views"]["Reconciliation Hold"]] == [
        "asset-1"
    ]
    assert held["cleanupManifest"]["automaticDeletion"] is False


def test_reddit_library_archive_is_non_destructive_and_state_derived(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    state = {"accounts": [], "subreddits": [], "contentOwners": [], "tasks": []}

    preview = archive_reddit_assets(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        asset_ids=["asset-1"],
        operator="operator",
        reason="Keep the weekly shelf trim.",
        as_of="2026-07-31T12:00:00Z",
    )
    assert preview["applied"] is False
    assert Path(
        factory.domains.publishability.rendered_asset("asset-1")["output_path"]
    ).is_file()

    applied = archive_reddit_assets(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        asset_ids=["asset-1"],
        operator="operator",
        reason="Keep the weekly shelf trim.",
        as_of="2026-07-31T12:00:00Z",
        apply=True,
    )
    assert applied["applied"] is True
    report = build_reddit_library_report(
        factory,
        campaign_slug="reddit-pilot",
        state=state,
        as_of="2026-07-31T12:00:00Z",
    )
    assert [card["assetId"] for card in report["views"]["Archived"]] == ["asset-1"]
    assert Path(
        factory.domains.publishability.rendered_asset("asset-1")["output_path"]
    ).is_file()
