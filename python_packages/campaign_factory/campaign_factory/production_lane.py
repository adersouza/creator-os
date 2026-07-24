from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .generation_workflow import run_generation_workflow

SCHEMA: Final = "campaign_factory.production_motion_recipe.v1"
BATCH_SCHEMA: Final = "campaign_factory.production_batch.v1"

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
}

_PRODUCTION_MODELS: Final[dict[str, tuple[str, str]]] = {
    "local": ("local_wan", "local_wan22_ti2v_5b_mlx"),
    "cloud": ("best_motion", "wavespeed_wan27_i2v_pro"),
}


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_production_motion_recipe(
    *,
    creator: str,
    intent: str,
    execution: str,
    source_sha256: str,
) -> dict[str, Any]:
    try:
        mode, model_id = _PRODUCTION_MODELS[execution]
    except KeyError as exc:
        raise ValueError("execution must be local or cloud") from exc
    if intent not in _INTENT_PROMPTS:
        raise ValueError(f"intent {intent!r} is not in the production motion catalog")
    core = {
        "schema": SCHEMA,
        "recipeId": f"{execution}_wan_creator_motion_v1",
        "status": "active",
        "creator": creator.strip().lower(),
        "intent": intent,
        "mode": mode,
        "modelId": model_id,
        "sourceSha256": source_sha256,
        "paidProviderFallbackAllowed": False,
        "researchSelectionRequired": False,
    }
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


def plan_production_batch(
    factory: Any,
    *,
    creator: str,
    intent: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
) -> dict[str, Any]:
    if isinstance(count, bool) or not 1 <= int(count) <= 100:
        raise ValueError("count must be between 1 and 100")
    creator_slug = creator.strip().lower().replace(" ", "_")
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
    sources = [
        dict(row)
        for row in rows
        if Path(str(row["stored_path"])).expanduser().resolve().is_file()
    ]
    if not sources:
        raise ValueError(f"no usable approved image inventory for creator {creator}")
    jobs: list[dict[str, Any]] = []
    for index in range(int(count)):
        source = sources[index % len(sources)]
        source_sha = str(source["content_hash"])
        seed = int(
            hashlib.sha256(
                f"{creator_slug}:{intent}:{index}:{source_sha}".encode()
            ).hexdigest()[:8],
            16,
        )
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
                "prompt": _INTENT_PROMPTS[intent],
                "seed": seed,
                "accountGroup": accounts,
                "audioPreference": audio_preference,
                "productionRecipe": recipe,
            }
        )
    return {
        "schema": BATCH_SCHEMA,
        "creator": creator_slug,
        "intent": intent,
        "execution": execution,
        "requested": int(count),
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
) -> dict[str, Any]:
    plan = plan_production_batch(
        factory,
        creator=creator,
        intent=intent,
        count=count,
        execution=execution,
        accounts=accounts,
        audio_preference=audio_preference,
    )
    results: list[dict[str, Any]] = []
    if apply and execution == "cloud":
        raise PermissionError(
            "cloud production apply requires configured paid-spend authorization"
        )
    for job in plan["jobs"]:
        if not apply:
            results.append({"jobId": job["jobId"], "status": "created"})
            continue
        try:
            result = run_generation_workflow(
                factory,
                mode=job["productionRecipe"]["mode"],
                campaign_slug=job["campaign"],
                accepted_still_path=Path(job["sourcePath"]),
                motion_prompt=job["prompt"],
                motion_model_id=job["productionRecipe"]["modelId"],
                production_motion_recipe=job["productionRecipe"],
                seed=job["seed"],
                audio_policy=audio_preference,
                dry_run=False,
                apply=True,
            )
            results.append(
                {"jobId": job["jobId"], "status": "completed", "result": result}
            )
        except Exception as exc:
            results.append(
                {"jobId": job["jobId"], "status": "failed", "error": str(exc)}
            )
    statuses = [item["status"] for item in results]
    output_hashes = {
        str(((item.get("result") or {}).get("result") or {}).get("outputSha256"))
        for item in results
        if ((item.get("result") or {}).get("result") or {}).get("outputSha256")
    }
    return {
        **plan,
        "apply": apply,
        "results": results,
        "summary": {
            "requested": plan["requested"],
            "created": len(results),
            "completed": statuses.count("completed"),
            "blocked": statuses.count("blocked"),
            "failed": statuses.count("failed"),
            "approved": 0,
            "scheduled": 0,
            "published": 0,
            "uniqueOutputs": len(output_hashes),
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
