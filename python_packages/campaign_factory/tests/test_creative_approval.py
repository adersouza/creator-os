from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from campaign_asset_test_support import add_audit_report
from campaign_factory.adapters import (
    threadsdash_draft_delivery as threadsdash_delivery_adapter,
)
from campaign_factory.adapters.threadsdash_draft_delivery import export_threadsdash
from campaign_factory.cost_tracker import ensure_cost_table
from campaign_factory.creative_approval import (
    APPROVAL_ATTESTATION_ISSUER,
    CreativeApprovalError,
    CreativeApprovalStore,
    build_and_record_creative_approval_v2,
    canonical_asset_approval_bindings,
    creative_export_projection,
    load_creative_approval,
    validate_approval_for_draft,
    validate_creative_approval,
)
from campaign_factory.motion_generation_stage import (
    _paid_generation_evidence,
    _record_paid_motion_execution_receipt,
    _verify_paid_authorization_at_call,
)
from creator_os_core.evidence_attestation import sign_evidence_attestation
from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA_V2,
    build_video_provider_spend_scope,
    sign_authorization,
    verify_authorization_v2,
)
from test_motion_generation_stage import (
    _asset_source_sha256,
    _motion_qc_receipt,
    _register_motion_fixture,
    _write_motion_qc_receipt,
    add_source_asset,
    make_factory,
)

from pipeline_contracts import SCHEMA_NAMES

EVIDENCE_SECRET = "creator-os-test-evidence-secret-32-bytes-long"
SPEND_SECRET = "creator-os-test-spend-secret-32-bytes-long"


