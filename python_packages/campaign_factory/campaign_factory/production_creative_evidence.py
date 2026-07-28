"""Small evidence helpers used by the existing production lane."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .production_compatibility import assess_source_compatibility
from .production_prompts import (
    build_creative_direction_prompt_card,
    compile_passive_prompt_card,
)


def prepare_source_creative_evidence(source: dict[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(str(source.get("metadata_json") or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    source["metadata"] = metadata if isinstance(metadata, dict) else {}
    source["compatibility"] = assess_source_compatibility(source)
    return source


def build_job_creative_evidence(
    *,
    creator: str,
    intent: str,
    source: dict[str, Any],
    selected_prompt: str,
    learning_decision: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    card = build_creative_direction_prompt_card(
        creator=creator,
        intent=intent,
        source=source,
        observed_facts=source["compatibility"]["observedFacts"],
        reference_pattern_id=(
            str(learning_decision.get("finalSelectedPattern") or "") or None
        ),
    )
    return card, compile_passive_prompt_card(card, base_prompt=selected_prompt)


def persist_asset_creative_evidence(
    conn: Any,
    *,
    registered: dict[str, Any],
    job: Mapping[str, Any],
) -> None:
    metadata = json.loads(str(registered.get("metadata_json") or "{}"))
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update(
        {
            "contentIntent": job["intent"],
            "promptCard": job["promptCard"],
            "compiledPrompt": job["compiledPrompt"],
            "compatibility": job["compatibility"],
            **(
                {
                    "referenceVideo": job["referenceVideo"],
                    "recreationCharacterCompatibility": job.get(
                        "recreationCharacterCompatibility"
                    ),
                }
                if job.get("referenceVideo")
                else {}
            ),
        }
    )
    conn.execute(
        "UPDATE rendered_assets SET metadata_json = ? WHERE id = ?",
        (json.dumps(metadata, sort_keys=True, separators=(",", ":")), registered["id"]),
    )
    conn.commit()
    registered["metadata_json"] = json.dumps(metadata, sort_keys=True)


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
                " ".join(original_prompt.split()).encode()
            ).hexdigest(),
            "expandedPromptSha256": hashlib.sha256(
                expanded_prompt.encode()
            ).hexdigest(),
            "promptExpansion": dict(expansion),
        }
    )
    return {**core, "recipeFingerprint": _fingerprint(core)}


def expand_production_job_prompt(job: Mapping[str, Any]) -> dict[str, Any]:
    from reel_factory.worker_api import expand_local_wan_i2v_prompt

    source = Path(str(job["sourcePath"])).expanduser().resolve()
    compiled_text = str(
        dict(job.get("compiledPrompt") or {}).get("text") or job["prompt"]
    )
    expansion = expand_local_wan_i2v_prompt(
        image_path=source,
        original_prompt=compiled_text,
    )
    expanded_prompt = " ".join(str(expansion.get("expandedPrompt") or "").split())
    recipe = bind_production_prompt_expansion(
        job["productionRecipe"],
        original_prompt=compiled_text,
        expansion=expansion,
    )
    return {
        **dict(job),
        "originalPrompt": compiled_text,
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
