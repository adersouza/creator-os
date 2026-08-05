from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from campaign_factory import recreation_prompting
from campaign_factory.db import init_db


@pytest.fixture(autouse=True)
def _prompt_spend_authorization_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CREATOR_OS_SPEND_AUTH_SECRET",
        "test-only-openai-prompt-authorization-secret",
    )
    monkeypatch.setenv("CREATOR_OS_OPENAI_PROMPT_QUOTE_USD", "1.25")
    monkeypatch.setenv("CREATOR_OS_PAID_DAILY_CAP_USD", "100")
    monkeypatch.setenv("CREATOR_OS_PAID_MONTHLY_CAP_USD", "1000")
    monkeypatch.setenv("CREATOR_OS_CREATOR_DAILY_CAP_USD", "100")
    monkeypatch.setenv("CREATOR_OS_CAMPAIGN_DAILY_CAP_USD", "100")
    monkeypatch.setenv("CREATOR_OS_OPENAI_DAILY_CAP_USD", "100")


def _cost_context(tmp_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(tmp_path / "cost.sqlite")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    connection.row_factory = None
    return {
        "cost_connection": connection,
        "campaign_id": "campaign_fixture",
        "run_id": f"run:{tmp_path.name}",
    }


def _soul_identity(creator: str = "stacey") -> dict[str, Any]:
    core = {
        "schema": "campaign_factory.verified_soul_identity_binding.v1",
        "creatorSlug": creator,
        "provider": "higgsfield",
        "soulId": f"soul-{creator}",
        "identityProfileId": f"identity-{creator}",
        "identityProfileVersion": 3,
        "identityProfileFingerprint": "f" * 64,
    }
    return {**core, "bindingFingerprint": recreation_prompting._fingerprint(core)}


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
                "Adult woman, age 19, with dark hair, seated in a softly lit "
                "bedroom, centered vertical frame."
            ),
            "seedancePrompt": (
                "Use the approved anchor as the exact adult woman, age 19, with "
                "dark hair. Add calm natural movement with stable framing and a "
                "relaxed expression."
            ),
            "klingPrompt": (
                "Use the approved anchor as the exact adult woman, age 19, with "
                "dark hair. Add natural blinking."
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
        **_cost_context(tmp_path),
    )

    assert observed["apiKey"] == "test-key"
    assert pack["providerPlans"]["kling"]["model"] == "kling3_0_turbo"
    assert pack["providerPlans"]["seedance"]["resolution"] == "480p"
    assert pack["identityPolicy"]["hairColorInvented"] is False
    assert pack["identityPolicy"]["tattoosInvented"] is False
    assert pack["creativeContext"]["mode"] == "calm_animation"
    assert pack["creativeContext"]["visualStyleId"] == "low_effort_selfie_reels.v1"
    planning = pack["promptPlanning"]
    assert planning["builderVersion"] == "creator_os_openai_prompt_builder.v17"
    request_text = json.dumps(observed["payload"], ensure_ascii=False).lower()
    assert "deliberately casual, believable handheld selfie" in request_text
    assert "cute fitted everyday clothing" in request_text
    assert "camera in front of part of the face" in request_text
    assert "adult woman, age 19, with dark hair" in request_text
    assert "young" not in request_text
    assert "tattoo" not in request_text
    assert planning["requestFingerprint"]
    assert planning["responseId"] == "resp_test"
    assert planning["usage"] == {
        "input_tokens": 321,
        "output_tokens": 123,
        "total_tokens": 444,
    }
    # The provider reported usage tokens here, so the ledger must carry them.
    # This previously asserted "not_exposed" even though the very same response
    # contained the token counts -- pinning the bug that left every paid call
    # reconciled as unknown and made run spend unanswerable.
    assert planning["cost"] == {
        "status": "tokens_only",
        "usd": None,
        "inputTokens": 321,
        "outputTokens": 123,
        "reasoningTokens": None,
    }
    authorization = planning["authorization"]
    assert authorization["status"] == "authorized"
    assert authorization["maximumCalls"] == 1
    assert authorization["requestFingerprint"] == planning["requestFingerprint"]
    assert authorization["quote"] == {
        "provider": "openai",
        "model": "gpt-5",
        "amount": 1.25,
        "unit": "USD",
        "source": "CREATOR_OS_OPENAI_PROMPT_QUOTE_USD",
        "pricingVersion": "operator_configured_maximum.v1",
        "pricingFingerprint": authorization["quote"]["pricingFingerprint"],
    }
    assert len(authorization["quote"]["pricingFingerprint"]) == 64
    assert planning["costLedger"]["reconciliationState"] == "unknown"
    # Distinguishes "no price table for the tokens we were told about" from
    # "the provider told us nothing" -- only the first is operator-fixable.
    assert (
        planning["costLedger"]["unknownReason"]
        == "provider_reports_tokens_not_usd:in=321:out=123:reasoning=None"
    )
    assert planning["promptGovernance"]["registryFingerprint"]
    receipt_path = Path(authorization["receiptPath"])
    assert receipt_path.is_file()
    assert (
        hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        == authorization["receiptSha256"]
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    recreation_prompting._verify_openai_prompt_authorization(
        receipt,
        secret="test-only-openai-prompt-authorization-secret",
        request_fingerprint=planning["requestFingerprint"],
    )
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


def test_openai_structural_image_prompt_preserves_visible_attraction_details() -> None:
    instruction = recreation_prompting._directed_instruction(
        "passive_selfie",
        False,
        reference_video_sha256=None,
        creator="stacey",
        soul_identity=_soul_identity(),
        structural_reference_image=True,
    )

    assert "sole creator identity source" in instruction
    assert "exact pose" in instruction
    assert "strap placement" in instruction
    assert "expression" in instruction
    assert "clothing" in instruction
    assert "visible breast size and fullness" in instruction
    assert "cleavage depth and shape" in instruction
    assert "waist-to-hip proportions" in instruction
    assert "butt size and roundness" in instruction
    assert "tightness and how it contours the body" in instruction
    assert "visible detail that makes the composition sexy" in instruction
    assert "Ground every detail in the visible reference" in instruction
    assert "invented mood" in instruction
    # Overlay artifacts must be dropped SILENTLY. Telling the model to treat
    # them as "outside the scene" made it write a sentence saying so -- "No
    # visible UI or text" -- which is both a negative and uses the very words
    # the surface guard rejects. The instruction induced the violation the
    # validator then punished, burning a paid call each time.
    assert "leave them out silently and write nothing at all about them" in instruction
    assert "describe each quality by what it is rather than by what it lacks" in (
        instruction
    )
    # The phone is a real prop in the operator's top-rated references ("phone
    # slightly covering face"), so the instruction must ask for it as-seen rather
    # than renaming it to a camera, which produced the wrong object entirely.
    assert "phone itself is a real prop" in instruction
    assert "covers part of the face" in instruction
    # The positive-phrasing requirement is asserted above; a second sentence
    # repeating it was removed. Guard against the instruction growing back into
    # mostly rules: the creative direction is what earns the shot, and every
    # extra prohibition both crowds it out and raises the salience of the words
    # it names. This ceiling is generous -- it only trips on real bloat.
    assert len(instruction) < 2000, f"instruction bloated to {len(instruction)} chars"
    assert "aspect ratio" not in instruction
    assert "Intent:" not in instruction
    assert "canvas dimensions in provider settings" in instruction
    assert "casual photographic imperfections" in instruction
    assert "scores and briefs" not in instruction
    assert "Operator preference JSON" not in instruction
    assert "Seedance" not in instruction
    assert "Kling" not in instruction
    assert "timeline" not in instruction
    assert "soul-stacey" not in instruction
    image_schema = recreation_prompting._response_schema(image_only=True)
    assert image_schema["required"] == ["anchorPrompt"]
    assert set(image_schema["properties"]) == {"anchorPrompt"}
    assert "negativePrompt" not in image_schema["properties"]


@pytest.mark.parametrize(
    ("has_reference_video", "structural_reference_image"),
    [(False, False), (False, True), (True, False)],
)
def test_openai_instructions_leave_canvas_ratio_and_internal_labels_to_runtime(
    has_reference_video: bool, structural_reference_image: bool
) -> None:
    instruction = recreation_prompting._directed_instruction(
        "passive_selfie",
        has_reference_video,
        reference_video_sha256=("a" * 64 if has_reference_video else None),
        creator="stacey",
        soul_identity=_soul_identity(),
        structural_reference_image=structural_reference_image,
    )

    assert "9:16" not in instruction
    assert "Intent:" not in instruction
    assert "snapshot" not in instruction.lower()


def test_openai_structural_image_request_returns_only_soul_image_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference_image = tmp_path / "reference.png"
    reference_image.write_bytes(b"structural reference")
    observed: dict[str, Any] = {}

    def fake_post(payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
        observed["payload"] = payload
        return {
            "id": "resp_image_only",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "anchorPrompt": (
                                        "Adult woman, age 19, with dark hair, seated at "
                                        "a three-quarter angle in a softly lit bedroom, "
                                        "wearing a fitted black top with a relaxed gaze."
                                    )
                                }
                            ),
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(recreation_prompting, "_post_responses", fake_post)
    pack = recreation_prompting.build_openai_prompt_pack(
        creator="stacey",
        creator_image=reference_image,
        intent="static_selfie",
        api_key="test-key",
        cache_root=tmp_path / "cache-image-only",
        external_call_authorized=True,
        soul_identity=_soul_identity(),
        **_cost_context(tmp_path),
    )

    schema = observed["payload"]["text"]["format"]["schema"]
    assert schema["required"] == ["anchorPrompt"]
    assert set(schema["properties"]) == {"anchorPrompt"}
    assert pack["promptScope"] == "soul_image_only"
    assert pack["providerPlans"] == {}
    assert "seedancePrompt" not in pack
    assert "klingPrompt" not in pack
    assert "timeline" not in pack
    recreation_prompting.validate_prompt_pack(pack)


def test_openai_prompt_pack_requires_signed_quote_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")
    monkeypatch.delenv("CREATOR_OS_OPENAI_PROMPT_QUOTE_USD")
    monkeypatch.setattr(
        recreation_prompting,
        "_post_responses",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unquoted request must not call OpenAI")
        ),
    )

    with pytest.raises(RuntimeError, match="openai_prompt_spend_quote_missing"):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / "cache",
            external_call_authorized=True,
            **_cost_context(tmp_path),
        )


