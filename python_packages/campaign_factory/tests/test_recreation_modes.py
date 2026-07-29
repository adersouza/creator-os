from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from campaign_factory import recreation_modes
from campaign_factory.production_prompts import CREATOR_SOUL_IDS


def _intake(
    *,
    cuts: list[float] | None = None,
    talking: bool = False,
    persons: int | None = 1,
    classification: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    measurements = {
        "faceVisibility": 0.8,
        "bodyExtent": 0.75,
        "sharpness": 0.9,
        "principalPersonCount": persons,
        "framingCompatibility": "compatible",
    }
    return {
        "reference": {
            "referenceId": "ref_url_example",
            "source": {"sha256": "a" * 64},
            "media": {
                "durationSeconds": 12.0,
                "width": 1080,
                "height": 1920,
                "hasAudio": True,
            },
            "sourceSpeakingClassification": (
                "DECLARED_TALKING" if talking else "UNKNOWN"
            ),
            "operatorClassification": classification,
            "operatorWarnings": warnings or [],
            "sceneCutsSeconds": cuts or [0.0],
            "selectedAnchor": {"timeSec": 6.0, "sha256": "b" * 64},
            "frameDerivatives": {
                role: {"timeSec": index, "sha256": f"{index + 1:064x}"}
                for index, role in enumerate(
                    ("first_clean", "last_clean", "best_anchor")
                )
            },
            "anchorCandidates": [
                {
                    "excluded": False,
                    "exclusions": [],
                    "measurements": measurements,
                }
            ],
            "contactSheet": {"sha256": "c" * 64},
        },
        "audio": {
            "classification": "REFERENCE_AUDIO_ELIGIBLE",
            "canonicalAudioId": "audio_ref_example",
            "occurrenceId": "audio_occ_example",
        },
    }


def _quote(model: str, _params: dict[str, Any]) -> dict[str, Any]:
    credits = {
        "text2image_soul_v2": 0.12,
        "kling3_0": 8.75,
        "kling3_0_motion_control": 32.0,
        "seedance_2_0_mini": 7.0,
        "seedance_2_0": 10.5,
    }[model]
    return {
        "model": model,
        "credits": credits,
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
    audio: str = "auto",
) -> dict[str, Any]:
    monkeypatch.setattr(recreation_modes, "_coarse_motion_energy", lambda _: motion)
    return recreation_modes.plan_recreation(
        creator=creator,
        source_video=Path("/private/reference.mp4"),
        intake=intake or _intake(),
        requested_mode=mode,
        audio_policy=audio,
        through=None,
        max_credits=100,
        quote_provider=_quote,
    )


@pytest.mark.parametrize("creator", ["stacey", "larissa", "lola"])
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("auto", "motion"),
        ("passive", "passive"),
        ("motion", "motion"),
        ("structural", "structural"),
        ("first_last", "first_last"),
        ("talking", "talking"),
    ],
)
def test_every_recreation_mode_preserves_creator_scope(
    monkeypatch: pytest.MonkeyPatch,
    creator: str,
    mode: str,
    expected: str,
) -> None:
    plan = _plan(monkeypatch, creator=creator, mode=mode, motion=0.05)

    assert plan["creator"] == creator
    assert plan["selectedMode"] == expected
    assert CREATOR_SOUL_IDS[creator] not in str(plan)
    if mode == "talking":
        assert plan["productionReadiness"] == "BLOCKED_TALKING_ROUTE_NOT_ENTITLED"


def test_auto_passive_plan_hides_soul_and_disables_provider_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch)
    assert plan["classification"]["label"] == "passive_single_shot"
    assert plan["selectedMode"] == "passive"
    assert plan["videoPlan"]["request"]["sound"] == "off"
    assert plan["audioDecision"]["selected"] == "embedded_trending_required"
    rendered = str(plan)
    assert CREATOR_SOUL_IDS["stacey"] not in rendered
    assert plan["anchorPlan"]["requests"][0]["soulIdExposed"] is False
    assert plan["quote"]["paidCalls"] == 0


