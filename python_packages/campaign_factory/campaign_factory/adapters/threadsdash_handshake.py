"""Zero-product-write Campaign Factory -> ThreadsDashboard seam probe."""

from __future__ import annotations

import ipaddress
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pipeline_contracts import validate_threadsdash_handshake

from .threadsdash_hmac import signed_headers

HANDSHAKE_PATH = "/api/campaign-factory/handshake"
INGEST_PATH = "/api/campaign-factory/drafts/ingest"
DEFAULT_ALLOWED_HOSTS = frozenset({"juno33.com", "www.juno33.com"})
RESPONSE_SCHEMA_V1 = "threadsdashboard.campaign_factory_handshake.v1"
RESPONSE_SCHEMA_V2 = "threadsdashboard.campaign_factory_handshake.v2"
HANDSHAKE_SCHEMA_V1 = "campaign_factory.threadsdash_handshake.v1"
HANDSHAKE_SCHEMA_V2 = "campaign_factory.threadsdash_handshake.v2"
DRAFT_PAYLOAD_SCHEMA_V2 = "campaign_factory.threadsdash_drafts.v2"
DRAFT_PAYLOAD_SCHEMA_V3 = "campaign_factory.threadsdash_drafts.v3"

OpenRequest = Callable[[Request, float], Any]


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_threadsdash_handshake_request(request: Request, timeout: float) -> Any:
    """Open one no-redirect handshake request; kept injectable for seam tests."""
    return build_opener(_RejectRedirects()).open(request, timeout=timeout)


def build_handshake_payload(
    trace_id: str, *, handshake_schema: str = HANDSHAKE_SCHEMA_V2
) -> dict[str, Any]:
    if handshake_schema not in {HANDSHAKE_SCHEMA_V1, HANDSHAKE_SCHEMA_V2}:
        raise ValueError("handshake_schema must be v1 or v2")
    draft_payload_contract: str | dict[str, Any]
    if handshake_schema == HANDSHAKE_SCHEMA_V1:
        draft_payload_contract = DRAFT_PAYLOAD_SCHEMA_V2
    else:
        draft_payload_contract = {
            "preferred": DRAFT_PAYLOAD_SCHEMA_V3,
            "supported": [DRAFT_PAYLOAD_SCHEMA_V3, DRAFT_PAYLOAD_SCHEMA_V2],
        }
    payload = {
        "schema": handshake_schema,
        "traceId": trace_id,
        "contracts": {
            "draftPayload": draft_payload_contract,
            "generatedAssetLineage": "reel_factory.generated_asset_lineage.v2",
            "audioIntent": "pipeline.audio_intent.v1",
            "performanceMetrics": "threadsdashboard.post_metric_history.read.v1",
        },
        "capabilities": {
            "draftOnly": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        },
    }
    validate_threadsdash_handshake(payload)
    return payload


def configured_handshake_url(env: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if env is None else env
    explicit = values.get("THREADSDASH_CAMPAIGN_FACTORY_HANDSHAKE_URL", "").strip()
    if explicit:
        return explicit
    ingest = (
        values.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or values.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
        or ""
    ).strip()
    if not ingest:
        return None
    parsed = urlparse(ingest)
    if parsed.path.rstrip("/") != INGEST_PATH:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, HANDSHAKE_PATH, "", "", ""))


def validate_handshake_url(url: str, *, env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ThreadsDashboard handshake URL is invalid")
    if parsed.path.rstrip("/") != HANDSHAKE_PATH:
        raise ValueError(
            f"ThreadsDashboard handshake URL path must be {HANDSHAKE_PATH}"
        )
    allow_local = (
        values.get("CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST", "0") == "1"
    )
    local = (
        host == "localhost"
        or host.endswith(".localhost")
        or host
        in {
            "127.0.0.1",
            "::1",
        }
    )
    if parsed.scheme != "https" and not (
        allow_local and local and parsed.scheme == "http"
    ):
        raise ValueError("ThreadsDashboard handshake URL must use https")
    if local and not allow_local:
        raise ValueError("localhost handshake requires explicit local-ingest opt-in")
    if not local:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError("ThreadsDashboard handshake URL cannot use a private IP")
        configured = {
            value.strip().lower().rstrip(".")
            for value in values.get("THREADSDASH_ALLOWED_INGEST_HOSTS", "").split(",")
            if value.strip()
        }
        if host not in (configured or set(DEFAULT_ALLOWED_HOSTS)):
            raise ValueError("ThreadsDashboard handshake URL host is not allowed")
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, HANDSHAKE_PATH, "", "", ""))