def test_openai_prompt_pack_blocks_media_changed_after_authorization_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator_image = tmp_path / "creator.png"
    creator_image.write_bytes(b"approved creator")
    original_authorize = recreation_prompting._authorize_openai_prompt_call
    provider_called = False

    def authorize_then_replace(*args: Any, **kwargs: Any) -> dict[str, Any]:
        authorization = original_authorize(*args, **kwargs)
        creator_image.write_bytes(b"substituted after authorization")
        return authorization

    def provider_call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal provider_called
        provider_called = True
        return {}

    monkeypatch.setattr(
        recreation_prompting,
        "_authorize_openai_prompt_call",
        authorize_then_replace,
    )
    monkeypatch.setattr(recreation_prompting, "_post_responses", provider_call)
    context = _cost_context(tmp_path)

    with pytest.raises(
        PermissionError, match="openai_prompt_creator_image_sha256_mismatch"
    ):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / "cache",
            external_call_authorized=True,
            **context,
        )

    assert provider_called is False
    row = (
        context["cost_connection"]
        .execute(
            """
        SELECT reconciliation_state, actual_usd, provider_reference
        FROM ai_cost_events ORDER BY created_at DESC LIMIT 1
        """
        )
        .fetchone()
    )
    assert row == ("reconciled", 0.0, None)


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


