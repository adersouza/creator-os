"""Operator-approved deterministic prompts for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from creator_os_core.fileops import sha256_file as _sha256_file
from creator_os_core.runtime_paths import resolve_runtime_paths

from pipeline_contracts import validate_operator_preference_profile

from .prompt_registry import bind_campaign_prompt

PROMPT_CARD_SCHEMA: Final = "campaign_factory.creative_direction_prompt_card.v1"
COMPILED_PROMPT_SCHEMA: Final = "campaign_factory.compiled_passive_prompt.v1"
REEL_CREATIVE_CONTEXT_SCHEMA: Final = "campaign_factory.reel_creative_context.v1"
UNKNOWN: Final = "unknown"

LOW_EFFORT_REEL_VISUAL_DIRECTION: Final = (
    "Favor a deliberately casual, believable handheld selfie aesthetic for Reel "
    "stills: close arm-length framing or a mirror self-portrait in an ordinary "
    "bedroom, bathroom, car seat, couch, living room, or simple outdoor setting. "
    "Use cute fitted everyday clothing, playful, coy, pouty, warm, or teasing "
    "expressions, attractive flirtatious posing within the approved wardrobe and "
    "exposure policy, natural household lighting, slight off-center composition, "
    "and ordinary lived-in background detail. Selected static mirror compositions "
    "may hold the camera in front of part of the face while preserving enough "
    "visible identity evidence. Use casual amateur realism and reserve polished "
    "editorial lighting or cinematic staging for an explicit request."
)

MODE_PURPOSES: Final[dict[str, str]] = {
    "static_reel": (
        "Turn one exact approved creator still into a locked low-effort-looking "
        "Reel without changing the visual identity or composition."
    ),
    "calm_animation": (
        "Add restrained, believable motion to one exact approved creator still "
        "while preserving identity, clothing, setting, and casual selfie energy."
    ),
    "recreate_reel": (
        "Recreate one authorized reference Reel's broad action, timing, framing, "
        "camera behavior, and performance energy with the approved creator identity."
    ),
}

INTENT_PROMPTS: Final[dict[str, str]] = {
    "passive_selfie": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld social camera behavior. The performance stays silent, restrained, "
        "and identity-stable."
    ),
    "flirty_portrait": (
        "A warm restrained gaze shift, a small confident head turn, one gentle hair "
        "adjustment, subtle breathing, and a natural handheld creator camera. The "
        "performance stays silent, restrained, and identity-stable."
    ),
    "outfit": (
        "A small posture shift to present the outfit, natural eye movement, one "
        "purposeful clothing adjustment, restrained fabric movement, and subtle "
        "handheld camera behavior. The performance stays silent and restrained."
    ),
    "lifestyle": (
        "Natural eye movement and a subtle head turn, one purposeful interaction "
        "with clothing or hair, restrained body movement, and casual handheld "
        "creator camera behavior. The performance stays silent and identity-stable."
    ),
    "animate_existing": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld camera behavior. The performance stays silent, restrained, and "
        "identity-stable."
    ),
    "recreate_reel": (
        "Recreate the supplied reference Reel's broad structure, performance, "
        "camera progression, pacing, framing, and social energy with the approved "
        "creator reference. Preserve identity and natural anatomy. Use original "
        "visual wording while provider audio remains disabled."
    ),
}

CREATOR_SOUL_IDS: Final = MappingProxyType(
    {
        creator: value
        for creator, variable in {
            "stacey": "CREATOR_OS_SOUL_ID_STACEY",
            "stacey1": "CREATOR_OS_SOUL_ID_STACEY1",
            "larissa": "CREATOR_OS_SOUL_ID_LARISSA",
            "lola": "CREATOR_OS_SOUL_ID_LOLA",
        }.items()
        if (value := str(os.environ.get(variable) or "").strip())
    }
)


def require_creator_soul_id(creator: str) -> tuple[str, str]:
    creator_slug = creator.strip().lower().replace(" ", "_")
    try:
        return creator_slug, CREATOR_SOUL_IDS[creator_slug]
    except KeyError as exc:
        raise ValueError(
            f"no pinned authenticated Higgsfield Soul identity for creator {creator}"
        ) from exc


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


MODE_PREFERENCE_KINDS: Final[dict[str, tuple[str, ...]]] = {
    # recreate_reel rebuilds an authorized Reel, so Reel structure references lead.
    "recreate_reel": ("reel", "profile"),
    # The selfie modes are driven by pose/framing references, not Reel edits.
    "static_reel": ("selfie", "profile"),
    "calm_animation": ("selfie", "profile"),
}
SELECTABLE_MIN_SCORE: Final = 4
AVOID_MAX_SCORE: Final = 2
_MAX_AVOID_EXAMPLES: Final = 4


def _outcome_adjusted_score(item: dict[str, Any], outcomes: dict[str, float]) -> float:
    """Blend the operator's initial score with measured Reel outcomes.

    The operator score is the prior and always dominates ordering; published
    outcomes only reorder items the operator already rated selectable. This is
    the "outcomes refine, never erase" rule from the operator's direction.
    """

    return float(item["score"]) + max(-0.9, min(0.9, outcomes.get(item["itemId"], 0.0)))


def select_preference_reference(
    profile: dict[str, Any],
    *,
    mode: str,
    intent: str,
    creator: str = "",
    outcomes: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Choose ONE operator-rated reference to drive this creation.

    The operator's direction is explicit that all 62 rated references must never
    be merged into a single prompt. Exactly one item is selected per creation so
    the authored prompt inherits that item's pose, framing, clothing, expression,
    and — most importantly — the operator's own reason for liking it.
    """

    weights = outcomes or {}
    kinds = MODE_PREFERENCE_KINDS.get(mode, ("reel", "selfie", "profile"))
    candidates = [
        item
        for item in profile["items"]
        if item["kind"] in kinds and int(item["score"]) >= SELECTABLE_MIN_SCORE
    ]
    if not candidates:
        return None
    # Deterministic per (collection, mode, intent, creator) so the same creation
    # request is reproducible, while different intents AND different creators
    # genuinely draw different references instead of reusing one master.
    rotation = int(
        hashlib.sha256(
            f"{profile['sourceFingerprint']}:{mode}:{intent}:{creator}".encode()
        ).hexdigest(),
        16,
    )
    ordered = sorted(
        candidates,
        key=lambda item: (
            -_outcome_adjusted_score(item, weights),
            # kind priority follows the mode's leading reference kind
            kinds.index(item["kind"]),
            item["itemId"],
        ),
    )
    # Rotate only within the top tier so a master is always chosen, but the same
    # master is not reused for every intent.
    top_score = _outcome_adjusted_score(ordered[0], weights)
    top_tier = [
        item for item in ordered if _outcome_adjusted_score(item, weights) >= top_score
    ]
    return top_tier[rotation % len(top_tier)]


