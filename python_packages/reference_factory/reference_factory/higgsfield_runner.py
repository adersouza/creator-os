from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reel_factory.higgsfield_cost_preflight import (
    BalanceProvider,
    cancel_higgsfield_spend_reservation,
    consume_higgsfield_spend_reservation,
    reserve_higgsfield_spend,
)

from .fileops import atomic_write_text

DEFAULT_STACEY_SOUL_ID = "5828d958-91dd-4d6d-8909-934503f47644"
DEFAULT_SOUL_IDS = {
    "stacey": DEFAULT_STACEY_SOUL_ID,
    DEFAULT_STACEY_SOUL_ID: DEFAULT_STACEY_SOUL_ID,
}
DEFAULT_IMAGE_MODEL = "text2image_soul_v2"
DEFAULT_VIDEO_MODEL = "kling3_0"
DEFAULT_VARIATION_MODEL = "grok_image"
DEFAULT_VARIATION_LAYOUT = "2x3"
DEFAULT_VARIATION_STRATEGY = "individual"
DEFAULT_SOUL_GRID_ASPECT_RATIO = "3:2"
DEFAULT_VARIATION_VIDEO_SECONDS = 5
DEFAULT_IMAGE_CREDITS = 0.12
DEFAULT_VIDEO_CREDITS = 7.5
DEFAULT_VARIATION_CREDITS = 1.0
DEFAULT_PANEL_VIDEO_CREDITS = DEFAULT_VIDEO_CREDITS
MIN_REFERENCE_BYTES = 100_000
MIN_RESULT_BYTES = 1
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60 * 30
DEFAULT_PROMPT_SCORE_THRESHOLD = 72
BLOCKED_PROVIDER_STATUSES = {
    "blocked",
    "moderated",
    "moderation_blocked",
    "nsfw",
    "rejected",
    "safety_blocked",
}
FAILED_PROVIDER_STATUSES = {"failed", "error", "cancelled", "canceled", "timeout"}


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PromptPair:
    reference_id: str
    image_prompt: dict[str, Any]
    video_prompt: dict[str, Any]