def test_openai_prompt_pack_blocks_disabled_creator_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_called = False

    def provider_call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal provider_called
        provider_called = True
        return {}

    monkeypatch.setattr(recreation_prompting, "_post_responses", provider_call)
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        recreation_prompting.build_openai_prompt_pack(
            creator="lola",
            creator_image=tmp_path / "missing.png",
            intent="passive_selfie",
            external_call_authorized=True,
        )
    assert provider_called is False


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

    with pytest.raises(ValueError, match="contains_forbidden_language"):
        recreation_prompting.build_openai_prompt_pack(
            creator="stacey",
            creator_image=creator_image,
            intent="passive_selfie",
            api_key="test-key",
            cache_root=tmp_path / "cache",
            external_call_authorized=True,
            **_cost_context(tmp_path),
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
        "anchorPrompt": (
            "Adult woman, age 19, with dark hair, seated in a softly lit bedroom."
        ),
        "seedancePrompt": (
            "The adult woman, age 19, with dark hair, moves naturally with stable "
            "framing."
        ),
        "klingPrompt": (
            "The adult woman, age 19, with dark hair, blinks naturally with a "
            "relaxed expression."
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
            **_cost_context(tmp_path),
        )


def test_frame_sample_plan_prioritizes_opening_and_endpoint() -> None:
    plan = recreation_prompting._frame_sample_plan(8.0)

    assert len(plan) >= 8
    assert plan[0] == {"role": "opening_first", "timestampSeconds": 0.0}
    assert [item["role"] for item in plan[1:4]] == [
        "opening_burst",
        "opening_burst",
        "opening_burst",
    ]
    assert plan[-1]["role"] == "endpoint"
    assert plan[-1]["timestampSeconds"] == pytest.approx(7.92)
    assert len({item["timestampSeconds"] for item in plan}) == len(plan)


def test_reference_prompt_input_is_exact_sha_bound_and_visually_directed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference_video = tmp_path / "reference.mp4"
    reference_video.write_bytes(b"unique reference reel")
    reference_sha = hashlib.sha256(reference_video.read_bytes()).hexdigest()
    observed: dict[str, Any] = {}

    def fake_samples(_video: Path, output_dir: Path) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for index, item in enumerate(recreation_prompting._frame_sample_plan(8.0)):
            frame = output_dir / f"frame-{index:02d}.jpg"
            frame.write_bytes(f"frame-{index}".encode())
            samples.append({**item, "path": frame})
        return samples

    def fake_post(payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
        observed["payload"] = payload
        observed["apiKey"] = api_key
        value = {
            "anchorPrompt": (
                "Adult woman, age 19, with dark hair, holds the exact opening pose "
                "at a low three-quarter body angle with fitted non-explicit styling."
            ),
            "seedancePrompt": (
                "The exact adult woman, age 19, with dark hair, follows the visible "
                "pose and framing progression with stable identity."
            ),
            "klingPrompt": (
                "The exact adult woman, age 19, with dark hair, holds the visible "
                "opening pose with subtle natural movement."
            ),
            "timeline": [
                {
                    "startSeconds": 0,
                    "endSeconds": 8,
                    "action": "Hold the opening pose, then complete the visible motion.",
                    "camera": "Follow the sampled framing progression.",
                }
            ],
        }
        return {
            "id": "resp_reference_test",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }
            ],
        }

    monkeypatch.setattr(recreation_prompting, "_sample_frames", fake_samples)
    monkeypatch.setattr(recreation_prompting, "_post_responses", fake_post)

    pack = recreation_prompting.build_openai_prompt_pack(
        creator="stacey",
        reference_video=reference_video,
        intent="recreate_reel",
        api_key="test-key",
        cache_root=tmp_path / "cache-reference",
        external_call_authorized=True,
        soul_identity=_soul_identity(),
        **_cost_context(tmp_path),
    )

    content = observed["payload"]["input"][0]["content"]
    instruction = content[0]["text"]
    labels = [item["text"] for item in content if item["type"] == "input_text"]
    assert reference_sha in instruction
    assert "exact pose, framing, body angle" in instruction
    assert "fuller-chest and cleavage framing" in instruction
    assert "rounded hip and butt silhouette" in instruction
    assert "adult woman, age 19, with dark hair" in instruction
    assert "creator slug stacey" not in instruction.lower()
    assert "soul-stacey" not in instruction
    assert "profile fingerprint" not in instruction.lower()
    assert "approved creator image" not in instruction.lower()
    assert "first image is the approved creator identity" not in instruction.lower()
    assert len(labels[1:]) >= 8
    assert len([item for item in content if item["type"] == "input_image"]) == len(
        labels[1:]
    )
    assert all(reference_sha in label for label in labels[1:])
    assert "role=opening_first" in labels[1]
    assert "role=endpoint" in labels[-1]
    assert pack["referenceVideo"]["sha256"] == reference_sha
    assert pack["creatorImage"] is None
    assert pack["soulIdentity"] == _soul_identity()
    assert pack["creatorPresentationPolicy"]["age"] == 19
    assert (
        pack["promptPlanning"]["authorization"]["payload"]["scope"][
            "inputFingerprints"
        ]["reference_video"]
        == reference_sha
    )


