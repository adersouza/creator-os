"""Campaign-owned spend authorization for WaveSpeed video generation."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import requests
from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA_V2,
    USD_UNIT,
    SpendAuthorizationError,
    canonical_json,
    sign_authorization,
)
from creator_os_core.runtime_guards import global_kill_switch_active

from pipeline_contracts.validator import validate_provider_spend_authorization_v2

from .cost_tracker import ensure_cost_table, record_ai_cost
from .provider_spend import AUTHORIZATION_TABLE, ensure_authorization_table

PRICING_VERSION = "wavespeed_public_2026-07-21"
_I2V_PER_SECOND = {"720p": 0.10, "1080p": 0.15}
_I2V_PRO_PER_FIVE_SECONDS = {"1080p": 0.60, "2k": 0.70, "4k": 0.80}
_REFERENCE_PRICES = {
    (5, "720p"): 1.00,
    (5, "1080p"): 1.60,
    (10, "720p"): 1.50,
    (10, "1080p"): 2.40,
}
_SPEECH_PER_FIVE_SECONDS = {"480p": 0.15, "720p": 0.30}


class BalanceProvider(Protocol):
    def balance(self) -> float | None: ...


class ModelCatalogProvider(Protocol):
    def model(self, model_id: str) -> dict[str, Any] | None: ...


class PricingProvider(Protocol):
    def quote(self, scope: dict[str, Any]) -> float | None: ...


@dataclass
class WaveSpeedBalanceProvider:
    api_key: str | None = None
    timeout_seconds: int = 60

    def balance(self) -> float | None:
        key = self.api_key or os.environ.get("WAVESPEED_API_KEY")
        if not key:
            return None
        response = requests.get(
            "https://api.wavespeed.ai/api/v3/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=(10, self.timeout_seconds),
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 200:
            return None
        data = body.get("data") if isinstance(body, dict) else None
        value = data.get("balance") if isinstance(data, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)


@dataclass
class WaveSpeedModelCatalogProvider:
    api_key: str | None = None
    timeout_seconds: int = 60

    def model(self, model_id: str) -> dict[str, Any] | None:
        key = self.api_key or os.environ.get("WAVESPEED_API_KEY")
        if not key:
            return None
        response = requests.get(
            "https://api.wavespeed.ai/api/v3/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=(10, self.timeout_seconds),
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 200:
            return None
        models = body.get("data")
        if not isinstance(models, list):
            return None
        matches = [
            item
            for item in models
            if isinstance(item, dict) and item.get("model_id") == model_id
        ]
        if len(matches) != 1:
            return None
        return matches[0]


@dataclass
class WaveSpeedPricingProvider:
    api_key: str | None = None
    timeout_seconds: int = 60

    def quote(self, scope: dict[str, Any]) -> float | None:
        key = self.api_key or os.environ.get("WAVESPEED_API_KEY")
        if not key:
            return None
        response = requests.post(
            "https://api.wavespeed.ai/api/v3/model/pricing",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model_id": scope["providerModel"],
                "inputs": _pricing_inputs(scope),
            },
            timeout=(10, self.timeout_seconds),
        )
        response.raise_for_status()
        return _find_price(response.json())


def quote_wavespeed_scope(scope: dict[str, Any]) -> dict[str, Any]:
    if scope.get("provider") != "wavespeed":
        raise ValueError("WaveSpeed quote requires a WaveSpeed spend scope")
    model = str(scope.get("providerModel") or "")
    parameters = scope.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("WaveSpeed quote parameters are missing")
    resolution = str(parameters.get("resolution") or "")
    duration = parameters.get("durationSeconds")
    duration_value = (
        0
        if model == "wavespeed-ai/wan-2.2/speech-to-video"
        else _duration_int(duration)
    )
    if model == "alibaba/wan-2.7/image-to-video":
        if resolution not in _I2V_PER_SECOND or duration_value not in {5, 10, 15}:
            raise ValueError("unsupported Wan 2.7 image-to-video pricing parameters")
        amount = _I2V_PER_SECOND[resolution] * duration_value
    elif model == "alibaba/wan-2.7/image-to-video-pro":
        if resolution not in _I2V_PRO_PER_FIVE_SECONDS or duration_value not in {
            5,
            10,
            15,
        }:
            raise ValueError("unsupported Wan 2.7 Pro pricing parameters")
        amount = _I2V_PRO_PER_FIVE_SECONDS[resolution] * (duration_value / 5)
    elif model == "alibaba/wan-2.7/reference-to-video":
        try:
            amount = _REFERENCE_PRICES[(duration_value, resolution)]
        except KeyError as exc:
            raise ValueError(
                "unsupported Wan 2.7 reference pricing parameters"
            ) from exc
    elif model == "wavespeed-ai/wan-2.2/speech-to-video":
        audio_duration = parameters.get("audioDurationSeconds")
        if resolution not in _SPEECH_PER_FIVE_SECONDS:
            raise ValueError("unsupported Wan 2.2 speech resolution")
        if (
            isinstance(audio_duration, bool)
            or not isinstance(audio_duration, (int, float))
            or not math.isfinite(float(audio_duration))
            or float(audio_duration) <= 0
            or float(audio_duration) > 600
        ):
            raise ValueError("speech audio duration must be between 0 and 600 seconds")
        blocks = math.ceil(float(audio_duration) / 5.0)
        amount = blocks * _SPEECH_PER_FIVE_SECONDS[resolution]
    else:
        raise ValueError(f"unpriced WaveSpeed model: {model}")
    pricing = {
        "version": PRICING_VERSION,
        "model": model,
        "parameters": parameters,
        "amount": round(float(amount), 4),
        "unit": USD_UNIT,
    }
    return {
        "provider": "wavespeed",
        "model": model,
        "amount": pricing["amount"],
        "unit": USD_UNIT,
        "pricingVersion": PRICING_VERSION,
        "pricingFingerprint": hashlib.sha256(canonical_json(pricing)).hexdigest(),
    }


def issue_wavespeed_spend_authorization(
    conn: sqlite3.Connection,
    *,
    scope: dict[str, Any],
    campaign_id: str | None,
    max_usd: float,
    secret: str,
    balance_provider: BalanceProvider | None = None,
    model_catalog_provider: ModelCatalogProvider | None = None,
    pricing_provider: PricingProvider | None = None,
    now: datetime.datetime | None = None,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Reserve and sign exactly one WaveSpeed submission."""
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise SpendAuthorizationError(
            "CREATOR_OS_SPEND_AUTH_SECRET must contain at least 32 bytes"
        )
    if global_kill_switch_active():
        raise PermissionError("creator_os_global_kill_switch_active")
    if (
        isinstance(max_usd, bool)
        or not isinstance(max_usd, (int, float))
        or not math.isfinite(float(max_usd))
        or float(max_usd) <= 0
    ):
        raise ValueError("paid WaveSpeed generation requires a finite positive USD cap")
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or not 60 <= ttl_seconds <= 3600
    ):
        raise ValueError("WaveSpeed authorization TTL must be 60 to 3600 seconds")
    fingerprint = str(scope.get("requestFingerprint") or "")
    if len(fingerprint) != 64:
        raise ValueError("provider spend scope fingerprint is invalid")
    quote = quote_wavespeed_scope(scope)
    catalog_model = (model_catalog_provider or WaveSpeedModelCatalogProvider()).model(
        str(scope.get("providerModel") or "")
    )
    if not isinstance(catalog_model, dict):
        raise PermissionError("wavespeed_model_catalog_unavailable_or_model_missing")
    base_price = catalog_model.get("base_price")
    if (
        isinstance(base_price, bool)
        or not isinstance(base_price, (int, float))
        or not math.isfinite(float(base_price))
        or float(base_price) <= 0
    ):
        raise PermissionError("wavespeed_model_catalog_price_invalid")
    live_price: float | None
    if scope.get("providerModel") == "wavespeed-ai/wan-2.2/speech-to-video":
        # The endpoint derives price from uploaded audio length, but uploads are
        # forbidden before authorization.  Use the documented 5-second block
        # rate bound to the locally measured audio duration instead.
        live_price = float(quote["amount"])
        live_price_source = "pinned_audio_duration_rate"
    else:
        live_price = (pricing_provider or WaveSpeedPricingProvider()).quote(scope)
        live_price_source = "wavespeed_model_pricing_api"
    if live_price is None or not math.isclose(
        live_price, float(quote["amount"]), rel_tol=0, abs_tol=0.0001
    ):
        raise PermissionError("wavespeed_live_price_mismatch_or_unavailable")
    quote = {
        **quote,
        "catalogBasePrice": float(base_price),
        "catalogModelId": str(catalog_model["model_id"]),
        "liveQuotedAmount": live_price,
        "livePriceSource": live_price_source,
    }
    quote["pricingFingerprint"] = hashlib.sha256(
        canonical_json(
            {key: value for key, value in quote.items() if key != "pricingFingerprint"}
        )
    ).hexdigest()
    amount = float(quote["amount"])
    if amount > float(max_usd):
        raise PermissionError("provider_quote_exceeds_run_cap")
    daily_cap = _positive_env("WAVESPEED_DAILY_BUDGET_USD")
    monthly_cap = _positive_env("WAVESPEED_MONTHLY_BUDGET_USD")
    cohort_cap = _positive_env("WAVESPEED_COHORT_MAX_USD")
    min_balance = _nonnegative_env("WAVESPEED_MIN_BALANCE_USD")
    balance = (balance_provider or WaveSpeedBalanceProvider()).balance()
    if balance is None:
        raise PermissionError("wavespeed_balance_unavailable")
    if balance - amount < min_balance:
        raise PermissionError("projected_balance_below_minimum")

    timestamp = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    issued_at = _iso(timestamp)
    expires_at = _iso(timestamp + datetime.timedelta(seconds=ttl_seconds))
    authorization_id = f"spauth_{uuid.uuid4().hex}"
    reservation_id = f"spres_{uuid.uuid4().hex}"
    cohort_id = str(scope.get("cohortId") or "")
    payload = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA_V2,
            "authorizationId": authorization_id,
            "reservationId": reservation_id,
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": issued_at,
            "expiresAt": expires_at,
            "scope": scope,
            "providerQuote": quote,
        },
        secret=secret,
    )
    validate_provider_spend_authorization_v2(payload)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_authorization_table(conn)
        existing = conn.execute(
            f"SELECT status FROM {AUTHORIZATION_TABLE} WHERE request_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            raise PermissionError("provider_spend_request_already_authorized")
        daily_spend = _reserved_total(
            conn, "substr(issued_at, 1, 10) = ?", issued_at[:10]
        )
        monthly_spend = _reserved_total(
            conn, "substr(issued_at, 1, 7) = ?", issued_at[:7]
        )
        cohort_spend = _reserved_total(conn, "cohort_id = ?", cohort_id)
        if daily_spend + amount > daily_cap:
            raise PermissionError("projected_daily_usd_exceeded")
        if monthly_spend + amount > monthly_cap:
            raise PermissionError("projected_monthly_usd_exceeded")
        if cohort_spend + amount > cohort_cap:
            raise PermissionError("projected_cohort_usd_exceeded")
        conn.execute(
            f"""
            INSERT INTO {AUTHORIZATION_TABLE}
                (authorization_id, reservation_id, provider, campaign_id, cohort_id,
                 request_fingerprint, amount, unit, scope_json, provider_quote_json,
                 status, issued_at, expires_at)
            VALUES (?, ?, 'wavespeed', ?, ?, ?, ?, ?, ?, ?, 'authorized', ?, ?)
            """,
            (
                authorization_id,
                reservation_id,
                campaign_id,
                cohort_id,
                fingerprint,
                amount,
                USD_UNIT,
                json.dumps(scope, sort_keys=True),
                json.dumps(quote, sort_keys=True),
                issued_at,
                expires_at,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return payload


def record_wavespeed_execution(
    conn: sqlite3.Connection,
    *,
    authorization: dict[str, Any],
    prediction_id: str,
    status: str,
    actual_usd: float | None = None,
) -> str:
    ensure_cost_table(conn)
    quote = authorization["providerQuote"]
    scope = authorization["scope"]
    if actual_usd is not None:
        if (
            isinstance(actual_usd, bool)
            or not isinstance(actual_usd, (int, float))
            or not math.isfinite(float(actual_usd))
            or float(actual_usd) < 0
        ):
            raise ValueError("WaveSpeed actual cost must be finite and non-negative")
        actual_usd = float(actual_usd)
    recorded_amount = actual_usd if actual_usd is not None else float(quote["amount"])
    if actual_usd is not None:
        cursor = conn.execute(
            f"""UPDATE {AUTHORIZATION_TABLE} SET amount = ?
            WHERE authorization_id = ? AND provider = 'wavespeed' AND unit = 'USD'
              AND status = 'consumed'""",
            (actual_usd, authorization["authorizationId"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise PermissionError("WaveSpeed authorization is not consumed")
    row = conn.execute(
        f"SELECT campaign_id FROM {AUTHORIZATION_TABLE} WHERE authorization_id = ?",
        (authorization["authorizationId"],),
    ).fetchone()
    return record_ai_cost(
        conn,
        provider="wavespeed",
        operation=str(scope["operation"]),
        campaign_id=str(row[0]) if row and row[0] else None,
        generations=1,
        estimated_cost_usd=recorded_amount,
        metadata={
            "schema": "campaign_factory.provider_execution_cost.v2",
            "authorizationId": authorization["authorizationId"],
            "model": scope["providerModel"],
            "predictionId": prediction_id,
            "predictionStatus": status,
            "requestFingerprint": scope["requestFingerprint"],
            "costSource": (
                "provider_prediction" if actual_usd is not None else "authorized_quote"
            ),
            "authorizedUsd": float(quote["amount"]),
            "actualUsd": actual_usd,
            "costOverrun": (
                actual_usd is not None and actual_usd > float(quote["amount"]) + 0.0001
            ),
        },
        source_event_key=(
            f"campaign_factory:{authorization['authorizationId']}:{prediction_id}"
        ),
        reservation_id=authorization["reservationId"],
        amount=recorded_amount,
        unit=USD_UNIT,
        provider_quote=quote,
        cohort_id=str(scope["cohortId"]),
        ensure_schema=False,
    )


def _reserved_total(conn: sqlite3.Connection, predicate: str, value: str) -> float:
    row = conn.execute(
        f"""SELECT COALESCE(SUM(amount), 0) FROM {AUTHORIZATION_TABLE}
        WHERE provider = 'wavespeed' AND unit = 'USD'
          AND status IN ('authorized', 'consumed') AND {predicate}""",
        (value,),
    ).fetchone()
    return float(row[0] or 0.0)


def _duration_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("WaveSpeed duration must be a whole number of seconds")
    return value


def _pricing_inputs(scope: dict[str, Any]) -> dict[str, Any]:
    parameters = scope.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("WaveSpeed pricing scope parameters are missing")
    model = str(scope.get("providerModel") or "")
    inputs: dict[str, Any] = {
        "prompt": "Creator OS exact pricing preflight",
        "resolution": parameters.get("resolution"),
        "seed": parameters.get("seed"),
    }
    duration = parameters.get("durationSeconds")
    if duration:
        inputs["duration"] = duration
    if model == "alibaba/wan-2.7/reference-to-video":
        inputs.update(
            {
                "videos": ["https://pricing.invalid/reference.mp4"],
                "aspect_ratio": "9:16",
                "enable_prompt_expansion": parameters.get("enablePromptExpansion"),
            }
        )
    elif model == "wavespeed-ai/wan-2.2/speech-to-video":
        inputs.update(
            {
                "image": "https://pricing.invalid/source.jpg",
                "audio": "https://pricing.invalid/speech.wav",
            }
        )
    else:
        inputs["image"] = "https://pricing.invalid/source.jpg"
        inputs["enable_prompt_expansion"] = parameters.get("enablePromptExpansion")
        if parameters.get("shotType"):
            inputs["shot_type"] = parameters["shotType"]
    return {key: value for key, value in inputs.items() if value is not None}


def _find_price(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    for key in (
        "unit_price",
        "price",
        "amount",
        "cost",
        "estimated_price",
        "estimatedPrice",
        "estimated_cost",
        "estimatedCost",
    ):
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            parsed = float(candidate)
            if math.isfinite(parsed) and parsed > 0:
                return parsed
        if isinstance(candidate, str):
            try:
                parsed = float(candidate)
            except ValueError:
                continue
            if math.isfinite(parsed) and parsed > 0:
                return parsed
    for key in ("data", "quote", "pricing", "result"):
        nested_price = _find_price(value.get(key))
        if nested_price is not None:
            return nested_price
    return None


def _positive_env(name: str) -> float:
    raw = os.environ.get(name)
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise PermissionError(f"{name}_missing_or_invalid") from exc
    if not math.isfinite(value) or value <= 0:
        raise PermissionError(f"{name}_missing_or_invalid")
    return value


def _nonnegative_env(name: str) -> float:
    raw = os.environ.get(name)
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise PermissionError(f"{name}_missing_or_invalid") from exc
    if not math.isfinite(value) or value < 0:
        raise PermissionError(f"{name}_missing_or_invalid")
    return value


def _iso(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
