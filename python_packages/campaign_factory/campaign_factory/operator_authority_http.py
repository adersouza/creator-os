from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .config import Settings
from .db import connect, init_db
from .operator_authority import (
    api_authority_for,
    authorize_api_operation,
    claim_api_authority_event,
    complete_api_authority_event,
)

AUTHORITY_HTTP_OUTCOME_SCHEMA = "campaign_factory.operator_http_outcome.v1"
MAX_REPLAY_BODY_BYTES = 64 * 1024
SAFE_REPLAY_HEADERS = frozenset({"content-type", "content-language"})
_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "session",
    "signature",
    "signedurl",
    "token",
    "apikey",
    "cookie",
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/=-]+|"
    r"(?:access[_-]?token|api[_-]?key|credential|password|secret|"
    r"signature|session[_-]?id|token)\s*[=:]\s*[^\s&]+)"
)


def install_operator_authority_middleware(
    app: FastAPI,
    *,
    settings_provider: Callable[[], Settings],
) -> None:
    app.state.local_api_authorizer = authorize_api_operation

    @app.middleware("http")
    async def operator_authority_receipt(request: Request, call_next: Any) -> Response:
        context = getattr(request.state, "local_api_auth", None)
        if context is None:
            return await call_next(request)
        body = await request.body()
        request_fingerprint = hashlib.sha256(
            b"\0".join(
                (
                    request.method.upper().encode(),
                    request.url.path.encode(),
                    request.url.query.encode(),
                    str(request.headers.get("idempotency-key") or "").encode(),
                    hashlib.sha256(body).hexdigest().encode(),
                )
            )
        ).hexdigest()
        request.state.operator_request_fingerprint = request_fingerprint
        try:
            authority = api_authority_for(
                method=request.method.upper(),
                path=request.url.path,
                context=context,
                request_fingerprint=request_fingerprint,
                idempotency_key=request.headers.get("idempotency-key"),
            )
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        request.state.operator_authority = authority
        if authority.get("effectClass") != "read_local":
            conn = connect(settings_provider().db_path)
            try:
                init_db(conn)
                try:
                    authority_claim = claim_api_authority_event(conn, authority)
                except HTTPException as exc:
                    return JSONResponse(
                        status_code=exc.status_code,
                        content={"detail": exc.detail},
                    )
            finally:
                conn.close()
            if authority_claim["status"] == "replay":
                return _response_from_authority_outcome(authority_claim.get("outcome"))
            if authority_claim["status"] == "in_progress":
                return JSONResponse(
                    status_code=409,
                    content={
                        "status": "operation_in_progress",
                        "operationId": authority["operationId"],
                    },
                )
            if authority_claim["status"] == "reconciliation_required":
                return JSONResponse(
                    status_code=409,
                    content={
                        "status": "operation_reconciliation_required",
                        "operationId": authority["operationId"],
                        "reconciliationOwner": authority_claim.get(
                            "reconciliationOwner"
                        ),
                    },
                )
        try:
            response = await call_next(request)
        except Exception as exc:
            if authority.get("effectClass") != "read_local":
                _complete_api_authority(
                    settings_provider(),
                    authority,
                    succeeded=False,
                    outcome=None,
                    retryable=True,
                    error=f"{type(exc).__name__}:{exc}",
                )
            raise
        if authority.get("effectClass") == "read_local":
            return response
        body_bytes = await _response_body(response)
        outcome = _build_authority_outcome(response, body_bytes)
        _complete_api_authority(
            settings_provider(),
            authority,
            succeeded=response.status_code < 400,
            outcome=outcome,
            retryable=response.status_code >= 500,
            error=(
                f"http_status_{response.status_code}"
                if response.status_code >= 400
                else None
            ),
        )
        replayable = Response(
            content=body_bytes,
            status_code=response.status_code,
            background=response.background,
        )
        replayable.raw_headers = list(response.raw_headers)
        return replayable


async def _response_body(response: Response) -> bytes:
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body
    iterator: Any = getattr(response, "body_iterator", None)
    if iterator is None:
        return b""
    chunks: list[bytes] = []
    async for chunk in iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