@pytest.mark.parametrize(
    "word",
    [
        "tattoo",
        "tattoos",
        "young",
        "overlay",
        "caption",
        "UI",
        "interface",
        "screenshot",
        "watermark",
        "logo",
    ],
)
def test_generated_prompt_language_rejects_forbidden_terms(word: str) -> None:
    with pytest.raises(ValueError, match="contains_forbidden_language"):
        recreation_prompting._validated_positive_prompt(
            f"Adult woman, age 19, with dark hair and {word} styling.",
            "seedance",
        )


def test_anchor_prompt_rejects_provider_aspect_ratio() -> None:
    with pytest.raises(ValueError, match="contains_provider_aspect_ratio"):
        recreation_prompting._validated_anchor_prompt(
            "Adult woman, age 19, with dark hair in a vertical 4:5 crop."
        )


def test_television_screen_still_normalizes_to_the_object() -> None:
    assert recreation_prompting._validated_anchor_prompt(
        "Adult woman, age 19, with dark hair near a TV screen emitting cool light."
    ).endswith("near a television emitting cool light.")
    assert recreation_prompting._validated_anchor_prompt(
        "Adult woman, age 19, with dark hair holding her phone screen up."
    ).endswith("holding her phone up.")


def test_ordinary_scene_words_are_not_treated_as_rendered_interfaces() -> None:
    """`screen` and `chrome` are scene words before they are interface words.

    Authored prompts were rejected for "gaze directed into the screen" (where
    the subject is looking) and would have been for "a chrome faucet at the sink
    front edge" (what the tap is made of). Neither makes a generator draw an
    interface. Operator direction is to relax first and restore a term only if a
    rendered interface actually appears in a generation.
    """

    for phrase in (
        "gaze directed into the screen, eyes partially hidden",
        "a chrome faucet and tap set at the sink front edge",
        "near a projection screen",
    ):
        recreation_prompting._validated_anchor_prompt(
            f"Adult woman, age 19, with dark hair, {phrase}."
        )
    # The terms that actually produce a drawn interface still fail closed.
    for word in ("app", "ui", "interface", "watermark", "overlay", "logo"):
        with pytest.raises(ValueError, match="contains_forbidden_language"):
            recreation_prompting._validated_anchor_prompt(
                f"Adult woman, age 19, with dark hair and {word} styling."
            )


