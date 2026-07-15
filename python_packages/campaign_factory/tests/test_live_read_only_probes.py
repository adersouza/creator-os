from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
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
        response = {
            "success": True,
            "schema": "threadsdashboard.campaign_factory_handshake.v1",
            "ok": True,
            "traceId": trace_id,
            "authMode": "hmac",
            "nonceClaimed": True,
            "contracts": build_handshake_payload(trace_id)["contracts"],
            "capabilities": build_handshake_payload(trace_id)["capabilities"],
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
    assert captured["timeout"] == 10.0
    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.get_header("X-campaign-factory-signature").startswith("v1=")


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


def test_provider_probe_calls_only_allowlisted_read_only_commands(
    tmp_path: Path,
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
            payload = [{"job_set_type": "text2image_soul_v2"}]
        elif "--video" in command:
            payload = [
                {"job_set_type": "kling_3_0"},
                {"job_set_type": "seedance_2_0"},
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
