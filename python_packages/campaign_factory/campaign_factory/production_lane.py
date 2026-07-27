from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_text
from creator_os_core.provider_spend import (
    build_generate_assets_spend_scope,
    verify_authorization,
)

from .audio_policy import (
    AUDIO_POLICIES,
    build_embedded_trending_audio_intent,
)
from .audio_radar import (
    AudioCache,
    AudioLocator,
    AudioMatchContext,
    NeedsEmbeddedAudioError,
    PlatformSoundId,
    TrendCandidate,
    bind_embedding_receipt,
    fulfill_embedded_trending,
    normalize_candidates,
    rank_candidates,
)
from .audio_radar.providers import (
    ProviderError,
    SocialCrawlInstagramProvider,
    TokchartTrendProvider,
)
from .production_batch_results import (
    block_duplicate_provider_outputs as _block_duplicate_provider_outputs,
)
from .production_batch_results import (
    finalize_production_batch as _finalize_production_batch,
)
from .production_batch_results import probe_production_video as _probe_production_video
from .provider_spend import (
    consume_provider_spend_authorization as consume_higgsfield_authorization,
)
from .provider_spend import (
    issue_provider_spend_authorization,
    record_provider_execution,
)

SCHEMA: Final = "campaign_factory.production_motion_recipe.v1"
BATCH_SCHEMA: Final = "campaign_factory.production_batch.v1"
DEFAULT_HIGGSFIELD_BATCH_MAX_CREDITS: Final = 100.0
DEFAULT_CLOUD_CONCURRENCY: Final = 2
_OPERATOR_VISUAL_SELECTION_COMPLETE = True
_PASSIVE_RECIPE_ENV: Final = "CREATOR_OS_PASSIVE_VIDEO_RECIPE"
_PASSIVE_RECIPE_CONFIG: Final[dict[str, dict[str, Any]]] = {
    "higgsfield_kling3_i2v": {
        "modelId": "higgsfield_kling3_i2v",
        "providerModel": "kling3_0",
        "recipeId": "higgsfield_passive_selfie",
        "durationSeconds": 5,
        "resolution": "720x1280",
        "mode": "pro",
        "sound": "off",
    },
    "higgsfield_seedance2_i2v": {
        "modelId": "higgsfield_seedance2_i2v",
        "providerModel": "seedance_2_0",
        "recipeId": "higgsfield_passive_selfie",
        "durationSeconds": 5,
        "resolution": "720p",
        "mode": "std",
        "sound": "off",
    },
}
_SUPPORTED_PASSIVE_INTENTS: Final = frozenset(
    {
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    }
)
_UNRESOLVED_INTENT_ERRORS: Final = {
    "motion_copy": (
        "motion_copy_unresolved: no operator-approved Higgsfield motion-transfer "
        "recipe is active"
    ),
    "dance": (
        "motion_copy_unresolved: no operator-approved Higgsfield motion-transfer "
        "recipe is active"
    ),
    "talking_selfie": (
        "talking_selfie_unresolved: no authenticated Higgsfield recipe has proven "
        "exact supplied-creator-audio preservation"
    ),
    "talking_motion_copy": (
        "talking_motion_unresolved: motion transfer and exact supplied-audio "
        "lip-sync are not both operator-approved"
    ),
}
_CREATOR_SOUL_IDS: Final = {
    "stacey": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
    "stacey1": "5828d958-91dd-4d6d-8909-934503f47644",
    "larissa": "44326567-b12c-410c-95b7-31891bb0629b",
    "lola": "4c86c548-7aa5-4ad1-bc03-b94aa4ce8385",
}

_INTENT_PROMPTS: Final[dict[str, str]] = {
    "passive_selfie": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld social camera behavior. No speaking, exaggerated movement, or "
        "identity-changing action."
    ),
    "flirty_portrait": (
        "A warm restrained gaze shift, a small confident head turn, one gentle hair "
        "adjustment, subtle breathing, and a natural handheld creator camera. No "
        "speaking, exaggerated movement, or identity-changing action."
    ),
    "outfit": (
        "A small posture shift to present the outfit, natural eye movement, one "
        "purposeful clothing adjustment, restrained fabric movement, and subtle "
        "handheld camera behavior. No speaking or exaggerated movement."
    ),
    "lifestyle": (
        "Natural eye movement and a subtle head turn, one purposeful interaction "
        "with clothing or hair, restrained body movement, and casual handheld "
        "creator camera behavior. No speaking or identity-changing action."
    ),
    "animate_existing": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld camera behavior. No speaking, exaggerated movement, or "
        "identity-changing action."
    ),
    "motion_copy": (
        "Transfer the driving video's body motion and timing faithfully while "
        "preserving the creator's face, body proportions, clothing, and portrait "
        "identity. Keep the source portrait framing and avoid camera cuts."
    ),
    "dance": (
        "Transfer the driving dance motion and timing faithfully while preserving "
        "the creator's face, body proportions, clothing, and portrait identity. "
        "Keep the source portrait framing and avoid camera cuts."
    ),
    "talking_selfie": (
        "A natural direct-to-camera creator delivery with accurate lip movement, "
        "subtle facial expression, restrained head motion, steady portrait framing, "
        "and consistent identity throughout."
    ),
    "talking_motion_copy": (
        "Transfer the driving video's body motion and timing while preserving the "
        "creator's identity and portrait framing, then synchronize the supplied "
        "creator voice without changing the face or body."
    ),
}

_TALKING_INTENTS: Final = frozenset({"talking_selfie", "talking_motion_copy"})
_MOTION_CONTROL_INTENTS: Final = frozenset(
    {"motion_copy", "dance", "talking_motion_copy"}
)

_AUDIO_ALIASES: Final = {
    "embedded_trending": "embedded_trending_required",
}


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_policy(value: str) -> str:
    resolved = _AUDIO_ALIASES.get(value, value)
    if resolved not in AUDIO_POLICIES:
        raise ValueError(f"unsupported production audio policy: {value}")
    return resolved


