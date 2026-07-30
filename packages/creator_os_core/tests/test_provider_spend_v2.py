from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA_V3,
    SpendAuthorizationError,
    build_paid_action_quote,
    build_paid_action_spend_scope,
    build_video_provider_spend_scope,
    sign_authorization,
    verify_authorization_v2,
    verify_authorization_v3,
)

SECRET = "test-only " * 8


def _scope(tmp_path: Path) -> dict[str, object]:
    image = tmp_path / "source.jpg"
    image.write_bytes(b"source")
    return build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model="alibaba/wan-2.7/image-to-video-pro",
        operation="image_to_video",
        campaign="campaign-one",
        cohort_id="cohort-one",
        prompt="Natural breathing and a gentle camera push toward the subject",
        media_paths={"image": image},
        parameters={"resolution": "1080p", "durationSeconds": 5, "seed": 42},
    )


def _authorization(scope: dict[str, object]) -> dict[str, object]:
    now = datetime.datetime.now(datetime.UTC)
    return sign_authorization(
        {
            "schema": "campaign_factory.provider_spend_authorization.v2",
            "authorizationId": "spauth_test",
            "reservationId": "spres_test",
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": (now - datetime.timedelta(seconds=1)).isoformat(),
            "expiresAt": (now + datetime.timedelta(minutes=5)).isoformat(),
            "scope": scope,
            "providerQuote": {
                "provider": "wavespeed",
                "model": "alibaba/wan-2.7/image-to-video-pro",
                "amount": 0.6,
                "unit": "USD",
                "pricingVersion": "test",
                "pricingFingerprint": "a" * 64,
                "catalogBasePrice": 0.6,
                "catalogModelId": "alibaba/wan-2.7/image-to-video-pro",
                "liveQuotedAmount": 0.6,
                "livePriceSource": "wavespeed_model_pricing_api",
            },
        },
        secret=SECRET,
    )


def test_v2_scope_binds_media_prompt_parameters_and_model(tmp_path: Path) -> None:
    first = _scope(tmp_path)
    image = tmp_path / "second.jpg"
    image.write_bytes(b"different source")
    second = build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model="alibaba/wan-2.7/image-to-video-pro",
        operation="image_to_video",
        campaign="campaign-one",
        cohort_id="cohort-one",
        prompt="Natural breathing and a gentle camera push toward the subject",
        media_paths={"image": image},
        parameters={"resolution": "1080p", "durationSeconds": 5, "seed": 42},
    )
    assert isinstance(first["mediaSha256"], dict)
    assert first["mediaSha256"]["image"]
    assert first["promptSha256"]
    assert first["requestFingerprint"] != second["requestFingerprint"]


def test_v2_authorization_rejects_scope_substitution(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    authorization = _authorization(scope)
    changed = {**scope, "parameters": {**scope["parameters"], "durationSeconds": 10}}
    with pytest.raises(SpendAuthorizationError, match="scope does not match"):
        verify_authorization_v2(authorization, expected_scope=changed, secret=SECRET)


def test_v3_paid_action_scope_and_quote_bind_every_budget_dimension() -> None:
    scope = build_paid_action_spend_scope(
        provider="openai",
        provider_model="gpt-5",
        action_type="recreation_prompt_pack",
        creator_id="creator_1",
        campaign_id="campaign_1",
        run_id="run_1",
        input_fingerprints={"request": "a" * 64},
        parameters={"maximumCalls": 1},
        prompt_governance={"registryFingerprint": "b" * 64},
    )
    quote = build_paid_action_quote(
        provider="openai",
        model="gpt-5",
        amount=1.25,
        source="operator_configured_quote",
        pricing_version="test.v1",
    )
    now = datetime.datetime.now(datetime.UTC)
    authorization = sign_authorization(
        {
            "schema": AUTHORIZATION_SCHEMA_V3,
            "authorizationId": "spauth_paid_action",
            "reservationId": "spres_paid_action",
            "issuer": "campaign_factory",
            "status": "authorized",
            "issuedAt": (now - datetime.timedelta(seconds=1)).isoformat(),
            "expiresAt": (now + datetime.timedelta(minutes=5)).isoformat(),
            "scope": scope,
            "providerQuote": quote,
        },
        secret=SECRET,
    )

    verified = verify_authorization_v3(
        authorization, expected_scope=scope, secret=SECRET, now=now
    )
    assert verified["scope"]["creatorId"] == "creator_1"
    assert verified["scope"]["campaignId"] == "campaign_1"
    assert verified["scope"]["runId"] == "run_1"
    assert verified["providerQuote"]["pricingFingerprint"]

    changed = {**scope, "actionType": "image_edit"}
    with pytest.raises(SpendAuthorizationError, match="scope does not match"):
        verify_authorization_v3(
            authorization, expected_scope=changed, secret=SECRET, now=now
        )
