from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "reference_paid.py"
SPEC = importlib.util.spec_from_file_location("reference_paid", SCRIPT)
assert SPEC and SPEC.loader
REFERENCE_PAID = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFERENCE_PAID)


def test_reference_paid_derives_canonical_creation_profile_from_creator() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE models (id TEXT, slug TEXT)")
    conn.executemany(
        "INSERT INTO models VALUES (?, ?)",
        [("creator_stacey", "Stacey"), ("creator_lola", "Lola")],
    )

    assert (
        REFERENCE_PAID._creation_profile_for_creator(
            conn,
            creator_id="creator_stacey",
            requested_profile=None,
        )
        == "stacey"
    )
    with pytest.raises(
        PermissionError, match="reference_paid_account_profile_creator_mismatch"
    ):
        REFERENCE_PAID._creation_profile_for_creator(
            conn,
            creator_id="creator_stacey",
            requested_profile="Larissa",
        )
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        REFERENCE_PAID._creation_profile_for_creator(
            conn,
            creator_id="creator_lola",
            requested_profile=None,
        )


def test_reference_paid_requires_explicit_apply_before_opening_databases() -> None:
    with pytest.raises(PermissionError, match="reference_paid_action_requires_apply"):
        REFERENCE_PAID.main(
            [
                "grok-analyze",
                "--creator",
                "creator",
                "--campaign",
                "campaign",
                "--run-id",
                "run",
                "--quote-usd",
                "0.10",
                "--max-usd",
                "1.00",
                "--pricing-version",
                "test",
                "--source",
                "/missing",
                "--reference-id",
                "ref_missing",
                "--source-asset-id",
                "source_missing",
            ]
        )


def test_reference_paid_composition_pins_route_quote_and_campaign_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        REFERENCE_PAID,
        "budget_limits_from_env",
        lambda **kwargs: {"limits": kwargs},
    )
    monkeypatch.setattr(
        REFERENCE_PAID,
        "authorize_reference_paid_action",
        lambda _conn, **kwargs: (
            captured.setdefault("authorization", kwargs) or {"unexpected": True}
        ),
    )
    monkeypatch.setattr(
        REFERENCE_PAID,
        "reconcile_reference_paid_action",
        lambda _conn, **kwargs: (
            captured.setdefault("reconciliation", kwargs) or {"unexpected": True}
        ),
    )
    authorize, reconcile = REFERENCE_PAID._paid_callbacks(
        object(),
        expected_provider="xai",
        expected_model="grok-4",
        expected_action_type="reference_analysis",
        creator_id="creator_1",
        campaign_id="campaign_1",
        run_id="run_1",
        reference_id="ref_1",
        reference_source_sha256="c" * 64,
        governance_context={
            "schema": "campaign_factory.creator_operation_context.v1",
            "creatorId": "creator_1",
            "campaignId": "campaign_1",
            "operation": "reference_analysis",
            "provider": "xai",
            "sourceAssetId": "source_1",
            "governanceFingerprint": "d" * 64,
        },
        quote_usd=0.25,
        max_usd=1.0,
        pricing_version="2026-07-30",
        secret="secret",
    )
    prompt = {"receiptFingerprint": "a" * 64}
    result = authorize(
        provider="xai",
        model="grok-4",
        action_type="reference_analysis",
        request_fingerprint="b" * 64,
        prompt_governance=prompt,
        current_prompt_registry={"definitions": []},
        compiled_prompt="prompt",
        prompt_inputs={
            "referenceId": "ref_1",
            "sourceSha256": "c" * 64,
            "rightsEvidenceFingerprint": "e" * 64,
        },
    )

    assert result is captured["authorization"]
    authorization = captured["authorization"]
    assert authorization["creator_id"] == "creator_1"
    assert authorization["campaign_id"] == "campaign_1"
    assert authorization["run_id"] == "run_1"
    assert authorization["reference_id"] == "ref_1"
    assert authorization["reference_source_sha256"] == "c" * 64
    assert authorization["governance_context"]["sourceAssetId"] == "source_1"
    assert authorization["quote"]["provider"] == "xai"
    assert authorization["quote"]["model"] == "grok-4"
    assert authorization["quote"]["amount"] == 0.25
    assert authorization["quote"]["source"] == "operator_exact_quote"
    assert authorization["quote"]["pricingVersion"] == "2026-07-30"

    paid_action = {"campaignLedgerEventId": "event_1"}
    reconcile(
        paid_action=paid_action,
        actual_usd=0.2,
        provider_reference="response_1",
        unknown_reason=None,
    )
    assert captured["reconciliation"]["paid_action"] == paid_action
    assert captured["reconciliation"]["provider_reference"] == "response_1"

    with pytest.raises(PermissionError, match="reference_paid_action_route_mismatch"):
        authorize(
            provider="xai",
            model="grok-3",
            action_type="reference_analysis",
            request_fingerprint="b" * 64,
            prompt_governance=prompt,
            current_prompt_registry={},
            compiled_prompt="prompt",
            prompt_inputs={
                "referenceId": "ref_1",
                "sourceSha256": "c" * 64,
                "rightsEvidenceFingerprint": "e" * 64,
            },
        )
    with pytest.raises(
        PermissionError, match="reference_paid_action_source_binding_mismatch"
    ):
        authorize(
            provider="xai",
            model="grok-4",
            action_type="reference_analysis",
            request_fingerprint="b" * 64,
            prompt_governance=prompt,
            current_prompt_registry={},
            compiled_prompt="prompt",
            prompt_inputs={
                "referenceId": "ref_other",
                "sourceSha256": "c" * 64,
                "rightsEvidenceFingerprint": "e" * 64,
            },
        )


def test_reference_paid_binding_rejects_cross_creator_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = tmp_path / "reference.mp4"
    media.write_bytes(b"exact governed reference")
    media_sha256 = hashlib.sha256(media.read_bytes()).hexdigest()
    campaign_conn = sqlite3.connect(":memory:")
    campaign_conn.row_factory = sqlite3.Row
    reference_conn = sqlite3.connect(":memory:")
    reference_conn.row_factory = sqlite3.Row
    campaign_conn.execute(
        """
        CREATE TABLE source_assets (
          id TEXT, campaign_id TEXT, model_id TEXT, content_hash TEXT,
          stored_path TEXT, status TEXT
        )
        """
    )
    reference_conn.execute(
        "CREATE TABLE source_files (reference_id TEXT, path TEXT, content_hash TEXT)"
    )
    campaign_conn.execute(
        "INSERT INTO source_assets VALUES (?, ?, ?, ?, ?, ?)",
        (
            "source_1",
            "campaign_1",
            "creator_other",
            media_sha256,
            str(media),
            "approved",
        ),
    )
    reference_conn.execute(
        "INSERT INTO source_files VALUES (?, ?, ?)",
        ("ref_1", str(media), media_sha256),
    )
    monkeypatch.setattr(
        REFERENCE_PAID,
        "resolve_campaign_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "cross-creator source must fail before governance resolution"
            )
        ),
    )

    with pytest.raises(
        PermissionError, match="reference_campaign_source_binding_mismatch"
    ):
        REFERENCE_PAID._resolve_reference_binding(
            campaign_conn,
            reference_conn,
            creator_id="creator_1",
            campaign_id="campaign_1",
            reference_id="ref_1",
            source_asset_id="source_1",
            provider="xai",
        )