def discover_production_audio_candidates() -> list[TrendCandidate]:
    """Discover candidates internally; missing providers never widen to silence."""

    candidates: list[TrendCandidate] = []
    fixture = _approved_audio_fixture_candidate()
    if fixture is not None:
        return normalize_candidates([fixture])
    for provider in (
        SocialCrawlInstagramProvider(),
        TokchartTrendProvider(),
    ):
        try:
            candidates.extend(provider.discover(region=None, limit=25))
        except ProviderError:
            continue
    return normalize_candidates(candidates)


def _approved_audio_fixture_candidate() -> TrendCandidate | None:
    raw = os.environ.get("CREATOR_OS_EMBEDDED_AUDIO_FIXTURE", "").strip()
    if not raw:
        return None
    expanded = Path(raw).expanduser()
    if expanded.is_symlink():
        raise ValueError("approved embedded-audio fixture must not be a symlink")
    path = expanded.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"approved embedded-audio fixture is missing: {path}")
    digest = _sha256_file(path)
    observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    return TrendCandidate(
        candidate_id=f"approved-local-fixture:{digest}",
        provider="operator_approved_fixture",
        title=os.environ.get("CREATOR_OS_EMBEDDED_AUDIO_FIXTURE_TITLE", path.stem),
        artist="approved local fixture",
        platform_sound_ids=(
            PlatformSoundId(platform="local_fixture", sound_id=digest[:24]),
        ),
        observed_at=observed_at,
        current_rank=1,
        usage_velocity=1_000_000,
        trend_score=1.0,
        canonical_track_id=f"local_fixture:{digest}",
        locator=AudioLocator(
            provider="operator_approved_fixture",
            platform="local_fixture",
            track_id=digest,
            kind="local_file",
            value=str(path),
        ),
        advisory_labels={"operatorApprovedFixture": True},
    )