def generate_with_higgsfield(
    *,
    data_root: Path,
    limit: int = 1,
    reference_id: str | None = None,
    soul_id: str = "Stacey",
    kling_mode: str = "std",
    wait: bool = False,
    dry_run: bool = False,
    max_credits: float | None = 8.0,
    estimated_cost_usd: float | None = None,
    no_video: bool = False,
    no_campaign_intake: bool = False,
    image_candidates: int = 1,
    variation_grid: bool = False,
    variation_model: str = DEFAULT_VARIATION_MODEL,
    variation_layout: str = DEFAULT_VARIATION_LAYOUT,
    variation_strategy: str = DEFAULT_VARIATION_STRATEGY,
    animate_variation_panels: bool = False,
    variation_panel_dir: Path | None = None,
    selected_image: Path | None = None,
    campaign_factory_root: Path | None = None,
    campaign: str | None = None,
    model: str | None = None,
    creative_plan: str | None = None,
    min_prompt_score: int | None = DEFAULT_PROMPT_SCORE_THRESHOLD,
    balance_provider: BalanceProvider | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    _validate_generation_budget_inputs(
        limit=limit,
        image_candidates=image_candidates,
        max_credits=max_credits,
        estimated_cost_usd=estimated_cost_usd,
    )
    pairs = load_prompt_pairs(
        data_root=data_root, limit=limit, reference_id=reference_id
    )
    scored_pairs = [(pair, score_prompt_pair(pair)) for pair in pairs]
    runnable = [
        pair
        for pair, score in scored_pairs
        if min_prompt_score is None or int(score["score"]) >= min_prompt_score
    ]
    blocked = [
        {"referenceId": pair.reference_id, "promptScore": score}
        for pair, score in scored_pairs
        if min_prompt_score is not None and int(score["score"]) < min_prompt_score
    ]
    estimated = estimate_credits(
        len(runnable),
        no_video=no_video,
        image_candidates=image_candidates,
        variation_grid=variation_grid,
        variation_strategy=variation_strategy,
        variation_layout=variation_layout,
        animate_variation_panels=animate_variation_panels,
        selected_image_provided=selected_image is not None,
        variation_panel_dir_provided=variation_panel_dir is not None,
    )
    if max_credits is not None and estimated > max_credits:
        return {
            "schema": "reference_factory.higgsfield_generation.v1",
            "status": "blocked",
            "reason": "max_credits_exceeded",
            "estimatedCredits": estimated,
            "maxCredits": max_credits,
            "count": len(runnable),
            "blockedPrompts": blocked,
            "runs": [],
        }

    paid_asset_count = estimate_generation_assets(
        len(runnable),
        no_video=no_video,
        image_candidates=image_candidates,
        variation_grid=variation_grid,
        variation_strategy=variation_strategy,
        variation_layout=variation_layout,
        animate_variation_panels=animate_variation_panels,
        selected_image_provided=selected_image is not None,
        variation_panel_dir_provided=variation_panel_dir is not None,
    )
    reservation_root = campaign_factory_root or data_root
    cost_preflight: dict[str, Any] | None = None
    reservation_id: str | None = None
    reservation_consumed = False
    cost_db_path = _campaign_cost_db_path(
        data_root=data_root, campaign_factory_root=campaign_factory_root
    )
    if not dry_run and paid_asset_count > 0:
        cost_preflight = reserve_higgsfield_spend(
            asset_count=paid_asset_count,
            estimated_cost_usd=estimated_cost_usd,
            provider=balance_provider,
            source=(
                "reference_factory:generate_with_higgsfield:"
                + (reference_id or "batch")
            ),
            root=reservation_root,
            cost_db_path=cost_db_path,
        )
        if not cost_preflight.get("allowed"):
            return {
                "schema": "reference_factory.higgsfield_generation.v1",
                "status": "blocked",
                "reason": "cost_preflight_blocked",
                "estimatedCredits": estimated,
                "estimatedCostUsd": estimated_cost_usd,
                "paidAssetCount": paid_asset_count,
                "costPreflight": cost_preflight,
                "count": len(runnable),
                "blockedPrompts": blocked,
                "runs": [],
            }
        reservation = cost_preflight.get("reservation")
        reservation_id = (
            reservation.get("id") if isinstance(reservation, dict) else None
        )
        if not isinstance(reservation_id, str) or not reservation_id:
            raise RuntimeError(
                "Reference Factory paid generation allowed without spend reservation"
            )

    output_root = data_root / "reference_intake" / "generated" / _day()
    output_root.mkdir(parents=True, exist_ok=True)
    soul_uuid = resolve_soul_id(soul_id)
    base_run = runner or _run_command

    def guarded_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal reservation_consumed
        if _is_paid_generation_command(cmd) and reservation_id:
            if not reservation_consumed:
                if not consume_higgsfield_spend_reservation(
                    reservation_id,
                    root=reservation_root,
                    cost_db_path=cost_db_path,
                ):
                    raise RuntimeError(
                        "Reference Factory spend reservation could not be consumed"
                    )
                reservation_consumed = True
                if cost_preflight and isinstance(
                    cost_preflight.get("reservation"), dict
                ):
                    cost_preflight["reservation"]["status"] = "consumed"
        return base_run(cmd)

    run = guarded_run
    score_by_ref = {pair.reference_id: score for pair, score in scored_pairs}
    try:
        runs = [
            _run_pair(
                pair,
                prompt_score=score_by_ref.get(pair.reference_id, {}),
                data_root=data_root,
                output_root=output_root,
                soul_name=soul_id,
                soul_uuid=soul_uuid,
                kling_mode=kling_mode,
                wait=wait,
                dry_run=dry_run,
                no_video=no_video,
                no_campaign_intake=no_campaign_intake,
                image_candidates=max(1, image_candidates),
                variation_grid=variation_grid,
                variation_model=variation_model,
                variation_layout=variation_layout,
                variation_strategy=variation_strategy,
                animate_variation_panels=animate_variation_panels,
                variation_panel_dir=variation_panel_dir,
                selected_image=selected_image,
                campaign_factory_root=campaign_factory_root,
                campaign=campaign,
                model=model,
                creative_plan=creative_plan,
                spend_reservation_id=reservation_id,
                runner=run,
            )
            for pair in runnable
        ]
    finally:
        if reservation_id and not reservation_consumed:
            cancel_higgsfield_spend_reservation(
                reservation_id,
                root=reservation_root,
                cost_db_path=cost_db_path,
            )
            if cost_preflight and isinstance(cost_preflight.get("reservation"), dict):
                cost_preflight["reservation"]["status"] = "cancelled"
    manifest = {
        "schema": "reference_factory.higgsfield_generation.v1",
        "status": _manifest_status(
            dry_run=dry_run,
            runs=runs,
            blocked=blocked,
            runnable_count=len(runnable),
            total_count=len(pairs),
        ),
        "generatedAt": _now(),
        "soulId": soul_id,
        "soulUuid": soul_uuid,
        "imageModel": DEFAULT_IMAGE_MODEL,
        "videoModel": DEFAULT_VIDEO_MODEL,
        "variationModel": variation_model,
        "variationLayout": variation_layout,
        "variationStrategy": variation_strategy,
        "animateVariationPanels": animate_variation_panels,
        "variationPanelDir": str(variation_panel_dir.expanduser())
        if variation_panel_dir
        else None,
        "klingMode": kling_mode,
        "sound": "off",
        "imageCandidates": max(1, image_candidates),
        "variationGrid": variation_grid,
        "estimatedCredits": estimated,
        "estimatedCostUsd": estimated_cost_usd,
        "paidAssetCount": paid_asset_count,
        "costPreflight": cost_preflight,
        "maxCredits": max_credits,
        "count": len(runs),
        "requestedCount": len(pairs),
        "minPromptScore": min_prompt_score,
        "promptScores": [
            {"referenceId": pair.reference_id, "promptScore": score}
            for pair, score in scored_pairs
        ],
        "blockedPrompts": blocked,
        "manifestPath": str(output_root / "higgsfield_generation_manifest.json"),
        "runs": runs,
    }
    atomic_write_text(
        (output_root / "higgsfield_generation_manifest.json"),
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _manifest_status(
    *,
    dry_run: bool,
    runs: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    runnable_count: int,
    total_count: int,
) -> str:
    if runnable_count == 0 and total_count > 0:
        return "blocked"
    if dry_run:
        return "dry_run_with_blocked" if blocked else "dry_run"
    ok = all(r["status"] in {"generated", "image_generated"} for r in runs)
    submitted = bool(runs) and all(r["status"] == "submitted" for r in runs)
    if submitted:
        return "submitted_with_blocked" if blocked else "submitted"
    if ok and blocked:
        return "ok_with_blocked"
    return "ok" if ok else "partial"


def run_daily_generation(
    *,
    data_root: Path,
    creative_plan: str,
    limit: int = 10,
    campaign: str,
    model: str,
    campaign_factory_root: Path,
    soul_id: str = "Stacey",
    kling_mode: str = "std",
    wait: bool = False,
    dry_run: bool = False,
    max_credits: float | None = 80.0,
    estimated_cost_usd: float | None = None,
    balance_provider: BalanceProvider | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    return generate_with_higgsfield(
        data_root=data_root,
        limit=limit,
        soul_id=soul_id,
        kling_mode=kling_mode,
        wait=wait,
        dry_run=dry_run,
        max_credits=max_credits,
        estimated_cost_usd=estimated_cost_usd,
        no_video=False,
        no_campaign_intake=False,
        image_candidates=1,
        variation_grid=False,
        variation_model=DEFAULT_VARIATION_MODEL,
        variation_layout=DEFAULT_VARIATION_LAYOUT,
        variation_strategy=DEFAULT_VARIATION_STRATEGY,
        animate_variation_panels=False,
        variation_panel_dir=None,
        selected_image=None,
        campaign_factory_root=campaign_factory_root,
        campaign=campaign,
        model=model,
        creative_plan=creative_plan,
        balance_provider=balance_provider,
        runner=runner,
    )


def load_prompt_pairs(
    *, data_root: Path, limit: int, reference_id: str | None = None
) -> list[PromptPair]:
    return _load_prompt_pairs(
        data_root=data_root, limit=limit, reference_id=reference_id
    )


def _load_prompt_pairs(
    *, data_root: Path, limit: int, reference_id: str | None
) -> list[PromptPair]:
    prompt_dir = data_root / "reference_intake"
    image_prompts = _read_jsonl(prompt_dir / "daily_higgsfield_image_prompts.jsonl")
    video_prompts = _read_jsonl(prompt_dir / "daily_kling_video_prompts.jsonl")
    by_ref: dict[str, dict[str, Any]] = {}
    for item in image_prompts:
        ref = str(item.get("sourceReferenceId") or item.get("referenceId") or "")
        if ref and ref not in by_ref:
            by_ref[ref] = item
    pairs = []
    for video in video_prompts:
        ref = str(video.get("sourceReferenceId") or video.get("referenceId") or "")
        if reference_id and ref != reference_id:
            continue
        if not _reference_source_is_usable(data_root, ref):
            continue
        image = by_ref.get(ref)
        if image:
            pairs.append(PromptPair(ref, image, video))
        if len(pairs) >= limit:
            break
    return pairs


def score_prompt_pair(pair: PromptPair) -> dict[str, Any]:
    image_score, image_reasons, image_warnings = _score_image_prompt(pair.image_prompt)
    video_score, video_reasons, video_warnings = _score_video_prompt(pair.video_prompt)
    score = round((image_score * 0.68) + (video_score * 0.32))
    warnings = image_warnings + video_warnings
    reasons = image_reasons + video_reasons
    return {
        "schema": "reference_factory.prompt_quality_score.v1",
        "score": int(max(0, min(100, score))),
        "imageScore": image_score,
        "videoScore": video_score,
        "status": "pass" if score >= DEFAULT_PROMPT_SCORE_THRESHOLD else "fail",
        "reasons": reasons,
        "warnings": warnings,
    }


def _score_image_prompt(prompt: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = 5
    reasons: list[str] = []
    warnings: list[str] = []
    compiled = _compiled_prompts(prompt)
    if compiled:
        compiled_score, compiled_reasons, compiled_warnings = _score_compiled_prompts(
            compiled, needs_video=False
        )
        score += round(compiled_score * 0.55)
        reasons.extend(compiled_reasons)
        warnings.extend(compiled_warnings)
    card, json_ok = _image_prompt_card(prompt)
    if json_ok:
        score += 28
        reasons.append("mainPrompt is valid ImageAt-style JSON")
    else:
        warnings.append("mainPrompt must be valid ImageAt-style JSON")
    text = " ".join(
        str(value).lower()
        for value in (
            prompt.get("mainPrompt"),
            card.get("prompt"),
            prompt.get("negative_prompt"),
            prompt.get("negativePrompt"),
        )
        if value
    )
    composition = (
        card.get("composition") if isinstance(card.get("composition"), dict) else {}
    )
    clothing = card.get("clothing") if isinstance(card.get("clothing"), dict) else {}
    environment = (
        card.get("environment") if isinstance(card.get("environment"), dict) else {}
    )
    constraints = (
        card.get("constraints") if isinstance(card.get("constraints"), dict) else {}
    )

    required_sections = [
        ("subject", card.get("subject")),
        ("composition", composition),
        ("clothing", clothing),
        ("environment", environment),
        (
            "lighting_and_camera",
            card.get("lighting_and_camera") or card.get("lightingAndCamera"),
        ),
        ("constraints", constraints),
        (
            "negative_prompt",
            card.get("negative_prompt") or prompt.get("negativePrompt"),
        ),
    ]
    for label, value in required_sections:
        if value:
            score += 7
            reasons.append(f"{label} present")
        else:
            warnings.append(f"missing {label}")

    must_keep = _list_from(constraints.get("must_keep")) + _list_from(
        card.get("must_keep")
    )
    avoid = _list_from(constraints.get("avoid")) + _list_from(card.get("avoid"))
    if len(must_keep) >= 3:
        score += 8
        reasons.append("must_keep is specific")
    else:
        warnings.append("must_keep needs at least three concrete visual anchors")
    if len(avoid) >= 3:
        score += 6
        reasons.append("avoid list is specific")
    else:
        warnings.append("avoid list needs identity/platform/model-error blockers")

    visual_terms = (
        "mirror",
        "selfie",
        "phone",
        "bedroom",
        "side profile",
        "leopard",
        "bodycon",
        "iphone",
        "black mirror",
        "natural daylight",
    )
    matches = [term for term in visual_terms if term in text]
    score += min(14, len(matches) * 2)
    if len(matches) >= 5:
        reasons.append("prompt has concrete source visual anchors")
    else:
        warnings.append("prompt may be too generic; add source-specific visual anchors")

    if any(
        term in text
        for term in (
            "explicit nudity",
            "platform-safe",
            "social-media-safe",
            "non-explicit",
        )
    ):
        score += 5
        reasons.append("spicy prompt includes safety/usefulness boundary")
    if card.get("prompt_schema_version") == "imageat_higgsfield.v1":
        score += 8
        reasons.append("prompt_schema_version is locked")
    else:
        score -= 20
        warnings.append("missing prompt_schema_version imageat_higgsfield.v1")
    return int(max(0, min(100, score))), reasons, warnings


def _score_video_prompt(prompt: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = 35
    reasons: list[str] = []
    warnings: list[str] = []
    compiled = _compiled_prompts(prompt)
    if compiled:
        compiled_score, compiled_reasons, compiled_warnings = _score_compiled_prompts(
            compiled, needs_video=True
        )
        score += round(compiled_score * 0.45)
        reasons.extend(compiled_reasons)
        warnings.extend(compiled_warnings)
    text = str(prompt.get("mainPrompt") or "").lower()
    scenes = prompt.get("scenes") if isinstance(prompt.get("scenes"), list) else []
    directives = (
        prompt.get("motion_directives")
        if isinstance(prompt.get("motion_directives"), dict)
        else {}
    )
    required_directives = (
        "duration_seconds",
        "camera_motion",
        "subject_motion",
        "must_preserve",
        "avoid",
        "fallback_provider",
    )
    if all(directives.get(key) for key in required_directives):
        score += 25
        reasons.append("motion_directives complete")
    else:
        score -= 18
        warnings.append("motion_directives missing required fields")
    if scenes:
        score += 18
        reasons.append("Kling scenes present")
    elif any(token in text for token in ("0.0-", "1.0s", "2.0s", "time")):
        score += 12
        reasons.append("Kling prompt has timestamped motion")
    else:
        warnings.append("Kling prompt needs timestamped motion beats")
    for term in (
        "first/reference frame",
        "preserve",
        "phone",
        "mirror",
        "no zoom",
        "no face reveal",
    ):
        if term in text:
            score += 5
    if "negativePrompt" in prompt or prompt.get("negativePrompt"):
        score += 7
        reasons.append("Kling negative prompt present")
    else:
        warnings.append("missing Kling negative prompt")
    return int(max(0, min(100, score))), reasons, warnings


def _score_compiled_prompts(
    compiled: dict[str, Any], *, needs_video: bool
) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    prompt_keys = ["soul_id_2x3_prompt", "single_panel_prompt"]
    if needs_video:
        prompt_keys.append("kling_video_prompt")
    prompt_text = " ".join(str(compiled.get(key) or "") for key in prompt_keys).lower()
    if all(compiled.get(key) for key in prompt_keys):
        score += 20
        reasons.append("Grok compiled prose prompts present")
    else:
        warnings.append("missing one or more Grok compiled prose prompts")
    breakdown = (
        compiled.get("structured_breakdown")
        if isinstance(compiled.get("structured_breakdown"), dict)
        else {}
    )
    if breakdown:
        score += 20
        reasons.append("Grok structured_breakdown present")
    else:
        warnings.append("missing Grok structured_breakdown")
    outfits = (
        breakdown.get("outfit_variations") if isinstance(breakdown, dict) else None
    )
    if isinstance(outfits, list) and len(outfits) == 6:
        score += 14
        reasons.append("Grok outfit_variations has 6 panel outfits")
    else:
        warnings.append("Grok outfit_variations must contain exactly 6 outfits")
    for key in ("pose_lock", "body_emphasis", "motion_directives", "key_constraints"):
        if breakdown.get(key):
            score += 8
            reasons.append(f"Grok {key} present")
        else:
            warnings.append(f"missing Grok {key}")
    confidence = compiled.get("confidence_score")
    if isinstance(confidence, int) and confidence >= 70:
        score += min(14, round((confidence - 70) / 3))
        reasons.append("Grok confidence_score is acceptable")
    else:
        warnings.append("Grok confidence_score missing or below 70")
    for term in (
        "deep cleavage",
        "pushed-up",
        "tiny waist",
        "wide hips",
        "thick thighs",
        "round",
        "ass",
        "s-curve",
        "fabric",
    ):
        if term in prompt_text:
            score += 2
    forbidden = (
        "platform ui",
        "screenshot",
        "username",
        "watermark",
        "tattoo",
        "hairstyle",
    )
    leaked = [term for term in forbidden if term in prompt_text]
    if leaked:
        score -= 35
        warnings.append("Grok prompt leaked forbidden terms: " + ", ".join(leaked))
    return int(max(0, min(100, score))), reasons, warnings


def _image_prompt_card(prompt: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    raw = prompt.get("mainPrompt")
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed, True
        except json.JSONDecodeError:
            pass
    card = (
        prompt.get("imagePromptJson")
        if isinstance(prompt.get("imagePromptJson"), dict)
        else {}
    )
    return card, False


def _list_from(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _reference_source_is_usable(data_root: Path, reference_id: str) -> bool:
    if not reference_id:
        return False
    db_path = data_root / "reference_factory.sqlite"
    if not db_path.exists():
        return True
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT path, size_bytes FROM source_files WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
    except sqlite3.Error:
        return True
    if not row:
        return False
    path_text, size_bytes = row
    path = Path(str(path_text))
    if int(size_bytes or 0) < MIN_REFERENCE_BYTES:
        return False
    return path.exists()


def estimate_credits(
    count: int,
    *,
    no_video: bool = False,
    image_candidates: int = 1,
    variation_grid: bool = False,
    variation_strategy: str = DEFAULT_VARIATION_STRATEGY,
    variation_layout: str = DEFAULT_VARIATION_LAYOUT,
    animate_variation_panels: bool = False,
    selected_image_provided: bool = False,
    variation_panel_dir_provided: bool = False,
) -> float:
    effective_image_candidates = (
        1
        if variation_grid and variation_strategy == "soul_grid"
        else max(1, image_candidates)
    )
    image_credits = (
        0.0
        if selected_image_provided
        else DEFAULT_IMAGE_CREDITS * effective_image_candidates
    )
    per = image_credits + (0.0 if no_video else DEFAULT_VIDEO_CREDITS)
    if variation_grid and variation_strategy != "soul_grid":
        variation_count = (
            len(_variation_outfits(variation_layout))
            if variation_strategy == "individual"
            else 1
        )
        if not variation_panel_dir_provided:
            per += DEFAULT_VARIATION_CREDITS * variation_count
        if animate_variation_panels and variation_strategy == "individual":
            per += DEFAULT_PANEL_VIDEO_CREDITS * variation_count
    return round(count * per, 2)


def estimate_generation_assets(
    count: int,
    *,
    no_video: bool = False,
    image_candidates: int = 1,
    variation_grid: bool = False,
    variation_strategy: str = DEFAULT_VARIATION_STRATEGY,
    variation_layout: str = DEFAULT_VARIATION_LAYOUT,
    animate_variation_panels: bool = False,
    selected_image_provided: bool = False,
    variation_panel_dir_provided: bool = False,
) -> int:
    """Count provider generation submissions covered by the USD reservation."""
    effective_image_candidates = (
        1
        if variation_grid and variation_strategy == "soul_grid"
        else max(1, image_candidates)
    )
    per_reference = 0 if selected_image_provided else effective_image_candidates
    if not no_video:
        per_reference += 1
    if variation_grid and variation_strategy != "soul_grid":
        variation_count = (
            len(_variation_outfits(variation_layout))
            if variation_strategy == "individual"
            else 1
        )
        if not variation_panel_dir_provided:
            per_reference += variation_count
        if animate_variation_panels and variation_strategy == "individual":
            per_reference += variation_count
    return max(0, count) * per_reference


def _validate_generation_budget_inputs(
    *,
    limit: int,
    image_candidates: int,
    max_credits: float | None,
    estimated_cost_usd: float | None,
) -> None:
    for name, value in (("limit", limit), ("image_candidates", image_candidates)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    for name, value in (
        ("max_credits", max_credits),
        ("estimated_cost_usd", estimated_cost_usd),
    ):
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"{name} must be finite and non-negative")


def _is_paid_generation_command(cmd: list[str]) -> bool:
    return (
        bool(cmd)
        and Path(cmd[0]).name == "higgsfield"
        and any(
            cmd[index : index + 2] == ["generate", "create"]
            for index in range(1, len(cmd) - 1)
        )
    )


def _campaign_cost_db_path(
    *, data_root: Path, campaign_factory_root: Path | None
) -> Path:
    env_path = os.environ.get("CAMPAIGN_FACTORY_DB")
    if env_path:
        return Path(env_path).expanduser()
    if campaign_factory_root:
        return campaign_factory_root.expanduser().resolve() / "campaign_factory.sqlite"
    root = data_root.expanduser().resolve()
    candidates = [
        root / "campaign_factory.sqlite",
        Path(__file__).resolve().parents[2]
        / "campaign_factory"
        / "campaign_factory.sqlite",
    ]
    return candidates[0] if candidates[0].exists() else candidates[-1]


def _load_cost_tracker_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "campaign_factory"
        / "campaign_factory"
        / "cost_tracker.py"
    )
    spec = importlib.util.spec_from_file_location("_creator_os_cost_tracker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load cost tracker from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_generation_cost(
    *,
    data_root: Path,
    campaign_factory_root: Path | None,
    provider: str,
    operation: str,
    campaign: str | None,
    model: str,
    result: dict[str, Any] | None,
    lineage_path: Path,
    reference_id: str,
    reservation_id: str | None,
) -> dict[str, Any] | None:
    result = result or {}
    job_id = _result_id(result)
    if not job_id:
        return None
    cost_tracker = _load_cost_tracker_module()
    db_path = _campaign_cost_db_path(
        data_root=data_root, campaign_factory_root=campaign_factory_root
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    actual_credits = _result_credits(result)
    # TODO: reconcile Higgsfield credits -> USD once the API exposes a stable conversion.
    metadata = {
        "schema": "reference_factory.ai_cost_metadata.v1",
        "actualCredits": actual_credits,
        "creditCurrency": "higgsfield_credits",
        "model": model,
        "jobId": job_id,
        "lineagePath": str(lineage_path),
        "referenceId": reference_id,
        "spendReservationId": reservation_id,
    }
    with sqlite3.connect(db_path) as conn:
        event_id = cost_tracker.record_ai_cost(
            conn,
            provider=provider,
            operation=operation,
            campaign_id=campaign,
            generations=1,
            metadata=metadata,
            source_event_key=f"reference_factory:{provider}:{operation}:{job_id}",
            reservation_id=reservation_id,
        )
    return {
        "eventId": event_id,
        "provider": provider,
        "operation": operation,
        "jobId": job_id,
        "actualCredits": actual_credits,
    }


def _record_image_generation_costs(
    *,
    data_root: Path,
    campaign_factory_root: Path | None,
    campaign: str | None,
    lineage_path: Path,
    reference_id: str,
    candidate_results: list[dict[str, Any]],
    reservation_id: str | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in candidate_results:
        result = item.get("result") if isinstance(item.get("result"), dict) else item
        event = _record_generation_cost(
            data_root=data_root,
            campaign_factory_root=campaign_factory_root,
            provider="higgsfield",
            operation="image_create",
            campaign=campaign,
            model=DEFAULT_IMAGE_MODEL,
            result=result,
            lineage_path=lineage_path,
            reference_id=reference_id,
            reservation_id=reservation_id,
        )
        if event:
            events.append(event)
    return events


def resolve_soul_id(soul_id: str) -> str:
    return DEFAULT_SOUL_IDS.get(soul_id.strip().lower(), soul_id.strip())


def _run_pair(
    pair: PromptPair,
    *,
    prompt_score: dict[str, Any],
    data_root: Path,
    output_root: Path,
    soul_name: str,
    soul_uuid: str,
    kling_mode: str,
    wait: bool,
    dry_run: bool,
    no_video: bool,
    no_campaign_intake: bool,
    image_candidates: int,
    variation_grid: bool,
    variation_model: str,
    variation_layout: str,
    variation_strategy: str,
    animate_variation_panels: bool,
    variation_panel_dir: Path | None,
    selected_image: Path | None,
    campaign_factory_root: Path | None,
    campaign: str | None,
    model: str | None,
    creative_plan: str | None,
    spend_reservation_id: str | None,
    runner: Runner,
) -> dict[str, Any]:
    out_dir = output_root / _safe_name(pair.reference_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_commands = [
        (
            _soul_grid_image_command(
                pair, soul_uuid=soul_uuid, variation_layout=variation_layout, wait=wait
            )
            if variation_grid and variation_strategy == "soul_grid"
            else _image_command(pair, soul_uuid=soul_uuid, wait=wait)
        )
        for _ in range(
            1
            if variation_grid and variation_strategy == "soul_grid"
            else max(1, image_candidates)
        )
    ]
    image_cmd = image_commands[0]

    video_cmd: list[str] | None = None
    variation_cmd: list[str] | None = None
    variation_commands: list[list[str]] = []
    image_result: dict[str, Any] | None = None
    video_result: dict[str, Any] | None = None
    variation_result: dict[str, Any] | None = None
    soul_grid_mode = variation_grid and variation_strategy == "soul_grid"
    soul_grid_suffix = (
        "_soul_grid_" + _safe_name(variation_layout) if soul_grid_mode else ""
    )
    video_asset = out_dir / f"kling_video{soul_grid_suffix}_result.json"
    status = "dry_run" if dry_run else "generation_failed"
    errors: list[str] = []
    local_image_path: str | None = None
    local_video_path: str | None = None
    local_variation_path: str | None = None
    candidate_results: list[dict[str, Any]] = []
    selected_candidate_index = 1
    lineage_path = out_dir / "generated_asset_lineage.json"
    cost_events: list[dict[str, Any]] = []

    if dry_run:
        candidate_results = [
            {"candidateIndex": idx + 1, "command": cmd}
            for idx, cmd in enumerate(image_commands)
        ]
        image_result = candidate_results[0]
        media_ref = (
            str(selected_image)
            if selected_image
            else "<generated_higgsfield_image_candidate_1>"
        )
        if variation_grid:
            if variation_strategy == "soul_grid":
                variation_result = {
                    "schema": "reference_factory.higgsfield_variation_result.v1",
                    "strategy": "soul_grid",
                    "layout": variation_layout,
                    "command": image_cmd,
                    "prompt": _soul_grid_prompt_text(pair, variation_layout),
                }
            elif variation_panel_dir:
                variation_result = _variation_result_from_panel_dir(
                    variation_panel_dir.expanduser(),
                    variation_layout=variation_layout,
                    dry_run=True,
                )
                panel_video_commands = (
                    _variation_panel_video_commands_from_result(
                        pair, variation_result, kling_mode, wait
                    )
                    if animate_variation_panels
                    else []
                )
                if panel_video_commands:
                    variation_result["panelVideoCommands"] = panel_video_commands
            elif variation_strategy == "individual":
                variation_commands = _individual_variation_commands(
                    pair, media_ref, variation_model, variation_layout, wait
                )
                panel_video_commands = (
                    _variation_panel_video_commands(
                        pair, variation_layout, kling_mode, wait
                    )
                    if animate_variation_panels
                    else []
                )
                variation_result = {
                    "strategy": "individual",
                    "panelCommands": variation_commands,
                }
                if panel_video_commands:
                    variation_result["panelVideoCommands"] = panel_video_commands
                variation_cmd = variation_commands[0] if variation_commands else None
            else:
                variation_cmd = _variation_command(
                    pair, media_ref, variation_model, variation_layout, wait
                )
                variation_result = {"command": variation_cmd}
        if not no_video:
            video_cmd = _video_command(pair, media_ref, kling_mode, wait)
            video_result = {"command": video_cmd}
    else:
        try:
            if selected_image:
                local_image_path = str(selected_image.expanduser())
                image_result = {"path": local_image_path, "selectedExternal": True}
                candidate_results = [
                    {
                        "candidateIndex": 1,
                        "result": image_result,
                        "localPath": local_image_path,
                        "selected": True,
                    }
                ]
            else:
                for idx, cmd in enumerate(image_commands, start=1):
                    image_stem = (
                        f"higgsfield_soul_grid_{_safe_name(variation_layout)}"
                        if soul_grid_mode
                        else f"higgsfield_image_candidate_{idx}"
                    )
                    image_asset = out_dir / f"{image_stem}_result.json"
                    if image_asset.exists():
                        result = _normalize_result(
                            json.loads(image_asset.read_text(encoding="utf-8"))
                        )
                        _raise_for_provider_status(result)
                    else:
                        result = _run_json(cmd, runner)
                        _raise_for_provider_status(result)
                        _write_job_id(out_dir / f"{image_stem}_job_id.txt", result)
                        atomic_write_text(
                            image_asset,
                            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                    local_path = _materialize_result_asset(result, out_dir / image_stem)
                    candidate_results.append(
                        {
                            "candidateIndex": idx,
                            "jobId": _result_id(result),
                            "resultUrl": _result_url(result),
                            "localPath": local_path,
                            "result": result,
                            "selected": idx == 1,
                        }
                    )
                first = candidate_results[0]
                image_result = (
                    first.get("result") if isinstance(first.get("result"), dict) else {}
                )
                local_image_path = str(first.get("localPath") or "") or None
                if wait and not local_image_path:
                    raise RuntimeError("Higgsfield image result did not materialize")
            media_ref = local_image_path or _result_id_or_url(image_result or {})
            if not media_ref:
                raise RuntimeError(
                    "Higgsfield image result did not include a usable media id, URL, or local file"
                )
            if not dry_run:
                cost_events.extend(
                    _record_image_generation_costs(
                        data_root=data_root,
                        campaign_factory_root=campaign_factory_root,
                        campaign=campaign,
                        lineage_path=lineage_path,
                        reference_id=pair.reference_id,
                        candidate_results=candidate_results,
                        reservation_id=spend_reservation_id,
                    )
                )
            if variation_grid:
                variation_stem = "variation_grid_" + _safe_name(variation_layout)
                if variation_strategy == "soul_grid":
                    selected_panel_path = (
                        _extract_soul_grid_selected_panel(
                            Path(local_image_path),
                            out_dir=out_dir,
                            variation_layout=variation_layout,
                        )
                        if local_image_path
                        else None
                    )
                    variation_result = {
                        "schema": "reference_factory.higgsfield_variation_result.v1",
                        "strategy": "soul_grid",
                        "layout": variation_layout,
                        "status": "generated",
                        "command": image_cmd,
                        "prompt": _soul_grid_prompt_text(pair, variation_layout),
                        "path": local_image_path,
                        "selectedPanelIndex": _default_soul_grid_selected_panel(
                            variation_layout
                        ),
                        "selectedPanelPath": str(selected_panel_path)
                        if selected_panel_path
                        else None,
                        "jobId": _result_id(image_result or {}),
                        "resultUrl": _result_url(image_result or {}),
                    }
                    local_variation_path = local_image_path
                    if selected_panel_path:
                        media_ref = str(selected_panel_path)
                elif variation_panel_dir:
                    try:
                        variation_result, local_variation_path = (
                            _use_existing_variation_panels(
                                out_dir=out_dir,
                                panel_dir=variation_panel_dir.expanduser(),
                                variation_layout=variation_layout,
                            )
                        )
                        if (
                            animate_variation_panels
                            and _variation_status(variation_result) == "generated"
                        ):
                            variation_result = _run_variation_panel_videos(
                                out_dir=out_dir,
                                pair=pair,
                                variation_result=variation_result,
                                variation_layout=variation_layout,
                                kling_mode=kling_mode,
                                wait=wait,
                                runner=runner,
                            )
                            if variation_result.get("panelVideoStatus") != "generated":
                                errors.append("variation_panel_video_failed")
                        if _variation_status(variation_result) != "generated":
                            errors.append(
                                f"variation_grid_{_variation_status(variation_result)}"
                            )
                    except Exception as exc:  # noqa: BLE001 - variation should not block video proof
                        errors.append(f"variation_panel_dir_failed: {exc}")
                        variation_result = {
                            "schema": "reference_factory.higgsfield_variation_result.v1",
                            "status": "failed",
                            "error": str(exc),
                            "strategy": "existing_panel_folder",
                            "layout": variation_layout,
                            "panelDir": str(variation_panel_dir.expanduser()),
                        }
                elif variation_strategy == "individual":
                    variation_commands = _individual_variation_commands(
                        pair, media_ref, variation_model, variation_layout, wait
                    )
                    variation_cmd = (
                        variation_commands[0] if variation_commands else None
                    )
                    try:
                        variation_result, local_variation_path = (
                            _run_individual_variations(
                                out_dir=out_dir,
                                media_ref=media_ref,
                                pair=pair,
                                variation_model=variation_model,
                                variation_layout=variation_layout,
                                wait=wait,
                                runner=runner,
                            )
                        )
                        if (
                            animate_variation_panels
                            and _variation_status(variation_result) == "generated"
                        ):
                            variation_result = _run_variation_panel_videos(
                                out_dir=out_dir,
                                pair=pair,
                                variation_result=variation_result,
                                variation_layout=variation_layout,
                                kling_mode=kling_mode,
                                wait=wait,
                                runner=runner,
                            )
                            if variation_result.get("panelVideoStatus") != "generated":
                                errors.append("variation_panel_video_failed")
                        if _variation_status(variation_result) != "generated":
                            errors.append(
                                f"variation_grid_{_variation_status(variation_result)}"
                            )
                    except Exception as exc:  # noqa: BLE001 - variation should not block video proof
                        errors.append(f"variation_grid_failed: {exc}")
                        variation_result = {
                            "schema": "reference_factory.higgsfield_variation_result.v1",
                            "status": "failed",
                            "error": str(exc),
                            "strategy": "individual",
                            "panelCommands": variation_commands,
                        }
                else:
                    variation_asset = out_dir / f"{variation_stem}_result.json"
                    variation_cmd = _variation_command(
                        pair, media_ref, variation_model, variation_layout, wait
                    )
                    try:
                        if variation_asset.exists():
                            cached_variation = _normalize_result(
                                json.loads(variation_asset.read_text(encoding="utf-8"))
                            )
                            if _variation_result_is_reusable(cached_variation):
                                variation_result = cached_variation
                            else:
                                variation_result = _run_json(variation_cmd, runner)
                                atomic_write_text(
                                    variation_asset,
                                    json.dumps(
                                        variation_result, indent=2, ensure_ascii=False
                                    )
                                    + "\n",
                                    encoding="utf-8",
                                )
                        else:
                            variation_result = _run_json(variation_cmd, runner)
                            atomic_write_text(
                                variation_asset,
                                json.dumps(
                                    variation_result, indent=2, ensure_ascii=False
                                )
                                + "\n",
                                encoding="utf-8",
                            )
                        local_variation_path = _materialize_result_asset(
                            variation_result, out_dir / variation_stem
                        )
                        if _variation_status(variation_result) != "generated":
                            errors.append(
                                f"variation_grid_{_variation_status(variation_result)}"
                            )
                    except Exception as exc:  # noqa: BLE001 - variation should not block video proof
                        errors.append(f"variation_grid_failed: {exc}")
                        variation_result = {
                            "schema": "reference_factory.higgsfield_variation_result.v1",
                            "status": "failed",
                            "error": str(exc),
                            "command": variation_cmd,
                        }
            if no_video:
                if local_image_path:
                    status = "image_generated"
                elif not wait and _result_id(image_result or {}):
                    status = "submitted"
                else:
                    raise RuntimeError("Higgsfield image result did not materialize")
            else:
                try:
                    if video_asset.exists():
                        video_result = _normalize_result(
                            json.loads(video_asset.read_text(encoding="utf-8"))
                        )
                        _raise_for_provider_status(video_result)
                    else:
                        video_cmd = _video_command(pair, media_ref, kling_mode, wait)
                        video_result = _run_json(video_cmd, runner)
                        _raise_for_provider_status(video_result)
                        _write_job_id(
                            out_dir / f"kling_video{soul_grid_suffix}_job_id.txt",
                            video_result,
                        )
                        atomic_write_text(
                            video_asset,
                            json.dumps(video_result, indent=2, ensure_ascii=False)
                            + "\n",
                            encoding="utf-8",
                        )
                    if video_cmd is None:
                        video_cmd = _video_command(pair, media_ref, kling_mode, wait)
                    local_video_path = _materialize_result_asset(
                        video_result, out_dir / "kling_video"
                    )
                    if local_video_path:
                        status = "generated"
                    elif not wait and _result_id(video_result or {}):
                        status = "submitted"
                    else:
                        raise RuntimeError(
                            "Higgsfield video result did not materialize"
                        )
                except Exception as exc:  # noqa: BLE001 - returned in manifest for fallback recovery
                    errors.append(f"kling_video_failed: {exc}")
                    status = "video_failed"
        except Exception as exc:  # noqa: BLE001 - returned in manifest for operator recovery
            errors.append(str(exc))

    variation_prompt = _variation_grid_prompt(pair, variation_layout=variation_layout)
    fallback_video_prompt = _fallback_video_prompt(pair)
    lineage = _lineage(
        pair=pair,
        prompt_score=prompt_score,
        variation_prompt=variation_prompt,
        fallback_video_prompt=fallback_video_prompt,
        soul_name=soul_name,
        soul_uuid=soul_uuid,
        image_result=image_result,
        video_result=video_result,
        variation_result=variation_result,
        candidate_results=candidate_results,
        selected_candidate_index=selected_candidate_index,
        local_image_path=local_image_path,
        local_video_path=local_video_path,
        local_variation_path=local_variation_path,
        variation_model=variation_model,
        variation_layout=variation_layout,
        variation_strategy=variation_strategy,
        status=status,
        estimated_credits=estimate_credits(
            1,
            no_video=no_video,
            image_candidates=image_candidates,
            variation_grid=variation_grid,
            variation_strategy=variation_strategy,
            variation_layout=variation_layout,
            animate_variation_panels=animate_variation_panels,
            selected_image_provided=selected_image is not None,
            variation_panel_dir_provided=variation_panel_dir is not None,
        ),
    )
    if not dry_run and status in {"generated", "image_generated", "submitted"}:
        if video_result:
            event = _record_generation_cost(
                data_root=data_root,
                campaign_factory_root=campaign_factory_root,
                provider="kling",
                operation="video_create",
                campaign=campaign,
                model=DEFAULT_VIDEO_MODEL,
                result=video_result,
                lineage_path=lineage_path,
                reference_id=pair.reference_id,
                reservation_id=spend_reservation_id,
            )
            if event:
                cost_events.append(event)
        if variation_result:
            event = _record_generation_cost(
                data_root=data_root,
                campaign_factory_root=campaign_factory_root,
                provider="higgsfield",
                operation="variation_create",
                campaign=campaign,
                model=variation_model,
                result=variation_result,
                lineage_path=lineage_path,
                reference_id=pair.reference_id,
                reservation_id=spend_reservation_id,
            )
            if event:
                cost_events.append(event)
    lineage["generation"]["costLedger"] = {
        "schema": "reference_factory.ai_cost_ledger.v1",
        "events": cost_events,
    }
    atomic_write_text(
        lineage_path,
        json.dumps(lineage, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    campaign_intake = None
    if (
        status == "generated"
        and local_video_path
        and not no_campaign_intake
        and campaign_factory_root
        and campaign
        and model
    ):
        campaign_intake = _campaign_intake(
            campaign_factory_root=campaign_factory_root,
            input_path=Path(local_video_path),
            lineage_path=lineage_path,
            campaign=campaign,
            model=model,
            creative_plan=creative_plan,
            runner=runner,
            dry_run=dry_run,
        )

    run_manifest = {
        "schema": "reference_factory.higgsfield_generation_run.v1",
        "referenceId": pair.reference_id,
        "status": status,
        "errors": errors,
        "imageCommand": image_cmd,
        "imageCommands": image_commands,
        "videoCommand": video_cmd,
        "variationCommand": variation_cmd,
        "variationCommands": variation_commands,
        "variationPrompt": variation_prompt,
        "animateVariationPanels": animate_variation_panels,
        "fallbackVideoPrompt": fallback_video_prompt,
        "imageCandidates": candidate_results,
        "selectedCandidateIndex": selected_candidate_index,
        "imageResult": image_result,
        "videoResult": video_result,
        "variationResult": variation_result,
        "localImagePath": local_image_path,
        "localVideoPath": local_video_path,
        "localVariationPath": local_variation_path,
        "lineagePath": str(lineage_path),
        "campaignIntake": campaign_intake,
    }
    atomic_write_text(
        (out_dir / "run_manifest.json"),
        json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return run_manifest


def _image_command(pair: PromptPair, *, soul_uuid: str, wait: bool) -> list[str]:
    cmd = [
        "higgsfield",
        "--json",
        "generate",
        "create",
        DEFAULT_IMAGE_MODEL,
        "--prompt",
        _soul_image_prompt_text(pair.image_prompt),
        "--custom_reference_id",
        soul_uuid,
        "--aspect_ratio",
        "9:16",
        "--quality",
        "2k",
    ]
    if wait:
        cmd.append("--wait")
    return cmd


def _soul_grid_image_command(
    pair: PromptPair, *, soul_uuid: str, variation_layout: str, wait: bool
) -> list[str]:
    cmd = [
        "higgsfield",
        "--json",
        "generate",
        "create",
        DEFAULT_IMAGE_MODEL,
        "--prompt",
        _soul_grid_prompt_text(pair, variation_layout),
        "--custom_reference_id",
        soul_uuid,
        "--aspect_ratio",
        DEFAULT_SOUL_GRID_ASPECT_RATIO,
        "--quality",
        "2k",
    ]
    if wait:
        cmd.append("--wait")
    return cmd


def _soul_image_prompt_text(prompt: dict[str, Any]) -> str:
    compiled = _compiled_prompts(prompt)
    if (
        isinstance(compiled.get("single_panel_prompt"), str)
        and compiled["single_panel_prompt"].strip()
    ):
        return compiled["single_panel_prompt"].strip()
    return _compiled_single_panel_prompt(prompt)


def _compiled_single_panel_prompt(prompt: dict[str, Any]) -> str:
    card, ok = _image_prompt_card(prompt)
    if not ok:
        return str(prompt.get("mainPrompt") or "").strip()
    outfit = _primary_outfit_text(card)
    pose = _pose_text(card)
    environment = _environment_text(card)
    lighting = _lighting_text(card)
    return (
        f"Same Soul ID woman in a tight {outfit}, taking a confident outfit-check selfie in {environment}. "
        f"Pose: {pose}. "
        f"Body emphasis: {_body_emphasis_text()}. "
        f"{lighting}, photorealistic skin texture, realistic fabric stretch and cling, iPhone selfie aesthetic, vertical 9:16, high detail, sharp focus."
    )


def _analysis_positive_text(prompt: dict[str, Any]) -> str:
    card, ok = _image_prompt_card(prompt)
    if not ok:
        return str(prompt.get("mainPrompt") or "").strip()
    positive_parts: list[str] = []
    for key in (
        "subject",
        "prompt",
        "composition",
        "body",
        "clothing",
        "skin",
        "expression_mood",
        "environment",
        "lighting_and_camera",
        "must_keep",
    ):
        part = _positive_prompt_fragment(card.get(key))
        if part:
            positive_parts.append(part)
    return " ".join(positive_parts).strip()


def _body_emphasis_text() -> str:
    return (
        "deep plunging cleavage, generous pushed-up full breasts, fabric straining against her chest, "
        "tiny cinched waist, wide hips, thick thighs, strong arched back, hips pushed out to the side, "
        "dramatic S-curve posture, round plump juicy ass prominently displayed in profile, "
        "pronounced glute definition, and skin-tight fabric clinging to every curve"
    )


def _pose_text(card: dict[str, Any]) -> str:
    text = json.dumps(card, ensure_ascii=False).lower()
    if "mirror" in text:
        return (
            "side-profile mirror selfie, smartphone raised near the face, strong arched back, "
            "hips pushed back and to the side, one free hand posed naturally, dramatic S-curve"
        )
    return (
        "front-three-quarter selfie pose, one arm raised holding a smartphone, other hand behind her head or in her hair, "
        "strong arched back, hips pushed out to the side, dramatic S-curve"
    )


def _environment_text(card: dict[str, Any]) -> str:
    text = json.dumps(card, ensure_ascii=False).lower()
    if "fireplace" in text:
        return "a bright luxury living room with a light stone fireplace and clean modern interior"
    if "bedroom" in text:
        return "a bright minimalist bedroom with soft bedding and clean white walls"
    if "bathroom" in text:
        return "a clean bright bathroom mirror-selfie setting"
    if "resort" in text or "pool" in text:
        return "a bright luxury resort setting"
    return "the same clean reference setting"


def _lighting_text(card: dict[str, Any]) -> str:
    text = json.dumps(
        card.get("lighting_and_camera") or card, ensure_ascii=False
    ).lower()
    if "daylight" in text or "natural" in text:
        return "soft natural daylight"
    if "flash" in text:
        return "realistic phone flash lighting"
    if "dusk" in text or "twilight" in text:
        return "soft twilight light"
    return "flattering realistic phone lighting"


def _primary_outfit_text(card: dict[str, Any]) -> str:
    text = json.dumps(card, ensure_ascii=False).lower()
    clothing = card.get("clothing") if isinstance(card.get("clothing"), dict) else {}
    raw = _positive_prompt_fragment(clothing) if clothing else ""
    if "strapless" in text and ("maxi" in text or "dress" in text):
        if "blue" in text:
            return "bright blue strapless bodycon maxi dress"
        return "strapless bodycon maxi dress"
    if "leopard" in text:
        return "leopard-print strapless bodycon mini dress"
    if raw:
        return raw
    return "fitted bodycon outfit"


def _positive_prompt_fragment(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _provider_positive_text(value)
    if isinstance(value, list):
        return " ".join(
            fragment for item in value if (fragment := _positive_prompt_fragment(item))
        )
    if isinstance(value, dict):
        fragments = []
        for key, inner in value.items():
            if key in {"avoid", "negative_prompt", "must_change"}:
                continue
            fragment = _positive_prompt_fragment(inner)
            if fragment:
                fragments.append(fragment)
        return " ".join(fragments)
    return _provider_positive_text(str(value))


def _provider_positive_text(text: str) -> str:
    pieces = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    kept: list[str] = []
    negative_markers = (
        " no ",
        "no ",
        " without ",
        "avoid",
        "do not",
        "don't",
        " not ",
        "non-nude",
        "watermark",
        "username",
        "platform ui",
        "platform-safe",
        "social-safe",
        "social-media-safe",
        "non-explicit",
        "when safe",
        "branding",
        "identifiers",
        "screenshot",
        "logo",
        "negative_prompt",
    )
    for piece in pieces:
        low = f" {piece.lower()} "
        if any(marker in low for marker in negative_markers):
            continue
        kept.append(piece)
    return " ".join(kept).strip()


def _soul_grid_prompt_text(pair: PromptPair, variation_layout: str) -> str:
    compiled = _compiled_prompts(pair.image_prompt)
    if (
        isinstance(compiled.get("soul_id_2x3_prompt"), str)
        and compiled["soul_id_2x3_prompt"].strip()
    ):
        return compiled["soul_id_2x3_prompt"].strip()
    card, ok = _image_prompt_card(pair.image_prompt)
    if not ok:
        environment = "the same clean reference setting"
        pose = "the same confident outfit-check pose from the reference"
        lighting = "flattering realistic phone lighting"
    else:
        environment = _environment_text(card)
        pose = _pose_text(card)
        lighting = _lighting_text(card)
    outfits = _variation_outfits_for_pair(pair, variation_layout)
    return (
        "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring six variations of the same Soul ID woman. "
        f"She is posing confidently for outfit-check selfies in {environment}. "
        f"All six panels show the same seductive pose: {pose}. "
        f"Body emphasis in every panel: {_body_emphasis_text()}. "
        "Outfit variations across the panels: "
        + " ".join(f"{idx}. {outfit}." for idx, outfit in enumerate(outfits, start=1))
        + f" {lighting}, photorealistic skin texture, realistic fabric stretch and cling, elegant modern interior, vertical composition inside each panel, iPhone selfie aesthetic, consistent face and body across all six panels, no extra panels, high detail, sharp focus."
    )


def _soul_grid_base_prompt(prompt: dict[str, Any]) -> str:
    card, ok = _image_prompt_card(prompt)
    if not ok:
        return _soul_image_prompt_text(prompt)
    positive_parts: list[str] = []
    for key in (
        "subject",
        "composition",
        "body",
        "clothing",
        "skin",
        "expression_mood",
        "environment",
        "lighting_and_camera",
        "must_keep",
    ):
        part = _positive_prompt_fragment(card.get(key))
        if part:
            positive_parts.append(part)
    return " ".join(positive_parts).strip()


def _variation_command(
    pair: PromptPair,
    media_ref: str,
    variation_model: str,
    variation_layout: str,
    wait: bool,
) -> list[str]:
    cmd = [
        "higgsfield",
        "--json",
        "generate",
        "create",
        variation_model,
        "--prompt",
        _variation_grid_prompt(pair, variation_layout=variation_layout),
        "--image",
        media_ref,
        "--aspect_ratio",
        "1:1",
    ]
    if wait:
        cmd.append("--wait")
    return cmd


def _video_command(
    pair: PromptPair, media_ref: str, kling_mode: str, wait: bool
) -> list[str]:
    cmd = [
        "higgsfield",
        "--json",
        "generate",
        "create",
        DEFAULT_VIDEO_MODEL,
        "--prompt",
        _kling_video_prompt_text(pair),
        "--start-image",
        media_ref,
        "--aspect_ratio",
        "9:16",
        "--duration",
        str(pair.video_prompt.get("durationSeconds") or 5),
        "--mode",
        kling_mode,
        "--sound",
        "off",
    ]
    if wait:
        cmd.append("--wait")
    return cmd


def _kling_video_prompt_text(pair: PromptPair) -> str:
    compiled = _compiled_prompts(pair.video_prompt)
    if (
        isinstance(compiled.get("kling_video_prompt"), str)
        and compiled["kling_video_prompt"].strip()
    ):
        prompt = compiled["kling_video_prompt"].strip()
        negative = str(compiled.get("kling_negative_prompt") or "").strip()
        if negative and "negative prompt" not in prompt.lower():
            prompt = f"{prompt} Negative prompt: {negative}"
        return prompt
    card, ok = _image_prompt_card(pair.image_prompt)
    duration = int(pair.video_prompt.get("durationSeconds") or 5)
    if ok:
        outfit = _primary_outfit_text(card)
        environment = _environment_text(card)
        lighting = _lighting_text(card)
    else:
        outfit = "tight bodycon outfit"
        environment = "the same reference setting"
        lighting = "soft realistic phone lighting"
    directives = (
        pair.video_prompt.get("motion_directives")
        if isinstance(pair.video_prompt.get("motion_directives"), dict)
        else {}
    )
    subject_motion = str(directives.get("subject_motion") or "").strip()
    camera_motion = str(
        directives.get("camera_motion") or "subtle natural handheld camera sway"
    ).strip()
    motion = (
        "slow rhythmic hip swaying side to side, strong arched back pushing out her round plump ass, "
        "visible glute movement and dress stretch, deep cleavage with natural breast bounce, "
        "one hand slowly running through her hair, seductive head tilts, and flirty facial expression changes"
    )
    if subject_motion and len(subject_motion) < 220:
        motion = f"{motion}, plus {subject_motion}"
    return (
        f"Stunning voluptuous woman in a tight {outfit}, taking a seductive selfie in {environment}. "
        "Start exactly from the reference image as Frame 0. "
        f"Animate smooth, sensual movement: {motion}. "
        f"Realistic iPhone Reels style, vertical 9:16, {camera_motion}, {lighting}, photorealistic skin and fabric movement, smooth motion. "
        f"Duration: {duration} seconds. "
        "Negative prompt: blurry, deformed, bad anatomy, flat chest, small breasts, flat ass, skinny body, loose dress, baggy clothing, zoom, fast motion, outfit change, background change, text, watermark, low quality, shaky, sudden jumps."
    )


def _compiled_prompts(prompt: dict[str, Any]) -> dict[str, Any]:
    compiled = prompt.get("compiledPrompts")
    return compiled if isinstance(compiled, dict) else {}


def _campaign_intake(
    *,
    campaign_factory_root: Path,
    input_path: Path,
    lineage_path: Path,
    campaign: str,
    model: str,
    creative_plan: str | None,
    runner: Runner,
    dry_run: bool,
) -> dict[str, Any]:
    python_path = campaign_factory_root / ".venv" / "bin" / "python"
    cmd = [
        "/usr/bin/env",
        f"PYTHONPATH={campaign_factory_root}",
        str(python_path),
        "-m",
        "campaign_factory.cli",
        "intake-finished-video",
        "--input",
        str(input_path),
        "--model",
        model,
        "--campaign",
        campaign,
        "--platform",
        "instagram",
        "--goal",
        "reach",
        "--source-lineage",
        str(lineage_path),
        "--dry-run-export",
    ]
    if creative_plan:
        cmd.extend(["--creative-plan", creative_plan])
    if dry_run:
        return {
            "schema": "reference_factory.campaign_intake.v1",
            "status": "dry_run",
            "command": cmd,
        }
    result = runner(cmd)
    return {
        "schema": "reference_factory.campaign_intake.v1",
        "status": "ok" if result.returncode == 0 else "failed",
        "command": cmd,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _lineage(
    *,
    pair: PromptPair,
    prompt_score: dict[str, Any],
    variation_prompt: str,
    fallback_video_prompt: str,
    soul_name: str,
    soul_uuid: str,
    image_result: dict[str, Any] | None,
    video_result: dict[str, Any] | None,
    variation_result: dict[str, Any] | None,
    candidate_results: list[dict[str, Any]],
    selected_candidate_index: int,
    local_image_path: str | None,
    local_video_path: str | None,
    local_variation_path: str | None,
    variation_model: str,
    variation_layout: str,
    variation_strategy: str,
    status: str,
    estimated_credits: float,
) -> dict[str, Any]:
    prompt_schema_version = _prompt_schema_version(pair.image_prompt)
    variation_provider = (
        DEFAULT_IMAGE_MODEL if variation_strategy == "soul_grid" else variation_model
    )
    selected_panel_path = (
        (variation_result or {}).get("selectedPanelPath")
        if isinstance(variation_result, dict)
        else None
    )
    selected_image_path = selected_panel_path or local_image_path
    return {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "pipelineTraceId": f"trace_higgsfield_{pair.reference_id}_{_result_id(video_result or {}) or _result_id(image_result or {}) or 'pending'}",
        "source": {
            "referenceId": pair.reference_id,
            "patternCardId": pair.image_prompt.get("sourcePatternId")
            or pair.video_prompt.get("sourcePatternId"),
            "promptId": pair.video_prompt.get("id") or pair.image_prompt.get("id"),
            "formatType": (pair.image_prompt.get("formatCard") or {}).get(
                "visualFormat"
            ),
            "promptSchemaVersion": prompt_schema_version,
        },
        "generation": {
            "tool": "higgsfield_kling_cli",
            "modelProfile": soul_name,
            "soulId": soul_uuid,
            "imageModel": DEFAULT_IMAGE_MODEL,
            "videoModel": DEFAULT_VIDEO_MODEL,
            "imageJobId": _result_id(image_result or {}),
            "videoJobId": _result_id(video_result or {}),
            "variationJobId": _result_id(variation_result or {}),
            "imageResultUrl": _result_url(image_result or {}),
            "videoResultUrl": _result_url(video_result or {}),
            "variationResultUrl": _result_url(variation_result or {}),
            "imagePath": local_image_path,
            "assetPath": local_video_path,
            "variationPath": local_variation_path,
            "status": status,
            "imageCandidates": _lineage_candidates(candidate_results),
            "selectedCandidateIndex": selected_candidate_index,
            "selectedImagePath": selected_image_path,
            "cost": {
                "estimatedCredits": estimated_credits,
                "actualCredits": _actual_credits_from_candidates(
                    candidate_results, video_result, variation_result
                ),
                "currency": "higgsfield_credits",
            },
            "fallback": {
                "provider": "grok_imagine",
                "when": "Use if Kling 3.0 rejects the prompt or fails generation.",
                "audio": "off",
                "prompt": fallback_video_prompt,
            },
            "variationGrid": {
                "provider": variation_provider,
                "layout": variation_layout,
                "strategy": (variation_result or {}).get("strategy")
                if isinstance(variation_result, dict)
                else variation_strategy,
                "prompt": variation_prompt,
                "status": _variation_status(variation_result),
                "panelVideoStatus": (variation_result or {}).get("panelVideoStatus")
                if isinstance(variation_result, dict)
                else None,
                "jobId": _result_id(variation_result or {}),
                "path": local_variation_path,
                "selectedPanelIndex": (variation_result or {}).get("selectedPanelIndex")
                if isinstance(variation_result, dict)
                else None,
                "selectedPanelPath": selected_panel_path,
                "gridVideoPath": (variation_result or {}).get("gridVideoPath")
                if isinstance(variation_result, dict)
                else None,
                "verticalSequenceVideoPath": (variation_result or {}).get(
                    "verticalSequenceVideoPath"
                )
                if isinstance(variation_result, dict)
                else None,
                "animatedGridVideoPath": (variation_result or {}).get(
                    "animatedGridVideoPath"
                )
                if isinstance(variation_result, dict)
                else None,
                "panels": (variation_result or {}).get("panels")
                if isinstance(variation_result, dict)
                else None,
                "panelVideos": (variation_result or {}).get("panelVideos")
                if isinstance(variation_result, dict)
                else None,
            },
        },
        "review": {
            "humanReviewRequired": True,
            "status": "draft",
        },
        "quality": {
            "copyRisk": "medium",
            "promptScore": prompt_score,
            "operatorRating": None,
        },
    }


def _variation_status(variation_result: dict[str, Any] | None) -> str:
    if not variation_result:
        return "planned"
    status = str(variation_result.get("status") or "").lower()
    if status in BLOCKED_PROVIDER_STATUSES:
        return "blocked"
    if status in FAILED_PROVIDER_STATUSES:
        return "failed"
    if not (_result_url(variation_result) or _result_local_path(variation_result)):
        if variation_result.get("command"):
            return "planned"
        return "failed"
    return "generated"


def _variation_result_is_reusable(variation_result: dict[str, Any]) -> bool:
    return _variation_status(variation_result) == "generated"


def _variation_grid_prompt(
    pair: PromptPair, *, variation_layout: str = DEFAULT_VARIATION_LAYOUT
) -> str:
    outfits = _variation_outfits_for_pair(pair, variation_layout)
    return (
        f"Make a {variation_layout} variation of this exact pose and background with these outfits: "
        f"Outfits: {', '.join(outfits)}. "
        "Keep the same person, phone covering the face, mirror-selfie framing, room, lighting, crop, and image quality. "
        "Only change the outfit. Sharp realistic phone-photo quality."
    )


def _individual_variation_commands(
    pair: PromptPair,
    media_ref: str,
    variation_model: str,
    variation_layout: str,
    wait: bool,
) -> list[list[str]]:
    commands = []
    for outfit in _variation_outfits_for_pair(pair, variation_layout):
        cmd = [
            "higgsfield",
            "--json",
            "generate",
            "create",
            variation_model,
            "--prompt",
            _variation_panel_prompt(outfit),
            "--image",
            media_ref,
            "--aspect_ratio",
            "9:16",
        ]
        if wait:
            cmd.append("--wait")
        commands.append(cmd)
    return commands


def _variation_panel_video_commands(
    pair: PromptPair,
    variation_layout: str,
    kling_mode: str,
    wait: bool,
) -> list[list[str]]:
    commands = []
    for idx, outfit in enumerate(
        _variation_outfits_for_pair(pair, variation_layout), start=1
    ):
        cmd = [
            "higgsfield",
            "--json",
            "generate",
            "create",
            DEFAULT_VIDEO_MODEL,
            "--prompt",
            _variation_panel_video_prompt(pair, outfit),
            "--start-image",
            f"<variation_panel_{idx}>",
            "--aspect_ratio",
            "9:16",
            "--duration",
            str(pair.video_prompt.get("durationSeconds") or 5),
            "--mode",
            kling_mode,
            "--sound",
            "off",
        ]
        if wait:
            cmd.append("--wait")
        commands.append(cmd)
    return commands


def _variation_panel_video_commands_from_result(
    pair: PromptPair,
    variation_result: dict[str, Any],
    kling_mode: str,
    wait: bool,
) -> list[list[str]]:
    panels = (
        variation_result.get("panels")
        if isinstance(variation_result.get("panels"), list)
        else []
    )
    commands = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        outfit = str(panel.get("outfit") or f"outfit {len(commands) + 1}")
        image_path = str(panel.get("path") or f"<variation_panel_{len(commands) + 1}>")
        cmd = [
            "higgsfield",
            "--json",
            "generate",
            "create",
            DEFAULT_VIDEO_MODEL,
            "--prompt",
            _variation_panel_video_prompt(pair, outfit),
            "--start-image",
            image_path,
            "--aspect_ratio",
            "9:16",
            "--duration",
            str(pair.video_prompt.get("durationSeconds") or 5),
            "--mode",
            kling_mode,
            "--sound",
            "off",
        ]
        if wait:
            cmd.append("--wait")
        commands.append(cmd)
    return commands


def _variation_panel_prompt(outfit: str) -> str:
    return (
        "Make one high-quality variation of this exact pose and background with this outfit: "
        f"{outfit}. Keep the same person, phone covering the face, mirror-selfie framing, "
        "side-profile pose, room, lighting, crop, and photo quality. Only change the outfit. "
        "Sharp realistic phone photo."
    )


def _variation_panel_video_prompt(pair: PromptPair, outfit: str) -> str:
    directives = (
        pair.video_prompt.get("motion_directives")
        if isinstance(pair.video_prompt.get("motion_directives"), dict)
        else {}
    )
    camera_motion = str(
        directives.get("camera_motion") or "very slight handheld phone sway"
    )
    return (
        "Use this image as the exact first frame. Create a short vertical mirror-selfie video with no audio. "
        f"Preserve the same outfit ({outfit}), face hidden by phone, side-profile pose, body crop, room, mirror, lighting, and iPhone realism. "
        "Motion: hold almost still, subtle breathing, tiny natural weight shift, slight free-arm movement, and very small hair movement. "
        f"Camera: {camera_motion}. "
        "Keep movement subtle and natural. No zoom. No face reveal. No outfit change. No text. No username. No UI. No watermark."
    )


def _variation_result_from_panel_dir(
    panel_dir: Path, *, variation_layout: str, dry_run: bool = False
) -> dict[str, Any]:
    panel_paths = _variation_panel_paths_from_dir(panel_dir, variation_layout)
    outfits = _variation_outfits(variation_layout)
    panels = [
        {
            "index": idx,
            "outfit": outfits[idx - 1],
            "path": str(path),
            "status": "existing" if not dry_run else "planned_existing",
        }
        for idx, path in enumerate(panel_paths, start=1)
    ]
    return {
        "schema": "reference_factory.higgsfield_variation_result.v1",
        "status": "completed" if not dry_run else "planned",
        "strategy": "existing_panel_folder",
        "layout": variation_layout,
        "panelDir": str(panel_dir),
        "path": str(panel_dir) if dry_run else None,
        "panels": panels,
    }


def _use_existing_variation_panels(
    *,
    out_dir: Path,
    panel_dir: Path,
    variation_layout: str,
) -> tuple[dict[str, Any], str | None]:
    variation_result = _variation_result_from_panel_dir(
        panel_dir, variation_layout=variation_layout
    )
    panel_paths = [Path(str(panel["path"])) for panel in variation_result["panels"]]
    grid_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_existing_panels.png"
    )
    grid_video_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_existing_panels.mp4"
    )
    vertical_sequence_path = (
        out_dir
        / f"variation_grid_{_safe_name(variation_layout)}_existing_panel_sequence.mp4"
    )
    _assemble_variation_grid(panel_paths, grid_path, variation_layout)
    _create_variation_grid_video(grid_path, grid_video_path)
    _create_variation_sequence_video(panel_paths, vertical_sequence_path)
    variation_result.update(
        {
            "path": str(grid_path),
            "gridVideoPath": str(grid_video_path),
            "verticalSequenceVideoPath": str(vertical_sequence_path),
        }
    )
    return variation_result, str(grid_path)


def _variation_panel_paths_from_dir(
    panel_dir: Path, variation_layout: str
) -> list[Path]:
    expected = len(_variation_outfits(variation_layout))
    if not panel_dir.exists() or not panel_dir.is_dir():
        raise FileNotFoundError(f"variation panel folder not found: {panel_dir}")
    paths = sorted(
        path
        for path in panel_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if len(paths) != expected:
        raise ValueError(
            f"{variation_layout} needs {expected} panel images in {panel_dir}, found {len(paths)}"
        )
    return paths


def _run_individual_variations(
    *,
    out_dir: Path,
    media_ref: str,
    pair: PromptPair,
    variation_model: str,
    variation_layout: str,
    wait: bool,
    runner: Runner,
) -> tuple[dict[str, Any], str | None]:
    panels: list[dict[str, Any]] = []
    panel_paths: list[Path] = []
    for idx, outfit in enumerate(
        _variation_outfits_for_pair(pair, variation_layout), start=1
    ):
        slug = f"{idx:02d}_{_safe_name(outfit)}"
        result_path = out_dir / f"variation_panel_{slug}_result.json"
        cmd = [
            "higgsfield",
            "--json",
            "generate",
            "create",
            variation_model,
            "--prompt",
            _variation_panel_prompt(outfit),
            "--image",
            media_ref,
            "--aspect_ratio",
            "9:16",
        ]
        if wait:
            cmd.append("--wait")

        if result_path.exists():
            panel_result = _normalize_result(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
            if not _variation_result_is_reusable(panel_result):
                panel_result = _run_json(cmd, runner)
                atomic_write_text(
                    result_path,
                    json.dumps(panel_result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
        else:
            panel_result = _run_json(cmd, runner)
            atomic_write_text(
                result_path,
                json.dumps(panel_result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        local_path = _materialize_result_asset(
            panel_result, out_dir / f"variation_panel_{slug}"
        )
        status = _variation_status(panel_result)
        if status == "generated" and local_path:
            panel_paths.append(Path(local_path))
        panels.append(
            {
                "index": idx,
                "outfit": outfit,
                "command": cmd,
                "jobId": _result_id(panel_result),
                "resultUrl": _result_url(panel_result),
                "path": local_path,
                "status": status,
            }
        )

    if len(panel_paths) != len(_variation_outfits(variation_layout)):
        return {
            "schema": "reference_factory.higgsfield_variation_result.v1",
            "status": "failed",
            "strategy": "individual",
            "layout": variation_layout,
            "panels": panels,
            "error": "not_all_variation_panels_generated",
        }, None

    grid_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_individual.png"
    )
    _assemble_variation_grid(panel_paths, grid_path, variation_layout)
    grid_video_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_individual.mp4"
    )
    vertical_sequence_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_sequence.mp4"
    )
    _create_variation_grid_video(grid_path, grid_video_path)
    _create_variation_sequence_video(panel_paths, vertical_sequence_path)
    return {
        "schema": "reference_factory.higgsfield_variation_result.v1",
        "status": "completed",
        "strategy": "individual",
        "layout": variation_layout,
        "path": str(grid_path),
        "gridVideoPath": str(grid_video_path),
        "verticalSequenceVideoPath": str(vertical_sequence_path),
        "panels": panels,
    }, str(grid_path)


def _run_variation_panel_videos(
    *,
    out_dir: Path,
    pair: PromptPair,
    variation_result: dict[str, Any],
    variation_layout: str,
    kling_mode: str,
    wait: bool,
    runner: Runner,
) -> dict[str, Any]:
    panels = (
        variation_result.get("panels")
        if isinstance(variation_result.get("panels"), list)
        else []
    )
    panel_videos: list[dict[str, Any]] = []
    video_paths: list[Path] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        idx = int(panel.get("index") or len(panel_videos) + 1)
        outfit = str(panel.get("outfit") or f"outfit {idx}")
        image_path = str(panel.get("path") or "")
        if not image_path:
            panel_videos.append(
                {
                    "index": idx,
                    "outfit": outfit,
                    "status": "failed",
                    "error": "missing_panel_image_path",
                }
            )
            continue
        result_path = out_dir / f"variation_panel_video_{idx:02d}_result.json"
        cmd = [
            "higgsfield",
            "--json",
            "generate",
            "create",
            DEFAULT_VIDEO_MODEL,
            "--prompt",
            _variation_panel_video_prompt(pair, outfit),
            "--start-image",
            image_path,
            "--aspect_ratio",
            "9:16",
            "--duration",
            str(pair.video_prompt.get("durationSeconds") or 5),
            "--mode",
            kling_mode,
            "--sound",
            "off",
        ]
        if wait:
            cmd.append("--wait")
        if result_path.exists():
            panel_result = _normalize_result(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
        else:
            panel_result = _run_json(cmd, runner)
            atomic_write_text(
                result_path,
                json.dumps(panel_result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        local_path = _materialize_result_asset(
            panel_result, out_dir / f"variation_panel_video_{idx:02d}"
        )
        status = "generated" if local_path else "failed"
        if local_path:
            video_paths.append(Path(local_path))
        panel_videos.append(
            {
                "index": idx,
                "outfit": outfit,
                "command": cmd,
                "jobId": _result_id(panel_result),
                "resultUrl": _result_url(panel_result),
                "path": local_path,
                "status": status,
            }
        )

    out = dict(variation_result)
    out["panelVideos"] = panel_videos
    expected = len(_variation_outfits(variation_layout))
    if len(video_paths) != expected:
        out["panelVideoStatus"] = "failed"
        out["panelVideoError"] = "not_all_panel_videos_generated"
        return out

    animated_grid_path = (
        out_dir / f"variation_grid_{_safe_name(variation_layout)}_kling_panels.mp4"
    )
    _assemble_variation_video_grid(video_paths, animated_grid_path, variation_layout)
    out["panelVideoStatus"] = "generated"
    out["animatedGridVideoPath"] = str(animated_grid_path)
    return out


def _assemble_variation_grid(
    panel_paths: list[Path], out_path: Path, variation_layout: str
) -> None:
    columns, rows = (3, 2) if variation_layout == "2x3" else (3, 3)
    expected = columns * rows
    if len(panel_paths) != expected:
        raise ValueError(
            f"{variation_layout} needs {expected} panel images, got {len(panel_paths)}"
        )
    inputs: list[str] = []
    filter_parts: list[str] = []
    layout_parts: list[str] = []
    for idx, path in enumerate(panel_paths):
        inputs.extend(["-i", str(path)])
        filter_parts.append(
            f"[{idx}:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960[v{idx}]"
        )
        col = idx % columns
        row = idx // columns
        layout_parts.append(f"{col * 540}_{row * 960}")
    stack_inputs = "".join(f"[v{idx}]" for idx in range(expected))
    filter_parts.append(
        f"{stack_inputs}xstack=inputs={expected}:layout={'|'.join(layout_parts)}[out]"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[out]",
        "-frames:v",
        "1",
        str(out_path),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to assemble variation grid")


def _assemble_variation_video_grid(
    video_paths: list[Path], out_path: Path, variation_layout: str
) -> None:
    columns, rows = (3, 2) if variation_layout == "2x3" else (3, 3)
    expected = columns * rows
    if len(video_paths) != expected:
        raise ValueError(
            f"{variation_layout} needs {expected} panel videos, got {len(video_paths)}"
        )
    inputs: list[str] = []
    filter_parts: list[str] = []
    layout_parts: list[str] = []
    for idx, path in enumerate(video_paths):
        inputs.extend(["-i", str(path)])
        filter_parts.append(
            f"[{idx}:v]scale=540:960:force_original_aspect_ratio=increase:flags=lanczos,crop=540:960,setpts=PTS-STARTPTS[v{idx}]"
        )
        col = idx % columns
        row = idx // columns
        layout_parts.append(f"{col * 540}_{row * 960}")
    stack_inputs = "".join(f"[v{idx}]" for idx in range(expected))
    filter_parts.append(
        f"{stack_inputs}xstack=inputs={expected}:layout={'|'.join(layout_parts)}:fill=black:shortest=1[out]"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[out]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "14",
        "-profile:v",
        "high",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "failed to assemble variation video grid"
        )


def _create_variation_grid_video(grid_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "24",
        "-i",
        str(grid_path),
        "-t",
        str(DEFAULT_VARIATION_VIDEO_SECONDS),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,format=yuv420p",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "14",
        "-profile:v",
        "high",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "failed to create variation grid video"
        )


def _default_soul_grid_selected_panel(variation_layout: str) -> int:
    return 5 if variation_layout == "2x3" else 5


def _extract_soul_grid_selected_panel(
    grid_path: Path, *, out_dir: Path, variation_layout: str
) -> Path:
    columns, rows = (3, 2) if variation_layout == "2x3" else (3, 3)
    selected_index = min(
        _default_soul_grid_selected_panel(variation_layout), columns * rows
    )
    width, height = _image_dimensions(grid_path)
    panel_width = width // columns
    panel_height = height // rows
    col = (selected_index - 1) % columns
    row = (selected_index - 1) // columns
    x = col * panel_width
    y = row * panel_height
    target_height = round(panel_width * 16 / 9)
    target_width = panel_width
    if target_height <= panel_height:
        y += max(0, (panel_height - target_height) // 2)
    else:
        target_height = panel_height
        target_width = round(panel_height * 9 / 16)
        x += max(0, (panel_width - target_width) // 2)
    out_path = (
        out_dir
        / f"higgsfield_soul_grid_{_safe_name(variation_layout)}_selected_panel_{selected_index}_9x16.png"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(grid_path),
        "-vf",
        f"crop={target_width}:{target_height}:{x}:{y},scale=1080:1920:flags=lanczos",
        "-frames:v",
        "1",
        str(out_path),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "failed to crop selected soul-grid panel"
        )
    return out_path


def _image_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or f"failed to read image dimensions for {path}"
        )
    width_match = re.search(r"pixelWidth:\s*(\d+)", result.stdout)
    height_match = re.search(r"pixelHeight:\s*(\d+)", result.stdout)
    if not width_match or not height_match:
        raise RuntimeError(f"failed to parse image dimensions for {path}")
    return int(width_match.group(1)), int(height_match.group(1))


def _create_variation_sequence_video(panel_paths: list[Path], out_path: Path) -> None:
    temp_dir = out_path.parent / f".{out_path.stem}_segments"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        list_path = temp_dir / "concat.txt"
        segment_paths: list[Path] = []
        per_panel_seconds = max(
            1, round(DEFAULT_VARIATION_VIDEO_SECONDS / max(1, len(panel_paths)))
        )
        for idx, path in enumerate(panel_paths, start=1):
            segment = temp_dir / f"segment_{idx:02d}.mp4"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "24",
                "-i",
                str(path),
                "-t",
                str(per_panel_seconds),
                "-vf",
                (
                    "scale=1120:1992:force_original_aspect_ratio=increase:flags=lanczos,"
                    "crop=1080:1920,"
                    "zoompan=z='min(zoom+0.0015,1.04)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    "d=1:s=1080x1920:fps=24,"
                    "format=yuv420p"
                ),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "14",
                "-profile:v",
                "high",
                "-level",
                "4.2",
                "-movflags",
                "+faststart",
                str(segment),
            ]
            result = subprocess.run(cmd, text=True, capture_output=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip()
                    or "failed to create variation sequence segment"
                )
            segment_paths.append(segment)
        atomic_write_text(
            list_path,
            "".join(f"file '{path}'\n" for path in segment_paths),
            encoding="utf-8",
        )
        concat_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_path),
        ]
        result = subprocess.run(concat_cmd, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "failed to create variation sequence video"
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _variation_outfits(variation_layout: str) -> list[str]:
    base = [
        "leopard-print fitted mini dress matching the reference outfit",
        "slightly shorter leopard-print bodycon mini dress",
        "brown-and-black animal-print strapless mini dress",
        "black fitted bodysuit with a low neckline",
        "cream off-shoulder fitted mini-dress variation",
        "forest green fitted velvet mini-dress variation",
    ]
    if variation_layout == "3x3":
        return base + [
            "navy ribbed tank top",
            "chocolate fuzzy cropped sweater",
            "white lace camisole",
        ]
    return base


def _variation_outfits_for_pair(pair: PromptPair, variation_layout: str) -> list[str]:
    text = json.dumps(pair.image_prompt, ensure_ascii=False).lower()
    if any(
        term in text
        for term in (
            "pale blue",
            "strapless",
            "maxi dress",
            "stone fireplace",
            "fireplace",
        )
    ):
        base = [
            "pale blue strapless fitted bodycon dress matching the reference outfit",
            "slightly shorter pale blue strapless fitted dress",
            "icy blue tube dress with a cleavage-enhancing fitted chest",
            "white strapless bodycon dress in the same silhouette",
            "soft grey fitted maxi dress with the same body-hugging shape",
            "black strapless fitted dress with a low neckline",
        ]
        if variation_layout == "3x3":
            return base + [
                "cream strapless fitted dress variation",
                "blush pink bodycon dress variation",
                "forest green fitted dress variation",
            ]
        return base
    return _variation_outfits(variation_layout)


def _fallback_video_prompt(pair: PromptPair) -> str:
    return (
        "Animate the selected image as a short vertical IG Reels style clip with no audio. "
        "Keep the first-frame identity, pose, outfit, room, lighting, crop, and phone/camera placement consistent. "
        f"Motion intent: {_kling_video_prompt_text(pair)}"
    )


def _prompt_schema_version(prompt: dict[str, Any]) -> str | None:
    card, _ok = _image_prompt_card(prompt)
    value = card.get("prompt_schema_version") if isinstance(card, dict) else None
    return str(value) if value else None


def _lineage_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in candidates:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        output.append(
            {
                "candidateIndex": item.get("candidateIndex"),
                "jobId": item.get("jobId") or _result_id(result),
                "resultUrl": item.get("resultUrl") or _result_url(result),
                "localPath": item.get("localPath"),
                "selected": bool(item.get("selected")),
            }
        )
    return output


def _actual_credits(*results: dict[str, Any] | None) -> float | None:
    total = 0.0
    found = False
    for result in results:
        value = _result_credits(result or {})
        if value is not None:
            total += value
            found = True
    return round(total, 4) if found else None


def _actual_credits_from_candidates(
    candidates: list[dict[str, Any]], *results: dict[str, Any] | None
) -> float | None:
    candidate_results = [
        item.get("result")
        for item in candidates
        if isinstance(item.get("result"), dict)
    ]
    return _actual_credits(*candidate_results, *results)


def _result_credits(result: dict[str, Any]) -> float | None:
    for key in ("credits", "creditCost", "costCredits", "cost"):
        value = result.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
    nested = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    if nested:
        return _result_credits(nested)
    return None


def _run_json(cmd: list[str], runner: Runner) -> dict[str, Any]:
    result = runner(cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(cmd)}")
    try:
        parsed = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Higgsfield CLI returned non-JSON output: {result.stdout[:300]}"
        ) from exc
    return _normalize_result(parsed)


def _normalize_result(parsed: Any) -> dict[str, Any]:
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _materialize_result_asset(result: dict[str, Any], prefix: Path) -> str | None:
    local = _result_local_path(result)
    if local and Path(local).exists():
        suffix = Path(local).suffix or ".bin"
        target = prefix.with_suffix(suffix)
        copied = False
        if Path(local).resolve() != target.resolve():
            shutil.copy2(local, target)
            copied = True
        if target.stat().st_size < MIN_RESULT_BYTES:
            if copied:
                target.unlink(missing_ok=True)
            return None
        return str(target)
    url = _result_url(result)
    if url and url.startswith("http"):
        suffix = _suffix_for_url(url)
        target = prefix.with_suffix(suffix)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                target.write_bytes(response.read())
            if target.stat().st_size < MIN_RESULT_BYTES:
                target.unlink(missing_ok=True)
                return None
            return str(target)
        except Exception:
            return None
    return None


def _write_job_id(path: Path, result: dict[str, Any]) -> None:
    job_id = _result_id(result)
    if job_id:
        atomic_write_text(path, job_id + "\n", encoding="utf-8")


def _raise_for_provider_status(result: dict[str, Any]) -> None:
    status = _provider_status(result)
    if status in BLOCKED_PROVIDER_STATUSES:
        raise RuntimeError(f"Higgsfield provider blocked generation: {status}")
    if status in FAILED_PROVIDER_STATUSES:
        raise RuntimeError(f"Higgsfield provider failed generation: {status}")


def _provider_status(result: dict[str, Any]) -> str | None:
    for key in ("status", "state"):
        value = str(result.get(key) or "").strip().lower()
        if value:
            return value
    first = _first_nested_result(result)
    if first is not None and first is not result:
        return _provider_status(first)
    return None


def _result_id_or_url(result: dict[str, Any]) -> str | None:
    return _result_id(result) or _result_url(result) or _result_local_path(result)


def _result_id(result: dict[str, Any]) -> str | None:
    for key in ("id", "job_id", "jobId", "uuid"):
        if result.get(key):
            return str(result[key])
    nested = result.get("job") if isinstance(result.get("job"), dict) else {}
    if nested.get("id"):
        return str(nested["id"])
    first = _first_nested_result(result)
    if first is not None and first is not result:
        return _result_id(first)
    return None


def _result_url(result: dict[str, Any]) -> str | None:
    for key in ("url", "result_url", "resultUrl", "download_url", "downloadUrl"):
        if result.get(key):
            return str(result[key])
    for key in ("outputs", "output", "results", "media", "medias", "assets"):
        value = result.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    return item
                if isinstance(item, dict):
                    found = _result_url(item)
                    if found:
                        return found
        if isinstance(value, dict):
            found = _result_url(value)
            if found:
                return found
    first = _first_nested_result(result)
    if first is not None and first is not result:
        return _result_url(first)
    return None


def _result_local_path(result: dict[str, Any]) -> str | None:
    for key in ("path", "file", "local_path", "localPath", "assetPath"):
        if result.get(key):
            return str(result[key])
    first = _first_nested_result(result)
    if first is not None and first is not result:
        return _result_local_path(first)
    return None


def _first_nested_result(result: dict[str, Any]) -> dict[str, Any] | None:
    value = result.get("result")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    if isinstance(value, dict):
        return value
    return None


def _suffix_for_url(url: str) -> str:
    clean = url.split("?", 1)[0].lower()
    for suffix in (".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg"):
        if clean.endswith(suffix):
            return suffix
    return ".bin"


def _safe_name(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)[:120]
        or "generated"
    )


def _day() -> str:
    return datetime.now(UTC).date().isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat()
