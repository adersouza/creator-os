from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from reference_factory.db import connect
from reference_factory.reference_gemini import analyze_reference_with_gemini_api
from reference_factory.reference_grok import (
    _execute_paid_action,
    _sha256_file,
    _xai_chat_completion,
    analyze_reference_with_grok_api,
)


def _paid_action(**kwargs: Any) -> dict[str, Any]:
    return {
        "schema": "campaign_factory.reference_paid_action_context.v1",
        "authorizationId": "auth_test",
        "attemptId": "attempt_test",
        "campaignLedgerEventId": "cost_test",
        "provider": kwargs["provider"],
        "model": kwargs["model"],
        "actionType": kwargs["action_type"],
        "requestFingerprint": kwargs["request_fingerprint"],
        "attemptPersistedBeforeExternalEffect": True,
    }


def _reconcile(**kwargs: Any) -> dict[str, Any]:
    actual = kwargs["actual_usd"]
    return {
        "schema": "campaign_factory.unified_paid_action_ledger.v1",
        "eventId": kwargs["paid_action"]["campaignLedgerEventId"],
        "actualUsd": actual,
        "netUsd": actual,
        "reconciliationState": "reconciled" if actual is not None else "unknown",
        "unknownReason": kwargs["unknown_reason"],
        "providerReference": kwargs["provider_reference"],
    }


def test_paid_effect_preserves_provider_reference_usage_and_actual_cost() -> None:
    response, receipt, evidence = _execute_paid_action(
        paid_action={"campaignLedgerEventId": "cost_test"},
        reconciler=_reconcile,
        external_call=lambda: {
            "content": '{"ok": true}',
            "providerReference": "provider_response_1",
            "usage": {"input_tokens": 12, "output_tokens": 4},
            "actualUsd": 0.019,
        },
    )

    assert response == '{"ok": true}'
    assert evidence == {
        "providerReference": "provider_response_1",
        "usage": {"input_tokens": 12, "output_tokens": 4},
        "actualUsd": 0.019,
    }
    assert receipt["actualUsd"] == 0.019
    assert receipt["providerReference"] == "provider_response_1"


def test_xai_effect_blocks_changed_media_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "reference.jpg"
    image.write_bytes(b"approved")
    expected = _sha256_file(image)
    image.write_bytes(b"changed")
    called = False

    def network_call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        "reference_factory.reference_grok.urlopen_json_with_retry", network_call
    )
    with pytest.raises(
        PermissionError, match="reference_provider_image_sha256_mismatch"
    ):
        _xai_chat_completion(
            api_key="secret",
            model="grok-4",
            prompt="prompt",
            image_path=image,
            expected_image_sha256=expected,
        )
    assert called is False


