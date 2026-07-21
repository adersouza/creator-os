from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.adapters import threadsdash_draft_delivery
from campaign_factory.adapters.threadsdash_handshake import (
    build_handshake_payload,
    configured_handshake_url,
    run_threadsdash_handshake,
    validate_handshake_url,
)
from campaign_factory.adapters.threadsdash_hmac import sign_body
from campaign_factory.provider_probe import run_provider_probe


class Response(BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_hmac_signature_matches_receiver_contract() -> None:
    assert sign_body(
        b'{"ok":true}',
        secret="secret",
        timestamp="1720000000",
        nonce="nonce_123",
    ) == ("v1=495bff12b97fd3b4dccabda61de247a2091175a2d3081a6eb4ad0bdfafda0d1f")


def test_handshake_validates_zero_write_response_and_uses_shared_trace() -> None:
    trace_id = "trace_1234567890abcdef"
    captured: dict[str, Any] = {}

    def open_request(request, timeout: float):
        captured["request"] = request
        captured["timeout"] = timeout
        proposal = build_handshake_payload(trace_id)
        response = {
            "success": True,
            "schema": "threadsdashboard.campaign_factory_handshake.v2",
            "ok": True,
            "traceId": trace_id,
            "authMode": "hmac",
            "nonceClaimed": True,
            "contracts": {
                "draftPayload": proposal["contracts"]["draftPayload"]["preferred"],
                "supportedDraftPayloads": proposal["contracts"]["draftPayload"][
                    "supported"
                ],
                "generatedAssetLineage": proposal["contracts"]["generatedAssetLineage"],
                "audioIntent": proposal["contracts"]["audioIntent"],
                "performanceMetrics": proposal["contracts"]["performanceMetrics"],
            },
            "capabilities": proposal["capabilities"],
            "productRowsWritten": 0,
        }
        return Response(json.dumps(response).encode())

    result = run_threadsdash_handshake(
        url="http://localhost:3000/api/campaign-factory/handshake",
        secret="test-secret",
        trace_id=trace_id,
        timestamp=1720000000,
        nonce="nonce_1234567890",
        env={"CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST": "1"},
        open_request=open_request,
    )

    assert result["status"] == "PASS"
    assert result["productRowsWritten"] == 0
    assert result["traceId"] == trace_id
    assert result["selectedDraftPayload"] == "campaign_factory.threadsdash_drafts.v3"
    assert captured["timeout"] == 10.0
    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.get_header("X-campaign-factory-signature").startswith("v1=")


def test_handshake_v1_remains_available_for_legacy_probe() -> None:
    trace_id = "trace_legacy_1234567890"
    proposal = build_handshake_payload(
        trace_id,
        handshake_schema="campaign_factory.threadsdash_handshake.v1",
    )

    def open_request(_request, _timeout: float):
        return Response(
            json.dumps(
                {
                    "success": True,
                    "schema": "threadsdashboard.campaign_factory_handshake.v1",
                    "ok": True,
                    "traceId": trace_id,
                    "authMode": "hmac",
                    "nonceClaimed": True,
                    "contracts": proposal["contracts"],
                    "capabilities": proposal["capabilities"],
                    "productRowsWritten": 0,
                }
            ).encode()
        )

    result = run_threadsdash_handshake(
        url="http://localhost:3000/api/campaign-factory/handshake",
        secret="test-secret",
        trace_id=trace_id,
        env={"CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST": "1"},
        open_request=open_request,
        handshake_schema="campaign_factory.threadsdash_handshake.v1",
    )

    assert result["selectedDraftPayload"] == "campaign_factory.threadsdash_drafts.v2"


def test_handshake_configuration_and_url_fail_closed() -> None:
    assert (
        configured_handshake_url(
            {
                "THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL": (
                    "https://juno33.com/api/campaign-factory/drafts/ingest"
                )
            }
        )
        == "https://juno33.com/api/campaign-factory/handshake"
    )
    with pytest.raises(ValueError, match="host is not allowed"):
        validate_handshake_url("https://example.com/api/campaign-factory/handshake")
    with pytest.raises(ValueError, match="must use https"):
        validate_handshake_url("http://juno33.com/api/campaign-factory/handshake")


@pytest.mark.parametrize(
    ("payload_schema", "expected_handshake"),
    [
        (
            "campaign_factory.threadsdash_drafts.v3",
            "campaign_factory.threadsdash_handshake.v2",
        ),
        (
            "campaign_factory.threadsdash_drafts.v2",
            "campaign_factory.threadsdash_handshake.v1",
        ),
    ],
)
def test_live_export_negotiates_the_exact_requested_contract_before_writes(
    monkeypatch: pytest.MonkeyPatch,
    payload_schema: str,
    expected_handshake: str,
) -> None:
    captured: dict[str, Any] = {}

    def handshake(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "status": "PASS",
            "selectedDraftPayload": payload_schema,
        }

    monkeypatch.setattr(
        threadsdash_draft_delivery, "run_threadsdash_handshake", handshake
    )
    result = threadsdash_draft_delivery._negotiate_threadsdash_draft_payload(
        payload_schema=payload_schema,
        ingest_url="https://juno33.com/api/campaign-factory/drafts/ingest",
        ingest_secret="secret",
    )

    assert result["selectedDraftPayload"] == payload_schema
    assert captured["handshake_schema"] == expected_handshake
    assert captured["url"] == "https://juno33.com/api/campaign-factory/handshake"


def test_live_export_rejects_a_negotiated_contract_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        threadsdash_draft_delivery,
        "run_threadsdash_handshake",
        lambda **_kwargs: {
            "status": "PASS",
            "selectedDraftPayload": "campaign_factory.threadsdash_drafts.v2",
        },
    )

    with pytest.raises(ValueError, match="selected a different draft payload"):
        threadsdash_draft_delivery._negotiate_threadsdash_draft_payload(
            payload_schema="campaign_factory.threadsdash_drafts.v3",
            ingest_url="https://juno33.com/api/campaign-factory/drafts/ingest",
            ingest_secret="secret",
        )


@pytest.mark.parametrize("model_key", ["job_type", "job_set_type", "id", "model_id"])
def test_provider_probe_calls_only_allowlisted_read_only_commands(
    tmp_path: Path,
    model_key: str,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1:3] == ["account", "status"]:
            payload: object = {"credits": 1000}
        elif command[1:3] == ["workspace", "status"]:
            payload = {"workspace": {"id": "private"}}
        elif "--image" in command:
            payload = [{model_key: "text2image_soul_v2"}]
        elif "--video" in command:
            payload = [
                {model_key: "kling_3_0"},
                {model_key: "seedance_2_0"},
            ]
        else:
            payload = {"credits": 1, "credits_exact": 0.12}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    result = run_provider_probe(
        artifact_root=artifact_root, trace_id="trace_1234567890", runner=runner
    )

    assert result["status"] == "PASS"
    assert result["providerCalls"] == 0
    assert result["costEventsCreated"] == 0
    assert result["quote"]["createdJob"] is False
    assert {(command[1], command[2]) for command in commands} <= {
        ("account", "status"),
        ("workspace", "status"),
        ("model", "list"),
        ("generate", "cost"),
    }
