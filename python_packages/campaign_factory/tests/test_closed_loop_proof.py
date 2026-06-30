from __future__ import annotations

import json
from pathlib import Path

from campaign_factory.closed_loop_proof import (
    CONTEXT_KEYS,
    ClosedLoopProofRun,
    build_account_routing_audit,
    canonical_caption_context_for_fingerprint,
    context_fingerprint,
    discover_creator_account_context,
    run_stacey_closed_loop_proof,
    select_stacey_instagram_account,
)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def select(self, table, params):
        return self.rows.get(table, [])


def test_select_stacey_instagram_account_uses_active_account_in_stacey_group():
    client = FakeClient(
        {
            "account_groups": [
                {"id": "group_lola", "name": "Lola"},
                {"id": "group_stacey", "name": "Stacey main"},
            ],
            "instagram_accounts": [
                {
                    "id": "ig_z",
                    "username": "z_stacey",
                    "status": "active",
                    "is_active": True,
                    "group_id": "group_stacey",
                },
                {
                    "id": "ig_a",
                    "username": "a_stacey",
                    "status": "active",
                    "is_active": True,
                    "group_id": "group_stacey",
                },
                {
                    "id": "ig_inactive",
                    "username": "inactive",
                    "status": "disabled",
                    "is_active": False,
                    "group_id": "group_stacey",
                },
            ],
        }
    )

    account = select_stacey_instagram_account(client, user_id="user_1")

    assert account["instagramAccountId"] == "ig_a"
    assert account["username"] == "a_stacey"
    assert account["groupName"] == "Stacey main"


def test_creator_account_discovery_bridges_account_group_ids_to_accounts_table():
    client = FakeClient(
        {
            "account_groups": [
                {
                    "id": "group_stacey",
                    "name": "Stacey main",
                    "account_ids": ["thread_a"],
                },
            ],
            "accounts": [
                {
                    "id": "thread_a",
                    "username": "stacey_threads",
                    "status": "active",
                    "is_active": True,
                    "group_id": "group_stacey",
                },
            ],
            "instagram_accounts": [
                {
                    "id": "ig_a",
                    "username": "stacey_ig",
                    "status": "active",
                    "is_active": True,
                    "group_id": None,
                    "linked_account_id": "thread_a",
                },
            ],
        }
    )

    discovery = discover_creator_account_context(
        client, user_id="user_1", creator="Stacey"
    )

    assert discovery["selectedAccount"]["instagramAccountId"] == "ig_a"
    assert (
        discovery["selectedAccount"]["resolutionPath"]
        == "account_groups.account_ids->accounts->instagram_accounts"
    )
    assert discovery["bridgedInstagramAccounts"][0]["linkedAccountId"] == "thread_a"


def test_creator_account_discovery_bridges_accounts_to_instagram_by_unique_username():
    client = FakeClient(
        {
            "account_groups": [
                {
                    "id": "group_stacey",
                    "name": "Stacey main",
                    "account_ids": ["thread_a"],
                },
            ],
            "accounts": [
                {
                    "id": "thread_a",
                    "username": "staceybenw",
                    "status": "active",
                    "is_active": True,
                    "group_id": "group_stacey",
                },
            ],
            "instagram_accounts": [
                {
                    "id": "ig_a",
                    "username": "staceybenw",
                    "status": "active",
                    "is_active": True,
                    "group_id": None,
                },
            ],
        }
    )

    discovery = discover_creator_account_context(
        client, user_id="user_1", creator="Stacey"
    )

    assert discovery["selectedAccount"]["instagramAccountId"] == "ig_a"
    assert (
        discovery["selectedAccount"]["resolutionPath"]
        == "account_groups.account_ids->accounts.username->instagram_accounts.username"
    )
    assert discovery["bridgedInstagramAccounts"][0]["linkedAccountId"] == "thread_a"


def test_account_routing_audit_reports_creator_like_null_group_instagram_rows():
    client = FakeClient(
        {
            "account_groups": [
                {"id": "group_stacey", "name": "Stacey main", "account_ids": []},
            ],
            "accounts": [],
            "instagram_accounts": [
                {
                    "id": "ig_like",
                    "username": "bennett_staceyy",
                    "status": "active",
                    "is_active": True,
                    "group_id": None,
                },
            ],
        }
    )

    audit = build_account_routing_audit(client, user_id="user_1", creator="Stacey")

    assert audit["status"] == "blocked"
    assert (
        audit["creatorLikeUngroupedInstagramAccounts"][0]["instagramAccountId"]
        == "ig_like"
    )
    assert (
        "attach instagram_accounts to the Stacey group" in audit["recommendations"][0]
    )


def test_creator_account_discovery_stops_safely_when_bridge_is_ambiguous():
    client = FakeClient(
        {
            "account_groups": [
                {
                    "id": "group_stacey",
                    "name": "Stacey main",
                    "account_ids": ["thread_a"],
                },
            ],
            "accounts": [
                {
                    "id": "thread_a",
                    "username": "stacey_threads",
                    "status": "active",
                    "is_active": True,
                    "group_id": "group_stacey",
                },
            ],
            "instagram_accounts": [
                {
                    "id": "ig_a",
                    "username": "stacey_a",
                    "status": "active",
                    "is_active": True,
                    "group_id": None,
                    "linked_account_id": "thread_a",
                },
                {
                    "id": "ig_b",
                    "username": "stacey_b",
                    "status": "active",
                    "is_active": True,
                    "group_id": None,
                    "linked_account_id": "thread_a",
                },
            ],
        }
    )

    discovery = discover_creator_account_context(
        client, user_id="user_1", creator="Stacey"
    )

    assert discovery["selectedAccount"] is None
    assert discovery["status"] == "ambiguous"
    assert "ambiguous_bridge" in discovery["blockingReasons"]


