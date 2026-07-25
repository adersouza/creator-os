from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from campaign_factory.provider_spend import ensure_authorization_table
from campaign_factory.provider_spend_v2 import (
    _find_price,
    issue_wavespeed_spend_authorization,
    quote_wavespeed_scope,
)
from creator_os_core.provider_spend import build_video_provider_spend_scope

SECRET = "test-only " * 8


class Balance:
    def __init__(self, value: float | None) -> None:
        self.value = value

    def balance(self) -> float | None:
        return self.value


class Catalog:
    def model(self, model_id: str) -> dict:
        return {"model_id": model_id, "base_price": 0.6}


class Pricing:
    def quote(self, _scope: dict) -> float:
        return 0.6


def _scope(tmp_path: Path, model: str, resolution: str, duration: int) -> dict:
    image = tmp_path / "image.jpg"
    image.write_bytes(b"source")
    return build_video_provider_spend_scope(
        provider="wavespeed",
        provider_model=model,
        operation="image_to_video",
        campaign="campaign",
        cohort_id="cohort",
        prompt="Natural breathing and a slow cinematic camera move",
        media_paths={"image": image},
        parameters={
            "resolution": resolution,
            "durationSeconds": duration,
            "seed": 42,
        },
    )


def test_wan27_pro_quote_covers_all_documented_quality_tiers(tmp_path: Path) -> None:
    assert (
        quote_wavespeed_scope(
            _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "1080p", 5)
        )["amount"]
        == 0.6
    )
    assert (
        quote_wavespeed_scope(
            _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "2k", 10)
        )["amount"]
        == 1.4
    )
    assert (
        quote_wavespeed_scope(
            _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "4k", 15)
        )["amount"]
        == 2.4
    )


def test_wan22_i2v_5b_quote_is_fixed_at_five_cents(tmp_path: Path) -> None:
    quote = quote_wavespeed_scope(
        _scope(tmp_path, "wavespeed-ai/wan-2.2/i2v-5b-720p", "720p", 5)
    )
    assert quote["amount"] == 0.05
    with pytest.raises(ValueError, match="pricing parameters"):
        quote_wavespeed_scope(
            _scope(tmp_path, "wavespeed-ai/wan-2.2/i2v-5b-720p", "1080p", 5)
        )


def test_premium_recipe_quotes_match_documented_duration_rates(
    tmp_path: Path,
) -> None:
    o3 = _scope(
        tmp_path,
        "kwaivgi/kling-video-o3-pro/image-to-video",
        "provider_default",
        5,
    )
    assert quote_wavespeed_scope(o3)["amount"] == 0.56

    vidu = _scope(tmp_path, "vidu/q3/image-to-video-pro", "1080p", 5)
    assert quote_wavespeed_scope(vidu)["amount"] == 0.5

    infinite = _scope(tmp_path, "wavespeed-ai/infinitetalk", "720p", 0)
    infinite["parameters"]["audioDurationSeconds"] = 8.0
    assert quote_wavespeed_scope(infinite)["amount"] == 0.48

    motion = _scope(
        tmp_path,
        "kwaivgi/kling-v3.0-pro/motion-control",
        "provider_default",
        0,
    )
    motion["parameters"]["referenceVideoDurationSeconds"] = 3.0
    assert quote_wavespeed_scope(motion)["amount"] == 0.504

    lipsync = _scope(tmp_path, "sync/lipsync-2-pro", "source", 0)
    lipsync["parameters"]["audioDurationSeconds"] = 8.0
    assert quote_wavespeed_scope(lipsync)["amount"] == 0.64

    lipsync3 = _scope(tmp_path, "sync/lipsync-3", "source", 0)
    lipsync3["parameters"]["sourceVideoDurationSeconds"] = 8.0
    assert quote_wavespeed_scope(lipsync3)["amount"] == 1.072


def test_authorization_requires_caps_balance_and_exact_run_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "WAVESPEED_DAILY_BUDGET_USD": "20",
        "WAVESPEED_MONTHLY_BUDGET_USD": "100",
        "WAVESPEED_COHORT_MAX_USD": "10",
        "WAVESPEED_MIN_BALANCE_USD": "2",
    }.items():
        monkeypatch.setenv(name, value)
    conn = sqlite3.connect(":memory:")
    ensure_authorization_table(conn)
    scope = _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "1080p", 5)
    with pytest.raises(PermissionError, match="run_cap"):
        issue_wavespeed_spend_authorization(
            conn,
            scope=scope,
            campaign_id=None,
            max_usd=0.5,
            secret=SECRET,
            balance_provider=Balance(20),
            model_catalog_provider=Catalog(),
            pricing_provider=Pricing(),
        )
    authorization = issue_wavespeed_spend_authorization(
        conn,
        scope=scope,
        campaign_id=None,
        max_usd=1,
        secret=SECRET,
        balance_provider=Balance(20),
        model_catalog_provider=Catalog(),
        pricing_provider=Pricing(),
    )
    assert authorization["providerQuote"]["amount"] == 0.6
    assert authorization["providerQuote"]["livePriceSource"] == (
        "wavespeed_model_pricing_api"
    )
    assert authorization["scope"] == scope


def test_authorization_fails_when_live_price_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "WAVESPEED_DAILY_BUDGET_USD": "20",
        "WAVESPEED_MONTHLY_BUDGET_USD": "100",
        "WAVESPEED_COHORT_MAX_USD": "10",
        "WAVESPEED_MIN_BALANCE_USD": "2",
    }.items():
        monkeypatch.setenv(name, value)
    conn = sqlite3.connect(":memory:")
    ensure_authorization_table(conn)
    scope = _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "1080p", 5)

    class DriftedPricing:
        def quote(self, _scope: dict) -> float:
            return 0.8

    with pytest.raises(PermissionError, match="live_price_mismatch"):
        issue_wavespeed_spend_authorization(
            conn,
            scope=scope,
            campaign_id=None,
            max_usd=1,
            secret=SECRET,
            balance_provider=Balance(20),
            model_catalog_provider=Catalog(),
            pricing_provider=DriftedPricing(),
        )
    count = conn.execute(
        "SELECT COUNT(*) FROM provider_spend_authorizations"
    ).fetchone()[0]
    assert count == 0


def test_official_pricing_response_unit_price_is_recognized() -> None:
    assert _find_price(
        {
            "code": 200,
            "data": {
                "model_id": "alibaba/wan-2.7/image-to-video-pro",
                "unit_price": 0.6,
                "currency": "USD",
            },
        }
    ) == pytest.approx(0.6)


def test_invalid_authorization_ttl_fails_before_live_checks_or_database_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAVESPEED_DAILY_BUDGET_USD", "20")
    monkeypatch.setenv("WAVESPEED_MONTHLY_BUDGET_USD", "100")
    monkeypatch.setenv("WAVESPEED_COHORT_MAX_USD", "10")
    monkeypatch.setenv("WAVESPEED_MIN_BALANCE_USD", "2")
    conn = sqlite3.connect(":memory:")
    ensure_authorization_table(conn)
    scope = _scope(tmp_path, "alibaba/wan-2.7/image-to-video-pro", "1080p", 5)
    with pytest.raises(ValueError, match="TTL"):
        issue_wavespeed_spend_authorization(
            conn,
            scope=scope,
            campaign_id=None,
            max_usd=1,
            secret=SECRET,
            balance_provider=Balance(20),
            model_catalog_provider=Catalog(),
            pricing_provider=Pricing(),
            ttl_seconds=0,
        )
    count = conn.execute(
        "SELECT COUNT(*) FROM provider_spend_authorizations"
    ).fetchone()[0]
    assert count == 0
