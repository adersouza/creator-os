from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from creator_os_core.provider_spend import (
    AUTHORIZATION_SCHEMA,
    SpendAuthorizationError,
    build_generate_assets_spend_scope,
    sign_authorization,
)
from reel_factory.generate_assets import AssetGenerationPlan, create_image_asset
from reel_factory.provider_spend_authorization import (
    require_campaign_spend_authorization,
    spend_scope_args_for_plan,
)

SECRET = "test-only-spend-authorization-secret-32-bytes"
SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"


def _args(prompt: Path, *, stem: str = "clip_1") -> list[str]:
    return [
        "image",
        "--prompt-json",
        str(prompt),
        "--stem",
        stem,
        "--campaign",
        "stacey",
        "--cohort-id",
        "stacey",
        "--soul-id",
        SOUL_ID,
    ]


def _authorization(scope: dict, *, now: datetime, **overrides) -> dict:
    payload = {
        "schema": AUTHORIZATION_SCHEMA,
        "authorizationId": "spauth_test",
        "reservationId": "spres_test",
        "issuer": "campaign_factory",
        "status": "authorized",
        "issuedAt": now.isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "scope": scope,
        "providerQuote": {
            "provider": "higgsfield",
            "amount": 5,
            "unit": "higgsfield_credits",
        },
        **overrides,
    }
    return sign_authorization(payload, secret=SECRET)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_authorization_fails_before_any_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text(
        json.dumps(
            {"higgsfieldGridPrompt": "test still", "klingMotionPrompt": "motion"}
        ),
        encoding="utf-8",
    )
    plan = AssetGenerationPlan(
        prompt_json=prompt,
        stem="clip_1",
        reference=None,
        soul_id=SOUL_ID,
        soul_name=None,
        start_image=None,
        out_dir=tmp_path / "out",
        source_dir=tmp_path / "source",
        campaign="stacey",
        cohort_id="stacey",
    )
    provider = Mock()
    monkeypatch.setattr("reel_factory.generate_assets._run_json", provider)

    with pytest.raises(SpendAuthorizationError, match="Campaign-issued"):
        create_image_asset(plan, download=False)

    provider.assert_not_called()


def test_invalid_expired_scope_and_replay_fail_closed(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text("{}", encoding="utf-8")
    args = _args(prompt)
    scope = build_generate_assets_spend_scope(args, root=tmp_path)
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    receipt_db = tmp_path / "receipts.sqlite"

    invalid = _authorization(scope, now=now)
    invalid["signature"] = "0" * 64
    invalid_path = _write(tmp_path / "invalid.json", invalid)
    with pytest.raises(SpendAuthorizationError, match="signature is invalid"):
        require_campaign_spend_authorization(
            args,
            root=tmp_path,
            authorization_file=invalid_path,
            secret=SECRET,
            receipt_db_path=receipt_db,
            now=now,
        )

    expired = _authorization(
        scope,
        now=now - timedelta(minutes=10),
        expiresAt=(now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    )
    expired_path = _write(tmp_path / "expired.json", expired)
    with pytest.raises(SpendAuthorizationError, match="expired or not active"):
        require_campaign_spend_authorization(
            args,
            root=tmp_path,
            authorization_file=expired_path,
            secret=SECRET,
            receipt_db_path=receipt_db,
            now=now,
        )

    other_scope = build_generate_assets_spend_scope(
        _args(prompt, stem="other"), root=tmp_path
    )
    wrong_scope_path = _write(
        tmp_path / "wrong-scope.json", _authorization(other_scope, now=now)
    )
    with pytest.raises(SpendAuthorizationError, match="scope does not match"):
        require_campaign_spend_authorization(
            args,
            root=tmp_path,
            authorization_file=wrong_scope_path,
            secret=SECRET,
            receipt_db_path=receipt_db,
            now=now,
        )

    valid_path = _write(tmp_path / "valid.json", _authorization(scope, now=now))
    consumed = require_campaign_spend_authorization(
        args,
        root=tmp_path,
        authorization_file=valid_path,
        secret=SECRET,
        receipt_db_path=receipt_db,
        now=now,
    )
    assert consumed["authorizationId"] == "spauth_test"
    with pytest.raises(SpendAuthorizationError, match="already consumed"):
        require_campaign_spend_authorization(
            args,
            root=tmp_path,
            authorization_file=valid_path,
            secret=SECRET,
            receipt_db_path=receipt_db,
            now=now,
        )


def test_valid_campaign_authorization_reaches_fake_provider_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = tmp_path / "prompt.json"
    prompt.write_text(
        json.dumps(
            {"higgsfieldGridPrompt": "test still", "klingMotionPrompt": "motion"}
        ),
        encoding="utf-8",
    )
    plan = AssetGenerationPlan(
        prompt_json=prompt,
        stem="clip_1",
        reference=None,
        soul_id=SOUL_ID,
        soul_name=None,
        start_image=None,
        out_dir=tmp_path / "out",
        source_dir=tmp_path / "source",
        campaign="stacey",
        cohort_id="stacey",
    )
    args = spend_scope_args_for_plan(plan, mode="image")
    scope = build_generate_assets_spend_scope(args, root=plan.source_dir.parent)
    now = datetime.now(UTC)
    auth_path = _write(tmp_path / "auth.json", _authorization(scope, now=now))
    plan = AssetGenerationPlan(
        **{**plan.__dict__, "spend_authorization_file": auth_path}
    )
    monkeypatch.setenv("CREATOR_OS_SPEND_AUTH_SECRET", SECRET)
    monkeypatch.setenv("CREATOR_OS_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(
        "reel_factory.generate_assets.ensure_required_capabilities",
        lambda *_args: {
            "schema": "cap",
            "createdAt": 1,
            "imageModels": [{"job_set_type": "text2image_soul_v2", "parameters": []}],
            "videoModels": [{"job_set_type": "kling3_0"}],
        },
    )
    provider = Mock(
        return_value={
            "id": "job_1",
            "status": "completed",
            "credits": 4,
            "params": {"custom_reference_id": SOUL_ID},
        }
    )
    monkeypatch.setattr("reel_factory.generate_assets._run_json", provider)

    result = create_image_asset(plan, download=False)

    assert result["ok"] is True
    provider.assert_called_once()
    execution = result["lineage"]["generation"]["providerExecution"]
    assert execution["authorizationId"] == "spauth_test"
    assert execution["events"][0]["jobId"] == "job_1"