def test_context_fingerprint_ignores_untracked_fields():
    context = {key: f"value:{key}" for key in CONTEXT_KEYS}
    with_extra = {**context, "debug": "ignored"}

    assert context_fingerprint(context) == context_fingerprint(with_extra)


def test_context_fingerprint_tracks_scene_compatibility_fields():
    context = {key: f"value:{key}" for key in CONTEXT_KEYS}
    changed = {**context, "sceneCompatibilityDecision": "blocked"}

    assert context_fingerprint(context) != context_fingerprint(changed)


def test_context_fingerprint_normalizes_absent_and_null_transport_fields():
    asset_context = {
        "caption_hash": "caption_hash",
        "render_recipe": None,
        "captionSceneFitVersion": None,
    }
    snapshot_context = {
        "caption_hash": "caption_hash",
    }

    assert canonical_caption_context_for_fingerprint(
        asset_context
    ) == canonical_caption_context_for_fingerprint(snapshot_context)
    assert context_fingerprint(asset_context) == context_fingerprint(snapshot_context)


def test_closed_loop_proof_writes_failed_stop_records(tmp_path: Path):
    run = ClosedLoopProofRun(campaign_slug="stacey_closed_loop", output_dir=tmp_path)

    result = run.stop("no_active_stacey_instagram_account", {"checkedGroups": []})

    json_path = tmp_path / "CLOSED_LOOP_PROOF.json"
    md_path = tmp_path / "CLOSED_LOOP_PROOF.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert result["result"] == "failed"
    assert data["stopReason"] == "no_active_stacey_instagram_account"
    assert data["campaign"]["slug"] == "stacey_closed_loop"
    assert "no_active_stacey_instagram_account" in markdown


def test_closed_loop_proof_stops_before_live_export_without_explicit_approval(
    monkeypatch, tmp_path: Path
):
    prompt_path = tmp_path / "stacey_prompt.json"
    output_path = tmp_path / "stacey.mp4"
    prompt_path.write_text("{}", encoding="utf-8")
    output_path.write_bytes(b"proof-render")
    export_called = {"value": False}

    class FakeSupabaseClient:
        def __init__(self, url, key):
            self.url = url
            self.key = key

        def select(self, table, params):
            rows = {
                "account_groups": [
                    {"id": "group_stacey", "name": "Stacey main", "account_ids": []}
                ],
                "accounts": [],
                "instagram_accounts": [
                    {
                        "id": "ig_stacey",
                        "username": "stacey_main",
                        "status": "active",
                        "is_active": True,
                        "group_id": "group_stacey",
                    }
                ],
            }
            return rows.get(table, [])

    class FakeFactory:
        def __init__(self, settings):
            self.settings = settings

        def campaign_by_slug(self, slug):
            return {"id": "campaign_1", "slug": slug}

        def export_manifest(self, *, campaign_slug):
            return {
                "assets": [
                    {
                        "renderedAssetId": "asset_1",
                        "filePath": str(output_path),
                        "contentHash": "content_1",
                        "captionHash": "caption_1",
                        "captionOutcomeContext": {
                            "caption_hash": "caption_1",
                            "creator_mix": "Stacey",
                            "rendered_output": str(output_path),
                        },
                    }
                ]
            }

        def distribution_plans_for_asset(self, rendered_asset_id):
            return [
                {
                    "id": "plan_1",
                    "renderedAssetId": rendered_asset_id,
                    "instagramAccountId": "ig_stacey",
                }
            ]

    def fake_readiness(*args, **kwargs):
        return {"liveExportAllowed": True, "blockingReasons": [], "warnings": []}

    def fail_export(*args, **kwargs):
        export_called["value"] = True
        raise AssertionError("live export must not run without --allow-live-export")

    monkeypatch.setattr(
        "campaign_factory.closed_loop_proof.SupabaseRestClient", FakeSupabaseClient
    )
    monkeypatch.setattr(
        "campaign_factory.closed_loop_proof.CampaignFactory", FakeFactory
    )
    monkeypatch.setattr(
        "campaign_factory.closed_loop_proof.evaluate_export_readiness", fake_readiness
    )
    monkeypatch.setattr(
        "campaign_factory.closed_loop_proof.export_threadsdash", fail_export
    )

    result = run_stacey_closed_loop_proof(
        campaign_slug="stacey_closed_loop",
        user_id="user_1",
        output_dir=tmp_path,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
        approved_rendered_asset_id="asset_1",
        prompt_path=prompt_path,
    )

    assert result["result"] == "pending"
    assert result["stopReason"] == "ready_for_live_export"
    assert result["distributionPlanId"] == "plan_1"
    assert export_called["value"] is False