def test_adult_age_format_normalizes_without_changing_presentation() -> None:
    prompt = recreation_prompting._validated_anchor_prompt(
        "Adult woman, 19, with dark hair in a softly lit bedroom."
    )
    assert "adult woman, age 19" in prompt.lower()
    recreation_prompting._validated_creator_presentation(prompt, "anchor")


@pytest.mark.parametrize("label", ["anchor", "seedance", "kling"])
def test_every_generated_prompt_rejects_internal_intent_label(label: str) -> None:
    with pytest.raises(ValueError, match="contains_internal_label"):
        recreation_prompting._validated_positive_prompt(
            "Intent: passive selfie. Adult woman, age 19, with dark hair.", label
        )


def test_creator_presentation_requires_explicit_adult_age_and_dark_hair() -> None:
    with pytest.raises(ValueError, match="missing_adult_presentation"):
        recreation_prompting._validated_creator_presentation(
            "Young woman with brunette hair in a casual selfie.", "anchor"
        )


def test_incomplete_response_names_the_token_ceiling_not_a_json_error() -> None:
    """A truncated pack must not surface as malformed provider output.

    The provider bills reasoning tokens against ``max_output_tokens``, so an
    undersized ceiling returns a partial JSON body. Parsing it raised a bare
    JSONDecodeError, which reads like the provider sent garbage and sends the
    reader to the wrong place entirely.
    """

    response = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "usage": {
            "output_tokens": 4000,
            "output_tokens_details": {"reasoning_tokens": 3904},
        },
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"anchorPrompt": "A ph'}],
            }
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        recreation_prompting._response_json(response)
    message = str(excinfo.value)
    assert "openai_prompt_generation_incomplete" in message
    assert "max_output_tokens" in message
    # The reported ceiling has to be the one actually sent, and the reasoning
    # spend has to be visible, or the limit cannot be sized from evidence.
    assert f"limit={recreation_prompting._MAX_OUTPUT_TOKENS}" in message
    assert "reasoning_tokens=3904" in message