def fulfill_production_audio(
    factory: Any,
    *,
    job: Mapping[str, Any],
    generation_result: dict[str, Any],
    candidates: list[TrendCandidate] | None = None,
    selected_at: str | None = None,
) -> dict[str, Any]:
    """Carry one generated asset through canonical embedded-audio fulfillment."""

    policy = _audio_policy(str(job.get("audioPolicy") or ""))
    if policy != "embedded_trending_required":
        return {"policy": policy, "requiredStage": "separate_optional_path"}
    stage = _motion_stage_result(generation_result)
    registered = stage.get("registeredAsset")
    if not isinstance(registered, dict):
        raise RuntimeError("production generated asset registration missing")
    rendered_asset_id = str(registered.get("id") or "")
    video_path = Path(str(registered.get("output_path") or "")).expanduser()
    if not rendered_asset_id or video_path.is_symlink():
        raise RuntimeError("production generated asset binding is unsafe")
    video_path = video_path.resolve()
    if not video_path.is_file():
        raise RuntimeError("production generated video is missing")
    discovered = (
        normalize_candidates(candidates)
        if candidates is not None
        else discover_production_audio_candidates()
    )
    ranked = rank_candidates(
        discovered,
        AudioMatchContext(
            creator=str(job.get("creator") or ""),
            account=str(job.get("accountGroup") or ""),
            motion_tags=(str(job.get("intent") or ""),),
            speaking=False,
        ),
    )
    if not ranked:
        raise NeedsEmbeddedAudioError(
            [{"status": "failed", "reason": "audio_candidates_exhausted"}]
        )
    completed_at = selected_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    final_path = video_path.with_name(
        f"{video_path.stem}__embedded_trending{video_path.suffix}"
    )
    fulfilled = fulfill_embedded_trending(
        video_path=video_path,
        ranked_candidates=ranked,
        cache=AudioCache(video_path.parent / ".audio-cache"),
        output_path=final_path,
        retrieved_at=completed_at,
        speaking=False,
    )
    receipt = fulfilled.embedding_receipt
    receipt["creativeContext"] = {
        "creator": job.get("creator"),
        "account": job.get("accountGroup"),
        "intent": job.get("intent"),
        "speaking": False,
    }
    receipt["audioIntent"] = build_embedded_trending_audio_intent(
        receipt,
        selected_at=completed_at,
    )
    receipt_path = final_path.with_suffix(".audio_embedding.json")
    atomic_write_text(
        receipt_path,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    binding = bind_embedding_receipt(
        factory.conn,
        rendered_asset_id=rendered_asset_id,
        embedding_receipt=receipt,
        bound_at=completed_at,
    )
    if binding["finalVideoSha256"] != receipt["finalVideo"]["sha256"]:
        raise RuntimeError("production audio binding SHA mismatch")
    refreshed = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    stage["registeredAsset"] = dict(refreshed) if refreshed else registered
    return {
        "policy": policy,
        "status": "verified",
        "receiptPath": str(receipt_path),
        "receipt": receipt,
        "binding": binding,
        "finalVideoSha256": binding["finalVideoSha256"],
        "outputPath": binding["outputPath"],
    }


def _motion_stage_result(generation_result: dict[str, Any]) -> dict[str, Any]:
    nested = generation_result.get("result")
    if isinstance(nested, dict) and (
        nested.get("schema") == "campaign_factory.motion_generation_stage_run.v1"
        or "registeredAsset" in nested
    ):
        return nested
    return generation_result


def build_production_motion_recipe(
    *,
    creator: str,
    intent: str,
    execution: str,
    source_sha256: str,
) -> dict[str, Any]:
    if intent not in _INTENT_PROMPTS:
        raise ValueError(f"intent {intent!r} is not in the production motion catalog")
    unresolved = _UNRESOLVED_INTENT_ERRORS.get(intent)
    if unresolved:
        raise ValueError(unresolved)
    if execution == "cloud":
        mode = "best_motion"
        configured = os.environ.get(
            _PASSIVE_RECIPE_ENV, "higgsfield_kling3_i2v"
        ).strip()
        try:
            stage = _PASSIVE_RECIPE_CONFIG[configured]
        except KeyError as exc:
            raise ValueError(
                f"{_PASSIVE_RECIPE_ENV} must pin one operator-approved "
                "Higgsfield passive recipe"
            ) from exc
        stages = ({**stage, "task": "image_to_video"},)
        model_id = str(stages[0]["modelId"])
    else:
        raise ValueError("production create requires Higgsfield cloud execution")
    core = {
        "schema": SCHEMA,
        "recipeId": f"{execution}_{intent}_creator_motion_v2",
        "status": "supported",
        "creator": creator.strip().lower(),
        "intent": intent,
        "mode": mode,
        "modelId": model_id,
        "stages": [dict(stage) for stage in stages],
        "sourceSha256": source_sha256,
        "paidProviderFallbackAllowed": False,
        "researchSelectionRequired": False,
        "operatorVisualSelectionRequired": False,
        "provider": "higgsfield",
    }
    return {**core, "recipeFingerprint": _fingerprint(core)}


def bind_production_prompt_expansion(
    recipe: Mapping[str, Any],
    *,
    original_prompt: str,
    expansion: Mapping[str, Any],
) -> dict[str, Any]:
    expanded_prompt = " ".join(str(expansion.get("expandedPrompt") or "").split())
    if len(expanded_prompt) < 20:
        raise ValueError("Qwen Wan prompt expansion did not return a usable prompt")
    core = {
        key: value for key, value in dict(recipe).items() if key != "recipeFingerprint"
    }
    core.update(
        {
            "originalPromptSha256": hashlib.sha256(
                " ".join(original_prompt.split()).encode("utf-8")
            ).hexdigest(),
            "expandedPromptSha256": hashlib.sha256(
                expanded_prompt.encode("utf-8")
            ).hexdigest(),
            "promptExpansion": dict(expansion),
        }
    )
    return {**core, "recipeFingerprint": _fingerprint(core)}


def validate_production_motion_recipe(
    recipe: dict[str, Any], *, model_id: str, source_sha256: str
) -> dict[str, Any]:
    core = dict(recipe)
    claimed = str(core.pop("recipeFingerprint", ""))
    if (
        core.get("schema") != SCHEMA
        or core.get("status") != "supported"
        or core.get("modelId") != model_id
        or core.get("sourceSha256") != source_sha256
        or core.get("researchSelectionRequired") is not False
        or core.get("operatorVisualSelectionRequired") is not False
        or core.get("provider") != "higgsfield"
        or core.get("paidProviderFallbackAllowed") is not False
        or claimed != _fingerprint(core)
    ):
        raise PermissionError("production_motion_recipe_invalid")
    return recipe


def bind_production_motion_recipe(
    recipe: Mapping[str, Any] | None,
    *,
    model_id: str,
    source_sha256: str,
    research_admission: Any,
) -> bool:
    if recipe is None:
        return False
    if research_admission is not None:
        raise PermissionError("mixed_local_production_and_research_evidence")
    validate_production_motion_recipe(
        dict(recipe), model_id=model_id, source_sha256=source_sha256
    )
    return True


def _deterministic_seed(
    *, creator: str, intent: str, index: int, source_sha256: str, used: set[int]
) -> int:
    nonce = 0
    while True:
        material = f"{creator}:{intent}:{index}:{source_sha256}:{nonce}".encode()
        seed = int(hashlib.sha256(material).hexdigest()[:8], 16) % 2_147_483_648
        if seed not in used:
            return seed
        nonce += 1


def plan_production_batch(
    factory: Any,
    *,
    creator: str,
    intent: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    speech_audio_path: Path | None = None,
    motion_reference_path: Path | None = None,
) -> dict[str, Any]:
    if isinstance(count, bool) or not 1 <= int(count) <= 100:
        raise ValueError("count must be between 1 and 100")
    if execution != "cloud":
        raise ValueError("production create requires Higgsfield cloud execution")
    unresolved = _UNRESOLVED_INTENT_ERRORS.get(intent)
    if unresolved:
        raise ValueError(unresolved)
    if intent not in _SUPPORTED_PASSIVE_INTENTS:
        raise ValueError(f"intent {intent!r} has no supported production recipe")
    creator_slug = creator.strip().lower().replace(" ", "_")
    resolved_audio_policy = _audio_policy(audio_preference)
    speech_audio = _optional_safe_media(speech_audio_path, "speech audio")
    motion_reference = _optional_safe_media(
        motion_reference_path, "motion reference video"
    )
    if intent in _TALKING_INTENTS:
        if resolved_audio_policy != "creator_voice":
            raise ValueError("talking intents require --audio creator_voice")
        if speech_audio is None:
            raise ValueError("talking intents require --speech-audio")
    elif speech_audio is not None:
        raise ValueError("--speech-audio is only valid for a talking intent")
    if intent in _MOTION_CONTROL_INTENTS:
        if motion_reference is None:
            raise ValueError("motion-copy intents require --motion-reference")
    elif motion_reference is not None:
        raise ValueError("--motion-reference is only valid for a motion-copy intent")
    speech_sha = _sha256_file(speech_audio) if speech_audio is not None else None
    motion_reference_sha = (
        _sha256_file(motion_reference) if motion_reference is not None else None
    )
    rows = factory.conn.execute(
        """
        SELECT s.*, c.slug AS campaign_slug, m.slug AS creator_slug
        FROM source_assets s
        JOIN campaigns c ON c.id = s.campaign_id
        JOIN models m ON m.id = s.model_id
        WHERE lower(m.slug) = ? AND s.media_type = 'image'
          AND lower(COALESCE(s.status, 'imported')) NOT IN ('rejected', 'quarantined')
        ORDER BY c.updated_at DESC, s.created_at DESC, s.id
        """,
        (creator_slug,),
    ).fetchall()
    sources: list[dict[str, Any]] = []
    seen_source_hashes: set[str] = set()
    substituted_sources = 0
    incompatible_sources = 0
    for row in rows:
        source = dict(row)
        raw_path = Path(str(source["stored_path"])).expanduser()
        if raw_path.is_symlink():
            substituted_sources += 1
            continue
        path = raw_path.resolve()
        recorded_sha = str(source["content_hash"])
        if not path.is_file() or _sha256_file(path) != recorded_sha:
            substituted_sources += 1
            continue
        if recorded_sha in seen_source_hashes:
            continue
        if execution == "cloud":
            resolution = _source_image_resolution(path)
            if resolution is None:
                substituted_sources += 1
                continue
            width, height = resolution
            ratio = width / height
            if not 0.50 <= ratio <= 0.65:
                incompatible_sources += 1
                continue
            if intent in _MOTION_CONTROL_INTENTS and min(width, height) < 300:
                incompatible_sources += 1
                continue
            source["sourceResolution"] = {
                "width": width,
                "height": height,
                "aspectRatio": round(ratio, 6),
            }
        source["stored_path"] = str(path)
        seen_source_hashes.add(recorded_sha)
        sources.append(source)
    if not sources:
        if incompatible_sources:
            raise ValueError(
                f"no portrait-reel approved image inventory for creator {creator}"
            )
        if substituted_sources:
            raise ValueError(
                f"approved source SHA mismatch for creator {creator}; "
                "refresh source inventory before generation"
            )
        raise ValueError(f"no usable approved image inventory for creator {creator}")
    jobs: list[dict[str, Any]] = []
    used_seeds: set[int] = set()
    for index in range(int(count)):
        source = sources[index % len(sources)]
        source_sha = str(source["content_hash"])
        seed = _deterministic_seed(
            creator=creator_slug,
            intent=intent,
            index=index,
            source_sha256=source_sha,
            used=used_seeds,
        )
        used_seeds.add(seed)
        recipe = build_production_motion_recipe(
            creator=creator_slug,
            intent=intent,
            execution=execution,
            source_sha256=source_sha,
        )
        identity = _fingerprint(
            {
                "source": source_sha,
                "seed": seed,
                "prompt": _INTENT_PROMPTS[intent],
                "model": recipe["modelId"],
                "speechAudio": speech_sha,
                "motionReference": motion_reference_sha,
            }
        )
        jobs.append(
            {
                "jobId": f"create_{identity[:20]}",
                "index": index,
                "campaign": source["campaign_slug"],
                "sourceAssetId": source["id"],
                "sourcePath": source["stored_path"],
                "sourceSha256": source_sha,
                "sourceResolution": source.get("sourceResolution"),
                "creator": creator_slug,
                "intent": intent,
                "prompt": _INTENT_PROMPTS[intent],
                "seed": seed,
                "requestFingerprint": identity,
                "accountGroup": accounts,
                "audioPolicy": resolved_audio_policy,
                "speechAudioPath": str(speech_audio) if speech_audio else None,
                "speechAudioSha256": speech_sha,
                "motionReferencePath": (
                    str(motion_reference) if motion_reference else None
                ),
                "motionReferenceSha256": motion_reference_sha,
                "quotedProviderCredits": None,
                "productionRecipe": recipe,
            }
        )
    return {
        "schema": BATCH_SCHEMA,
        "creator": creator_slug,
        "intent": intent,
        "execution": execution,
        "requested": int(count),
        "maxConcurrency": DEFAULT_CLOUD_CONCURRENCY,
        "provider": "higgsfield",
        "providerQuoteStatus": "required_before_apply",
        "quotedProviderCredits": None,
        "jobs": jobs,
    }


def run_production_batch(
    factory: Any,
    *,
    creator: str,
    intent: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    apply: bool,
    max_total_credits: float = DEFAULT_HIGGSFIELD_BATCH_MAX_CREDITS,
    max_concurrency: int = DEFAULT_CLOUD_CONCURRENCY,
    speech_audio_path: Path | None = None,
    motion_reference_path: Path | None = None,
) -> dict[str, Any]:
    plan = plan_production_batch(
        factory,
        creator=creator,
        intent=intent,
        count=count,
        execution=execution,
        accounts=accounts,
        audio_preference=audio_preference,
        speech_audio_path=speech_audio_path,
        motion_reference_path=motion_reference_path,
    )
    results: list[dict[str, Any]] = []
    if (
        isinstance(max_total_credits, bool)
        or not isinstance(max_total_credits, (int, float))
        or not math.isfinite(float(max_total_credits))
        or float(max_total_credits) <= 0
    ):
        raise ValueError(
            "Higgsfield production requires a finite positive batch credit cap"
        )
    if isinstance(max_concurrency, bool) or not 1 <= int(max_concurrency) <= 4:
        raise ValueError("production concurrency must be between 1 and 4")
    plan["maxConcurrency"] = min(int(max_concurrency), plan["requested"])
    plan["maxTotalCredits"] = float(max_total_credits)
    plan["paidGenerationAuthorized"] = False
    if not apply:
        results = [
            {"jobId": job["jobId"], "index": job["index"], "status": "created"}
            for job in plan["jobs"]
        ]
        return _finalize_production_batch(plan, results, apply=False)

    prepared: list[dict[str, Any]] = []
    for job in plan["jobs"]:
        try:
            prepared.append(
                _expand_production_job_prompt(job)
                if execution == "cloud"
                else dict(job)
            )
        except Exception as exc:
            results.append(
                {
                    "jobId": job["jobId"],
                    "index": job["index"],
                    "status": "failed",
                    "error": str(exc),
                }
            )
    plan["jobs"] = [
        next(
            (
                prepared_job
                for prepared_job in prepared
                if prepared_job["jobId"] == job["jobId"]
            ),
            job,
        )
        for job in plan["jobs"]
    ]
    prepared = _authorize_higgsfield_jobs(
        factory,
        prepared,
        max_total_credits=float(max_total_credits),
    )
    prepared_by_id = {str(job["jobId"]): job for job in prepared}
    plan["jobs"] = [prepared_by_id.get(str(job["jobId"]), job) for job in plan["jobs"]]
    plan["quotedProviderCredits"] = round(
        sum(float(job["quotedProviderCredits"]) for job in prepared), 4
    )
    plan["providerQuoteStatus"] = "authorized"
    plan["paidGenerationAuthorized"] = True
    audio_candidates = (
        discover_production_audio_candidates()
        if _audio_policy(audio_preference) == "embedded_trending_required"
        else []
    )
    concurrent = (
        execution == "cloud"
        and len(prepared) > 1
        and _supports_isolated_factories(factory)
    )
    workers = min(plan["maxConcurrency"], len(prepared)) if concurrent else 1
    if workers > 1:
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="creator-os-higgsfield"
        ) as executor:
            futures = {
                executor.submit(
                    _run_production_job_isolated,
                    factory,
                    job=job,
                    audio_candidates=audio_candidates,
                    max_credits_per_job=float(job["quotedProviderCredits"]),
                ): job
                for job in prepared
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        {
                            "jobId": job["jobId"],
                            "index": job["index"],
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
    else:
        for job in prepared:
            results.append(
                _run_production_job(
                    factory,
                    job=job,
                    audio_candidates=audio_candidates,
                    max_credits_per_job=float(job["quotedProviderCredits"]),
                )
            )
    results.sort(key=lambda item: int(item.get("index") or 0))
    _block_duplicate_provider_outputs(results)
    return _finalize_production_batch(plan, results, apply=True)


def _expand_production_job_prompt(job: Mapping[str, Any]) -> dict[str, Any]:
    from reel_factory.worker_api import expand_local_wan_i2v_prompt

    source = Path(str(job["sourcePath"])).expanduser().resolve()
    expansion = expand_local_wan_i2v_prompt(
        image_path=source,
        original_prompt=str(job["prompt"]),
    )
    expanded_prompt = " ".join(str(expansion.get("expandedPrompt") or "").split())
    recipe = bind_production_prompt_expansion(
        job["productionRecipe"],
        original_prompt=str(job["prompt"]),
        expansion=expansion,
    )
    return {
        **dict(job),
        "originalPrompt": job["prompt"],
        "prompt": expanded_prompt,
        "promptExpansion": expansion,
        "productionRecipe": recipe,
        "requestFingerprint": _fingerprint(
            {
                "source": job["sourceSha256"],
                "seed": job["seed"],
                "prompt": expanded_prompt,
                "model": recipe["modelId"],
            }
        ),
    }


def _supports_isolated_factories(factory: Any) -> bool:
    return getattr(factory, "settings", None) is not None and callable(
        getattr(factory, "close", None)
    )


class _BoundHiggsfieldQuote:
    def __init__(self, quote: Mapping[str, Any]) -> None:
        self._quote = dict(quote)

    def quote(self, _scope: dict[str, Any]) -> dict[str, Any]:
        return dict(self._quote)


def _higgsfield_request(
    job: Mapping[str, Any],
    *,
    max_credits: float,
) -> Any:
    from reel_factory.worker_api import HiggsfieldProductionRequest

    creator = str(job["creator"])
    try:
        soul_id = _CREATOR_SOUL_IDS[creator]
    except KeyError as exc:
        raise ValueError(
            f"no pinned authenticated Higgsfield Soul identity for creator {creator}"
        ) from exc
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    return HiggsfieldProductionRequest(
        recipe_id="higgsfield_passive_selfie",
        creator=creator,
        soul_id=soul_id,
        source_approval=str(job["sourceAssetId"]),
        source_image_path=Path(str(job["sourcePath"])),
        output_path=Path(str(job["providerOutputPath"])),
        review_root=Path(str(job["providerReviewRoot"])),
        prompt=str(job["prompt"]),
        model=str(stage["providerModel"]),
        duration_seconds=int(stage["durationSeconds"]),
        max_credits=max_credits,
        seed=int(job["seed"]),
    )


def _higgsfield_spend_scope(job: Mapping[str, Any]) -> dict[str, Any]:
    stage = list(job["productionRecipe"].get("stages") or [])[0]
    args = [
        "video",
        "--stem",
        str(job["jobId"]),
        "--soul-id",
        _CREATOR_SOUL_IDS[str(job["creator"])],
        "--campaign",
        str(job["campaign"]),
        "--cohort-id",
        str(job["jobId"]),
        "--start-image",
        str(job["sourcePath"]),
        "--video-model",
        str(stage["providerModel"]),
        "--video-aspect-ratio",
        "9:16",
        "--video-duration",
        str(stage["durationSeconds"]),
        "--video-mode",
        str(stage["mode"]),
        "--video-sound",
        "off",
    ]
    return build_generate_assets_spend_scope(args, root=Path.cwd())


def _authorize_higgsfield_jobs(
    factory: Any,
    jobs: list[dict[str, Any]],
    *,
    max_total_credits: float,
) -> list[dict[str, Any]]:
    """Quote and authorize the whole batch before the first paid submission."""

    from reel_factory.worker_api import (
        build_higgsfield_production_plan,
        discover_higgsfield_production_capabilities,
        quote_higgsfield_production_plan,
    )

    if not jobs:
        return []
    capabilities = discover_higgsfield_production_capabilities()
    prepared: list[dict[str, Any]] = []
    total = 0.0
    for job in jobs:
        campaign = factory.domains.campaign_by_slug(str(job["campaign"]))
        model_slug = factory.domains.reel_execution.model_slug_for_campaign(
            campaign["id"]
        )
        dirs = factory.domains.campaign_dirs(model_slug, campaign["slug"])
        output = dirs["rendered"] / (
            f"{job['jobId']}_{job['productionRecipe']['modelId']}.mp4"
        )
        review_root = dirs["audits"] / "higgsfield_production"
        candidate = {
            **job,
            "providerOutputPath": str(output),
            "providerReviewRoot": str(review_root),
        }
        request = _higgsfield_request(candidate, max_credits=max_total_credits)
        provider_plan = build_higgsfield_production_plan(
            request,
            capabilities=capabilities,
        )
        quote = quote_higgsfield_production_plan(provider_plan)
        amount = float(quote["amount"])
        total = round(total + amount, 4)
        prepared.append(
            {
                **candidate,
                "quotedProviderCredits": amount,
                "providerPlanFingerprint": provider_plan["requestFingerprint"],
                "_higgsfieldCapabilities": capabilities,
                "_higgsfieldQuote": quote,
                "_campaignId": str(campaign["id"]),
            }
        )
    if total > max_total_credits:
        raise PermissionError(
            "production_batch_quote_exceeds_total_credit_cap: "
            f"{total:.4f} > {max_total_credits:.4f}"
        )
    secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    authorized: list[dict[str, Any]] = []
    for job in prepared:
        scope = _higgsfield_spend_scope(job)
        authorization = issue_provider_spend_authorization(
            factory.conn,
            scope=scope,
            campaign_id=str(job["_campaignId"]),
            max_credits=float(job["quotedProviderCredits"]),
            secret=secret,
            quote_provider=_BoundHiggsfieldQuote(job["_higgsfieldQuote"]),
        )
        authorized.append(
            {
                **job,
                "_higgsfieldSpendScope": scope,
                "_higgsfieldAuthorization": authorization,
            }
        )
    return authorized


def _run_production_job_isolated(
    factory: Any,
    *,
    job: Mapping[str, Any],
    audio_candidates: list[TrendCandidate],
    max_credits_per_job: float,
) -> dict[str, Any]:
    worker_factory = type(factory)(factory.settings)
    try:
        return _run_production_job(
            worker_factory,
            job=job,
            audio_candidates=audio_candidates,
            max_credits_per_job=max_credits_per_job,
        )
    finally:
        worker_factory.close()


def _run_production_job(
    factory: Any,
    *,
    job: Mapping[str, Any],
    audio_candidates: list[TrendCandidate],
    max_credits_per_job: float,
) -> dict[str, Any]:
    base = {"jobId": job["jobId"], "index": job["index"]}
    provider_rows: list[dict[str, Any]] = []
    try:
        result, provider = _execute_higgsfield_provider_job(
            factory,
            job=job,
            max_credits=max_credits_per_job,
        )
        provider_rows.append(provider)
        hard_qc = run_production_hard_qc(job=job, generation_result=result)
        if hard_qc["status"] == "blocked":
            return {
                **base,
                "status": "blocked",
                "error": "production_hard_qc_failed",
                "hardQc": hard_qc,
                "provider": provider,
                "providers": provider_rows,
                "stageResults": [result],
                "result": result,
            }
        audio_fulfillment = fulfill_production_audio(
            factory,
            job=job,
            generation_result=result,
            candidates=audio_candidates,
        )
        result["audioFulfillment"] = audio_fulfillment
        return {
            **base,
            "status": "completed",
            "hardQc": hard_qc,
            "provider": provider,
            "providers": provider_rows,
            "stageResults": [result],
            "result": result,
        }
    except NeedsEmbeddedAudioError as exc:
        return {
            **base,
            "status": "blocked",
            "error": exc.code,
            "attempts": exc.attempts,
            "provider": provider_rows[-1] if provider_rows else None,
            "providers": provider_rows,
            "stageResults": [],
        }
    except Exception as exc:
        return {
            **base,
            "status": "failed",
            "error": str(exc),
            "provider": (
                provider_rows[-1]
                if provider_rows
                else _failed_provider_execution(factory, job)
            ),
            "providers": provider_rows,
            "stageResults": [],
        }


def _execute_higgsfield_provider_job(
    factory: Any,
    *,
    job: Mapping[str, Any],
    max_credits: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from reel_factory.worker_api import execute_higgsfield_production

    from .motion_generation_stage import _register_review_asset

    authorization_value = job.get("_higgsfieldAuthorization")
    scope_value = job.get("_higgsfieldSpendScope")
    capabilities_value = job.get("_higgsfieldCapabilities")
    if not isinstance(authorization_value, dict):
        raise PermissionError("higgsfield_spend_authorization_missing")
    if not isinstance(scope_value, dict):
        raise PermissionError("higgsfield_spend_authorization_missing")
    if not isinstance(capabilities_value, dict):
        raise PermissionError("higgsfield_spend_authorization_missing")
    authorization = authorization_value
    scope = scope_value
    capabilities = capabilities_value
    secret = os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET", "")
    verify_authorization(
        authorization,
        expected_scope=scope,
        secret=secret,
        now=datetime.now(UTC),
    )
    consume_higgsfield_authorization(
        factory.conn, str(authorization["authorizationId"])
    )
    campaign = factory.domains.campaign_by_slug(str(job["campaign"]))
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    pipeline_job = factory.domains.events.create_pipeline_job(
        "higgsfield_motion_generation",
        campaign["id"],
        {
            "jobId": job["jobId"],
            "sourceAssetId": job["sourceAssetId"],
            "sourceSha256": job["sourceSha256"],
            "modelId": job["productionRecipe"]["modelId"],
            "requestFingerprint": job["requestFingerprint"],
            "providerPlanFingerprint": job["providerPlanFingerprint"],
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        request = _higgsfield_request(job, max_credits=max_credits)
        receipt = execute_higgsfield_production(
            request,
            capabilities=capabilities,
            confirm_paid=True,
        )
        output = receipt.get("finalOutput")
        if not isinstance(output, dict):
            raise RuntimeError("higgsfield_final_output_missing")
        output_path = Path(str(output.get("path") or "")).expanduser().resolve()
        output_sha = str(output.get("sha256") or "")
        receipt_path = (
            Path(str(receipt.get("evidencePath") or "")).expanduser().resolve()
        )
        if (
            receipt_path.is_symlink()
            or not receipt_path.is_file()
            or output_path.is_symlink()
            or not output_path.is_file()
            or _sha256_file(output_path) != output_sha
        ):
            raise RuntimeError("higgsfield_provider_evidence_mismatch")
        cost_ids = record_provider_execution(
            factory.conn,
            authorization=authorization,
            execution={
                "events": [
                    {
                        "provider": "higgsfield",
                        "operation": "video_generation",
                        "model": receipt["model"],
                        "jobId": receipt["generationId"],
                        "actualCredits": receipt.get("creditsConsumed"),
                    }
                ]
            },
        )
        provider = {
            "requestId": receipt["generationId"],
            "model": receipt["model"],
            "status": receipt["status"],
            "submittedAt": receipt.get("submittedAt"),
            "completedAt": receipt.get("completedAt"),
            "outputUrl": receipt.get("resultUrl"),
            "outputSha256": output_sha,
            "generationDurationSeconds": receipt.get("generationDurationSeconds"),
            "providerCostCredits": receipt.get("creditsConsumed"),
            "requestFingerprint": job["providerPlanFingerprint"],
            "evidencePath": str(receipt_path),
        }
        paid_evidence = {
            "schema": "campaign_factory.higgsfield_paid_generation_evidence.v1",
            "provider": "higgsfield",
            "authorizationId": authorization["authorizationId"],
            "reservationId": authorization["reservationId"],
            "spendScopeFingerprint": scope["requestFingerprint"],
            "providerPlanFingerprint": job["providerPlanFingerprint"],
            "providerModel": receipt["model"],
            "generationId": receipt["generationId"],
            "soulId": receipt["soulId"],
            "seed": job["seed"],
            "quote": receipt["creditQuote"],
            "creditsConsumed": receipt.get("creditsConsumed"),
            "costEventIds": cost_ids,
            "source": receipt["source"],
            "output": {"path": str(output_path), "sha256": output_sha},
            "providerReceipt": {
                "path": str(receipt_path),
                "sha256": _sha256_file(receipt_path),
            },
        }
        worker_result = {
            "schema": "reel_factory.higgsfield_motion_generation.v1",
            "backend": "higgsfield_cli",
            "paidGeneration": True,
            "providerCalls": 1,
            "paidGenerationEvidence": paid_evidence,
            "result": {
                "predictionId": receipt["generationId"],
                "providerModel": receipt["model"],
                "status": receipt["status"],
                "outputSha256": output_sha,
                "requestFingerprint": job["providerPlanFingerprint"],
                "evidencePath": str(receipt_path),
                "audio": {"mode": "none"},
            },
        }
        registered = _register_review_asset(
            factory,
            campaign=campaign,
            source_asset_id=str(job["sourceAssetId"]),
            model_slug=model_slug,
            model_id=str(job["productionRecipe"]["modelId"]),
            source_path=Path(str(job["sourcePath"])).resolve(),
            source_hash=str(job["sourceSha256"]),
            output_path=output_path,
            worker_result=worker_result,
            paid=True,
            motion_task="image_to_video",
            request_fingerprint=str(job["requestFingerprint"]),
            production_motion_recipe=job["productionRecipe"],
            prompt=str(job["prompt"]),
            audio_policy=str(job["audioPolicy"]),
            pipeline_job_id=str(pipeline_job["id"]),
        )
        result = {
            "schema": "campaign_factory.motion_generation_stage_run.v1",
            "campaign": job["campaign"],
            "modelId": job["productionRecipe"]["modelId"],
            "dryRun": False,
            "apply": True,
            "paidGeneration": True,
            "providerCalls": 1,
            "worker": worker_result,
            "registeredAsset": registered,
            "pipelineJobId": pipeline_job["id"],
            "humanReviewRequired": False,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
        factory.domains.events.finish_pipeline_job(pipeline_job["id"], result)
        return result, provider
    except Exception as exc:
        factory.domains.events.fail_pipeline_job(
            pipeline_job["id"],
            str(exc),
            {"jobId": job["jobId"], "provider": "higgsfield"},
        )
        raise


def _provider_execution(generation_result: Mapping[str, Any]) -> dict[str, Any] | None:
    stage = _motion_stage_result(dict(generation_result))
    worker = stage.get("worker")
    worker = worker if isinstance(worker, dict) else {}
    execution = worker.get("result")
    if not isinstance(execution, dict) or not execution.get("predictionId"):
        return None
    return _provider_receipt_summary(execution)


def _provider_receipt_summary(
    execution: Mapping[str, Any], *, evidence_path: Path | None = None
) -> dict[str, Any]:
    return {
        "requestId": execution.get("predictionId"),
        "model": execution.get("providerModel"),
        "status": execution.get("status"),
        "submittedAt": execution.get("submittedAt"),
        "completedAt": execution.get("completedAt"),
        "outputUrl": execution.get("outputUrl"),
        "outputSha256": execution.get("outputSha256"),
        "outputRecords": execution.get("outputRecords") or [],
        "generationDurationSeconds": execution.get("generationDurationSeconds"),
        "providerInferenceMilliseconds": execution.get("providerInferenceMilliseconds"),
        "providerCostUsd": execution.get("providerCostUsd"),
        "requestFingerprint": execution.get("requestFingerprint"),
        "evidencePath": execution.get("evidencePath")
        or (str(evidence_path) if evidence_path is not None else None),
    }


def _failed_provider_execution(
    factory: Any, job: Mapping[str, Any]
) -> dict[str, Any] | None:
    try:
        review_root_value = str(job.get("providerReviewRoot") or "").strip()
        if review_root_value:
            review_root = Path(review_root_value).expanduser()
            receipt_dir = review_root.resolve() / "receipts"
            higgsfield_matches: list[dict[str, Any]] = []
            for path in receipt_dir.glob("*.higgsfield_submission.json"):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    receipt = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(receipt, dict) and receipt.get(
                    "requestFingerprint"
                ) == job.get("providerPlanFingerprint"):
                    higgsfield_matches.append(receipt)
            if len(higgsfield_matches) == 1:
                receipt = higgsfield_matches[0]
                final = receipt.get("finalOutput")
                final = final if isinstance(final, dict) else {}
                return {
                    "requestId": receipt.get("generationId"),
                    "model": receipt.get("model"),
                    "status": receipt.get("status"),
                    "submittedAt": receipt.get("submittedAt"),
                    "completedAt": receipt.get("completedAt"),
                    "outputSha256": final.get("sha256"),
                    "generationDurationSeconds": receipt.get(
                        "generationDurationSeconds"
                    ),
                    "providerCostCredits": receipt.get("creditsConsumed"),
                    "requestFingerprint": receipt.get("requestFingerprint"),
                    "evidencePath": receipt.get("evidencePath"),
                }
        campaign = factory.domains.campaign_by_slug(str(job["campaign"]))
        model_slug = factory.domains.reel_execution.model_slug_for_campaign(
            campaign["id"]
        )
        evidence_dir = (
            factory.domains.campaign_dirs(model_slug, campaign["slug"])["audits"]
            / "motion_generation"
        )
        prompt_sha = hashlib.sha256(
            " ".join(str(job["prompt"]).split()).encode("utf-8")
        ).hexdigest()
        stages = list(job["productionRecipe"].get("stages") or [])
        expected_provider_model = (
            str(stages[0].get("providerModel") or "") if stages else ""
        )
        wavespeed_matches: list[tuple[dict[str, Any], Path]] = []
        for path in evidence_dir.glob("*.wavespeed_submission.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, dict):
                continue
            if (
                receipt.get("creator") == job.get("creator")
                and receipt.get("intent") == job.get("intent")
                and receipt.get("sourceSha256") == job.get("sourceSha256")
                and receipt.get("expandedPromptSha256") == prompt_sha
                and receipt.get("providerModel") == expected_provider_model
                and (
                    receipt.get("requestIdentitySeed") == job.get("seed")
                    or receipt.get("seed") == job.get("seed")
                )
                and receipt.get("predictionId")
            ):
                wavespeed_matches.append((receipt, path))
        if len(wavespeed_matches) != 1:
            return None
        receipt, path = wavespeed_matches[0]
        return _provider_receipt_summary(receipt, evidence_path=path)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None


def _optional_safe_media(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    expanded = Path(path).expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is missing: {resolved}")
    return resolved


def _source_image_resolution(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        return None
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


def run_production_hard_qc(
    *, job: Mapping[str, Any], generation_result: dict[str, Any]
) -> dict[str, Any]:
    blockers: list[str] = []
    source_path = Path(str(job["sourcePath"])).expanduser().resolve()
    if (
        source_path.is_symlink()
        or not source_path.is_file()
        or _sha256_file(source_path) != job["sourceSha256"]
    ):
        blockers.append("source_substitution")
    stage = _motion_stage_result(generation_result)
    registered = stage.get("registeredAsset")
    if not isinstance(registered, dict):
        blockers.append("unreadable_or_corrupt_media")
        return _hard_qc_receipt(job, blockers=blockers, output_sha256=None, probe=None)
    output = Path(str(registered.get("output_path") or "")).expanduser()
    output_sha: str | None = None
    probe: dict[str, Any] | None = None
    if output.is_symlink() or not output.resolve().is_file():
        blockers.append("unreadable_or_corrupt_media")
    else:
        output = output.resolve()
        try:
            output_sha = _sha256_file(output)
            if output_sha != str(registered.get("content_hash") or ""):
                blockers.append("source_substitution")
            probe = _probe_production_video(output)
            if probe["durationSeconds"] <= 0 or probe["durationSeconds"] > 60:
                blockers.append("invalid_duration_or_codec")
            if probe["codec"] not in {"h264", "hevc", "av1", "vp9"}:
                blockers.append("invalid_duration_or_codec")
            ratio = probe["width"] / probe["height"]
            if not 0.50 <= ratio <= 0.65:
                blockers.append("invalid_duration_or_codec")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            blockers.append("unreadable_or_corrupt_media")
    provider = _provider_execution(generation_result)
    if provider is not None:
        stages = list(job["productionRecipe"].get("stages") or [])
        expected_model = str(stages[-1].get("providerModel") or "") if stages else None
        if (
            provider.get("model") != expected_model
            or provider.get("outputSha256") != output_sha
            or provider.get("requestFingerprint") is None
        ):
            blockers.append("source_substitution")
    return _hard_qc_receipt(
        job, blockers=blockers, output_sha256=output_sha, probe=probe
    )


def _hard_qc_receipt(
    job: Mapping[str, Any],
    *,
    blockers: list[str],
    output_sha256: str | None,
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    unique_blockers = sorted(set(blockers))
    receipt = {
        "schema": "campaign_factory.production_hard_qc.v1",
        "jobId": job["jobId"],
        "sourceSha256": job["sourceSha256"],
        "outputSha256": output_sha256,
        "checks": {
            "sourceBinding": "failed"
            if "source_substitution" in unique_blockers
            else "passed",
            "mediaIntegrity": (
                "failed"
                if {
                    "unreadable_or_corrupt_media",
                    "invalid_duration_or_codec",
                }.intersection(unique_blockers)
                else "passed"
            ),
            "identityAndAnatomy": "not_reported_by_available_analyzers",
        },
        "probe": probe,
        "blockers": unique_blockers,
        "status": "blocked" if unique_blockers else "passed",
    }
    return {**receipt, "receiptFingerprint": _fingerprint(receipt)}