@pytest.fixture(autouse=True)
def _evidence_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def _v2_fixture(tmp_path: Path) -> tuple[dict, dict, dict]:
    source = tmp_path / "source-v2.jpg"
    output = tmp_path / "output-v2.mp4"
    receipt = tmp_path / "motion-qc-v2.json"
    source.write_bytes(b"source-v2")
    output.write_bytes(b"output-v2")
    receipt.write_text(
        json.dumps(
            _motion_qc_receipt(_sha(output), source_sha256=_sha(source)),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    model_id = "local_wan22_i2v_a14b_q4_mlx"
    identity = {"profileId": "stacey", "creatorKey": "stacey"}
    intent = {"intentId": "intent-1", "purpose": "organic_reel"}
    recipe = {"recipeId": "recipe-1", "task": "image_to_video"}
    model_fingerprint = "8" * 64
    decision = {
        "decisionId": "router-decision-1",
        "selectedModelId": model_id,
        "selectedModelFingerprint": model_fingerprint,
    }
    admission_core = {
        "schema": "campaign_factory.local_motion_admission.v1",
        "routerDecision": decision,
        "evidenceRecords": {
            "creatorIdentityProfile": identity,
            "contentIntent": intent,
            "benchmarkRecipe": recipe,
        },
    }
    admission = {
        **admission_core,
        "admissionFingerprint": _fingerprint(admission_core),
    }
    asset = {
        "id": "rendered-asset-1",
        "campaign_id": "campaign-1",
        "source_asset_id": "source-asset-1",
        "content_hash": _sha(output),
        "output_path": str(output),
        "recipe": model_id,
        "frame_type": "generated_motion",
        "created_at": "2026-07-22T20:01:30Z",
        "metadata_json": json.dumps(
            {
                "schema": "campaign_factory.motion_generation_asset.v1",
                "requestFingerprint": "1" * 64,
                "modelId": model_id,
                "generationInput": {"path": str(source), "sha256": _sha(source)},
                "localMotionAdmission": admission,
            },
            sort_keys=True,
        ),
    }
    draft = {
        "campaignId": "campaign-1",
        "renderedAssetId": asset["id"],
        "sourceAssetId": asset["source_asset_id"],
        "contentHash": asset["content_hash"],
        "accountId": "account-1",
        "instagramAccountId": "instagram-1",
        "distributionPlanId": "plan-1",
        "distributionSurface": "instagram_reel",
        "contentSurface": "reel",
        "content": "A real post caption",
        "instagramPostCaption": "A real post caption",
        "instagramPostCaptionHash": "3" * 64,
        "burnedCaptionText": "Short hook",
        "burnedCaptionHash": "4" * 64,
        "overlaySemanticQc": {"passed": True, "policyVersion": "2.0.0"},
        "captionTimingQc": {"passed": True, "policyVersion": "2.0.0"},
        "publishMode": "auto",
        "instagramTrialReels": False,
        "trialGraduationStrategy": None,
        "shareToFeed": True,
        "collaborators": [],
        "audioIntent": {
            "generatedAudio": None,
            "sourceAudio": None,
            "nativeInstagramAudio": {"status": "needs_operator_selection"},
        },
        "handoffManifest": {"status": "not_required"},
        "variantAssignment": {"cell": "baseline"},
    }
    projection = creative_export_projection(draft, campaign_slug="may")
    canonical = canonical_asset_approval_bindings(asset)
    manifest_core = {
        "schema": "campaign_factory.creative_review_manifest.v1",
        "generatedAt": "2026-07-22T20:02:00Z",
        "campaign": {"id": "campaign-1", "slug": "may"},
        "renderedAsset": canonical["renderedAsset"],
        "draftPayloadSchema": "campaign_factory.draft_payload.v3",
        "draft": draft,
        "providerCalls": 0,
        "productionWrites": 0,
    }
    manifest = {
        **manifest_core,
        "manifestFingerprint": _fingerprint(manifest_core),
    }
    manifest_path = tmp_path / "review-manifest-v2.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    core = {
        "schema": "campaign_factory.creative_approval.v2",
        "approvalId": "approval-v2-1",
        "approvedBy": "operator",
        "approvedAt": "2026-07-22T20:02:00Z",
        "campaign": {"id": "campaign-1", "slug": "may"},
        **canonical,
        "qcEvidence": [
            {
                "checkId": "contentforge.motion_specific_qc",
                "receiptPath": str(receipt),
                "receiptSha256": _sha(receipt),
                "subjectSha256": _sha(output),
                "passed": True,
            }
        ],
        "reviewManifest": {
            "path": str(manifest_path),
            "sha256": _sha(manifest_path),
        },
        "exportProjection": projection,
        "contentSemantics": {
            "burnedOverlayText": draft["burnedCaptionText"],
            "instagramPostCaption": draft["instagramPostCaption"],
            "generatedAudio": None,
            "sourceAudio": None,
            "nativeInstagramAudio": draft["audioIntent"]["nativeInstagramAudio"],
        },
    }
    return (_sign_v2(core), asset, draft)


class _BuilderPublishability:
    def __init__(self, asset: dict, receipt: dict) -> None:
        self.asset = asset
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


class _BuilderFactory:
    def __init__(self, asset: dict, receipt: dict) -> None:
        asset.setdefault("review_state", "approved")
        campaign = {"id": asset["campaign_id"], "slug": "may"}
        publishability = _BuilderPublishability(asset, receipt)

        class _Domains:
            pass

        self.domains = _Domains()
        self.domains.publishability = publishability
        self.domains.campaign_by_slug = lambda slug: campaign if slug == "may" else None


def test_supported_builder_uses_exact_generated_review_manifest_and_registered_qc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _payload, asset, draft = _v2_fixture(tmp_path)
    receipt = json.loads((tmp_path / "motion-qc-v2.json").read_text())
    factory = _BuilderFactory(asset, receipt)
    calls = {"exports": 0}

    def fake_export(_factory, **kwargs):
        calls["exports"] += 1
        assert kwargs["dry_run"] is True
        assert kwargs["review_only"] is True
        assert kwargs["rendered_asset_ids"] == [asset["id"]]
        return {
            "payload": {
                "schema": "campaign_factory.threadsdash_drafts.v3",
                "drafts": [draft],
            }
        }

    monkeypatch.setattr(
        "campaign_factory.adapters.threadsdash_draft_delivery.export_threadsdash",
        fake_export,
    )
    result = build_and_record_creative_approval_v2(
        factory,
        campaign_slug="may",
        rendered_asset_id=asset["id"],
        user_id="operator-user",
        approved_by="operator",
        root=tmp_path / "built-approvals",
    )
    approval = load_creative_approval(Path(result["approvalPath"]))
    assert calls == {"exports": 1}
    assert result["executionClass"] == "local_model"
    assert result["providerCalls"] == result["productionWrites"] == 0
    assert approval["reviewManifest"] == result["reviewManifest"]
    assert (
        validate_approval_for_draft(approval, draft, campaign_slug="may")["projection"]
        == approval["exportProjection"]
    )


def test_supported_builder_uses_real_campaign_review_export_without_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        fixture_dir = tmp_path / "admission-fixture"
        fixture_dir.mkdir()
        _fixture_approval, fixture_asset, _fixture_draft = _v2_fixture(fixture_dir)
        fixture_metadata = json.loads(fixture_asset["metadata_json"])
        metadata = json.loads(asset["metadata_json"])
        metadata["localMotionAdmission"] = fixture_metadata["localMotionAdmission"]
        cf.conn.execute(
            "UPDATE rendered_assets SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata, sort_keys=True), asset["id"]),
        )
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "builder-passing",
            _motion_qc_receipt(
                asset["content_hash"],
                source_sha256=_asset_source_sha256(asset),
            ),
        )
        cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path, created_by="test"
        )
        add_audit_report(cf, rendered_asset_id=asset["id"])
        cf.conn.execute(
            "UPDATE rendered_assets SET audit_status = 'approved_candidate' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        result = build_and_record_creative_approval_v2(
            cf,
            campaign_slug="may",
            rendered_asset_id=asset["id"],
            user_id="operator-user",
            approved_by="operator",
            root=cf.settings.creative_approvals_dir,
            publish_mode="notify",
        )
        assert result["providerCalls"] == result["productionWrites"] == 0
        assert result["executionClass"] == "local_model"
        approval = load_creative_approval(Path(result["approvalPath"]))
        assert approval["renderedAsset"]["id"] == asset["id"]
        dry_run_export = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="operator-user",
            dry_run=True,
            rendered_asset_ids=[asset["id"]],
            max_drafts=1,
            publish_mode="notify",
        )
        assert dry_run_export["draftCount"] == 1
        assert dry_run_export["supabase"]["attempted"] is False
        assert approval["exportProjection"] == creative_export_projection(
            dry_run_export["payload"]["drafts"][0], campaign_slug="may"
        )

        external_calls = {"negotiate": 0, "upload": 0, "ingest": 0}
        monkeypatch.setattr(
            threadsdash_delivery_adapter,
            "evaluate_export_readiness",
            lambda *_args, **_kwargs: {
                "liveExportAllowed": True,
                "blockingReasons": [],
                "warnings": [],
            },
        )
        monkeypatch.setattr(
            threadsdash_delivery_adapter,
            "_campaign_factory_manifest_blockers",
            lambda *_args, **_kwargs: [],
        )

        def negotiate(**kwargs):
            external_calls["negotiate"] += 1
            return {
                "status": "PASS",
                "selectedDraftPayload": kwargs["payload_schema"],
            }

        def upload(*_args, **_kwargs):
            external_calls["upload"] += 1
            return []

        def ingest(*_args, **_kwargs):
            external_calls["ingest"] += 1
            return {
                "attempted": True,
                "success": True,
                "postIds": ["post-approved-1"],
                "writtenDrafts": 1,
            }

        monkeypatch.setattr(
            threadsdash_delivery_adapter,
            "_negotiate_threadsdash_draft_payload",
            negotiate,
        )
        monkeypatch.setattr(
            threadsdash_delivery_adapter,
            "_upload_media_for_dashboard_ingest",
            upload,
        )
        monkeypatch.setattr(
            threadsdash_delivery_adapter, "_post_threadsdash_draft_ingest", ingest
        )
        monkeypatch.setattr(
            threadsdash_delivery_adapter,
            "_reconcile_dashboard_ingest_post_ids",
            lambda **_kwargs: ["post-approved-1"],
        )
        applied = export_threadsdash(
            cf,
            campaign_slug="may",
            user_id="operator-user",
            dry_run=False,
            rendered_asset_ids=[asset["id"]],
            max_drafts=1,
            publish_mode="notify",
            allow_warnings=True,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            threadsdash_ingest_url="https://juno33.com/api/campaign-factory/drafts/ingest",
            threadsdash_ingest_secret="test-secret",
        )
        assert applied["draftCount"] == 1
        assert applied["dashboardIngest"]["postIds"] == ["post-approved-1"]
        assert external_calls == {"negotiate": 1, "upload": 1, "ingest": 1}
    finally:
        cf.close()


