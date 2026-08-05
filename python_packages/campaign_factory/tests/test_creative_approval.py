from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_factory.creative_approval import (
    APPROVAL_ATTESTATION_ISSUER,
    CreativeApprovalError,
    CreativeApprovalStore,
    _validate_higgsfield_ledger_for_approval,
    asset_requires_creative_approval,
    build_and_record_creative_approval_v2,
    canonical_asset_approval_bindings,
    load_creative_approval,
    validate_approval_for_draft,
    validate_creative_approval,
)
from creator_os_core.evidence_attestation import sign_evidence_attestation

from pipeline_contracts import SCHEMA_NAMES

EVIDENCE_SECRET = "creator-os-test-evidence-secret-32-bytes-long"
SPEND_SECRET = "creator-os-test-spend-secret-32-bytes-long"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_higgsfield_paid_asset_binds_exact_provider_execution(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "output.mp4"
    output.write_bytes(b"output")
    request_fingerprint = hashlib.sha256(b"provider-request").hexdigest()
    source_binding = {"path": str(source), "sha256": _sha(source)}
    output_binding = {"path": str(output), "sha256": _sha(output)}
    provider_receipt = {
        "schema": "reel_factory.higgsfield_production_receipt.v1",
        "status": "completed",
        "authorizationId": "auth-higgsfield-1",
        "providerRequestFingerprint": request_fingerprint,
        "model": "kling3_0_turbo",
        "generationId": "generation-higgsfield-1",
        "soulId": "soul-stacey-1",
        "source": source_binding,
        "finalOutput": output_binding,
    }
    provider_path = tmp_path / "higgsfield-receipt.json"
    provider_path.write_text(json.dumps(provider_receipt, sort_keys=True))
    recipe = {
        "schema": "campaign_factory.production_motion_recipe.v1",
        "recipeId": "cloud-passive-selfie-v2",
        "creator": "stacey",
        "intent": "passive_selfie",
        "modelId": "higgsfield_kling3_turbo_i2v",
        "provider": "higgsfield",
    }
    paid_evidence = {
        "schema": "campaign_factory.higgsfield_paid_generation_evidence.v1",
        "provider": "higgsfield",
        "authorizationId": "auth-higgsfield-1",
        "providerPlanFingerprint": request_fingerprint,
        "providerModel": "kling3_0_turbo",
        "generationId": "generation-higgsfield-1",
        "soulId": "soul-stacey-1",
        "costEventIds": ["cost-higgsfield-1"],
        "source": source_binding,
        "output": output_binding,
        "providerReceipt": {"path": str(provider_path), "sha256": _sha(provider_path)},
    }
    asset = {
        "id": "asset-higgsfield-1",
        "campaign_id": "campaign-1",
        "source_asset_id": "source-asset-1",
        "content_hash": output_binding["sha256"],
        "output_path": str(output),
        "frame_type": "generated_motion",
        "metadata_json": json.dumps(
            {
                "schema": "campaign_factory.motion_generation_asset.v1",
                "modelId": "higgsfield_kling3_turbo_i2v",
                "generationInput": source_binding,
                "productionMotionRecipe": recipe,
                "paidGeneration": True,
                "paidGenerationEvidence": paid_evidence,
            },
            sort_keys=True,
        ),
    }

    bindings = canonical_asset_approval_bindings(asset)

    assert bindings["executionEvidence"]["provider"] == "higgsfield"
    assert bindings["executionEvidence"]["providerEvidence"]["sha256"] == _sha(
        provider_path
    )
    assert bindings["input"] == source_binding
    assert bindings["output"] == output_binding

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE provider_spend_authorizations (
          authorization_id TEXT PRIMARY KEY, reservation_id TEXT, provider TEXT,
          campaign_id TEXT, request_fingerprint TEXT, scope_json TEXT, status TEXT
        );
        CREATE TABLE ai_cost_events (
          id TEXT PRIMARY KEY, reservation_id TEXT, campaign_id TEXT,
          provider TEXT, metadata_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO provider_spend_authorizations VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "auth-higgsfield-1",
            "reservation-higgsfield-1",
            "higgsfield",
            "campaign-1",
            request_fingerprint,
            json.dumps({"requestFingerprint": request_fingerprint}),
            "consumed",
        ),
    )
    conn.execute(
        "INSERT INTO ai_cost_events VALUES (?, ?, ?, ?, ?)",
        (
            "cost-higgsfield-1",
            "reservation-higgsfield-1",
            "campaign-1",
            "higgsfield",
            json.dumps(
                {
                    "authorizationId": "auth-higgsfield-1",
                    "jobId": "generation-higgsfield-1",
                    "requestFingerprint": request_fingerprint,
                    "model": "kling3_0_turbo",
                }
            ),
        ),
    )
    paid_evidence["reservationId"] = "reservation-higgsfield-1"
    asset["metadata_json"] = json.dumps(
        {
            **json.loads(asset["metadata_json"]),
            "paidGenerationEvidence": paid_evidence,
        },
        sort_keys=True,
    )
    _validate_higgsfield_ledger_for_approval(
        SimpleNamespace(conn=conn), asset, bindings
    )

    fabricated = {
        **bindings,
        "executionEvidence": {
            **bindings["executionEvidence"],
            "authorizationId": "fabricated-authorization",
        },
    }
    with pytest.raises(
        CreativeApprovalError,
        match="creative_approval_higgsfield_authorization_missing",
    ):
        _validate_higgsfield_ledger_for_approval(
            SimpleNamespace(conn=conn), asset, fabricated
        )

    conn.execute("DELETE FROM ai_cost_events")
    with pytest.raises(
        CreativeApprovalError, match="creative_approval_higgsfield_cost_missing"
    ):
        _validate_higgsfield_ledger_for_approval(
            SimpleNamespace(conn=conn), asset, bindings
        )

    provider_receipt["generationId"] = "substituted-generation"
    provider_path.write_text(json.dumps(provider_receipt, sort_keys=True))
    with pytest.raises(
        CreativeApprovalError,
        match="creative_approval_provider_execution_evidence_missing_or_substituted",
    ):
        canonical_asset_approval_bindings(asset)


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _review_decision() -> dict:
    return {
        "identityAcceptable": True,
        "faceStable": True,
        "bodyConsistent": True,
        "anatomyAcceptable": True,
        "motionAcceptable": True,
        "captionAcceptable": True,
        "audioAcceptable": True,
        "intentSatisfied": True,
        "wouldPost": True,
        "notes": None,
    }