def _complete_api_authority(
    settings: Settings,
    authority: dict[str, Any],
    *,
    succeeded: bool,
    outcome: dict[str, Any] | None,
    retryable: bool,
    error: str | None,
) -> None:
    conn = connect(settings.db_path)
    try:
        init_db(conn)
        complete_api_authority_event(
            conn,
            authority,
            succeeded=succeeded,
            outcome=outcome,
            retryable=retryable,
            error=error,
        )
    finally:
        conn.close()


def _build_authority_outcome(response: Response, body: bytes) -> dict[str, Any]:
    safe_headers = _safe_response_headers(response.raw_headers)
    evidence: dict[str, Any] = {
        "schema": AUTHORITY_HTTP_OUTCOME_SCHEMA,
        "statusCode": response.status_code,
        "headers": safe_headers,
        "bodyBytes": len(body),
        "bodySha256": hashlib.sha256(body).hexdigest(),
    }
    reason = _non_replayable_reason(response=response, body=body)
    if reason is not None:
        return {
            **evidence,
            "replayable": False,
            "reconciliationRequired": True,
            "nonReplayableReason": reason,
        }
    return {
        **evidence,
        "replayable": True,
        "reconciliationRequired": False,
        "bodyBase64": base64.b64encode(body).decode("ascii"),
    }


def _safe_response_headers(raw_headers: list[tuple[bytes, bytes]]) -> list[list[str]]:
    headers: list[list[str]] = []
    for raw_name, raw_value in raw_headers:
        name = raw_name.decode("latin-1").lower()
        if name not in SAFE_REPLAY_HEADERS:
            continue
        headers.append([name, raw_value.decode("latin-1")])
    return headers


def _non_replayable_reason(*, response: Response, body: bytes) -> str | None:
    if len(body) > MAX_REPLAY_BODY_BYTES:
        return "response_body_exceeds_replay_limit"
    if not body:
        return None
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type and "+json" not in content_type:
        return "response_body_media_type_not_replayable"
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "response_body_invalid_json"
    if _contains_sensitive_payload(payload):
        return "response_body_contains_sensitive_material"
    return None


def _contains_sensitive_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
                return True
            if _contains_sensitive_payload(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_payload(item) for item in value)
    if not isinstance(value, str):
        return False
    if _SENSITIVE_TEXT.search(value):
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return True
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
            return True
    return False


def _response_from_authority_outcome(outcome: Any) -> Response:
    if (
        not isinstance(outcome, dict)
        or outcome.get("schema") != AUTHORITY_HTTP_OUTCOME_SCHEMA
    ):
        return JSONResponse(
            status_code=409,
            content={
                "status": "operation_reconciliation_required",
                "detail": "idempotency_outcome_not_safely_replayable",
            },
        )
    if outcome.get("replayable") is not True:
        return JSONResponse(
            status_code=409,
            content={
                "status": "operation_reconciliation_required",
                "detail": str(
                    outcome.get("nonReplayableReason")
                    or "idempotency_outcome_not_replayable"
                ),
            },
        )
    try:
        body = base64.b64decode(str(outcome["bodyBase64"]), validate=True)
        status_code = int(outcome["statusCode"])
        if len(body) != int(outcome["bodyBytes"]):
            raise ValueError("idempotency body length mismatch")
        if hashlib.sha256(body).hexdigest() != outcome["bodySha256"]:
            raise ValueError("idempotency body digest mismatch")
        raw_headers = _validated_replay_headers(outcome.get("headers"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(500, "idempotency_outcome_invalid") from exc
    response = Response(content=body, status_code=status_code)
    response.raw_headers = raw_headers
    return response


def _validated_replay_headers(raw: Any) -> list[tuple[bytes, bytes]]:
    if not isinstance(raw, list):
        raise ValueError("idempotency headers invalid")
    headers: list[tuple[bytes, bytes]] = []
    for pair in raw:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) for item in pair)
        ):
            raise ValueError("idempotency header invalid")
        name = pair[0].lower()
        if name not in SAFE_REPLAY_HEADERS:
            raise ValueError("idempotency header not allowed")
        headers.append((name.encode("latin-1"), pair[1].encode("latin-1")))
    return headers