def _paid_v2_fixture(tmp_path: Path) -> tuple[dict, dict, dict]:
    cf = make_factory(tmp_path)
    try:
        source_asset = add_source_asset(cf, tmp_path)
        campaign = cf.domains.campaign_by_slug("may")
        source = tmp_path / "paid-source.jpg"
        output = tmp_path / "paid-output.mp4"
        source.write_bytes(b"paid-source")
        output.write_bytes(b"paid-output")
        source_sha = _sha(source)
        output_sha = _sha(output)
        campaign_request = "6" * 64
        prompt = "A realistic creator-conditioned motion prompt for review"
        scope = build_video_provider_spend_scope(
            provider="wavespeed",
            provider_model="alibaba/wan-2.7/image-to-video",
            operation="image_to_video",
            campaign=str(campaign["id"]),
            cohort_id="paid-v2-fixture",
            prompt=prompt,
            media_paths={"source_image": source},
            parameters={"durationSeconds": 6, "resolution": "1080p"},
        )
        provider_request = scope["requestFingerprint"]
        issued_at = datetime.now(UTC) - timedelta(minutes=1)
        authorization = sign_authorization(
            {
                "schema": AUTHORIZATION_SCHEMA_V2,
                "authorizationId": "spauth-paid-1",
                "reservationId": "spres-paid-1",
                "issuer": "campaign_factory",
                "status": "authorized",
                "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
                "expiresAt": (issued_at + timedelta(minutes=10))
                .isoformat()
                .replace("+00:00", "Z"),
                "scope": scope,
                "providerQuote": {
                    "provider": "wavespeed",
                    "model": scope["providerModel"],
                    "amount": 0.6,
                    "unit": "USD",
                    "pricingVersion": "test-v1",
                    "pricingFingerprint": "5" * 64,
                    "catalogBasePrice": 0.6,
                    "catalogModelId": scope["providerModel"],
                    "liveQuotedAmount": 0.6,
                    "livePriceSource": "wavespeed_model_pricing_api",
                },
            },
            secret=SPEND_SECRET,
        )
        verified_at = datetime.now(UTC)
        verify_authorization_v2(
            authorization,
            expected_scope=scope,
            secret=SPEND_SECRET,
            now=verified_at,
        )
        authorization_path = tmp_path / "paid-authorization.json"
        authorization_path.write_text(json.dumps(authorization, sort_keys=True))
        provider_evidence = {
            "schema": "reel_factory.wavespeed_submission.v1",
            "requestFingerprint": provider_request,
            "authorizationId": authorization["authorizationId"],
            "providerModel": authorization["scope"]["providerModel"],
            "status": "completed",
            "predictionId": "prediction-paid-1",
            "outputPath": str(output),
            "outputSha256": output_sha,
        }
        provider_path = tmp_path / "paid-provider-evidence.json"
        provider_path.write_text(json.dumps(provider_evidence, sort_keys=True))
        ensure_cost_table(cf.conn)
        cost_metadata = {
            "authorizationId": authorization["authorizationId"],
            "predictionId": provider_evidence["predictionId"],
            "requestFingerprint": provider_request,
        }
        cf.conn.execute(
            """INSERT INTO ai_cost_events
            (id, campaign_id, provider, operation, estimated_cost_usd, metadata_json)
            VALUES ('cost-paid-1', ?, 'wavespeed', 'image_to_video', 0.6, ?)""",
            (campaign["id"], json.dumps(cost_metadata, sort_keys=True)),
        )
        cf.conn.commit()
        worker_result = {
            "providerCalls": 1,
            "campaignCostEventId": "cost-paid-1",
            "result": {
                **provider_evidence,
                "evidencePath": str(provider_path),
                "scope": authorization["scope"],
            },
        }
        worker_result["paidExecutionReceipt"] = _record_paid_motion_execution_receipt(
            cf,
            evidence_dir=tmp_path / "paid-execution-receipts",
            authorization=authorization,
            authorization_path=authorization_path,
            authorization_verified_at=verified_at.isoformat().replace("+00:00", "Z"),
            source_path=source,
            source_sha256=source_sha,
            output_path=output,
            prediction_id=provider_evidence["predictionId"],
            provider_result=worker_result["result"],
            cost_event_id="cost-paid-1",
        )
        paid = _paid_generation_evidence(
            cf,
            campaign=campaign,
            model_slug="stacey",
            model_id="wavespeed_wan27_i2v",
            motion_task="image_to_video",
            source_asset_id=source_asset["id"],
            source_path=source,
            source_hash=source_sha,
            output_path=output,
            output_hash=output_sha,
            request_fingerprint=campaign_request,
            prompt=prompt,
            worker_result=worker_result,
            authorization=authorization,
            authorization_path=authorization_path,
            produced_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    finally:
        cf.close()
    asset = {
        "id": "paid-rendered-asset-1",
        "campaign_id": campaign["id"],
        "source_asset_id": source_asset["id"],
        "content_hash": output_sha,
        "output_path": str(output),
        "frame_type": "generated_motion",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "metadata_json": json.dumps(
            {
                "schema": "campaign_factory.motion_generation_asset.v1",
                "modelId": "wavespeed_wan27_i2v",
                "requestFingerprint": campaign_request,
                "generationInput": {"path": str(source), "sha256": source_sha},
                "paidGeneration": True,
                "paidGenerationEvidence": paid,
            },
            sort_keys=True,
        ),
    }
    base = tmp_path / "base"
    base.mkdir()
    _local_payload, _local_asset, base_draft = _v2_fixture(base)
    draft = {
        **base_draft,
        "campaignId": asset["campaign_id"],
        "renderedAssetId": asset["id"],
        "sourceAssetId": asset["source_asset_id"],
        "contentHash": output_sha,
    }
    canonical = canonical_asset_approval_bindings(asset)
    receipt = _motion_qc_receipt(output_sha, source_sha256=source_sha)
    receipt_path = tmp_path / "paid-motion-qc.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    manifest_core = {
        "schema": "campaign_factory.creative_review_manifest.v1",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "campaign": {"id": asset["campaign_id"], "slug": "may"},
        "renderedAsset": canonical["renderedAsset"],
        "draftPayloadSchema": "campaign_factory.threadsdash_drafts.v3",
        "draft": draft,
        "providerCalls": 0,
        "productionWrites": 0,
    }
    manifest = {**manifest_core, "manifestFingerprint": _fingerprint(manifest_core)}
    manifest_path = tmp_path / "paid-review-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    core = {
        "schema": "campaign_factory.creative_approval.v2",
        "approvalId": "approval-paid-v2-1",
        "approvedBy": "operator",
        "approvedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "campaign": {"id": asset["campaign_id"], "slug": "may"},
        **canonical,
        "qcEvidence": [
            {
                "checkId": "contentforge.motion_specific_qc",
                "receiptPath": str(receipt_path),
                "receiptSha256": _sha(receipt_path),
                "subjectSha256": output_sha,
                "passed": True,
            }
        ],
        "reviewManifest": {"path": str(manifest_path), "sha256": _sha(manifest_path)},
        "exportProjection": creative_export_projection(draft, campaign_slug="may"),
        "contentSemantics": {
            "burnedOverlayText": draft["burnedCaptionText"],
            "instagramPostCaption": draft["instagramPostCaption"],
            "generatedAudio": None,
            "sourceAudio": None,
            "nativeInstagramAudio": draft["audioIntent"]["nativeInstagramAudio"],
        },
    }
    return _sign_v2(core), asset, draft


