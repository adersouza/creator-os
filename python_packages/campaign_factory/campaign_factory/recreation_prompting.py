"""OpenAI-authored, evidence-bound prompts for Soul and short-form video."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_text
from creator_os_core.provider_spend import (
    build_paid_action_quote,
    build_paid_action_spend_scope,
    verify_authorization_v3,
)
from creator_os_core.runtime_paths import resolve_runtime_paths

from .all_provider_cost import (
    begin_paid_action_attempt,
    budget_limits_from_env,
    issue_paid_action_authorization,
    reconcile_paid_action_cost,
)
from .cli_support import _load_env_file
from .production_prompts import (
    LOW_EFFORT_REEL_VISUAL_DIRECTION,
    build_reel_creative_context,
)
from .production_source_selection import require_creation_enabled_creator
from .prompt_registry import PROMPT_REGISTRY, bind_campaign_prompt

SCHEMA: Final = "campaign_factory.recreation_prompt_pack.v1"
PROMPT_BUILDER_VERSION: Final = "creator_os_openai_prompt_builder.v5"
_API_URL: Final = "https://api.openai.com/v1/responses"
_ANCHOR_FORBIDDEN: Final = (
    "phone",
    "iphone",
    "smartphone",
    "story",
    "screenshot",
    "social media",
    "interface",
    "icon",
    "watermark",
    "caption",
    "overlay",
    "tattoo",
    "hair color",
    "blonde",
    "brunette",
)
_NEGATIVE_LANGUAGE = re.compile(
    r"\bnegative[_ -]?prompts?\b"
    r"|\b(?:no|not|avoid|without|never|exclude|prevent|prohibit)\b"
    r"|\bdo\s+not\b|\bdon['’]t\b|\bmustn['’]t\b|\bshouldn['’]t\b",
    flags=re.IGNORECASE,
)
_FORBIDDEN_GENERATED_LANGUAGE = re.compile(
    r"\b(?:tattoo|tattoos|young)\b", flags=re.IGNORECASE
)
_CREATOR_PRESENTATION_POLICY: Final = {
    "adultPresentation": "adult woman",
    "age": 19,
    "operatorDirectedHairColor": "dark hair",
    "explicitness": "non_explicit",
}
_FRAME_SAMPLING_POLICY: Final = {
    "schema": "campaign_factory.recreation_frame_sampling.v2",
    "strategy": "opening_burst_distributed_endpoint",
    "minimumSamples": 8,
    "firstFrameAnchorRequired": True,
}


def build_openai_prompt_pack(
    *,
    creator: str,
    creator_image: Path | None = None,
    intent: str,
    reference_video: Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    cache_root: Path | None = None,
    external_call_authorized: bool = False,
    cost_connection: sqlite3.Connection | None = None,
    campaign_id: str | None = None,
    run_id: str | None = None,
    governance_context: dict[str, Any] | None = None,
    soul_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask one vision model for a Soul anchor and exact provider prompts."""

    creator = require_creation_enabled_creator(creator)
    video = (
        _regular_file(reference_video, "reference video")
        if reference_video is not None
        else None
    )
    image = (
        None
        if video is not None
        else _regular_file(
            _required_path(creator_image, "creator image"), "creator image"
        )
    )
    selected_model = model or os.environ.get("CREATOR_OS_OPENAI_PROMPT_MODEL", "gpt-5")
    creative_context = build_reel_creative_context(
        mode="recreate_reel" if video else "calm_animation",
        intent=intent,
    )
    image_sha256 = _sha256(image) if image is not None else None
    video_sha256 = _sha256(video) if video else None
    selected_soul_identity = None
    if video is not None:
        selected_soul_identity = (
            _validate_soul_identity_binding(soul_identity, creator=creator)
            if soul_identity is not None
            else _verified_soul_identity_binding(
                creator=creator, governance_context=governance_context
            )
        )
    instruction = _directed_instruction(
        intent,
        bool(video),
        reference_video_sha256=video_sha256,
        creator=creator,
        soul_identity=selected_soul_identity,
    )
    prompt_inputs = {
        "creator": creator.strip().lower(),
        "intent": intent,
        "creatorImageSha256": image_sha256,
        "referenceVideoSha256": video_sha256,
        "creativeContextFingerprint": creative_context["contextFingerprint"],
        "frameSamplingPolicy": _FRAME_SAMPLING_POLICY,
        "soulIdentityBindingFingerprint": (
            selected_soul_identity["bindingFingerprint"]
            if selected_soul_identity
            else None
        ),
    }
    prompt_governance = bind_campaign_prompt(
        prompt_id="campaign.openai_recreation_pack",
        version="5",
        provider="openai",
        model=selected_model,
        compiled_prompt=instruction,
        inputs=prompt_inputs,
    )
    request_core = {
        "schema": "campaign_factory.openai_prompt_request.v1",
        "builderVersion": PROMPT_BUILDER_VERSION,
        "creator": creator.strip().lower(),
        "intent": intent,
        "model": selected_model,
        "creatorImageSha256": image_sha256,
        "referenceVideoSha256": video_sha256,
        "creativeContext": creative_context,
        "instruction": instruction,
        "promptInputs": prompt_inputs,
        "frameSamplingPolicy": _FRAME_SAMPLING_POLICY,
        "responseSchema": _response_schema(),
        "promptGovernance": prompt_governance,
    }
    request_fingerprint = _fingerprint(request_core)
    cache_path = _prompt_cache_path(request_fingerprint, cache_root=cache_root)
    cached = _load_cached_prompt_pack(cache_path, request_fingerprint)
    if cached is not None:
        return {
            **cached,
            "cache": {
                "status": "hit",
                "path": str(cache_path),
                "providerCallMade": False,
                "promptCallAuthorization": {
                    "authorized": bool(external_call_authorized),
                    "scope": "request_fingerprint",
                    "requestFingerprint": request_fingerprint,
                    "maximumCalls": 1,
                    "cacheCheckedFirst": True,
                    "currentRunCalls": 0,
                },
            },
        }

    if not external_call_authorized:
        raise PermissionError("openai_prompt_call_authorization_required")
    key = api_key or _openai_api_key()
    if not key:
        raise RuntimeError("openai_prompt_generation_key_missing")
    if cost_connection is None or not campaign_id or not run_id:
        raise PermissionError("openai_prompt_unified_cost_context_required")
    authorization = _authorize_openai_prompt_call(
        request_core,
        request_fingerprint=request_fingerprint,
        cache_path=cache_path,
        conn=cost_connection,
        creator_id=creator.strip().lower(),
        campaign_id=campaign_id,
        run_id=run_id,
        governance_context=governance_context,
    )
    attempt_id = str(authorization["attemptId"])
    event_id = begin_paid_action_attempt(
        cost_connection,
        authorization=authorization["payload"],
        secret=str(os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET") or ""),
        attempt_id=attempt_id,
        current_prompt_registry=PROMPT_REGISTRY,
        compiled_prompt=instruction,
        prompt_inputs=prompt_inputs,
    )

    provider_call_started = False
    try:
        with tempfile.TemporaryDirectory(prefix="creator-os-prompt-frames-") as raw_tmp:
            temp_root = Path(raw_tmp)
            exact_image_url = (
                _data_url_exact(image, str(image_sha256)) if image is not None else None
            )
            video_snapshot = (
                _snapshot_exact_file(
                    video,
                    expected_sha256=str(video_sha256),
                    destination=temp_root / f"reference-video{video.suffix}",
                )
                if video is not None
                else None
            )
            frames = (
                _sample_frames(video_snapshot, temp_root)
                if video_snapshot is not None
                else []
            )
            content: list[dict[str, Any]] = [
                {"type": "input_text", "text": instruction}
            ]
            if exact_image_url is not None:
                content.append(
                    {
                        "type": "input_image",
                        "detail": "high",
                        "image_url": exact_image_url,
                    }
                )
            for index, sample in enumerate(frames, start=1):
                frame = Path(str(sample["path"]))
                content.extend(
                    [
                        {
                            "type": "input_text",
                            "text": (
                                f"Exact reference SHA-256 {video_sha256}; "
                                f"chronological sample {index}/{len(frames)}; "
                                f"role={sample['role']}; "
                                f"timestamp={sample['timestampSeconds']:.3f}s."
                            ),
                        },
                        {
                            "type": "input_image",
                            "detail": "high",
                            "image_url": _data_url_exact(frame, _sha256(frame)),
                        },
                    ]
                )
            provider_call_started = True
            response = _post_responses(
                {
                    "model": selected_model,
                    "store": False,
                    "max_output_tokens": 4000,
                    "input": [{"role": "user", "content": content}],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "creator_os_prompt_pack",
                            "strict": True,
                            "schema": _response_schema(),
                        }
                    },
                },
                api_key=key,
            )
    except Exception:
        reconcile_paid_action_cost(
            cost_connection,
            event_id=event_id,
            actual_usd=None if provider_call_started else 0,
            unknown_reason=(
                "provider_outcome_ambiguous" if provider_call_started else None
            ),
        )
        raise
    response_cost = _response_cost(response)
    cost_ledger = reconcile_paid_action_cost(
        cost_connection,
        event_id=event_id,
        actual_usd=(
            float(response_cost["usd"])
            if response_cost.get("status") == "reported"
            else None
        ),
        provider_reference=str(response.get("id") or "") or None,
        unknown_reason=(
            "provider_cost_not_exposed"
            if response_cost.get("status") != "reported"
            else None
        ),
    )

    value = _response_json(response)
    anchor_prompt = _validated_creator_presentation(
        _validated_anchor_prompt(str(value["anchorPrompt"])), "anchor"
    )
    seedance_prompt = _validated_creator_presentation(
        _validated_positive_prompt(str(value["seedancePrompt"]), "seedance"),
        "seedance",
    )
    kling_prompt = _validated_creator_presentation(
        _validated_positive_prompt(str(value["klingPrompt"]), "kling"),
        "kling",
    )
    if not kling_prompt or len(kling_prompt) > 2500:
        raise ValueError("openai_kling_prompt_must_be_1_to_2500_characters")
    timeline = [
        {
            **item,
            "action": _validated_positive_prompt(
                str(item["action"]), f"timeline_action_{index}"
            ),
            "camera": _validated_positive_prompt(
                str(item["camera"]), f"timeline_camera_{index}"
            ),
        }
        for index, item in enumerate(value["timeline"])
    ]
    core = {
        "schema": SCHEMA,
        "creator": creator.strip().lower(),
        "intent": intent,
        "provider": "openai",
        "model": selected_model,
        "promptPlanning": {
            "builderVersion": PROMPT_BUILDER_VERSION,
            "requestFingerprint": request_fingerprint,
            "responseId": str(response.get("id") or "") or None,
            "usage": _json_record(response.get("usage")),
            "cost": response_cost,
            "costLedger": cost_ledger,
            "authorization": authorization,
            "promptGovernance": prompt_governance,
        },
        "creatorImage": (
            {"sha256": image_sha256, "path": str(image)} if image is not None else None
        ),
        "soulIdentity": selected_soul_identity,
        "referenceVideo": (
            {"sha256": video_sha256, "path": str(video)} if video else None
        ),
        "creativeContext": creative_context,
        "creatorPresentationPolicy": _CREATOR_PRESENTATION_POLICY,
        "anchorPrompt": anchor_prompt,
        "seedancePrompt": seedance_prompt,
        "klingPrompt": kling_prompt,
        "timeline": timeline,
        "identityPolicy": {
            "identitySource": (
                "verified_higgsfield_soul"
                if selected_soul_identity is not None
                else "approved_creator_image"
            ),
            "hairColorInvented": False,
            "tattoosInvented": False,
            "permanentFeaturesInvented": False,
        },
        "providerPlans": {
            "seedance": {
                "model": "seedance_2_0",
                "resolution": "480p",
                "mode": "fast",
                "bitrateMode": "high",
                "generateAudio": False,
                "conditioning": (
                    "approved_anchor_image_reference_plus_authorized_video_reference"
                    "_and_creator_element_prompt_token"
                    if video
                    else "approved_anchor_image_and_prompt"
                ),
            },
            "kling": {
                "model": "kling3_0_turbo",
                "resolution": "720p",
                "generateAudio": False,
                "conditioning": "approved_anchor_image_and_prompt",
                "promptCharacterLimit": 2500,
                "executionStatus": "planning_only_not_connected_for_recreation",
            },
        },
    }
    pack = {**core, "promptPackFingerprint": _fingerprint(core)}
    _write_prompt_cache(cache_path, pack)
    return {
        **pack,
        "cache": {
            "status": "miss",
            "path": str(cache_path),
            "providerCallMade": True,
            "promptCallAuthorization": {
                "authorized": True,
                "scope": "request_fingerprint",
                "requestFingerprint": request_fingerprint,
                "maximumCalls": 1,
                "cacheCheckedFirst": True,
                "currentRunCalls": 1,
            },
        },
    }


