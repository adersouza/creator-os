from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_text

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
from .generation_workflow import run_generation_workflow

SCHEMA: Final = "campaign_factory.production_motion_recipe.v1"
BATCH_SCHEMA: Final = "campaign_factory.production_batch.v1"
DEFAULT_CLOUD_BATCH_MAX_USD: Final = 0.25
DEFAULT_CLOUD_CONCURRENCY: Final = 2

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

_CLOUD_INTENT_STAGES: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    intent: (
        {
            "modelId": "wavespeed_kling_o3_pro_i2v",
            "providerModel": "kwaivgi/kling-video-o3-pro/image-to-video",
            "task": "image_to_video",
            "resolution": "provider_default",
            "durationSeconds": 5,
            "estimatedCostUsd": 0.56,
        },
    )
    for intent in (
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    )
}
_CLOUD_INTENT_STAGES.update(
    {
        "motion_copy": (
            {
                "modelId": "wavespeed_kling_v3_pro_motion_control",
                "providerModel": "kwaivgi/kling-v3.0-pro/motion-control",
                "task": "motion_control",
                "resolution": "provider_default",
                "durationSeconds": None,
            },
        ),
        "dance": (
            {
                "modelId": "wavespeed_kling_v3_pro_motion_control",
                "providerModel": "kwaivgi/kling-v3.0-pro/motion-control",
                "task": "motion_control",
                "resolution": "provider_default",
                "durationSeconds": None,
            },
        ),
        "talking_selfie": (
            {
                "modelId": "wavespeed_infinitetalk",
                "providerModel": "wavespeed-ai/infinitetalk",
                "task": "audio_image_to_video",
                "resolution": "720p",
                "durationSeconds": None,
            },
        ),
        "talking_motion_copy": (
            {
                "modelId": "wavespeed_kling_v3_pro_motion_control",
                "providerModel": "kwaivgi/kling-v3.0-pro/motion-control",
                "task": "motion_control",
                "resolution": "provider_default",
                "durationSeconds": None,
            },
            {
                "modelId": "wavespeed_sync_lipsync2_pro",
                "providerModel": "sync/lipsync-2-pro",
                "task": "video_lipsync",
                "resolution": "source",
                "durationSeconds": None,
            },
        ),
    }
)
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
    if execution == "cloud":
        mode = "best_motion"
        try:
            stages = _CLOUD_INTENT_STAGES[intent]
        except KeyError as exc:
            raise ValueError(
                f"intent {intent!r} has no cloud production recipe"
            ) from exc
        model_id = str(stages[0]["modelId"])
    else:
        raise ValueError("production create now requires WaveSpeed cloud execution")
    core = {
        "schema": SCHEMA,
        "recipeId": f"{execution}_{intent}_creator_motion_v2",
        "status": "active",
        "creator": creator.strip().lower(),
        "intent": intent,
        "mode": mode,
        "modelId": model_id,
        "stages": [dict(stage) for stage in stages],
        "sourceSha256": source_sha256,
        "paidProviderFallbackAllowed": False,
        "researchSelectionRequired": False,
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
        or core.get("status") != "active"
        or core.get("modelId") != model_id
        or core.get("sourceSha256") != source_sha256
        or core.get("researchSelectionRequired") is not False
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
    if execution != "cloud":
        raise ValueError("production create now requires --execution cloud")
    speech_sha = _sha256_file(speech_audio) if speech_audio is not None else None
    motion_reference_sha = (
        _sha256_file(motion_reference) if motion_reference is not None else None
    )
    per_job_estimate = (
        _estimate_cloud_job_cost(
            intent,
            speech_audio=speech_audio,
            motion_reference=motion_reference,
        )
        if execution == "cloud"
        else 0.0
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
                "estimatedProviderCostUsd": per_job_estimate,
                "productionRecipe": recipe,
            }
        )
    return {
        "schema": BATCH_SCHEMA,
        "creator": creator_slug,
        "intent": intent,
        "execution": execution,
        "requested": int(count),
        "maxConcurrency": DEFAULT_CLOUD_CONCURRENCY if execution == "cloud" else 1,
        "estimatedProviderCostUsd": (
            round(int(count) * per_job_estimate, 4) if execution == "cloud" else 0.0
        ),
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
    max_total_usd: float = DEFAULT_CLOUD_BATCH_MAX_USD,
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
    if execution == "cloud":
        if (
            isinstance(max_total_usd, bool)
            or not isinstance(max_total_usd, (int, float))
            or not math.isfinite(float(max_total_usd))
            or float(max_total_usd) <= 0
        ):
            raise ValueError("cloud production requires a finite positive batch cap")
        if apply and plan["estimatedProviderCostUsd"] > float(max_total_usd):
            raise PermissionError(
                "production_batch_quote_exceeds_total_spend_cap: "
                f"{plan['estimatedProviderCostUsd']:.2f} > {float(max_total_usd):.2f}"
            )
    if isinstance(max_concurrency, bool) or not 1 <= int(max_concurrency) <= 4:
        raise ValueError("production concurrency must be between 1 and 4")
    plan["maxConcurrency"] = min(int(max_concurrency), plan["requested"])
    plan["maxTotalUsd"] = float(max_total_usd) if execution == "cloud" else 0.0
    plan["paidGenerationAuthorized"] = bool(
        apply
        and execution == "cloud"
        and plan["estimatedProviderCostUsd"] <= max_total_usd
    )
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
            max_workers=workers, thread_name_prefix="creator-os-wavespeed"
        ) as executor:
            futures = {
                executor.submit(
                    _run_production_job_isolated,
                    factory,
                    job=job,
                    audio_candidates=audio_candidates,
                    max_usd_per_job=float(job["estimatedProviderCostUsd"]),
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
                    max_usd_per_job=float(job["estimatedProviderCostUsd"]),
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


def _run_production_job_isolated(
    factory: Any,
    *,
    job: Mapping[str, Any],
    audio_candidates: list[TrendCandidate],
    max_usd_per_job: float,
) -> dict[str, Any]:
    worker_factory = type(factory)(factory.settings)
    try:
        return _run_production_job(
            worker_factory,
            job=job,
            audio_candidates=audio_candidates,
            max_usd_per_job=max_usd_per_job,
        )
    finally:
        worker_factory.close()


def _run_production_job(
    factory: Any,
    *,
    job: Mapping[str, Any],
    audio_candidates: list[TrendCandidate],
    max_usd_per_job: float,
) -> dict[str, Any]:
    base = {"jobId": job["jobId"], "index": job["index"]}
    stage_results: list[dict[str, Any]] = []
    provider_rows: list[dict[str, Any]] = []
    try:
        cloud = str(job["productionRecipe"]["mode"]) == "best_motion"
        if cloud:
            stages = list(job["productionRecipe"].get("stages") or [])
            if not stages:
                raise RuntimeError("cloud production recipe stages are missing")
        else:
            stages = [
                {
                    "modelId": job["productionRecipe"]["modelId"],
                    "task": "image_to_video",
                    "resolution": None,
                    "durationSeconds": None,
                }
            ]
        prior_video: Path | None = None
        result: dict[str, Any] | None = None
        for stage_index, stage in enumerate(stages):
            task = str(stage["task"])
            stage_recipe = (
                dict(job["productionRecipe"])
                if stage_index == 0
                else _production_followup_stage_recipe(
                    job,
                    stage=stage,
                    stage_index=stage_index,
                    source_video=_required_stage_output(prior_video),
                )
            )
            result = run_generation_workflow(
                factory,
                mode=job["productionRecipe"]["mode"],
                campaign_slug=job["campaign"],
                accepted_still_path=(
                    None if task == "video_lipsync" else Path(str(job["sourcePath"]))
                ),
                source_video_path=prior_video if task == "video_lipsync" else None,
                motion_reference_video_paths=(
                    (Path(str(job["motionReferencePath"])),)
                    if task == "motion_control"
                    else ()
                ),
                audio_path=(
                    Path(str(job["speechAudioPath"]))
                    if task in {"audio_image_to_video", "video_lipsync"}
                    else None
                ),
                motion_prompt=str(job["prompt"]),
                motion_model_id=str(stage["modelId"]),
                motion_task=task,
                production_motion_recipe=stage_recipe,
                seed=int(job["seed"]),
                duration_seconds=stage.get("durationSeconds"),
                resolution=stage.get("resolution"),
                audio_policy=(
                    "creator_voice"
                    if task in {"audio_image_to_video", "video_lipsync"}
                    else (
                        "silent_allowed" if len(stages) > 1 else str(job["audioPolicy"])
                    )
                ),
                audio_selected_reason=(
                    "intermediate motion-control stage before creator-voice lipsync"
                    if len(stages) > 1 and task == "motion_control"
                    else None
                ),
                workspace=Path.cwd(),
                paid_confirmation=cloud,
                max_usd=(
                    _stage_cost_cap(job, stage_index=stage_index) if cloud else None
                ),
                dry_run=False,
                apply=True,
            )
            stage_results.append(result)
            provider = _provider_execution(result)
            if provider is not None:
                provider_rows.append(provider)
            prior_video = _registered_output_path(result)
        if result is None:  # pragma: no cover - guarded by recipe validation
            raise RuntimeError("production recipe produced no stage")
        hard_qc = run_production_hard_qc(job=job, generation_result=result)
        provider = provider_rows[-1] if provider_rows else None
        if hard_qc["status"] == "blocked":
            return {
                **base,
                "status": "blocked",
                "error": "production_hard_qc_failed",
                "hardQc": hard_qc,
                "provider": provider,
                "providers": provider_rows,
                "stageResults": stage_results,
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
            "stageResults": stage_results,
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
            "stageResults": stage_results,
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
            "stageResults": stage_results,
        }


def _required_stage_output(path: Path | None) -> Path:
    if path is None:
        raise RuntimeError("production prior stage output is missing")
    return path


def _registered_output_path(generation_result: Mapping[str, Any]) -> Path:
    stage = _motion_stage_result(dict(generation_result))
    registered = stage.get("registeredAsset")
    if not isinstance(registered, dict):
        raise RuntimeError("production stage registered asset is missing")
    path = Path(str(registered.get("output_path") or "")).expanduser()
    if path.is_symlink():
        raise RuntimeError("production stage registered asset is unsafe")
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError("production stage output is missing")
    return resolved


def _production_followup_stage_recipe(
    job: Mapping[str, Any],
    *,
    stage: Mapping[str, Any],
    stage_index: int,
    source_video: Path,
) -> dict[str, Any]:
    source_sha = _sha256_file(source_video)
    original = dict(job["productionRecipe"])
    core = {
        key: value
        for key, value in original.items()
        if key
        not in {
            "recipeFingerprint",
            "originalPromptSha256",
            "expandedPromptSha256",
            "promptExpansion",
        }
    }
    core.update(
        {
            "recipeId": f"{original['recipeId']}_stage_{stage_index + 1}",
            "modelId": stage["modelId"],
            "stages": [dict(stage)],
            "sourceSha256": source_sha,
            "originalPromptSha256": hashlib.sha256(
                " ".join(
                    str(job.get("originalPrompt") or job["prompt"]).split()
                ).encode("utf-8")
            ).hexdigest(),
            "expandedPromptSha256": hashlib.sha256(
                " ".join(str(job["prompt"]).split()).encode("utf-8")
            ).hexdigest(),
            "promptExpansion": dict(job.get("promptExpansion") or {}),
        }
    )
    return {**core, "recipeFingerprint": _fingerprint(core)}


def _stage_cost_cap(job: Mapping[str, Any], *, stage_index: int) -> float:
    stages = list(job["productionRecipe"].get("stages") or [])
    if len(stages) == 1:
        return float(job["estimatedProviderCostUsd"])
    speech = _optional_safe_media(
        Path(str(job["speechAudioPath"])) if job.get("speechAudioPath") else None,
        "speech audio",
    )
    reference = _optional_safe_media(
        (
            Path(str(job["motionReferencePath"]))
            if job.get("motionReferencePath")
            else None
        ),
        "motion reference video",
    )
    if stage_index == 0:
        assert reference is not None
        return round(
            max(3.0, _media_duration_seconds(reference, "motion reference")) * 0.168, 4
        )
    assert speech is not None
    return round(_media_duration_seconds(speech, "speech audio") * 0.08, 4)


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
        matches: list[tuple[dict[str, Any], Path]] = []
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
                matches.append((receipt, path))
        if len(matches) != 1:
            return None
        receipt, path = matches[0]
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


def _media_duration_seconds(path: Path, label: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe_missing")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise ValueError(f"{label} duration could not be measured") from exc
    if completed.returncode != 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"{label} duration could not be measured")
    return round(duration, 3)


def _estimate_cloud_job_cost(
    intent: str,
    *,
    speech_audio: Path | None,
    motion_reference: Path | None,
) -> float:
    if intent in {
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    }:
        return 0.56
    speech_duration = (
        _media_duration_seconds(speech_audio, "speech audio")
        if speech_audio is not None
        else 0.0
    )
    reference_duration = (
        _media_duration_seconds(motion_reference, "motion reference video")
        if motion_reference is not None
        else 0.0
    )
    if intent == "talking_selfie":
        if speech_duration > 600:
            raise ValueError("InfiniteTalk speech audio exceeds 600 seconds")
        return round(max(5.0, speech_duration) * 0.06, 4)
    if intent in {"motion_copy", "dance"}:
        if not 3 <= reference_duration <= 30:
            raise ValueError("Kling motion reference must be 3 to 30 seconds")
        return round(max(3.0, reference_duration) * 0.168, 4)
    if intent == "talking_motion_copy":
        if not 3 <= reference_duration <= 30:
            raise ValueError("Kling motion reference must be 3 to 30 seconds")
        if speech_duration > 600:
            raise ValueError("Sync speech audio exceeds 600 seconds")
        return round(
            max(3.0, reference_duration) * 0.168 + speech_duration * 0.08,
            4,
        )
    raise ValueError(f"intent {intent!r} has no cloud pricing recipe")


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


def _probe_production_video(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe_missing")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("production_video_ffprobe_failed")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        video = next(
            stream
            for stream in streams
            if int(stream.get("width") or 0) > 0 and int(stream.get("height") or 0) > 0
        )
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
        raise RuntimeError("production_video_ffprobe_invalid") from exc
    return {
        "codec": str(video.get("codec_name") or ""),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "durationSeconds": round(duration, 3),
    }


def _block_duplicate_provider_outputs(results: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for item in results:
        provider = item.get("provider")
        digest = (
            str(provider.get("outputSha256") or "")
            if isinstance(provider, dict)
            else ""
        )
        if not digest:
            continue
        if digest in seen:
            item["status"] = "blocked"
            item["error"] = "duplicate_provider_output"
            hard_qc = item.get("hardQc")
            if isinstance(hard_qc, dict):
                hard_qc["blockers"] = sorted(
                    set(hard_qc.get("blockers") or []).union({"duplicate_output"})
                )
                hard_qc["status"] = "blocked"
                unsigned = {
                    key: value
                    for key, value in hard_qc.items()
                    if key != "receiptFingerprint"
                }
                hard_qc["receiptFingerprint"] = _fingerprint(unsigned)
        else:
            seen.add(digest)


def _finalize_production_batch(
    plan: dict[str, Any], results: list[dict[str, Any]], *, apply: bool
) -> dict[str, Any]:
    statuses = [str(item.get("status") or "") for item in results]
    final_provider_rows = [
        item["provider"] for item in results if isinstance(item.get("provider"), dict)
    ]
    provider_rows = [
        provider
        for item in results
        for provider in (
            item.get("providers")
            if isinstance(item.get("providers"), list)
            else ([item["provider"]] if isinstance(item.get("provider"), dict) else [])
        )
        if isinstance(provider, dict)
    ]
    raw_hashes = {
        str(provider.get("outputSha256"))
        for provider in final_provider_rows
        if provider.get("outputSha256")
    }
    final_hashes = {
        digest
        for item in results
        if item.get("status") == "completed"
        and (
            digest := str(
                ((item.get("result") or {}).get("audioFulfillment") or {}).get(
                    "finalVideoSha256"
                )
                or (
                    _motion_stage_result(item.get("result") or {}).get(
                        "registeredAsset"
                    )
                    or {}
                ).get("content_hash")
                or ""
            )
        )
    }
    costs = [provider.get("providerCostUsd") for provider in provider_rows]
    costs_reported = bool(provider_rows) and all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in costs
    )
    return {
        **plan,
        "apply": apply,
        "results": results,
        "summary": {
            "requested": plan["requested"],
            "created": len(results),
            "submitted": len(provider_rows),
            "jobsSubmitted": len(final_provider_rows),
            "completed": statuses.count("completed"),
            "blocked": statuses.count("blocked"),
            "failed": statuses.count("failed"),
            "approved": statuses.count("completed"),
            "scheduled": 0,
            "published": 0,
            "uniqueOutputs": len(raw_hashes or final_hashes),
            "uniqueFinalOutputs": len(final_hashes),
            "totalProviderCostUsd": (
                round(sum(float(value) for value in costs), 4)
                if costs_reported
                else None
            ),
            "providerCostReported": costs_reported,
            "estimatedProviderCostUsd": plan["estimatedProviderCostUsd"],
            "generationTimesSeconds": [
                provider.get("generationDurationSeconds") for provider in provider_rows
            ],
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