def _operator_review_file(
    tmp_path: Path,
    *,
    asset_id: str,
    final_sha: str,
    manifest_sha: str,
    suffix: str = "",
) -> dict:
    core = {
        "schema": "creator_os.operator_media_review.v1",
        "reviewId": f"review{suffix or '-1'}",
        "renderedAssetId": asset_id,
        "finalSha256": final_sha,
        "reviewManifestSha256": manifest_sha,
        "reviewedBy": "operator",
        "reviewedAt": "2026-07-22T20:02:00Z",
        **_review_decision(),
    }
    payload = {**core, "reviewFingerprint": _fingerprint(core)}
    path = tmp_path / f"operator-review{suffix}.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "sha256": _sha(path)}


def _final_artifact_qc_item(
    tmp_path: Path, final_sha: str, *, suffix: str = ""
) -> dict:
    receipt = {
        "subjectSha256": final_sha,
        "overallVerdict": "pass",
        "readinessSummary": {
            "uploadReady": True,
            "blockingReasons": [],
            "blockingCodes": [],
        },
        "finalArtifactIntegrity": {
            "schema": "campaign_factory.final_artifact_integrity.v1",
            "subjectSha256": final_sha,
            "passed": True,
            "decode": {"passed": True},
            "probe": {"passed": True},
            "captionBinding": {"passed": True},
            "audioBinding": {"passed": True},
        },
        "analyzerEvidence": {
            "analyzerVersion": "test",
            "implementationFingerprint": "f" * 64,
            "implementationComponents": {"similarity.js": "e" * 64},
        },
    }
    path = tmp_path / f"final-artifact-audit{suffix}.json"
    path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return {
        "checkId": "contentforge.final_artifact_audit",
        "receiptPath": str(path),
        "receiptSha256": _sha(path),
        "subjectSha256": final_sha,
        "passed": True,
    }


def _sign_v2(core: dict) -> dict:
    payload = {**core, "approvalFingerprint": _fingerprint(core)}
    attestation = sign_evidence_attestation(
        payload,
        issuer=APPROVAL_ATTESTATION_ISSUER,
        issued_at=core["approvedAt"],
        secret=EVIDENCE_SECRET,
    )
    return {**payload, "operatorAttestation": attestation}


def _resign_v2(payload: dict) -> None:
    core = dict(payload)
    core.pop("approvalFingerprint", None)
    core.pop("operatorAttestation", None)
    payload.clear()
    payload.update(_sign_v2(core))