def validate_prompt_pack(value: dict[str, Any]) -> dict[str, Any]:
    core = {
        key: item
        for key, item in value.items()
        if key not in {"promptPackFingerprint", "cache"}
    }
    if core.get("schema") != SCHEMA or value.get(
        "promptPackFingerprint"
    ) != _fingerprint(core):
        raise ValueError("recreation_prompt_pack_invalid")
    if core.get("referenceVideo") is not None and core.get("creatorImage") is None:
        _validate_soul_identity_binding(
            core.get("soulIdentity"), creator=str(core.get("creator") or "")
        )
    anchor = _validated_anchor_prompt(str(core.get("anchorPrompt") or ""))
    seedance = _validated_positive_prompt(
        str(core.get("seedancePrompt") or ""), "seedance"
    )
    kling = _validated_positive_prompt(str(core.get("klingPrompt") or ""), "kling")
    if core.get("creatorPresentationPolicy") is not None:
        if core.get("creatorPresentationPolicy") != _CREATOR_PRESENTATION_POLICY:
            raise ValueError("recreation_creator_presentation_policy_invalid")
        _validated_creator_presentation(anchor, "anchor")
        _validated_creator_presentation(seedance, "seedance")
        _validated_creator_presentation(kling, "kling")
    if not kling or len(kling) > 2500:
        raise ValueError("recreation_kling_prompt_invalid")
    for index, item in enumerate(core.get("timeline") or []):
        _validated_positive_prompt(
            str(item.get("action") or ""), f"timeline_action_{index}"
        )
        _validated_positive_prompt(
            str(item.get("camera") or ""), f"timeline_camera_{index}"
        )
    planning = core.get("promptPlanning")
    if (
        not isinstance(planning, dict)
        or planning.get("builderVersion") != PROMPT_BUILDER_VERSION
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(planning.get("requestFingerprint") or "")
        )
    ):
        raise ValueError("recreation_prompt_planning_lineage_invalid")
    return value


