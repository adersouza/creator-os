from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from campaign_asset_test_support import add_audit_report
from campaign_factory.adapters.threadsdash_draft_payload import (
    DEFAULT_DRAFT_PAYLOAD_SCHEMA,
)
from campaign_factory.adapters.threadsdash_export_saga import (
    prepare_export,
    set_export_state,
)
from campaign_factory.production_readiness import build_production_readiness_proof
from campaign_test_support import (
    add_rendered_asset,
    authorize_campaign_governance,
    make_factory,
)

CLI_PYTHONPATH = ":".join(
    [
        str(Path(__file__).resolve().parents[1]),
        str(Path(__file__).resolve().parents[3] / "reel_factory"),
        str(Path(__file__).resolve().parents[4] / "packages" / "pipeline_contracts"),
        str(Path(__file__).resolve().parents[4] / "packages" / "creator_os_core"),
    ]
)
RUNTIME_SHA = "a" * 40
TD_SHA = "b" * 40


def test_production_readiness_proof_requires_real_operational_evidence(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
        )

        assert report["readyForSupervisedCanary"] is False
        assert report["gates"] == {
            "governanceAndSources": False,
            "exactFinalHandoff": False,
            "currentThreadsDashboardAcceptance": False,
            "postPromotionDailyOrchestrator": False,
        }
        assert (
            "no_governance_eligible_campaign_source" in report["operatorDataBlockers"]
        )
        assert "no_exact_final_asset_can_handoff" in report["operatorDataBlockers"]
        assert (
            "authoritative_runtime_promotion_receipt_missing"
            in report["runtimeProofBlockers"]
        )
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_production_readiness_proof_connects_exact_sha_to_current_acceptance(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(
            cf,
            tmp_path,
            creator="model",
            campaign="may",
            provider="higgsfield",
        )
        source, _ = add_rendered_asset(cf, tmp_path)
        for state in ("paused", "production_ready"):
            cf.domains.creator_governance.transition_campaign(
                "may", new_status=state, actor="test", reason="readiness fixture"
            )
        generation_source = tmp_path / "generation-source.png"
        generation_source.write_bytes(b"approved-generation-source")
        generation_sha = hashlib.sha256(generation_source.read_bytes()).hexdigest()
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, platform, source_prompt, account_ids_json,
             status, created_at, updated_at)
            VALUES ('source-generation-ready', ?, ?, ?, ?, ?,
                    'generation-source.png', 'image', 'instagram', '{}', '[]',
                    'approved', '2026-08-03T12:00:00Z', '2026-08-03T12:00:00Z')
            """,
            (
                source["campaign_id"],
                source["model_id"],
                generation_sha,
                str(generation_source),
                str(generation_source),
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO creative_plans
            (id, name, target_account, status, linked_campaign_slug,
             daily_base_video_target, style_lanes_json, created_at, updated_at)
            VALUES ('plan-ready', 'plan-ready', 'model', 'active', 'may', 1,
                    '[{"mode":"calm_animation"}]',
                    '2026-08-03T12:00:00Z', '2026-08-03T12:00:00Z')
            """
        )
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved', audit_status = 'approved_candidate',
                recipe = 'reviewed_non_generated_fixture'
            WHERE id = 'asset_1'
            """
        )
        asset = dict(
            cf.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()
        )
        add_audit_report(cf, rendered_asset_id="asset_1")
        cf.conn.execute(
            """
            INSERT INTO approval_decisions
            (id, campaign_id, rendered_asset_id, subject_sha256, decision,
             notes, created_at)
            VALUES ('approval-ready', ?, 'asset_1', ?, 'approved',
                    'operator would post', '2026-08-03T12:10:00Z')
            """,
            (asset["campaign_id"], asset["content_hash"]),
        )
        payload = {
            "schema": DEFAULT_DRAFT_PAYLOAD_SCHEMA,
            "drafts": [
                {
                    "renderedAssetId": "asset_1",
                    "sourceAssetId": source["id"],
                    "contentHash": asset["content_hash"],
                    "instagramAccountId": "ig_1",
                }
            ],
        }
        prepare_export(
            cf.conn,
            export_id="tdexp-ready",
            campaign_id=asset["campaign_id"],
            user_id="operator",
            manifest_path=str(tmp_path / "manifest.json"),
            payload=payload,
        )
        set_export_state(cf.conn, "tdexp-ready", "submitted")
        set_export_state(
            cf.conn,
            "tdexp-ready",
            "accepted",
            acknowledgment={"status": "accepted", "postIds": ["post-ready"]},
        )
        cf.conn.execute(
            """
            UPDATE threadsdash_exports
            SET acknowledged_at = '2026-08-03T13:00:00Z'
            WHERE id = 'tdexp-ready'
            """
        )
        cf.conn.execute(
            """
            INSERT INTO daily_orchestrator_runs
            (id, run_key, status, algorithm_version, policy_fingerprint,
             requested_items, selected_items, limits_json, stop_reason,
             next_run_reason, created_at, updated_at)
            VALUES ('run-ready', 'run-ready', 'completed', 'test', ?, 1, 1,
                    '{}', 'target_reached', 'next day',
                    '2026-08-03T12:30:00Z', '2026-08-03T12:31:00Z')
            """,
            ("c" * 64,),
        )
        cf.conn.execute(
            """
            INSERT INTO daily_orchestrator_items
            (id, run_id, ordinal, creator_id, campaign_id, source_asset_id,
             mode, intent, state, attempt_count, max_attempts, next_attempt_at,
             selection_reason_json, decision_fingerprint, result_json,
             error_code, created_at, updated_at)
            VALUES ('item-ready', 'run-ready', 0, ?, ?, ?,
                    'calm_animation', 'passive_selfie', 'completed', 1, 3, NULL,
                    '{}', ?, '{"schema":"campaign_factory.creation_batch.v1"}',
                    NULL, '2026-08-03T12:30:00Z', '2026-08-03T12:31:00Z')
            """,
            (
                source["model_id"],
                asset["campaign_id"],
                "source-generation-ready",
                "d" * 64,
            ),
        )
        cf.conn.commit()

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            promotion_receipt={
                "schema": "creator_os.runtime_promotion_receipt.v1",
                "receiptAuthority": "authoritative",
                "promotionId": "promotion-ready",
                "createdAt": "2026-08-03T12:00:00Z",
                "status": "promoted",
                "destinationCommitAfter": RUNTIME_SHA,
            },
            expected_runtime_sha=RUNTIME_SHA,
            threadsdash_deployed_sha=TD_SHA,
            threadsdash_deployed_at="2026-08-03T12:45:00Z",
            now="2026-08-03T14:00:00Z",
        )

        assert report["readyForSupervisedCanary"] is True, report
        assert report["handoff"]["handoffReadySha256s"] == [asset["content_hash"]]
        assert report["threadsdashboard"]["acceptedExports"][0]["finalSha256s"] == [
            asset["content_hash"]
        ]
        assert report["runtime"]["postPromotionCompletedRunCount"] == 1
        assert report["operatorDataBlockers"] == []
        assert report["runtimeProofBlockers"] == []
    finally:
        cf.close()


def test_production_readiness_proof_rejects_stale_or_incomplete_final_audit(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved', audit_status = 'approved_candidate',
                recipe = 'reviewed_non_generated_fixture'
            WHERE id = 'asset_1'
            """
        )
        asset = dict(
            cf.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()
        )
        audit = add_audit_report(cf, rendered_asset_id="asset_1")
        audit_payload = json.loads(Path(audit["path"]).read_text(encoding="utf-8"))
        audit_payload["readinessSummary"]["identityVerificationStatus"] = "pending"
        audit_payload["finalArtifactIntegrity"]["audioBinding"]["passed"] = False
        Path(audit["path"]).write_text(json.dumps(audit_payload), encoding="utf-8")
        cf.conn.execute(
            """
            INSERT INTO approval_decisions
            (id, campaign_id, rendered_asset_id, subject_sha256, decision,
             notes, created_at)
            VALUES ('approval-incomplete', ?, 'asset_1', ?, 'approved',
                    'fixture', '2026-08-03T12:10:00Z')
            """,
            (asset["campaign_id"], asset["content_hash"]),
        )
        cf.conn.commit()

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
        )

        assert report["handoff"]["handoffReadyCount"] == 0
        assert report["handoff"]["blockerCounts"] == {
            "current_sha_audio_qc_not_passed": 1,
            "current_sha_identity_qc_not_passed": 1,
        }
    finally:
        cf.close()


def test_production_readiness_cli_keeps_database_byte_identical(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    db_path = cf.settings.db_path
    approvals = cf.settings.creative_approvals_dir
    cf.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    completed = subprocess.run(
        [sys.executable, "-m", "campaign_factory.cli", "production-readiness-proof"],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(db_path),
            "CAMPAIGN_FACTORY_CREATIVE_APPROVALS": str(approvals),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["wouldWrite"] is False
    assert payload["readyForSupervisedCanary"] is False
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
