from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from campaign_factory import recreation_modes
from campaign_factory.recreation_prompting import SCHEMA as PROMPT_SCHEMA


def _intake(
    *,
    talking: bool = False,
    classification: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "reference": {
            "referenceId": "ref_url_example",
            "source": {"sha256": "a" * 64},
            "media": {"durationSeconds": 6.0, "hasAudio": True},
            "sourceSpeakingClassification": (
                "DECLARED_TALKING" if talking else "UNKNOWN"
            ),
            "operatorClassification": classification,
            "operatorWarnings": warnings or [],
            "sceneCutsSeconds": [0.0],
            "selectedAnchor": {"timeSec": 3.0, "sha256": "b" * 64},
            "frameDerivatives": {
                "first_clean": {"timeSec": 0.0, "sha256": "c" * 64},
                "best_anchor": {"timeSec": 3.0, "sha256": "d" * 64},
            },
            "anchorCandidates": [
                {
                    "excluded": False,
                    "exclusions": [],
                    "measurements": {
                        "faceVisibility": 0.8,
                        "bodyExtent": 0.75,
                        "sharpness": 0.9,
                        "principalPersonCount": 1,
                        "framingCompatibility": "compatible",
                    },
                }
            ],
        },
        "audio": {
            "classification": "REFERENCE_AUDIO_ELIGIBLE",
            "canonicalAudioId": "audio_ref_example",
            "occurrenceId": "audio_occ_example",
        },
    }


def _prompt_pack() -> dict[str, Any]:
    core = {
        "schema": PROMPT_SCHEMA,
        "anchorPrompt": "Adult woman seated in a softly lit bedroom, vertical framing.",
        "seedancePrompt": (
            "Use the approved anchor as the exact person. Copy the six-second "
            "gesture timeline with fixed framing and silent provider output."
        ),
        "klingPrompt": (
            "Use the approved anchor as the exact person. Add calm breathing, "
            "natural blinking, and subtle head movement."
        ),
        "promptPlanning": {
            "builderVersion": "creator_os_openai_prompt_builder.v4",
            "requestFingerprint": "e" * 64,
            "responseId": "response-test",
            "usage": {},
            "cost": {"status": "not_exposed", "usd": None},
        },
    }
    return {
        **core,
        "promptPackFingerprint": recreation_modes._fingerprint(core),
    }


def _quote(model: str, _params: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "credits": {
            "text2image_soul_v2": 0.12,
            "kling3_0_turbo": 5.0,
            "seedance_2_0": 10.5,
        }[model],
        "unit": "higgsfield_credits",
        "source": "test",
    }


def _plan(
    monkeypatch: pytest.MonkeyPatch,
    *,
    creator: str = "stacey",
    mode: str = "auto",
    intake: dict[str, Any] | None = None,
    motion: float = 0.01,
    prompts: bool = True,
) -> dict[str, Any]:
    monkeypatch.setattr(recreation_modes, "_coarse_motion_energy", lambda _: motion)
    provider_identity_id = f"registry-soul-{creator}"
    return recreation_modes.plan_recreation(
        creator=creator,
        source_video=Path("/private/reference.mp4"),
        intake=intake or _intake(),
        requested_mode=mode,
        audio_policy="auto",
        through=None,
        max_credits=100,
        creator_governance={
            "creatorId": f"model-{creator}",
            "creatorSlug": creator,
            "creatorLifecycleVersion": 3,
            "campaignId": f"campaign-{creator}",
            "campaignLifecycleVersion": 4,
            "identityProfileId": f"identity-{creator}",
            "identityProfileVersion": 2,
            "identityProfileFingerprint": "f" * 64,
            "providerIdentityId": provider_identity_id,
            "authorizationEventIds": ["authorization-event-1"],
            "governanceFingerprint": "g" * 64,
        },
        prompt_pack=_prompt_pack() if prompts else None,
        quote_provider=_quote,
    )