def _approval(tmp_path: Path) -> dict:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.mp4"
    receipt = tmp_path / "qc.json"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    receipt.write_text("{}")
    core = {
        "schema": "campaign_factory.creative_approval.v1",
        "approvalId": "approval-1",
        "approvedBy": "operator",
        "approvedAt": "2026-07-22T12:00:00Z",
        "creatorIdentity": {"id": "stacey", "fingerprint": "a" * 64},
        "contentIntent": {"id": "intent-1", "fingerprint": "b" * 64},
        "benchmarkRecipe": {"id": "recipe-1", "fingerprint": "c" * 64},
        "model": {"id": "local-model", "fingerprint": "d" * 64},
        "input": {"path": str(source), "sha256": _sha(source)},
        "output": {"path": str(output), "sha256": _sha(output)},
        "qcEvidence": [
            {
                "checkId": "contentforge.motion_specific_qc",
                "receiptPath": str(receipt),
                "receiptSha256": _sha(receipt),
                "subjectSha256": _sha(output),
                "passed": True,
            }
        ],
        "exportPayload": {
            "schema": "campaign_draft_payload.v2",
            "fingerprint": "e" * 64,
        },
        "contentSemantics": {
            "burnedOverlayText": None,
            "instagramPostCaption": "caption",
            "generatedAudio": None,
            "sourceAudio": None,
            "nativeInstagramAudio": {"status": "needs_operator_selection"},
        },
    }
    return {**core, "approvalFingerprint": _fingerprint(core)}