def test_complete_response_still_parses() -> None:
    response = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"anchorPrompt": "ok"}'}],
            }
        ],
    }
    assert recreation_prompting._response_json(response) == {"anchorPrompt": "ok"}


def test_run_cap_survives_more_than_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single failed call must not permanently brick that reference.

    The run cap used to be the single-call quote, so one reservation filled the
    run budget exactly and every retry died on provider_budget_exceeded:run.
    """

    monkeypatch.delenv("CREATOR_OS_OPENAI_PROMPT_RUN_CAP_USD", raising=False)
    assert recreation_prompting._prompt_run_cap_usd(0.5) > 0.5


def test_run_cap_is_still_configurable_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATOR_OS_OPENAI_PROMPT_RUN_CAP_USD", "3.00")
    assert recreation_prompting._prompt_run_cap_usd(0.5) == 3.00
    # A cap under one call's quote could never authorize anything; say so
    # rather than failing later with an exhausted-budget error.
    monkeypatch.setenv("CREATOR_OS_OPENAI_PROMPT_RUN_CAP_USD", "0.10")
    with pytest.raises(ValueError, match="run_cap_below_single_call_quote"):
        recreation_prompting._prompt_run_cap_usd(0.5)
    monkeypatch.setenv("CREATOR_OS_OPENAI_PROMPT_RUN_CAP_USD", "0")
    with pytest.raises(ValueError, match="must be positive"):
        recreation_prompting._prompt_run_cap_usd(0.5)


def test_usage_tokens_are_recorded_when_provider_reports_no_dollars() -> None:
    """OpenAI reports `usage`, never `cost`; reading only `cost` lost the spend."""

    parsed = recreation_prompting._response_cost(
        {
            "usage": {
                "input_tokens": 1500,
                "output_tokens": 900,
                "output_tokens_details": {"reasoning_tokens": 640},
            }
        }
    )
    assert parsed["status"] == "tokens_only"
    assert parsed["inputTokens"] == 1500
    assert parsed["outputTokens"] == 900
    assert parsed["reasoningTokens"] == 640
    # An explicitly reported dollar amount still wins when one is present.
    assert recreation_prompting._response_cost({"cost": {"usd": 0.02}}) == {
        "status": "reported",
        "usd": 0.02,
    }