def _preference_collection_root() -> Path | None:
    """Directory of the operator collection whose manifest owns the rated media."""

    configured = str(os.environ.get("CREATOR_OS_OPERATOR_PREFERENCE_COLLECTION") or "")
    if configured:
        root = Path(configured).expanduser()
        return root if root.is_dir() else None
    base = resolve_runtime_paths().reference_data_root / "operator_collections"
    if not base.is_dir():
        return None
    manifests = sorted(
        candidate
        for candidate in base.iterdir()
        if (candidate / "manifest.json").is_file()
    )
    return manifests[-1] if manifests else None


def _selected_reference_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Emit one selected reference under the operator's stated authority order.

    Authority order: the operator's raw written note outranks the score, which
    outranks the derived recommendation. The derived text is therefore labelled
    subordinate so prompt authoring cannot silently prefer it.
    """

    payload: dict[str, Any] = {
        "itemId": item["itemId"],
        "kind": item["kind"],
        "title": item["title"],
        "score": item["score"],
        "operatorNote": item["operatorNotes"],
        "authority": (
            "operatorNote is authoritative; derivedRecommendation is a "
            "subordinate synthesis and must not contradict it"
        ),
        "derivedRecommendation": item["recommendation"],
        "useAs": (
            "Reproduce this reference's pose, framing, clothing, expression, "
            "lighting, and setting. Identity comes only from the approved Soul "
            "binding, never from the reference."
        ),
    }
    media = _selected_reference_media(item)
    if media is not None:
        payload["media"] = media
    return payload


def _selected_reference_media(item: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve one rated item to its authorized collection media, if deterministic.

    Only ``selfie`` items resolve: their itemId is the file stem inside the
    collection's ``selfies`` directory. ``profile`` items are keyed by an opaque
    hash with no recoverable mapping, and ``reel`` items are never attached —
    a recreate job's own Reel stays the sole structural media reference.

    The media is structural input for prompt authoring only. It is never sent to
    Soul or any generation provider; only the authored text prompt is.
    """

    kind = str(item.get("kind") or "")
    if kind != "selfie":
        return None
    stem = str(item.get("itemId") or "").partition(":")[2]
    if not stem or "/" in stem or stem.startswith("."):
        return None
    root = _preference_collection_root()
    if root is None:
        return None
    path = (root / "selfies" / f"{stem}.png").resolve()
    if not path.is_file() or path.is_symlink():
        return None
    if root.resolve() not in path.parents:
        return None
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "role": "structural_style_reference",
        "authority": (
            "subordinate to the job's own authorized reference and to the "
            "verified Soul identity binding"
        ),
    }


