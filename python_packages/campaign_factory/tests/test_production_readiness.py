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
from campaign_factory.adapters.threadsdash_handoff_evidence import (
    canonical_fingerprint,
    contract_binding,
)
from campaign_factory.production_readiness import build_production_readiness_proof
from campaign_test_support import (
    add_rendered_asset,
    authorize_campaign_governance,
    make_factory,
)
from creator_os_core.evidence_attestation import sign_evidence_attestation

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
EVIDENCE_SECRET = "production-readiness-test-secret-000000000000000000"


def _deployment_receipt(*, observed_at: str = "2026-08-03T13:00:00Z") -> dict:
    core = {
        "schema": "threadsdashboard.deployment_receipt.v1",
        "receiptId": "td-deploy-ready",
        "repository": "adersouza/ThreadsDashboard",
        "environment": "production",
        "provider": "vercel",
        "projectId": "threadsdashboard",
        "deploymentId": "deployment-ready",
        "deploymentStatus": "READY",
        "productionAliasCurrent": True,
        "deployedCommit": TD_SHA,
        "deployedAt": "2026-08-03T12:45:00Z",
        "observedAt": observed_at,
        "contract": contract_binding(DEFAULT_DRAFT_PAYLOAD_SCHEMA),
    }
    return {
        **core,
        "producerAttestation": sign_evidence_attestation(
            core,
            issuer="threadsdashboard.deployment",
            issued_at=core["observedAt"],
            secret=EVIDENCE_SECRET,
        ),
    }


def _verified_audio_intent(final_sha256: str) -> dict:
    return {
        "schema": "pipeline.audio_intent.v1",
        "policy": "embedded_trending_required",
        "mode": "embedded_trending_audio",
        "required": True,
        "status": "verified",
        "fulfillment": {
            "status": "verified",
            "proof_type": "embedded_output_audio_stream",
            "evidence_class": "EXACT_BYTE_VERIFIED",
            "output_sha256": final_sha256,
        },
        "rights": {
            "required": True,
            "usageRightsStatus": "licensed",
            "rightsSource": "operator_license",
            "territory": "US",
            "accountScope": "ig_1",
            "commercialUseAllowed": True,
            "evidenceReceipt": "rights-receipt-ready",
            "expiresAt": "2027-08-03T00:00:00Z",
        },
        "gates": {"allow_live_schedule": True, "allow_publish": True},
    }


