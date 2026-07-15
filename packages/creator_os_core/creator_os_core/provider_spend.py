"""Shared wire helpers for Campaign-issued provider spend authorizations.

Policy and persistence deliberately do not live here.  Campaign Factory owns
those decisions; workers only use these helpers to bind and verify the signed
execution scope they receive.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUTHORIZATION_SCHEMA = "campaign_factory.provider_spend_authorization.v1"
HIGGSFIELD_CREDIT_UNIT = "higgsfield_credits"
PAID_GENERATION_MODES = {"create", "image", "reference-image", "video"}


class SpendAuthorizationError(PermissionError):
    """Raised before a provider call when spend authority is absent or invalid."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def file_sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"spend-scope input is missing: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _option_map(args: Sequence[str]) -> dict[str, str | bool]:
    options: dict[str, str | bool] = {}
    index = 1
    while index < len(args):
        item = args[index]
        if not item.startswith("--"):
            raise ValueError(f"unexpected generate-assets argument: {item}")
        if index + 1 < len(args) and not args[index + 1].startswith("--"):
            options[item] = args[index + 1]
            index += 2
        else:
            options[item] = True
            index += 1
    return options


def build_generate_assets_spend_scope(
    args: Sequence[str], *, root: str | Path
) -> dict[str, Any]:
    """Build the immutable paid-call scope shared by Campaign and Reel Factory."""
    if not args:
        raise ValueError("generate-assets mode is required")
    mode = str(args[0])
    if mode not in PAID_GENERATION_MODES:
        raise ValueError(f"mode is not a paid generation mode: {mode}")
    options = _option_map(args)
    soul_id = options.get("--soul-id")
    if not isinstance(soul_id, str) or not soul_id.strip():
        raise SpendAuthorizationError(
            "paid generation requires an explicit Campaign-selected --soul-id"
        )
    root_path = Path(root).expanduser().resolve()

    def path_option(name: str) -> str | None:
        value = options.get(name)
        if not isinstance(value, str) or not value:
            return None
        path = Path(value).expanduser()
        return str(
            (root_path / path).resolve() if not path.is_absolute() else path.resolve()
        )

    prompt_path = path_option("--prompt-json")
    reference_path = path_option("--reference")
    start_image = path_option("--start-image")
    end_image = path_option("--end-image")
    video_reference = path_option("--video-reference")
    image_count = 6 if options.get("--image-mode") == "six-pack" else 1
    provider_calls = image_count if mode == "image" else 1
    if mode == "create":
        provider_calls += 1
    provider_models: list[str] = []
    if mode in {"create", "image", "reference-image"}:
        provider_models.extend(
            [str(options.get("--image-model") or "text2image_soul_v2")] * image_count
        )
    if mode in {"create", "video"}:
        provider_models.append(str(options.get("--video-model") or "kling3_0"))
    scope = {
        "mode": mode,
        "provider": "higgsfield",
        "campaign": str(options.get("--campaign") or ""),
        "cohortId": str(options.get("--cohort-id") or "creator_os_default"),
        "stem": str(options.get("--stem") or ""),
        "soulId": soul_id.strip(),
        "providerModels": provider_models,
        "providerCallCount": provider_calls,
        "promptSha256": file_sha256(prompt_path),
        "referenceSha256": file_sha256(reference_path),
        "startImageSha256": file_sha256(start_image),
        "endImageSha256": file_sha256(end_image),
        "videoReferenceSha256": file_sha256(video_reference),
        "imageAspectRatio": str(
            options.get("--image-aspect-ratio")
            or ("3:4" if mode == "reference-image" else "9:16")
        ),
        "imageQuality": str(options.get("--image-quality") or "2k"),
        "videoAspectRatio": str(options.get("--video-aspect-ratio") or "9:16"),
        "videoDuration": int(str(options.get("--video-duration") or "5")),
        "videoMode": str(options.get("--video-mode") or "pro"),
        "videoSound": str(options.get("--video-sound") or "off"),
    }
    return {**scope, "requestFingerprint": spend_scope_fingerprint(scope)}


def spend_scope_fingerprint(scope: Mapping[str, Any]) -> str:
    unsigned = {
        key: value for key, value in scope.items() if key != "requestFingerprint"
    }
    return hashlib.sha256(canonical_json(unsigned)).hexdigest()


def sign_authorization(payload: Mapping[str, Any], *, secret: str) -> dict[str, Any]:
    _validate_secret(secret)
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    signature = hmac.new(
        secret.encode("utf-8"), canonical_json(unsigned), hashlib.sha256
    )
    return {**unsigned, "signature": signature.hexdigest()}


def verify_authorization(
    payload: Mapping[str, Any],
    *,
    expected_scope: Mapping[str, Any],
    secret: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_secret(secret)
    if payload.get("schema") != AUTHORIZATION_SCHEMA:
        raise SpendAuthorizationError("invalid provider spend authorization schema")
    signature = payload.get("signature")
    if not isinstance(signature, str) or len(signature) != 64:
        raise SpendAuthorizationError(
            "provider spend authorization signature is missing"
        )
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    expected_signature = hmac.new(
        secret.encode("utf-8"), canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise SpendAuthorizationError(
            "provider spend authorization signature is invalid"
        )
    authorization_id = payload.get("authorizationId")
    reservation_id = payload.get("reservationId")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise SpendAuthorizationError("provider spend authorization id is missing")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise SpendAuthorizationError("provider spend reservation id is missing")
    if payload.get("issuer") != "campaign_factory":
        raise SpendAuthorizationError("provider spend authorization issuer is invalid")
    if payload.get("status") != "authorized":
        raise SpendAuthorizationError("provider spend authorization is not executable")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise SpendAuthorizationError("provider spend authorization scope is missing")
    if canonical_json(scope) != canonical_json(dict(expected_scope)):
        raise SpendAuthorizationError(
            "provider spend authorization scope does not match"
        )
    if scope.get("requestFingerprint") != spend_scope_fingerprint(scope):
        raise SpendAuthorizationError("provider spend request fingerprint is invalid")
    quote = payload.get("providerQuote")
    if not isinstance(quote, dict):
        raise SpendAuthorizationError("provider quote is missing")
    amount = quote.get("amount")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or float(amount) <= 0
        or quote.get("unit") != HIGGSFIELD_CREDIT_UNIT
    ):
        raise SpendAuthorizationError("provider quote is invalid")
    current = now or datetime.now(UTC)
    issued_at = _parse_time(payload.get("issuedAt"), "issuedAt")
    expires_at = _parse_time(payload.get("expiresAt"), "expiresAt")
    if expires_at <= issued_at or current < issued_at or current >= expires_at:
        raise SpendAuthorizationError(
            "provider spend authorization is expired or not active"
        )
    return dict(payload)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SpendAuthorizationError(
            f"provider spend authorization {field} is missing"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpendAuthorizationError(
            f"provider spend authorization {field} is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise SpendAuthorizationError(
            f"provider spend authorization {field} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _validate_secret(secret: str) -> None:
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise SpendAuthorizationError(
            "CREATOR_OS_SPEND_AUTH_SECRET must contain at least 32 bytes"
        )