def _operator_preference_context(
    mode: str,
    *,
    intent: str = "",
    creator: str = "",
    outcomes: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    configured = str(os.environ.get("CREATOR_OS_OPERATOR_PREFERENCE_PROFILE") or "")
    path = (
        Path(configured).expanduser()
        if configured
        else resolve_runtime_paths().reference_data_root
        / "learning"
        / "operator_preference_profile.json"
    )
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("operator preference profile path is not a trusted file")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("operator preference profile is not valid JSON") from exc
    validate_operator_preference_profile(profile)
    if profile["status"] != "active":
        return None
    # Measured outcomes reach selection through the profile artifact, because
    # Reference Factory owns published post outcomes and Campaign Factory is
    # forbidden from importing it.
    resolved_outcomes: dict[str, float] = {
        str(key): float(value)
        for key, value in (profile.get("outcomeWeights") or {}).items()
    }
    resolved_outcomes.update(outcomes or {})
    selected = select_preference_reference(
        profile,
        mode=mode,
        intent=intent,
        creator=creator,
        outcomes=resolved_outcomes,
    )
    if selected is None:
        return None
    avoid = [
        {
            "itemId": item["itemId"],
            "kind": item["kind"],
            "score": item["score"],
            "operatorNote": item["operatorNotes"],
        }
        for item in sorted(profile["items"], key=lambda i: (i["score"], i["itemId"]))
        if int(item["score"]) <= AVOID_MAX_SCORE and item["operatorNotes"]
    ][:_MAX_AVOID_EXAMPLES]
    return {
        "schema": profile["schema"],
        "collectionId": profile["collectionId"],
        "sourceFingerprint": profile["sourceFingerprint"],
        "evidenceStatus": "operator_initial_preference_prior_not_performance_proof",
        "selectionPolicy": (
            "Exactly one rated reference drives this creation. Never merge the "
            "full rated collection into one prompt."
        ),
        "selectedReference": _selected_reference_payload(selected),
        "avoid": avoid,
        "houseDirection": profile["houseDirection"],
        "principles": profile["brief"]["principles"],
    }


def build_reel_creative_context(
    *,
    mode: str,
    intent: str,
    creator: str = "",
    preference_outcomes: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return the operator-owned creative purpose carried by every Reel mode."""

    if mode not in MODE_PURPOSES:
        raise ValueError(f"unsupported Creator OS mode: {mode}")
    reference_driven = mode == "recreate_reel"
    operator_preferences = _operator_preference_context(
        mode, intent=intent, creator=creator, outcomes=preference_outcomes
    )
    core: dict[str, Any] = {
        "schema": REEL_CREATIVE_CONTEXT_SCHEMA,
        "mode": mode,
        "intent": intent,
        "purpose": MODE_PURPOSES[mode],
        "stylePolicy": (
            "authorized_reference_is_style_authority"
            if reference_driven
            else "operator_low_effort_selfie_default"
        ),
        "visualStyleId": (
            "authorized_reference_recreation.v1"
            if reference_driven
            else "low_effort_selfie_reels.v1"
        ),
        "visualDirection": (
            "Follow the authorized reference Reel's visible style and structure."
            if reference_driven
            else LOW_EFFORT_REEL_VISUAL_DIRECTION
        ),
        "identityPolicy": (
            "The verified selected Higgsfield Soul binding is the sole identity "
            "source; reference Reel frames supply structure only."
            if reference_driven
            else "Soul ID and the exact approved creator image supply identity."
        ),
        "overlayPolicy": "Burned overlay copy is added later by Reel Factory.",
        "learningPolicy": (
            "Approved learning may refine selection but cannot replace mode purpose "
            "or operator creative direction."
        ),
    }
    if operator_preferences is not None:
        core["operatorPreferenceProfile"] = operator_preferences
        # Creation lineage: which rated reference influenced this creation, and
        # which rating snapshot it came from. Published outcomes are joined back
        # on these two fields to refine later selection.
        core["preferenceLineage"] = {
            "itemId": operator_preferences["selectedReference"]["itemId"],
            "sourceFingerprint": operator_preferences["sourceFingerprint"],
            "collectionId": operator_preferences["collectionId"],
        }
    return {**core, "contextFingerprint": _fingerprint(core)}


def _fact(facts: dict[str, Any], key: str) -> Any:
    value = facts.get(key)
    return value if value not in (None, "", [], {}) else UNKNOWN


def build_creative_direction_prompt_card(
    *,
    creator: str,
    intent: str,
    source: dict[str, Any],
    observed_facts: dict[str, Any],
    reference_pattern_id: str | None = None,
) -> dict[str, Any]:
    """Build one evidence-bound card without inferring unobserved visual facts."""

    metadata = source.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    pattern = (
        reference_pattern_id
        or metadata.get("approvedReferencePatternId")
        or metadata.get("referencePatternId")
        or UNKNOWN
    )
    core: dict[str, Any] = {
        "schema": PROMPT_CARD_SCHEMA,
        "creator": creator,
        "contentIntent": intent,
        "source": {
            "id": str(source["id"]),
            "sha256": str(source["content_hash"]),
        },
        "sceneType": _fact(observed_facts, "sceneType"),
        "approvedReferencePatternId": pattern,
        "emotionalBeat": metadata.get("emotionalBeat") or UNKNOWN,
        "performanceHook": metadata.get("performanceHook") or UNKNOWN,
        "blocking": {
            "foreground": _fact(observed_facts, "foreground"),
            "midground": _fact(observed_facts, "midground"),
            "background": _fact(observed_facts, "background"),
            "screenPosition": _fact(observed_facts, "screenPosition"),
            "bodyDirection": _fact(observed_facts, "bodyDirection"),
            "gazeDirection": _fact(observed_facts, "gazeDirection"),
        },
        "cameraGrammar": {
            "approximateDiagonalFieldOfView": _fact(
                observed_facts, "approximateDiagonalFieldOfView"
            ),
            "cameraHeight": _fact(observed_facts, "cameraHeight"),
            "cameraDistance": _fact(observed_facts, "cameraDistance"),
            "movementProfile": "restrained casual handheld movement",
        },
        "lightingMotivation": {
            "primarySource": _fact(observed_facts, "lightingPrimarySource"),
            "direction": _fact(observed_facts, "lightingDirection"),
            "exposurePriority": _fact(observed_facts, "exposurePriority"),
        },
        "motionArc": {
            "startingPose": _fact(observed_facts, "poseClass"),
            "movementDuringClip": INTENT_PROMPTS[intent],
            "endingPose": "same pose family",
        },
        "invariants": {
            "identity": "same creator identity",
            "outfit": "same outfit",
            "setting": "same setting",
            "composition": "same portrait composition and pose family",
        },
        "audioRhythmIntent": "silent provider output; Audio Radar handoff follows",
        "whyConceptShouldWork": (
            "operator-approved passive intent applied to an approved exact source"
        ),
        "continuityRequirements": [
            "same creator identity",
            "same outfit",
            "same setting",
            "same pose family",
            "restrained casual movement",
            "full face and head visibility",
            "clean one-person frame",
            "continuous shot",
            "silent provider output",
        ],
        "evidenceProvenance": {
            "sourceMetadata": metadata.get("analysisReceiptId") or UNKNOWN,
            "referencePattern": pattern,
            "compatibilitySchema": observed_facts.get("schema") or UNKNOWN,
        },
    }
    core["promptGovernance"] = bind_campaign_prompt(
        prompt_id="campaign.creative_direction",
        version="1",
        provider="any",
        model="local_deterministic",
        compiled_prompt={"intentPrompt": INTENT_PROMPTS[intent]},
        inputs={
            "creator": creator,
            "intent": intent,
            "sourceSha256": source["content_hash"],
            "observedFacts": observed_facts,
            "referencePatternId": pattern,
        },
    )
    return {**core, "promptCardFingerprint": _fingerprint(core)}


def validate_prompt_card(card: dict[str, Any]) -> dict[str, Any]:
    core = {key: value for key, value in card.items() if key != "promptCardFingerprint"}
    if core.get("schema") != PROMPT_CARD_SCHEMA or card.get(
        "promptCardFingerprint"
    ) != _fingerprint(core):
        raise ValueError("creative_direction_prompt_card_invalid")
    return card


def compile_passive_prompt_card(
    card: dict[str, Any], *, base_prompt: str
) -> dict[str, Any]:
    validate_prompt_card(card)
    intent = str(card.get("contentIntent") or "")
    if intent not in {
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    }:
        raise ValueError("prompt card compilation supports passive intents only")
    text = " ".join(
        (
            base_prompt.strip(),
            "Preserve the same person, outfit, setting, pose family, camera angle, "
            "and lighting. Keep the full head and face visible in a clean one-person "
            "continuous shot with restrained movement.",
            "Provider output stays silent for downstream Audio Radar finishing.",
        )
    )
    governance = bind_campaign_prompt(
        prompt_id="campaign.passive_provider_compile",
        version="1",
        provider="any",
        model="local_deterministic",
        compiled_prompt=text,
        inputs={
            "promptCardFingerprint": card["promptCardFingerprint"],
            "basePrompt": base_prompt,
        },
    )
    core = {
        "schema": COMPILED_PROMPT_SCHEMA,
        "promptCardFingerprint": card["promptCardFingerprint"],
        "text": " ".join(text.split()),
        "promptGovernance": governance,
    }
    return {**core, "compiledPromptFingerprint": _fingerprint(core)}