def _install_fake_genai(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    google = ModuleType("google")
    google.genai = SimpleNamespace(Client=lambda **_kwargs: client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)


def test_paid_analyzers_require_creator_before_queue_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = False

    def queue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal queued
        queued = True
        return {}

    _install_fake_genai(monkeypatch, SimpleNamespace())
    monkeypatch.setattr(
        "reference_factory.reference_gemini.queue_reference_analysis", queue
    )
    monkeypatch.setattr(
        "reference_factory.reference_grok.queue_reference_analysis", queue
    )
    callbacks = {
        "paid_action_authorizer": lambda **_kwargs: {},
        "paid_action_reconciler": lambda **_kwargs: {},
    }

    with pytest.raises(PermissionError, match="creator_creation_not_enabled:missing"):
        analyze_reference_with_gemini_api(
            connect(tmp_path / "gemini.sqlite"),
            source_root=tmp_path,
            data_root=tmp_path / "gemini-data",
            api_key="gemini-secret",
            **callbacks,
        )
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:missing"):
        analyze_reference_with_grok_api(
            connect(tmp_path / "grok.sqlite"),
            source_root=tmp_path,
            data_root=tmp_path / "grok-data",
            api_key="grok-secret",
            **callbacks,
        )

    assert queued is False


def test_gemini_requires_campaign_callbacks_before_queue_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def queue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    _install_fake_genai(monkeypatch, SimpleNamespace())
    monkeypatch.setattr(
        "reference_factory.reference_gemini.queue_reference_analysis", queue
    )
    with pytest.raises(
        PermissionError,
        match="reference_paid_action_requires_campaign_factory_authorization",
    ):
        analyze_reference_with_gemini_api(
            connect(tmp_path / "reference.sqlite"),
            source_root=tmp_path,
            data_root=tmp_path / "data",
            api_key="gemini-secret",
        )
    assert called is False


def test_gemini_authorizes_before_upload_and_reconciles_provider_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"approved-reference")
    events: list[str] = []
    rights_checks: list[dict[str, Any]] = []

    class Files:
        def upload(self, *, file: str) -> Any:
            uploaded_path = Path(file)
            assert uploaded_path != source
            assert uploaded_path.read_bytes() == source.read_bytes()
            events.append("upload")
            return SimpleNamespace(name=None)

    class Models:
        def generate_content(self, **_kwargs: Any) -> Any:
            events.append("generate")
            return SimpleNamespace(
                text='{"schema":"reference_factory.reference_analysis.v1"}',
                response_id="gemini_response_1",
                usage_metadata={"prompt_token_count": 10},
                cost=0.031,
            )

    _install_fake_genai(
        monkeypatch,
        SimpleNamespace(files=Files(), models=Models()),
    )
    monkeypatch.setattr(
        "reference_factory.reference_gemini.queue_reference_analysis",
        lambda *_args, **_kwargs: {
            "queued": 1,
            "jobs": [
                {
                    "id": "job_1",
                    "referenceId": "ref_1",
                    "sourcePath": str(source),
                    "promptText": "Analyze this reference.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "reference_factory.reference_gemini.import_reference_analysis",
        lambda *_args, **_kwargs: {"imported": 0, "errors": []},
    )
    monkeypatch.setattr(
        "reference_factory.reference_gemini.require_reference_provider_rights",
        lambda _conn, **kwargs: (
            rights_checks.append(kwargs)
            or {
                "rightsEvidenceFingerprint": "rights_1",
                "eligible": True,
            }
        ),
    )

    def authorize(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["prompt_inputs"]["sourceSha256"] == _sha256_file(source)
        events.append("authorize")
        return _paid_action(**kwargs)

    reconciled: list[dict[str, Any]] = []

    def reconcile(**kwargs: Any) -> dict[str, Any]:
        reconciled.append(kwargs)
        events.append("reconcile")
        return _reconcile(**kwargs)

    result = analyze_reference_with_gemini_api(
        connect(tmp_path / "reference.sqlite"),
        source_root=tmp_path,
        data_root=tmp_path / "data",
        account_profile="Stacey",
        api_key="gemini-secret",
        paid_action_authorizer=authorize,
        paid_action_reconciler=reconcile,
    )

    assert result["analyzed"] == 1
    assert events == ["authorize", "upload", "generate", "reconcile"]
    assert len(rights_checks) == 2
    assert rights_checks[0]["operation"] == "reference_analysis"
    assert rights_checks[0]["expected_source_sha256"] == _sha256_file(source)
    assert reconciled[0]["actual_usd"] == 0.031
    assert reconciled[0]["provider_reference"] == "gemini_response_1"
    imported = json.loads(Path(result["importPath"]).read_text(encoding="utf-8"))
    evidence = imported["items"][0]["providerResponseEvidence"]
    assert evidence["providerReference"] == "gemini_response_1"
    assert evidence["usage"] == {"prompt_token_count": 10}


def test_gemini_blocks_ineligible_reference_rights_before_authorization_or_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"reference-without-rights")
    uploaded = False
    authorized = False

    class Files:
        def upload(self, **_kwargs: Any) -> Any:
            nonlocal uploaded
            uploaded = True
            return SimpleNamespace(name=None)

    _install_fake_genai(
        monkeypatch,
        SimpleNamespace(files=Files(), models=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "reference_factory.reference_gemini.queue_reference_analysis",
        lambda *_args, **_kwargs: {
            "jobs": [
                {
                    "id": "job_1",
                    "referenceId": "ref_1",
                    "sourcePath": str(source),
                    "promptText": "Analyze this reference.",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "reference_factory.reference_gemini.require_reference_provider_rights",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("reference_provider_rights_ineligible:rights_revoked")
        ),
    )

    def authorize(**_kwargs: Any) -> dict[str, Any]:
        nonlocal authorized
        authorized = True
        return {}

    result = analyze_reference_with_gemini_api(
        connect(tmp_path / "reference.sqlite"),
        source_root=tmp_path,
        data_root=tmp_path / "data",
        account_profile="Stacey",
        api_key="gemini-secret",
        paid_action_authorizer=authorize,
        paid_action_reconciler=_reconcile,
    )

    assert result["analyzed"] == 0
    assert "rights_revoked" in str(result["errors"][0]["error"])
    assert authorized is False
    assert uploaded is False