def compile_video_prompt(
    prompt_pack: dict[str, Any],
    provider_model: str,
    prompt_card: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the provider-specific prompt and pack fingerprint to one job."""

    prompt_text = str(
        prompt_pack[
            "klingPrompt" if provider_model == "kling3_0_turbo" else "seedancePrompt"
        ]
    )
    card = {
        **prompt_card,
        "openaiPromptPackFingerprint": prompt_pack["promptPackFingerprint"],
    }
    card["promptCardFingerprint"] = _fingerprint(card)
    governance = bind_campaign_prompt(
        prompt_id="campaign.recreation_provider_compile",
        version="3",
        provider=(
            "higgsfield"
            if provider_model in {"kling3_0_turbo", "seedance_2_0"}
            else "any"
        ),
        model=provider_model,
        compiled_prompt=prompt_text,
        inputs={
            "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
            "promptCardFingerprint": card["promptCardFingerprint"],
        },
    )
    return card, {
        "schema": "campaign_factory.openai_video_prompt.v1",
        "text": prompt_text,
        "promptGovernance": governance,
        "compiledPromptFingerprint": _fingerprint(
            {
                "text": prompt_text,
                "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
                "providerModel": provider_model,
                "promptGovernance": governance,
            }
        ),
    }


def _instruction(intent: str, has_reference_video: bool) -> str:
    source = (
        "The first image is the approved creator identity. The remaining images are "
        "chronological samples from one authorized reference Reel."
        if has_reference_video
        else "The image is the approved creator identity for a calm short animation."
    )
    action = (
        "Copy the reference Reel's chronological actions, timing, framing, camera "
        "behavior, setting category, wardrobe category, and performance energy."
        if has_reference_video
        else "Invent one attractive, realistic 9:16 scene and pose that will animate "
        "well with calm eye, head, breathing, hair, and small hand movements."
    )
    visual_direction = (
        ""
        if has_reference_video
        else f" Default visual direction: {LOW_EFFORT_REEL_VISUAL_DIRECTION}"
    )
    return (
        f"{source} {action}{visual_direction} Return an anchorPrompt for Higgsfield Soul 2, a detailed "
        "Seedance 2 Fast prompt, a Kling 3 Turbo prompt with a 2500-character "
        f"maximum, and a chronological timeline. Intent: {intent}. "
        "The anchor prompt describes adult-coded pose, wardrobe, setting, lighting, "
        "framing, and composition using affirmative desired-result language. The "
        "approved creator image exclusively supplies identity, face, skin tone, "
        "hair, tattoos, beauty marks, and permanent body details, so the anchor "
        "prompt stays focused on the scene and composition. Video prompts explicitly "
        "use the approved anchor as the exact person, preserve every visible identity "
        "and permanent feature, and describe only desired visuals, movement, timing, "
        "and camera behavior in affirmative language. Provider settings control "
        "audio separately. Source writing stays outside the generated prompts."
    )


def _directed_instruction(
    intent: str,
    has_reference_video: bool,
    *,
    reference_video_sha256: str | None,
    creator: str,
    soul_identity: dict[str, Any] | None,
) -> str:
    reference_sha = str(reference_video_sha256 or "")
    if has_reference_video and not re.fullmatch(r"[0-9a-f]{64}", reference_sha):
        raise ValueError("reference_video_sha256_required_for_prompt_instruction")
    if has_reference_video and soul_identity is None:
        raise PermissionError("verified_soul_identity_required_for_recreation_prompt")
    reference_direction = (
        " The chronological samples belong to exactly one authorized reference Reel, "
        f"bound to SHA-256 {reference_sha}. Analyze every visible sample for the "
        "exact pose, framing, body angle, and first-frame composition. When visibly "
        "supported, retain non-explicit fuller-chest and cleavage framing or a rounded "
        "hip and butt silhouette as deliberate composition facts. Treat the opening "
        "burst as the first-frame anchor authority "
        "and use the distributed and endpoint samples for continuity."
        if has_reference_video
        else ""
    )
    identity_direction = (
        f" Creator slug {creator.strip().lower()} is bound to verified Higgsfield "
        f"Soul ID {soul_identity['soulId']} with profile fingerprint "
        f"{soul_identity['identityProfileFingerprint']}. The Soul is the sole "
        "identity source; use the Reel frames only for structure, pose, framing, "
        "body angle, scene, wardrobe category, movement, and camera behavior. "
        "Keep returned prompts scene and composition focused."
        if soul_identity is not None
        else ""
    )
    presentation_direction = (
        " Every generated provider prompt presents the creator as an adult woman, "
        "age 19, with dark hair. Generated prompts omit all commentary about permanent "
        "skin markings."
    )
    base_instruction = _instruction(intent, has_reference_video).replace(
        "hair, tattoos, beauty marks, and permanent body details",
        "hair and permanent identity details",
    )
    if has_reference_video:
        base_instruction = base_instruction.replace(
            "The first image is the approved creator identity. The remaining images "
            "are chronological samples from one authorized reference Reel.",
            "All images are chronological structural samples from one authorized "
            "reference Reel. The verified selected Higgsfield Soul binding is the "
            "sole creator identity source.",
        ).replace(
            "The approved creator image exclusively supplies identity, face, skin "
            "tone, hair and permanent identity details, so the anchor prompt stays "
            "focused on the scene and composition.",
            "The verified selected Higgsfield Soul binding exclusively supplies "
            "identity, face, skin tone, hair, and permanent identity details. The "
            "reference Reel frames supply only structure, pose, framing, scene, "
            "wardrobe category, movement, timing, and camera behavior, so the anchor "
            "prompt stays focused on the scene and composition.",
        )
    return (
        base_instruction
        + reference_direction
        + identity_direction
        + presentation_direction
    )


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "anchorPrompt",
            "seedancePrompt",
            "klingPrompt",
            "timeline",
        ],
        "properties": {
            "anchorPrompt": {"type": "string"},
            "seedancePrompt": {"type": "string"},
            "klingPrompt": {"type": "string", "maxLength": 2500},
            "timeline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["startSeconds", "endSeconds", "action", "camera"],
                    "properties": {
                        "startSeconds": {"type": "number"},
                        "endSeconds": {"type": "number"},
                        "action": {"type": "string"},
                        "camera": {"type": "string"},
                    },
                },
            },
        },
    }


def _post_responses(payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _API_URL,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError(
            f"openai_prompt_generation_failed:{exc.code}:{detail}"
        ) from None
    if not isinstance(value, dict):
        raise RuntimeError("openai_prompt_generation_returned_non_object")
    return value


def _response_json(response: dict[str, Any]) -> dict[str, Any]:
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            value = json.loads(str(content.get("text") or ""))
            if isinstance(value, dict):
                return value
    raise RuntimeError("openai_prompt_generation_output_missing")


def _prompt_cache_path(request_fingerprint: str, *, cache_root: Path | None) -> Path:
    root = (
        cache_root
        if cache_root is not None
        else resolve_runtime_paths().state_root / "openai_prompt_packs"
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root.resolve() / f"{request_fingerprint}.json"


def _load_cached_prompt_pack(
    path: Path, request_fingerprint: str
) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    planning = value.get("promptPlanning")
    if (
        not isinstance(planning, dict)
        or planning.get("requestFingerprint") != request_fingerprint
    ):
        return None
    try:
        validate_prompt_pack(value)
    except ValueError:
        return None
    return value


def _write_prompt_cache(path: Path, pack: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(pack, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _authorize_openai_prompt_call(
    request_core: dict[str, Any],
    *,
    request_fingerprint: str,
    cache_path: Path,
    conn: sqlite3.Connection,
    creator_id: str,
    campaign_id: str,
    run_id: str,
    governance_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reserve unified budget and persist the signed one-call authorization."""

    secret = str(os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET") or "")
    if len(secret.encode()) < 32:
        raise RuntimeError("openai_prompt_spend_authorization_secret_missing")
    quote_raw = str(os.environ.get("CREATOR_OS_OPENAI_PROMPT_QUOTE_USD") or "")
    try:
        quote_usd = float(quote_raw)
    except ValueError as exc:
        raise RuntimeError("openai_prompt_spend_quote_missing") from exc
    if not math.isfinite(quote_usd) or quote_usd <= 0:
        raise RuntimeError("openai_prompt_spend_quote_missing")
    attempt_id = f"openaiattempt_{uuid.uuid4().hex}"
    scope = build_paid_action_spend_scope(
        provider="openai",
        provider_model=str(request_core["model"]),
        action_type="recreation_prompt_pack",
        creator_id=creator_id,
        campaign_id=campaign_id,
        run_id=run_id,
        input_fingerprints={
            "prompt_request": request_fingerprint,
            **(
                {"creator_image": str(request_core["creatorImageSha256"])}
                if request_core.get("creatorImageSha256")
                else {}
            ),
            **(
                {"reference_video": str(request_core["referenceVideoSha256"])}
                if request_core.get("referenceVideoSha256")
                else {}
            ),
            **(
                {
                    "soul_identity": str(
                        request_core["promptInputs"]["soulIdentityBindingFingerprint"]
                    )
                }
                if request_core["promptInputs"].get("soulIdentityBindingFingerprint")
                else {}
            ),
        },
        parameters={
            "maximumCalls": 1,
            "builderVersion": request_core["builderVersion"],
        },
        prompt_governance=request_core["promptGovernance"],
    )
    quote = build_paid_action_quote(
        provider="openai",
        model=str(request_core["model"]),
        amount=quote_usd,
        source="CREATOR_OS_OPENAI_PROMPT_QUOTE_USD",
        pricing_version="operator_configured_maximum.v1",
    )
    receipt = issue_paid_action_authorization(
        conn,
        scope=scope,
        quote=quote,
        secret=secret,
        limits=budget_limits_from_env(provider="openai", run_cap_usd=quote_usd),
        governance_context=governance_context,
        current_prompt_registry=PROMPT_REGISTRY,
        compiled_prompt=request_core["instruction"],
        prompt_inputs=request_core["promptInputs"],
    )
    authorization_root = cache_path.parent / "authorizations"
    authorization_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(authorization_root, 0o700)
    authorization_id = str(receipt["authorizationId"])
    receipt_path = authorization_root / f"{request_fingerprint}.{authorization_id}.json"
    receipt_text = json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_write_text(receipt_path, receipt_text, encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    return {
        "authorizationId": authorization_id,
        "attemptId": attempt_id,
        "status": "authorized",
        "requestFingerprint": request_fingerprint,
        "spendRequestFingerprint": scope["requestFingerprint"],
        "maximumCalls": 1,
        "quote": quote,
        "receiptPath": str(receipt_path),
        "receiptSha256": hashlib.sha256(receipt_text.encode()).hexdigest(),
        "signatureAlgorithm": "HMAC-SHA256",
        "payload": receipt,
    }


def _verify_openai_prompt_authorization(
    receipt: dict[str, Any],
    *,
    secret: str,
    request_fingerprint: str,
) -> None:
    scope = receipt.get("scope")
    if not isinstance(scope, dict):
        raise PermissionError("openai_prompt_spend_authorization_invalid")
    try:
        verify_authorization_v3(
            receipt,
            expected_scope=scope,
            secret=secret,
        )
    except (ValueError, PermissionError) as exc:
        raise PermissionError("openai_prompt_spend_authorization_invalid") from exc
    inputs = scope.get("inputFingerprints")
    if not isinstance(inputs, dict) or request_fingerprint not in inputs.values():
        raise PermissionError("openai_prompt_spend_authorization_invalid")


def _json_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value))


def _response_cost(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("cost")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"status": "reported", "usd": float(raw)}
    if isinstance(raw, dict):
        usd = raw.get("usd")
        if isinstance(usd, (int, float)) and not isinstance(usd, bool):
            return {"status": "reported", "usd": float(usd)}
    return {"status": "not_exposed", "usd": None}


def _frame_sample_plan(duration: float) -> list[dict[str, Any]]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("reference duration must be positive")
    candidates = (
        ("opening_first", 0.0),
        ("opening_burst", min(0.15, duration * 0.03)),
        ("opening_burst", min(0.4, duration * 0.08)),
        ("opening_burst", min(0.8, duration * 0.16)),
        ("distributed", duration * 0.30),
        ("midpoint", duration * 0.50),
        ("distributed", duration * 0.78),
        ("endpoint", max(0.0, duration - min(0.08, duration * 0.01))),
    )
    plan: list[dict[str, Any]] = []
    for role, timestamp in candidates:
        normalized = round(min(max(timestamp, 0.0), duration), 6)
        if any(abs(normalized - item["timestampSeconds"]) < 0.001 for item in plan):
            continue
        plan.append({"role": role, "timestampSeconds": normalized})
    return plan


def _sample_frames(video: Path, output_dir: Path) -> list[dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg_and_ffprobe_required_for_openai_reel_prompting")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("openai_reel_duration_probe_failed") from exc
    if probe.returncode != 0 or duration <= 0:
        raise RuntimeError("openai_reel_duration_probe_failed")
    frames: list[dict[str, Any]] = []
    for index, sample in enumerate(_frame_sample_plan(duration)):
        timestamp = float(sample["timestampSeconds"])
        frame = output_dir / (
            f"frame-{index:02d}-{sample['role']}-{round(timestamp * 1000):06d}ms.jpg"
        )
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-ss",
                f"{timestamp:.6f}",
                "-frames:v",
                "1",
                "-vf",
                "scale=512:-2",
                "-q:v",
                "2",
                str(frame),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0 or not frame.is_file():
            raise RuntimeError("openai_reel_frame_sampling_failed")
        frames.append({**sample, "path": frame})
    if len(frames) < int(_FRAME_SAMPLING_POLICY["minimumSamples"]):
        raise RuntimeError("openai_reel_frame_sampling_failed")
    return frames


def _data_url_exact(path: Path, expected_sha256: str) -> str:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise PermissionError("openai_prompt_creator_image_sha256_mismatch")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


def _snapshot_exact_file(
    source: Path,
    *,
    expected_sha256: str,
    destination: Path,
) -> Path:
    digest = hashlib.sha256()
    with source.open("rb") as source_handle, destination.open("xb") as output:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise PermissionError("openai_prompt_reference_video_sha256_mismatch")
    return destination


def _validated_anchor_prompt(value: str) -> str:
    prompt = _validated_positive_prompt(value, "anchor")
    lower = prompt.lower()
    found = [
        token
        for token in _ANCHOR_FORBIDDEN
        if re.search(rf"\b{re.escape(token)}\b", lower)
    ]
    if found:
        raise ValueError(f"openai_anchor_prompt_contains_identity_or_ui_terms:{found}")
    return prompt


def _validated_positive_prompt(value: str, label: str) -> str:
    prompt = " ".join(value.split())
    if not prompt:
        raise ValueError(f"openai_{label}_prompt_missing")
    match = _NEGATIVE_LANGUAGE.search(prompt)
    if match:
        raise ValueError(
            f"openai_{label}_prompt_contains_negative_language:{match.group(0)}"
        )
    forbidden = _FORBIDDEN_GENERATED_LANGUAGE.search(prompt)
    if forbidden:
        raise ValueError(
            f"openai_{label}_prompt_contains_forbidden_language:{forbidden.group(0)}"
        )
    return prompt


def _validated_creator_presentation(value: str, label: str) -> str:
    lower = value.lower()
    if (
        "adult woman" not in lower
        or not re.search(r"\bage\s+19\b", lower)
        or "dark hair" not in lower
    ):
        raise ValueError(f"openai_{label}_prompt_missing_adult_presentation")
    return value


def _verified_soul_identity_binding(
    *,
    creator: str,
    governance_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = governance_context if isinstance(governance_context, dict) else {}
    creator_slug = creator.strip().lower()
    soul_id = str(context.get("providerIdentityId") or "").strip()
    profile_id = str(context.get("identityProfileId") or "").strip()
    profile_fingerprint = str(context.get("identityProfileFingerprint") or "").strip()
    profile_version = context.get("identityProfileVersion")
    if (
        context.get("creatorSlug") != creator_slug
        or context.get("provider") not in {None, "higgsfield"}
        or not soul_id
        or not profile_id
        or not isinstance(profile_version, int)
        or profile_version < 1
        or not re.fullmatch(r"[0-9a-f]{64}", profile_fingerprint)
    ):
        raise PermissionError("verified_soul_identity_required_for_recreation_prompt")
    core = {
        "schema": "campaign_factory.verified_soul_identity_binding.v1",
        "creatorSlug": creator_slug,
        "provider": "higgsfield",
        "soulId": soul_id,
        "identityProfileId": profile_id,
        "identityProfileVersion": profile_version,
        "identityProfileFingerprint": profile_fingerprint,
    }
    return _validate_soul_identity_binding(
        {**core, "bindingFingerprint": _fingerprint(core)}, creator=creator_slug
    )


def _validate_soul_identity_binding(value: Any, *, creator: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PermissionError("verified_soul_identity_required_for_recreation_prompt")
    core = {key: item for key, item in value.items() if key != "bindingFingerprint"}
    if (
        core.get("schema") != "campaign_factory.verified_soul_identity_binding.v1"
        or core.get("creatorSlug") != creator.strip().lower()
        or core.get("provider") != "higgsfield"
        or not str(core.get("soulId") or "").strip()
        or not str(core.get("identityProfileId") or "").strip()
        or not isinstance(core.get("identityProfileVersion"), int)
        or int(core["identityProfileVersion"]) < 1
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(core.get("identityProfileFingerprint") or "")
        )
        or value.get("bindingFingerprint") != _fingerprint(core)
    ):
        raise PermissionError("verified_soul_identity_required_for_recreation_prompt")
    return dict(value)


def _openai_api_key() -> str | None:
    runtime = resolve_runtime_paths()
    return os.environ.get("OPENAI_API_KEY") or _load_env_file(
        runtime.config_root / "generation.env"
    ).get("OPENAI_API_KEY")


def _required_path(value: Path | None, label: str) -> Path:
    if value is None:
        raise ValueError(f"{label} is required")
    return value


def _regular_file(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