@pytest.mark.parametrize("creator", ["stacey", "larissa", "lola"])
def test_calm_uses_openai_kling_turbo_prompt(
    monkeypatch: pytest.MonkeyPatch, creator: str
) -> None:
    plan = _plan(monkeypatch, creator=creator)
    request = plan["videoPlan"]["request"]

    assert plan["selectedMode"] == "calm"
    assert plan["videoPlan"]["model"] == "kling3_0_turbo"
    assert request["prompt"] == _prompt_pack()["klingPrompt"]
    assert request["resolution"] == "720p"
    assert "video_references" not in request
    assert "start_image" not in plan["videoPlan"]["quoteParameters"]
    assert plan["videoPlan"]["referenceEvidence"]["sentToProvider"] is False
    assert f"registry-soul-{creator}" not in str(plan)
    assert plan["creatorGovernance"]["identityProfileFingerprint"] == "f" * 64


def test_reel_motion_uses_prompt_only_seedance_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, motion=0.1)
    request = plan["videoPlan"]["request"]

    assert plan["selectedMode"] == "structural"
    assert plan["videoPlan"]["model"] == "seedance_2_0"
    assert request["prompt"] == _prompt_pack()["seedancePrompt"]
    assert request["resolution"] == "480p"
    assert request["mode"] == "fast"
    assert request["bitrate_mode"] == "high"
    assert request["generate_audio"] is False
    assert "video_references" not in request
    assert "start_image" not in plan["videoPlan"]["quoteParameters"]
    assert plan["videoPlan"]["referenceEvidence"]["sentToProvider"] is False


def test_talking_reel_requires_identity_motion_and_lipsync_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, intake=_intake(talking=True), motion=0.1)

    assert plan["selectedMode"] == "structural"
    assert plan["videoPlan"]["operatorReviewRequired"] == [
        "identity",
        "motion",
        "lip_sync",
    ]
    assert plan["audioDecision"]["selected"] == "creator_or_reference_audio_required"


def test_openai_anchor_prompt_is_the_soul_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, motion=0.1)

    assert (
        plan["anchorPlan"]["requests"][0]["request"]["prompt"]
        == _prompt_pack()["anchorPrompt"]
    )
    assert (
        plan["anchorPlan"]["requests"][0]["request"]["conditioning"]
        == "text_only_soul_identity"
    )
    assert "image_references" not in plan["anchorPlan"]["requests"][0]["request"]
    assert plan["anchorPlan"]["videoSubmissionBlockedUntilApproved"] is True


def test_missing_prompt_pack_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(monkeypatch, prompts=False)

    assert plan["productionReadiness"] == "BLOCKED_OPENAI_PROMPT_PACK_REQUIRED"
    assert plan["videoPlan"] is None
    assert plan["quote"]["providerGenerationCalls"] == 0


def test_plan_is_stable_and_never_generates_or_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _plan(monkeypatch, motion=0.1)
    second = _plan(monkeypatch, motion=0.1)

    assert first["runId"] == second["runId"]
    assert first["planFingerprint"] == second["planFingerprint"]
    assert first["quote"]["totalCredits"] == pytest.approx(10.62)
    assert first["paidCalls"] == 0
    assert first["generationIds"] == []
    assert first["publishingAllowed"] is False


def test_secondary_person_warning_keeps_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        monkeypatch,
        intake=_intake(
            classification="walking",
            warnings=["secondary_person_interaction"],
        ),
        motion=0.1,
    )

    assert plan["selectedMode"] == "structural"
    assert plan["productionReadiness"] == "MANUAL_REVIEW_REQUIRED"


def test_recreation_requires_matching_registry_governance_before_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = 0

    def quote(_model: str, _params: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called += 1
        return {}

    with pytest.raises(PermissionError, match="recreation_creator_governance_mismatch"):
        recreation_modes.plan_recreation(
            creator="stacey",
            source_video=Path("/private/reference.mp4"),
            intake=_intake(),
            requested_mode="auto",
            audio_policy="auto",
            through=None,
            max_credits=100,
            creator_governance={
                "creatorSlug": "larissa",
                "identityProfileFingerprint": "f" * 64,
                "governanceFingerprint": "g" * 64,
            },
            prompt_pack=_prompt_pack(),
            quote_provider=quote,
        )
    assert called == 0