def test_motion_request_uses_only_observed_contract_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, mode="motion", motion=0.05)
    request = plan["videoPlan"]["request"]
    assert request == {
        "image_references": ["<approved_soul_anchor>"],
        "video_references": [
            {
                "referenceId": "ref_url_example",
                "sha256": "a" * 64,
                "excerpt": plan["excerpt"],
            }
        ],
        "background_source": "input_image",
        "mode": "pro",
    }
    assert plan["productionReadiness"] == "EXPERIMENTAL_AUTHORIZATION_REQUIRED"
    assert plan["videoPlan"]["unsupportedFieldsAdded"] == []


def test_structural_request_is_not_called_identity_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, mode="structural", motion=0.1)
    assert plan["videoPlan"]["model"] == "seedance_2_0"
    assert plan["videoPlan"]["identityReplacementClaimed"] is False
    request = plan["videoPlan"]["request"]
    assert request["prompt"] == (
        "<<<approved_creator_reference_element>>> place her in this video. "
        "same motion but my model instead"
    )
    assert request["image_references"] == ["<approved_soul_anchor>"]
    assert request["reference_elements"] == ["<approved_creator_reference_element>"]
    assert request["video_references"][0]["sha256"] == "a" * 64
    assert request["generate_audio"] is False
    assert request["resolution"] == "480p"
    assert request["mode"] == "fast"
    assert request["bitrate_mode"] == "high"
    assert request["multi_shot_mode"] == "custom"
    assert plan["anchorPlan"]["requests"][0]["role"] == "opening"
    assert plan["anchorPlan"]["requests"][0]["referenceFrame"]["role"] == "first_clean"
    assert plan["reviewPackage"]["selectedSourceFrame"]["role"] == "first_clean"


def test_structural_request_uses_timeline_but_excludes_source_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _intake()
    reference = intake["reference"]
    reference["overlayTextInventory"] = {
        "status": "observed",
        "observations": [{"timeSec": 0.0, "text": "ORIGINAL DATING HOOK"}],
    }
    reference["structuralMotionAnalysis"] = {
        "status": "ready",
        "analysis": {
            "motionPrompt": (
                "Recreate the shoulder turn from ORIGINAL DATING HOOK with a "
                "stable ending pose."
            ),
            "structure": {
                "timeline": [
                    {
                        "startSeconds": 0.0,
                        "endSeconds": 2.5,
                        "action": "Hold eye contact and begin a shoulder turn.",
                        "camera": "Keep the vertical framing fixed.",
                    },
                    {
                        "startSeconds": 2.5,
                        "endSeconds": 7.0,
                        "action": "Finish the turn and settle.",
                        "camera": "Use only slight handheld drift.",
                    },
                ]
            },
        },
    }
    prompt = _plan(monkeypatch, mode="structural", intake=intake, motion=0.1)[
        "videoPlan"
    ]["request"]["prompt"]
    assert prompt.startswith(
        "<<<approved_creator_reference_element>>> place her in this video. "
        "same motion but my model instead"
    )
    assert "[0-2.5s]" in prompt
    assert "[2.5-7s]" in prompt
    assert "ORIGINAL DATING HOOK" not in prompt
    assert "motion, timing, framing, and camera movement only" in prompt
    assert "no writing or graphic borders" in prompt


def test_first_last_uses_two_review_gated_soul_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, mode="first_last")
    assert plan["anchorPlan"]["count"] == 2
    assert [row["role"] for row in plan["anchorPlan"]["requests"]] == [
        "opening",
        "ending",
    ]
    assert plan["videoPlan"]["request"]["sound"] == "off"
    assert plan["quote"]["totalCredits"] == pytest.approx(8.99)


def test_talking_is_precisely_blocked_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, intake=_intake(talking=True))
    assert plan["selectedMode"] == "talking"
    assert plan["productionReadiness"] == "BLOCKED_TALKING_ROUTE_NOT_ENTITLED"
    assert plan["videoPlan"]["status"] == "talking_route_not_entitled"
    assert plan["videoPlan"]["silentFallbackAllowed"] is False