def _setup_ready_chain(
    cf, tmp_path: Path, *, disconnect_runtime: bool = False
) -> tuple[dict, dict, Path]:
    authorize_campaign_governance(
        cf,
        tmp_path,
        creator="model",
        campaign="may",
        provider="higgsfield",
    )
    source, _ = add_rendered_asset(cf, tmp_path)
    cf.conn.execute(
        "UPDATE source_assets SET media_type = 'image', status = 'approved' WHERE id = ?",
        (source["id"],),
    )
    for state in ("paused", "production_ready"):
        cf.domains.creator_governance.transition_campaign(
            "may", new_status=state, actor="test", reason="readiness fixture"
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
        cf.conn.execute("SELECT * FROM rendered_assets WHERE id = 'asset_1'").fetchone()
    )
    audit = add_audit_report(cf, rendered_asset_id="asset_1")
    audit_sha = hashlib.sha256(Path(audit["path"]).read_bytes()).hexdigest()
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
    publishability = {
        "exportable": True,
        "publishableCandidate": True,
        "failureReasons": [],
    }
    handoff_manifest = {"surfaceReadiness": {"canHandoff": True, "scheduleSafe": True}}
    payload = {
        "schema": DEFAULT_DRAFT_PAYLOAD_SCHEMA,
        "drafts": [
            {
                "campaignId": asset["campaign_id"],
                "renderedAssetId": "asset_1",
                "sourceAssetId": source["id"],
                "contentHash": asset["content_hash"],
                "instagramAccountId": "ig_1",
                "distributionPlanId": "distribution-ready",
                "plannedWindowStart": "2026-08-03T15:00:00Z",
                "plannedWindowEnd": "2026-08-03T16:00:00Z",
                "publishability": publishability,
                "handoffManifest": handoff_manifest,
                "metadata": {
                    "campaign_factory": {"account_eligibility": {"allowed": True}}
                },
                "audioIntent": _verified_audio_intent(asset["content_hash"]),
                "mediaPreparation": {
                    "schema": "creator_os.media_preparation_evidence.v1",
                    "method": "exact_final",
                    "outputSha256": asset["content_hash"],
                    "auditReportId": audit["id"],
                    "auditReportSha256": audit_sha,
                    "auditSubjectSha256": asset["content_hash"],
                    "auditStatus": "approved_candidate",
                    "auditOverallVerdict": "pass",
                    "qcStatus": "passed",
                    "postProcessChain": [],
                },
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"payload": payload}), encoding="utf-8")
    prepare_export(
        cf.conn,
        export_id="tdexp-ready",
        campaign_id=asset["campaign_id"],
        user_id="operator",
        manifest_path=str(manifest_path),
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
    batch = {
        "schema": "campaign_factory.production_batch.v1",
        "results": [
            {
                "status": "completed",
                "renderedAssetId": "asset_1",
                "outputSha256": asset["content_hash"],
            }
        ],
        "summary": {"requested": 1, "completed": 1, "failed": 0},
    }
    runtime_source_id = source["id"]
    if disconnect_runtime:
        other_path = tmp_path / "other-source.png"
        other_path.write_bytes(b"other-source")
        runtime_source_id = "source-other"
        cf.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, media_type, platform, source_prompt, account_ids_json,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'other-source.png', 'image', 'instagram',
                    '{}', '[]', 'approved',
                    '2026-08-03T12:00:00Z', '2026-08-03T12:00:00Z')
            """,
            (
                runtime_source_id,
                source["campaign_id"],
                source["model_id"],
                hashlib.sha256(other_path.read_bytes()).hexdigest(),
                str(other_path),
                str(other_path),
            ),
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
                '{}', ?, ?, NULL,
                '2026-08-03T12:30:00Z', '2026-08-03T12:31:00Z')
        """,
        (
            source["model_id"],
            asset["campaign_id"],
            runtime_source_id,
            "d" * 64,
            json.dumps(batch, sort_keys=True),
        ),
    )
    cf.conn.commit()
    return source, asset, manifest_path


def _proof_kwargs() -> dict:
    return {
        "promotion_receipt": {
            "schema": "creator_os.runtime_promotion_receipt.v1",
            "receiptAuthority": "authoritative",
            "promotionId": "promotion-ready",
            "createdAt": "2026-08-03T12:00:00Z",
            "status": "promoted",
            "destinationCommitAfter": RUNTIME_SHA,
        },
        "expected_runtime_sha": RUNTIME_SHA,
        "threadsdash_deployment_receipt": _deployment_receipt(),
        "now": "2026-08-03T14:00:00Z",
    }


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
            "schedulingEligibility": False,
            "postPromotionDailyOrchestrator": False,
            "linkedCanaryChain": False,
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
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        _, asset, _ = _setup_ready_chain(cf, tmp_path)

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **_proof_kwargs(),
        )

        assert report["readyForSupervisedCanary"] is True, report
        assert report["handoff"]["handoffReadySha256s"] == [asset["content_hash"]]
        assert report["canaryCandidates"][0]["finalSha256"] == asset["content_hash"]
        assert report["canaryCandidates"][0]["postId"] == "post-ready"
        assert report["runtime"]["postPromotionCompletedRunCount"] == 1
        assert report["operatorDataBlockers"] == []
        assert report["runtimeProofBlockers"] == []
    finally:
        cf.close()