def run_threadsdash_handshake(
    *,
    url: str,
    secret: str,
    trace_id: str | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
    env: Mapping[str, str] | None = None,
    open_request: OpenRequest | None = None,
    handshake_schema: str = HANDSHAKE_SCHEMA_V2,
) -> dict[str, Any]:
    """Validate the seam without creating drafts, posts, or schedules."""
    actual_trace_id = trace_id or f"trace_{uuid.uuid4().hex}"
    safe_url = validate_handshake_url(url, env=env)
    payload = build_handshake_payload(
        actual_trace_id, handshake_schema=handshake_schema
    )
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature_timestamp = str(timestamp or int(time.time()))
    signature_nonce = nonce or uuid.uuid4().hex
    request = Request(
        safe_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **signed_headers(
                body,
                secret=secret,
                timestamp=signature_timestamp,
                nonce=signature_nonce,
            ),
        },
    )
    opener = open_request or _open_threadsdash_handshake_request
    try:
        with opener(request, 10.0) as response:
            status = int(getattr(response, "status", 200))
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"ThreadsDashboard handshake rejected: HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("ThreadsDashboard handshake network failure") from exc
    if status != 200:
        raise RuntimeError(f"ThreadsDashboard handshake returned HTTP {status}")
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ThreadsDashboard handshake returned invalid JSON") from exc
    expected = payload["contracts"]
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError("ThreadsDashboard handshake did not return success")
    response_contracts = result.get("contracts")
    contract_ok = response_contracts == expected
    selected_draft_payload: str | None = None
    if handshake_schema == HANDSHAKE_SCHEMA_V2:
        proposed = expected["draftPayload"]
        response_contracts = (
            response_contracts if isinstance(response_contracts, dict) else {}
        )
        selected_draft_payload = response_contracts.get("draftPayload")
        supported = response_contracts.get("supportedDraftPayloads")
        contract_ok = (
            isinstance(proposed, dict)
            and selected_draft_payload == proposed.get("preferred")
            and isinstance(supported, list)
            and all(item in supported for item in proposed.get("supported") or [])
            and response_contracts.get("generatedAssetLineage")
            == expected["generatedAssetLineage"]
            and response_contracts.get("audioIntent") == expected["audioIntent"]
            and response_contracts.get("performanceMetrics")
            == expected["performanceMetrics"]
        )
    expected_response_schema = (
        RESPONSE_SCHEMA_V2
        if handshake_schema == HANDSHAKE_SCHEMA_V2
        else RESPONSE_SCHEMA_V1
    )
    invariants = {
        "schema": result.get("schema") == expected_response_schema,
        "trace": result.get("traceId") == actual_trace_id,
        "auth": result.get("authMode") == "hmac",
        "nonce": result.get("nonceClaimed") is True,
        "contracts": contract_ok,
        "capabilities": result.get("capabilities") == payload["capabilities"],
        "zeroProductRows": result.get("productRowsWritten") == 0,
    }
    failed = [name for name, ok in invariants.items() if not ok]
    if failed:
        raise RuntimeError(
            f"ThreadsDashboard handshake invariant failed: {', '.join(failed)}"
        )
    return {
        "schema": "campaign_factory.threadsdash_handshake_result.v1",
        "status": "PASS",
        "traceId": actual_trace_id,
        "authMode": "hmac",
        "nonceClaimed": True,
        "productRowsWritten": 0,
        "contracts": response_contracts,
        "selectedDraftPayload": selected_draft_payload or DRAFT_PAYLOAD_SCHEMA_V2,
        "capabilities": payload["capabilities"],
    }