def test_paid_v2_approval_binds_provider_spend_request_and_output(
    tmp_path: Path,
) -> None:
    payload, asset, draft = _paid_v2_fixture(tmp_path)
    assert payload["executionEvidence"]["class"] == "paid_provider"
    assert "localMotionAdmission" not in json.loads(asset["metadata_json"])
    assert validate_creative_approval(payload) == payload
    assert (
        validate_approval_for_draft(payload, draft, campaign_slug="may")["approval"]
        == payload
    )


def test_paid_v2_approval_rejects_substituted_provider_evidence(
    tmp_path: Path,
) -> None:
    payload, _asset, _draft = _paid_v2_fixture(tmp_path)
    Path(payload["executionEvidence"]["providerEvidence"]["path"]).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(CreativeApprovalError, match="provider_execution_evidence"):
        validate_creative_approval(payload)


def test_paid_provider_call_rejects_self_authored_signature(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    scope = build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model="alibaba/wan-2.7/image-to-video",
        operation="image_to_video",
        campaign="campaign-1",
        cohort_id="cohort-1",
        prompt="Animate this creator image",
        media_paths={"source_image": source},
        parameters={"durationSeconds": 6},
    )
    issued_at = datetime.now(UTC) - timedelta(minutes=1)
    unsigned = {
        "schema": AUTHORIZATION_SCHEMA_V2,
        "authorizationId": "spauth-forged",
        "reservationId": "spres-forged",
        "issuer": "campaign_factory",
        "status": "authorized",
        "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
        "expiresAt": (issued_at + timedelta(minutes=10))
        .isoformat()
        .replace("+00:00", "Z"),
        "scope": scope,
        "providerQuote": {
            "provider": "wavespeed",
            "model": scope["providerModel"],
            "amount": 0.6,
            "unit": "USD",
            "pricingVersion": "test-v1",
            "pricingFingerprint": "5" * 64,
            "catalogBasePrice": 0.6,
            "catalogModelId": scope["providerModel"],
            "liveQuotedAmount": 0.6,
            "livePriceSource": "wavespeed_model_pricing_api",
        },
    }
    forged = {**unsigned, "signature": "5" * 64}
    with pytest.raises(Exception, match="signature is invalid"):
        _verify_paid_authorization_at_call(
            forged,
            expected_scope=scope,
            secret=SPEND_SECRET,
            now=datetime.now(UTC),
        )


