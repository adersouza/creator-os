from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from campaign_factory import recreation_prompting


def test_openai_prompt_pack_binds_identity_and_provider_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")
    observed: dict[str, Any] = {}

    def fake_post(payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
        observed["payload"] = payload
        observed["apiKey"] = api_key
        value = {
            "anchorPrompt": (
                "Adult woman seated in a softly lit bedroom, centered vertical frame."
            ),
            "seedancePrompt": (
                "Use the approved anchor as the exact person. Add calm natural "
                "movement with stable framing and a relaxed expression."
            ),
            "klingPrompt": (
                "Use the approved anchor as the exact person. Add natural blinking."
            ),
            "timeline": [
                {
                    "startSeconds": 0,
                    "endSeconds": 5,
                    "action": "Breathe and blink naturally.",
                    "camera": "Remain fixed.",
                }
            ],
        }
        return {
            "id": "resp_test",
            "usage": {
                "input_tokens": 321,
                "output_tokens": 123,
                "total_tokens": 444,
            },
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }
            ],
        }

    monkeypatch.setattr(recreation_prompting, "_post_responses", fake_post)
    pack = recreation_prompting.build_openai_prompt_pack(
        creator="stacey",
        creator_image=creator_image,
        intent="passive_selfie",
        api_key="test-key",
        cache_root=tmp_path / "cache",
        external_call_authorized=True,
    )

    assert observed["apiKey"] == "test-key"
    assert pack["providerPlans"]["kling"]["model"] == "kling3_0_turbo"
    assert pack["providerPlans"]["seedance"]["resolution"] == "480p"
    assert pack["identityPolicy"]["hairColorInvented"] is False
    assert pack["identityPolicy"]["tattoosInvented"] is False
    assert pack["promptPlanning"] == {
        "builderVersion": "creator_os_openai_prompt_builder.v2",
        "requestFingerprint": pack["promptPlanning"]["requestFingerprint"],
        "responseId": "resp_test",
        "usage": {
            "input_tokens": 321,
            "output_tokens": 123,
            "total_tokens": 444,
        },
        "cost": {"status": "not_exposed", "usd": None},
    }
    assert pack["cache"]["status"] == "miss"
    assert pack["cache"]["promptCallAuthorization"] == {
        "authorized": True,
        "scope": "request_fingerprint",
        "requestFingerprint": pack["promptPlanning"]["requestFingerprint"],
        "maximumCalls": 1,
        "cacheCheckedFirst": True,
        "currentRunCalls": 1,
    }
    response_properties = observed["payload"]["text"]["format"]["schema"]["properties"]
    assert "negativePrompt" not in response_properties
    recreation_prompting.validate_prompt_pack(pack)
    monkeypatch.setattr(
        recreation_prompting,
        "_post_responses",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cached prompt pack must avoid a second OpenAI call")
        ),
    )
    cached = recreation_prompting.build_openai_prompt_pack(
        creator="stacey",
        creator_image=creator_image,
        intent="passive_selfie",
        cache_root=tmp_path / "cache",
    )
    assert cached["cache"]["status"] == "hit"
    assert cached["cache"]["providerCallMade"] is False
    assert cached["cache"]["promptCallAuthorization"]["authorized"] is False
    assert cached["cache"]["promptCallAuthorization"]["currentRunCalls"] == 0
    assert cached["promptPackFingerprint"] == pack["promptPackFingerprint"]


def test_openai_prompt_pack_cache_miss_requires_external_call_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")
    monkeypatch.setattr(
        recreation_prompting,
        "_post_responses",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unauthorized request must not call OpenAI")
        ),
    )

    with pytest.raises(
        PermissionError, match="openai_prompt_call_authorization_required"
    ):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / "cache",
        )


def test_anchor_prompt_rejects_invented_identity_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")

    monkeypatch.setattr(
        recreation_prompting,
        "_post_responses",
        lambda *_args, **_kwargs: {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "anchorPrompt": (
                                        "Adult brunette woman with a new tattoo."
                                    ),
                                    "seedancePrompt": "Animate calmly.",
                                    "klingPrompt": "Animate calmly.",
                                    "timeline": [],
                                }
                            ),
                        }
                    ],
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="identity_or_ui_terms"):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / "cache",
            external_call_authorized=True,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "anchorPrompt",
            "Adult woman in a softly lit bedroom with no visible logos.",
            "anchor_prompt_contains_negative_language",
        ),
        (
            "seedancePrompt",
            "Animate calmly without camera movement.",
            "seedance_prompt_contains_negative_language",
        ),
        (
            "klingPrompt",
            "Natural blinking. Avoid large gestures.",
            "kling_prompt_contains_negative_language",
        ),
    ],
)
def test_openai_prompt_pack_rejects_negative_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    error: str,
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")
    response = {
        "anchorPrompt": "Adult woman seated in a softly lit bedroom.",
        "seedancePrompt": "Calm natural movement with stable framing.",
        "klingPrompt": "Natural blinking with a relaxed expression.",
        "timeline": [
            {
                "startSeconds": 0,
                "endSeconds": 5,
                "action": "Breathe and blink naturally.",
                "camera": "Remain fixed.",
            }
        ],
    }
    response[field] = value
    monkeypatch.setattr(
        recreation_prompting,
        "_post_responses",
        lambda *_args, **_kwargs: {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(response)}],
                }
            ]
        },
    )

    with pytest.raises(ValueError, match=error):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / f"cache-{field}",
            external_call_authorized=True,
        )