def test_production_readiness_rejects_disconnected_operational_edges(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        _setup_ready_chain(cf, tmp_path, disconnect_runtime=True)

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **_proof_kwargs(),
        )

        assert report["gates"]["governanceAndSources"] is True
        assert report["gates"]["exactFinalHandoff"] is True
        assert report["gates"]["currentThreadsDashboardAcceptance"] is True
        assert report["gates"]["postPromotionDailyOrchestrator"] is True
        assert report["gates"]["linkedCanaryChain"] is False
        assert report["readyForSupervisedCanary"] is False
    finally:
        cf.close()


def test_production_readiness_rejects_tampered_calm_source(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        source, _, _ = _setup_ready_chain(cf, tmp_path)
        Path(source["stored_path"]).write_bytes(b"tampered-source")

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **_proof_kwargs(),
        )

        assert report["gates"]["governanceAndSources"] is False
        blocked_sources = [
            item
            for campaign in report["governance"]["blockedCampaigns"]
            for item in campaign["sources"]
            if item["sourceAssetId"] == source["id"]
        ]
        assert "approved_source_bytes_unverified" in blocked_sources[0]["blockers"]
        assert report["readyForSupervisedCanary"] is False
    finally:
        cf.close()


def test_production_readiness_rejects_missing_audio_rights(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        _, _, manifest_path = _setup_ready_chain(cf, tmp_path)
        wrapper = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = wrapper["payload"]
        payload["drafts"][0]["audioIntent"]["rights"]["usageRightsStatus"] = (
            "rights_unknown"
        )
        manifest_path.write_text(json.dumps(wrapper), encoding="utf-8")
        cf.conn.execute(
            "UPDATE threadsdash_exports SET request_fingerprint = ? WHERE id = ?",
            (canonical_fingerprint(payload), "tdexp-ready"),
        )
        cf.conn.commit()

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **_proof_kwargs(),
        )

        assert report["gates"]["schedulingEligibility"] is False
        assert report["threadsdashboard"]["blockerCounts"] == {
            "audio_rights_receipt_missing_or_invalid": 1
        }
        assert report["readyForSupervisedCanary"] is False
    finally:
        cf.close()


def test_production_readiness_rejects_forged_deployment_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        _setup_ready_chain(cf, tmp_path)
        kwargs = _proof_kwargs()
        kwargs["threadsdash_deployment_receipt"]["deployedCommit"] = "c" * 40

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **kwargs,
        )

        assert (
            "threadsdashboard_deployment_receipt_unauthentic"
            in report["runtimeProofBlockers"]
        )
        assert report["readyForSupervisedCanary"] is False
    finally:
        cf.close()


def test_production_readiness_rejects_stale_deployment_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)
    cf = make_factory(tmp_path)
    try:
        _setup_ready_chain(cf, tmp_path)
        kwargs = _proof_kwargs()
        kwargs["threadsdash_deployment_receipt"] = _deployment_receipt(
            observed_at="2026-08-03T12:59:00Z"
        )

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
            **kwargs,
        )

        assert (
            "threadsdashboard_deployment_receipt_stale"
            in report["runtimeProofBlockers"]
        )
        assert report["gates"]["currentThreadsDashboardAcceptance"] is False
        assert report["readyForSupervisedCanary"] is False
    finally:
        cf.close()


def test_production_readiness_rejects_contentforge_run_substitution(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        _, _, _ = _setup_ready_chain(cf, tmp_path)
        audit = cf.conn.execute(
            "SELECT report_path FROM audit_reports WHERE rendered_asset_id = 'asset_1'"
        ).fetchone()
        audit_path = Path(audit["report_path"])
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        payload["contentForgeRunId"] = "substituted-run"
        audit_path.write_text(json.dumps(payload), encoding="utf-8")

        report = build_production_readiness_proof(
            cf.conn,
            creative_approvals_dir=cf.settings.creative_approvals_dir,
        )

        assert report["handoff"]["blockerCounts"] == {
            "current_sha_contentforge_receipt_binding_mismatch": 1
        }
        assert report["readyForSupervisedCanary"] is False
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