def test_paid_provider_call_rejects_incomplete_scope(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    scope = build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model="alibaba/wan-2.7/image-to-video",
        operation="image_to_video",
        campaign="campaign-1",
        cohort_id="cohort-1",
        prompt="Animate this creator image",
        media_paths={"source_image": source},
        parameters={"durationSeconds": 6},
    )
    incomplete_scope = dict(scope)
    incomplete_scope.pop("operation")
    issued_at = datetime.now(UTC) - timedelta(minutes=1)
    forged = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA_V2,
            "authorizationId": "spauth-incomplete",
            "reservationId": "spres-incomplete",
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
            "expiresAt": (issued_at + timedelta(minutes=10))
            .isoformat()
            .replace("+00:00", "Z"),
            "scope": incomplete_scope,
            "providerQuote": {
                "provider": "wavespeed",
                "model": scope["providerModel"],
                "amount": 0.6,
                "unit": "USD",
                "pricingVersion": "test-v1",
                "pricingFingerprint": "5" * 64,
                "catalogBasePrice": 0.6,
                "catalogModelId": scope["providerModel"],
                "liveQuotedAmount": 0.6,
                "livePriceSource": "wavespeed_model_pricing_api",
            },
        },
        secret=SPEND_SECRET,
    )
    with pytest.raises(Exception):
        _verify_paid_authorization_at_call(
            forged,
            expected_scope=incomplete_scope,
            secret=SPEND_SECRET,
            now=datetime.now(UTC),
        )


