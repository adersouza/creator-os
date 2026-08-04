"""Prove the operator preference path CHANGES creation, not just records it.

These tests fail if reference selection becomes inert - i.e. if the profile is
merely attached to the context without picking a reference, if the operator's
raw note stops reaching prompt authoring, if rejected references can be
selected, or if measured outcomes stop reordering selection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_factory.production_prompts import (
    build_reel_creative_context,
    select_preference_reference,
)

from pipeline_contracts import operator_preference_profile_fingerprint


def _profile(**overrides):
    profile = {
        "schema": "reference_factory.operator_preference_profile.v1",
        "collectionId": "2026-08-03-style-direction",
        "status": "active",
        "generatedAt": "2026-08-04T00:00:00+00:00",
        "sourceFingerprint": "f" * 64,
        "summary": {
            "average": 4.0,
            "byKind": {"profile": 1, "reel": 1, "selfie": 2},
            "byScore": {"1": 1, "2": 0, "3": 0, "4": 0, "5": 3},
            "rated": 4,
            "remaining": 0,
            "total": 4,
        },
        "houseDirection": {
            "audienceGoal": "hook and retain",
            "visualPriorities": ["amateur realism"],
            "editingPriorities": ["fast hook"],
            "identityDirection": "approved Soul only",
        },
        "brief": {
            "principles": ["one reference per creation"],
            "masterItemIds": [
                "selfie:selfie_reference_20",
                "selfie:selfie_reference_31",
                "reel:Dbjps06N5c2",
            ],
            "strongItemIds": [],
            "usefulItemIds": [],
            "avoidItemIds": ["profile:badexample"],
        },
        "items": [
            {
                "itemId": "selfie:selfie_reference_20",
                "kind": "selfie",
                "title": "mirror selfie",
                "score": 5,
                "operatorNotes": "perfect cleavage and tight shirt hook",
                "recommendation": "derived synthesis for selfie 20",
                "updatedAt": "2026-08-04T00:00:00+00:00",
            },
            {
                "itemId": "selfie:selfie_reference_31",
                "kind": "selfie",
                "title": "couch selfie",
                "score": 5,
                "operatorNotes": "great amateur lighting in an ordinary room",
                "recommendation": "derived synthesis for selfie 31",
                "updatedAt": "2026-08-04T00:00:00+00:00",
            },
            {
                "itemId": "reel:Dbjps06N5c2",
                "kind": "reel",
                "title": "Dbjps06N5c2",
                "score": 5,
                "operatorNotes": "very reusable, keeps viewers to the end",
                "recommendation": "derived synthesis for the reel",
                "updatedAt": "2026-08-04T00:00:00+00:00",
            },
            {
                "itemId": "profile:badexample",
                "kind": "profile",
                "title": "rejected profile",
                "score": 1,
                "operatorNotes": "over-edited studio look, do not copy",
                "recommendation": "avoid",
                "updatedAt": "2026-08-04T00:00:00+00:00",
            },
        ],
    }
    profile.update(overrides)
    # The contract binds sourceFingerprint to the operator's ratings payload.
    profile["sourceFingerprint"] = operator_preference_profile_fingerprint(profile)
    return profile


@pytest.fixture()
def profile_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "operator_preference_profile.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")
    monkeypatch.setenv("CREATOR_OS_OPERATOR_PREFERENCE_PROFILE", str(path))
    return path


def test_exactly_one_reference_is_selected_not_the_whole_collection(profile_path):
    context = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    preference = context["operatorPreferenceProfile"]
    assert "selectedReference" in preference
    # The operator's direction forbids merging all rated references into one prompt.
    assert "examples" not in preference
    assert isinstance(preference["selectedReference"], dict)


def test_selected_reference_carries_the_operator_raw_note_into_prompt_context(
    profile_path,
):
    context = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    selected = context["operatorPreferenceProfile"]["selectedReference"]
    assert selected["operatorNote"]
    # Authority order: the raw note must outrank the derived recommendation.
    assert "operatorNote is authoritative" in selected["authority"]
    source = _profile()
    expected = {item["itemId"]: item["operatorNotes"] for item in source["items"]}[
        selected["itemId"]
    ]
    assert selected["operatorNote"] == expected


def test_rejected_references_are_never_selected_but_are_shown_as_avoid(profile_path):
    context = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    preference = context["operatorPreferenceProfile"]
    assert preference["selectedReference"]["score"] >= 4
    avoid_ids = {entry["itemId"] for entry in preference["avoid"]}
    assert "profile:badexample" in avoid_ids
    assert preference["selectedReference"]["itemId"] not in avoid_ids


def test_mode_changes_which_reference_kind_is_selected(profile_path):
    static_context = build_reel_creative_context(
        mode="static_reel", intent="calm_selfie"
    )
    recreate_context = build_reel_creative_context(
        mode="recreate_reel", intent="recreate_reel"
    )

    static_selected = static_context["operatorPreferenceProfile"]["selectedReference"]
    recreate_selected = recreate_context["operatorPreferenceProfile"][
        "selectedReference"
    ]
    # recreate_reel must lead with Reel structure; the selfie modes must not.
    assert static_selected["kind"] == "selfie"
    assert recreate_selected["kind"] == "reel"
    assert static_selected["itemId"] != recreate_selected["itemId"]


def test_selection_materially_changes_the_authored_context_fingerprint(profile_path):
    """The whole point: a different selection must produce a different prompt."""

    baseline = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    # Measured outcomes demote the reference the prior would have chosen.
    chosen = baseline["operatorPreferenceProfile"]["selectedReference"]["itemId"]
    steered = build_reel_creative_context(
        mode="static_reel",
        intent="calm_selfie",
        preference_outcomes={chosen: -0.9},
    )

    steered_id = steered["operatorPreferenceProfile"]["selectedReference"]["itemId"]
    assert steered_id != chosen
    # The authored context - what OpenAI receives - genuinely differs.
    assert steered["contextFingerprint"] != baseline["contextFingerprint"]
    assert (
        steered["operatorPreferenceProfile"]["selectedReference"]["operatorNote"]
        != baseline["operatorPreferenceProfile"]["selectedReference"]["operatorNote"]
    )


def test_creation_lineage_records_the_influencing_item_and_fingerprint(profile_path):
    context = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    lineage = context["preferenceLineage"]
    assert (
        lineage["itemId"]
        == context["operatorPreferenceProfile"]["selectedReference"]["itemId"]
    )
    assert lineage["sourceFingerprint"] == _profile()["sourceFingerprint"]
    assert lineage["collectionId"] == "2026-08-03-style-direction"


def test_outcome_weights_travel_through_the_profile_artifact(tmp_path, monkeypatch):
    """Reference Factory writes weights into the artifact; selection honors them."""

    baseline_profile = _profile()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(baseline_profile), encoding="utf-8")
    monkeypatch.setenv("CREATOR_OS_OPERATOR_PREFERENCE_PROFILE", str(path))
    baseline = build_reel_creative_context(mode="static_reel", intent="calm_selfie")
    chosen = baseline["operatorPreferenceProfile"]["selectedReference"]["itemId"]

    weighted = _profile(outcomeWeights={chosen: -0.9})
    path.write_text(json.dumps(weighted), encoding="utf-8")
    after = build_reel_creative_context(mode="static_reel", intent="calm_selfie")

    assert after["operatorPreferenceProfile"]["selectedReference"]["itemId"] != chosen


def test_outcomes_cannot_promote_a_reference_the_operator_rejected():
    """Measured performance refines the operator's prior; it never overrides it."""

    profile = _profile()
    selected = select_preference_reference(
        profile,
        mode="static_reel",
        intent="calm_selfie",
        # An implausibly strong outcome signal on a rejected reference.
        outcomes={"profile:badexample": 1.0},
    )

    assert selected is not None
    assert selected["itemId"] != "profile:badexample"
    assert selected["score"] >= 4