def test_auto_multishot_requires_manual_review_and_never_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, intake=_intake(cuts=[0.0, 2.0, 5.0]))
    assert plan["classification"]["label"] == "multi_shot"
    assert plan["selectedMode"] == "structural"
    assert plan["productionReadiness"] == "MANUAL_REVIEW_REQUIRED"
    assert plan["paidCalls"] == 0
    assert plan["generationIds"] == []


def test_explicit_motion_multishot_blocks_before_video_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        monkeypatch,
        mode="motion",
        intake=_intake(cuts=[0.0, 2.0, 5.0]),
        motion=0.08,
    )
    assert plan["productionReadiness"] == "BLOCKED_INCOMPATIBLE_MOTION_SOURCE"
    assert plan["videoPlan"]["compatibility"]["classification"] == "UNSUPPORTED"
    assert [row["model"] for row in plan["quote"]["items"]] == ["text2image_soul_v2"]
    assert plan["quote"]["skipped"] == [
        {
            "model": "kling3_0_motion_control",
            "reason": "motion_source_unsupported_before_quote",
        }
    ]
    assert plan["quote"]["totalCredits"] is None


def test_explicit_audio_choice_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(monkeypatch, audio="original_embedded")
    assert plan["audioDecision"] == {
        "requested": "original_embedded",
        "selected": "original_embedded",
        "reason": "explicit",
    }


def test_quote_cap_and_stable_run_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _plan(monkeypatch, mode="structural")
    second = _plan(monkeypatch, mode="structural")
    assert first["runId"] == second["runId"]
    assert first["planFingerprint"] == second["planFingerprint"]
    assert first["quote"]["withinAuthorizedCap"] is True
    assert first["quote"]["totalCredits"] == pytest.approx(10.62)


@pytest.mark.parametrize(
    ("classification_input", "expected"),
    [
        (_intake(talking=True), "talking"),
        (_intake(persons=2), "multi_person"),
        (_intake(cuts=[0.0, 4.0]), "multi_shot"),
    ],
)
def test_auto_route_classifications(
    monkeypatch: pytest.MonkeyPatch,
    classification_input: dict[str, Any],
    expected: str,
) -> None:
    plan = _plan(monkeypatch, intake=classification_input)
    assert plan["classification"]["label"] == expected


def test_operator_transition_classification_routes_auto_to_first_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        monkeypatch,
        intake=_intake(classification="first_last_transition"),
        motion=0.12,
    )
    assert plan["classification"]["operatorConfirmed"] is True
    assert plan["selectedMode"] == "first_last"
    assert plan["videoPlan"]["model"] == "kling3_0"


def test_secondary_person_interaction_keeps_motion_possible_but_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        monkeypatch,
        intake=_intake(
            classification="walking",
            warnings=["secondary_person_interaction"],
        ),
        motion=0.08,
    )
    assert plan["selectedMode"] == "motion"
    assert plan["productionReadiness"] == "MANUAL_REVIEW_REQUIRED"
    assert plan["videoPlan"]["compatibility"]["classification"] == "POSSIBLE_FIT"
    assert (
        "secondary_person_interaction_requires_manual_approval"
        in plan["videoPlan"]["compatibility"]["warnings"]
    )


def test_operator_heavy_occlusion_routes_to_manual_structural_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        monkeypatch,
        intake=_intake(
            classification="heavy_occlusion",
            warnings=["identity_reset_required"],
        ),
    )
    assert plan["selectedMode"] == "structural"
    assert plan["productionReadiness"] == "MANUAL_REVIEW_REQUIRED"
    assert "identity_reset_required" in plan["classification"]["warnings"]


def test_non_talking_evidence_removes_lipsync_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _intake(classification="simple_pose_motion")
    intake["reference"]["sourceSpeakingClassification"] = "DECLARED_NON_TALKING"
    intake["reference"]["media"]["durationSeconds"] = 7.0
    plan = _plan(monkeypatch, intake=intake, motion=0.04)
    compatibility = plan["videoPlan"]["compatibility"]
    assert compatibility["classification"] == "STRONG_FIT"
    assert "talking_or_lipsync_requirement_unresolved" not in compatibility["warnings"]