class _BuilderPublishability:
    def __init__(
        self, asset: dict, receipt: dict, *, audit_path: Path | None = None
    ) -> None:
        self.asset = asset
        self.audit_path = audit_path
        canonical = json.dumps(receipt, separators=(",", ":"), sort_keys=True)
        self.row = {
            "receipt_json": canonical,
            "receipt_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }

    def rendered_asset(self, rendered_asset_id: str) -> dict:
        assert rendered_asset_id == self.asset["id"]
        return self.asset

    def motion_qc_gate(self, _asset: dict) -> dict:
        return {"failures": []}

    def latest_motion_qc_receipt(self, _rendered_asset_id: str) -> dict:
        return self.row

    def latest_audit_for_asset(self, _rendered_asset_id: str) -> dict:
        return {
            "subjectSha256": self.asset["content_hash"],
            "reportPath": str(self.audit_path) if self.audit_path else None,
        }


class _BuilderFactory:
    def __init__(
        self, asset: dict, receipt: dict, *, audit_path: Path | None = None
    ) -> None:
        asset.setdefault("review_state", "approved")
        campaign = {"id": asset["campaign_id"], "slug": "may"}
        publishability = _BuilderPublishability(asset, receipt, audit_path=audit_path)

        class _Domains:
            pass

        self.domains = _Domains()
        self.domains.publishability = publishability
        self.domains.campaign_by_slug = lambda slug: campaign if slug == "may" else None


def test_static_reel_requires_exact_v2_approval_and_builds_from_final_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    still = tmp_path / "approved-still.jpg"
    output = tmp_path / "static-reel.mp4"
    still.write_bytes(b"approved-still")
    output.write_bytes(b"static-reel")
    asset = {
        "id": "static-asset-1",
        "campaign_id": "campaign-1",
        "source_asset_id": "source-asset-1",
        "content_hash": _sha(output),
        "output_path": str(output),
        "recipe": "static_mp4",
        "creator_model": "Stacey",
        "content_surface": "reel",
        "metadata_json": json.dumps(
            {
                "humanReviewRequired": True,
                "staticMp4Render": {"stillPath": str(still)},
                "generatedAssetLineage": {
                    "source": {
                        "parentStillPath": str(still),
                        "parentStillHash": _sha(still),
                    },
                    "generation": {"tool": "reel_factory.static_mp4"},
                },
            },
            sort_keys=True,
        ),
    }
    audit = {
        "subjectSha256": asset["content_hash"],
        "overallVerdict": "pass",
        "readinessSummary": {
            "uploadReady": True,
            "blockingReasons": [],
            "blockingCodes": [],
        },
        "finalArtifactIntegrity": {
            "schema": "campaign_factory.final_artifact_integrity.v1",
            "subjectSha256": asset["content_hash"],
            "passed": True,
            "decode": {"passed": True},
            "probe": {"passed": True},
            "captionBinding": {"passed": True},
            "audioBinding": {"passed": True},
        },
        "analyzerEvidence": {
            "analyzerVersion": "test",
            "implementationFingerprint": "f" * 64,
            "implementationComponents": {"similarity.js": "e" * 64},
        },
    }
    audit_path = tmp_path / "static-final-audit.json"
    audit_path.write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    draft = {
        "campaignId": "campaign-1",
        "renderedAssetId": asset["id"],
        "sourceAssetId": asset["source_asset_id"],
        "contentHash": asset["content_hash"],
        "content": "A real post caption",
        "instagramPostCaption": "A real post caption",
        "burnedCaptionText": None,
        "audioIntent": {},
    }
    factory = _BuilderFactory(asset, {}, audit_path=audit_path)
    monkeypatch.setattr(
        "campaign_factory.adapters.threadsdash_draft_delivery.export_threadsdash",
        lambda *_args, **_kwargs: {
            "payload": {
                "schema": "campaign_factory.threadsdash_drafts.v3",
                "drafts": [draft],
            }
        },
    )

    assert asset_requires_creative_approval(asset) is True
    result = build_and_record_creative_approval_v2(
        factory,
        campaign_slug="may",
        rendered_asset_id=asset["id"],
        user_id="operator-user",
        approved_by="operator",
        review_decision=_review_decision(),
        root=tmp_path / "static-approvals",
    )
    approval = load_creative_approval(Path(result["approvalPath"]))

    assert approval["qcEvidence"][0]["checkId"] == "contentforge.final_artifact_audit"
    assert approval["output"]["sha256"] == asset["content_hash"]
    assert (
        validate_approval_for_draft(approval, draft, campaign_slug="may")["approval"]
        == approval
    )


def test_creative_approval_binds_every_exact_artifact(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    assert validate_creative_approval(payload) == payload
    store = CreativeApprovalStore(tmp_path / "approvals")
    with pytest.raises(CreativeApprovalError, match="v1_read_only"):
        store.record(payload)


def test_creative_approval_v1_is_preserved_as_non_operational_history(
    tmp_path: Path,
) -> None:
    payload = _approval(tmp_path)
    root = tmp_path / "approvals"
    root.mkdir()
    path = root / f"{payload['approvalId']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_creative_approval(path) == payload

    store = CreativeApprovalStore(root)
    inventory = store.legacy_inventory()
    assert inventory["summary"] == {
        "historicalV1Records": 1,
        "operationallyEligible": 0,
        "automaticallyMigratable": 0,
        "unsafeJsonPaths": 0,
    }
    assert inventory["records"][0]["classification"] == "valid_historical_v1"
    assert inventory["records"][0]["blockingReason"] == (
        "creative_approval_v1_not_operational"
    )
    assert inventory["records"][0]["automaticallyMigratable"] is False


def test_creative_approval_inventory_never_follows_symlinks(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / "approvals"
    root.mkdir()
    unsafe = root / "unsafe.json"
    unsafe.symlink_to(outside)

    store = CreativeApprovalStore(root)
    inventory = store.legacy_inventory()
    assert inventory["summary"]["historicalV1Records"] == 0
    assert inventory["summary"]["unsafeJsonPaths"] == 1
    assert inventory["unsafePaths"] == [str(unsafe.absolute())]
    with pytest.raises(CreativeApprovalError, match="missing_or_unsafe"):
        load_creative_approval(unsafe)


def test_v2_contract_is_visible_through_the_canonical_manifest() -> None:
    assert SCHEMA_NAMES["creative_approval_v2"] == "creative_approval.v2.schema.json"


def test_creative_approval_rejects_output_substitution(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    Path(payload["output"]["path"]).write_bytes(b"substituted")
    with pytest.raises(CreativeApprovalError, match="output_missing_or_substituted"):
        validate_creative_approval(payload)


def test_active_production_motion_still_requires_exact_v2_approval() -> None:
    assert (
        asset_requires_creative_approval(
            {
                "metadata": {
                    "schema": "campaign_factory.motion_generation_asset.v1",
                    "productionMotionRecipe": {"status": "active"},
                    "creativeApprovalRequired": False,
                    "humanReviewRequired": False,
                }
            }
        )
        is True
    )


def test_creative_approval_rejects_failed_qc(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    payload["qcEvidence"][0]["passed"] = False
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    with pytest.raises(CreativeApprovalError, match="qc_blocked"):
        validate_creative_approval(payload)


def test_creative_approval_rejects_semantic_conflation(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    payload["contentSemantics"].pop("nativeInstagramAudio")
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    with pytest.raises(CreativeApprovalError, match="content_semantics_invalid"):
        validate_creative_approval(payload)