def test_paid_v2_approval_rejects_fake_cost_binding(tmp_path: Path) -> None:
    payload, _asset, _draft = _paid_v2_fixture(tmp_path)
    payload["executionEvidence"]["spendRecord"]["fingerprint"] = "0" * 64
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="execution_chain_mismatch"):
        validate_creative_approval(payload)


def test_creative_approval_binds_every_exact_artifact(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    assert validate_creative_approval(payload) == payload
    store = CreativeApprovalStore(tmp_path / "approvals")
    path = store.record(payload)
    assert load_creative_approval(path) == payload
    assert store.record(payload) == path


def test_v2_contract_is_visible_through_the_canonical_manifest() -> None:
    assert SCHEMA_NAMES["creative_approval_v2"] == "creative_approval.v2.schema.json"


def test_creative_approval_rejects_output_substitution(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    Path(payload["output"]["path"]).write_bytes(b"substituted")
    with pytest.raises(CreativeApprovalError, match="output_missing_or_substituted"):
        validate_creative_approval(payload)


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


def test_creative_approval_rejects_identity_collision(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    store = CreativeApprovalStore(tmp_path / "approvals")
    path = store.record(payload)
    decoded = json.loads(path.read_text())
    decoded["approvedBy"] = "attacker"
    path.write_text(json.dumps(decoded))
    with pytest.raises(CreativeApprovalError, match="identity_collision"):
        store.record(payload)


def test_v2_approval_binds_trusted_qc_asset_and_exact_export(tmp_path: Path) -> None:
    payload, asset, draft = _v2_fixture(tmp_path)
    assert validate_creative_approval(payload) == payload
    assert (
        validate_approval_for_draft(payload, draft, campaign_slug="may")["projection"]
        == payload["exportProjection"]
    )
    store = CreativeApprovalStore(tmp_path / "approvals-v2")
    store.record(payload)
    status = store.status_for_asset(asset)
    assert status["state"] == "approved"
    assert status["approvalId"] == "approval-v2-1"


def test_v2_approval_rejects_self_authored_pass_receipt(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    output_sha = payload["output"]["sha256"]
    fake_receipt = {
        "checkId": "contentforge.motion_specific_qc",
        "policy": {"id": "contentforge.motion_specific_qc", "version": "2.0.0"},
        "subjectSha256": output_sha,
        "status": "passed",
        "passed": True,
    }
    path = Path(payload["qcEvidence"][0]["receiptPath"])
    path.write_text(json.dumps(fake_receipt), encoding="utf-8")
    payload["qcEvidence"][0]["receiptSha256"] = _sha(path)
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="qc_untrusted"):
        validate_creative_approval(payload)


def test_v2_approval_rejects_forged_analyzer_implementation_receipt(
    tmp_path: Path,
) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    path = Path(payload["qcEvidence"][0]["receiptPath"])
    decoded = json.loads(path.read_text(encoding="utf-8"))
    decoded["trustedEvidence"]["analyzerRegistry"]["analyzers"][0][
        "implementationFingerprint"
    ] = "9" * 64
    receipt_core = dict(decoded)
    receipt_core.pop("receiptFingerprint")
    decoded["receiptFingerprint"] = _fingerprint(receipt_core)
    path.write_text(json.dumps(decoded, sort_keys=True), encoding="utf-8")
    payload["qcEvidence"][0]["receiptSha256"] = _sha(path)
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="qc_untrusted"):
        validate_creative_approval(payload)


def test_v2_approval_rejects_unknown_qc_policy(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    path = Path(payload["qcEvidence"][0]["receiptPath"])
    decoded = json.loads(path.read_text(encoding="utf-8"))
    decoded["checkId"] = "operator.looked_good"
    path.write_text(json.dumps(decoded, sort_keys=True), encoding="utf-8")
    payload["qcEvidence"][0].update(
        {
            "checkId": "operator.looked_good",
            "receiptSha256": _sha(path),
        }
    )
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="qc_policy_unsupported"):
        validate_creative_approval(payload)


def test_v2_export_projection_rejects_semantic_substitution(tmp_path: Path) -> None:
    payload, _asset, draft = _v2_fixture(tmp_path)
    changed = {
        **draft,
        "content": "A substituted caption",
        "instagramPostCaption": "A substituted caption",
    }
    with pytest.raises(CreativeApprovalError, match="export_projection_mismatch"):
        validate_approval_for_draft(payload, changed, campaign_slug="may")


def test_v2_export_projection_rejects_changed_content_alias(tmp_path: Path) -> None:
    payload, _asset, draft = _v2_fixture(tmp_path)
    changed = {**draft, "content": "A changed delivery caption"}
    with pytest.raises(CreativeApprovalError, match="draft_content_caption_mismatch"):
        validate_approval_for_draft(payload, changed, campaign_slug="may")


def test_v2_export_projection_rejects_self_consistent_forged_projection(
    tmp_path: Path,
) -> None:
    payload, _asset, draft = _v2_fixture(tmp_path)
    projection_core = dict(payload["exportProjection"])
    projection_core.pop("fingerprint")
    projection_core["instagramPostCaption"] = "A forged approved caption"
    payload["exportProjection"] = {
        **projection_core,
        "fingerprint": _fingerprint(projection_core),
    }
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="manifest_projection_mismatch"):
        validate_creative_approval(payload)


def test_export_projection_ignores_only_declared_volatile_fields(
    tmp_path: Path,
) -> None:
    _payload, _asset, draft = _v2_fixture(tmp_path)
    changed = dict(draft)
    changed["audioIntent"] = {
        **draft["audioIntent"],
        "createdAt": "2026-07-23T00:00:00Z",
        "url": "https://example.invalid/transient",
    }
    assert creative_export_projection(
        changed, campaign_slug="may"
    ) == creative_export_projection(draft, campaign_slug="may")


def test_v2_approval_rejects_tampered_operator_attestation(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["operatorAttestation"]["signature"] = "0" * 64
    with pytest.raises(CreativeApprovalError, match="operator_attestation_invalid"):
        validate_creative_approval(payload)


def test_v2_approval_rejects_future_approval_timestamp(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["approvedAt"] = "2999-07-22T20:02:00Z"
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="approved_at_future"):
        validate_creative_approval(payload)


@pytest.mark.parametrize("approved_at", ["not-a-timestamp", "2026-07-22T20:02:00"])
def test_v2_approval_rejects_malformed_or_naive_approval_timestamp(
    tmp_path: Path, approved_at: str
) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["approvedAt"] = approved_at
    with pytest.raises(
        CreativeApprovalError, match="approved_at_(invalid|timezone_missing)"
    ):
        validate_creative_approval(payload)


def test_v2_local_motion_approval_requires_generation_admission(
    tmp_path: Path,
) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["executionEvidence"] = {
        "class": "paid_provider",
        "provider": "wavespeed",
    }
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="contract_invalid"):
        validate_creative_approval(payload)


def test_local_generated_asset_without_admission_is_not_approval_ready(
    tmp_path: Path,
) -> None:
    payload, asset, _draft = _v2_fixture(tmp_path)
    store = CreativeApprovalStore(tmp_path / "approvals-missing-admission")
    store.record(payload)
    metadata = json.loads(asset["metadata_json"])
    metadata["localMotionAdmission"] = None
    asset["metadata_json"] = json.dumps(metadata, sort_keys=True)
    assert store.status_for_asset(asset) == {
        "state": "invalid",
        "blockingReason": "creative_approval_canonical_asset_invalid",
    }


def test_v2_approval_rejects_qc_after_operator_approval(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["approvedAt"] = "2026-07-22T20:00:30Z"
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="qc_time_order_invalid"):
        validate_creative_approval(payload)


@pytest.mark.parametrize(
    "field",
    [
        "creatorIdentity",
        "contentIntent",
        "generationRecipe",
    ],
)
def test_v2_approval_rejects_canonical_binding_substitution(
    tmp_path: Path, field: str
) -> None:
    payload, asset, _draft = _v2_fixture(tmp_path)
    payload[field] = {
        "id": f"substituted-{field}",
        "fingerprint": "9" * 64,
    }
    _resign_v2(payload)
    assert validate_creative_approval(payload) == payload
    store = CreativeApprovalStore(tmp_path / f"approvals-{field}")
    store.record(payload)
    assert store.status_for_asset(asset) == {
        "state": "invalid",
        "blockingReason": "creative_approval_invalid",
    }


def test_v2_approval_rejects_model_class_substitution(tmp_path: Path) -> None:
    payload, _asset, _draft = _v2_fixture(tmp_path)
    payload["model"] = {"id": "substituted-model", "fingerprint": "9" * 64}
    _resign_v2(payload)
    with pytest.raises(CreativeApprovalError, match="local_model_mismatch"):
        validate_creative_approval(payload)


def test_v2_approval_rejects_canonical_local_admission_substitution(
    tmp_path: Path,
) -> None:
    payload, asset, _draft = _v2_fixture(tmp_path)
    payload["executionEvidence"]["admission"] = {
        "id": "substituted-admission",
        "fingerprint": "9" * 64,
    }
    _resign_v2(payload)
    assert validate_creative_approval(payload) == payload
    store = CreativeApprovalStore(tmp_path / "approvals-execution")
    store.record(payload)
    assert store.status_for_asset(asset) == {
        "state": "invalid",
        "blockingReason": "creative_approval_invalid",
    }


def test_v2_approval_rejects_canonical_input_substitution(tmp_path: Path) -> None:
    payload, asset, _draft = _v2_fixture(tmp_path)
    alternate = tmp_path / "alternate-source.jpg"
    alternate.write_bytes(b"alternate")
    metadata = json.loads(asset["metadata_json"])
    metadata["generationInput"] = {
        "path": str(alternate),
        "sha256": _sha(alternate),
    }
    asset["metadata_json"] = json.dumps(metadata, sort_keys=True)
    store = CreativeApprovalStore(tmp_path / "approvals-input")
    store.record(payload)
    assert store.status_for_asset(asset) == {
        "state": "invalid",
        "blockingReason": "creative_approval_invalid",
    }
