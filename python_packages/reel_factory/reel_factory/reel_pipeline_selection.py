"""Caption discovery, fitting, recipe selection, and recovery for Reel Pipeline."""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from .caption_bank import caption_static_metadata, load_or_build_caption_bank_store
from .caption_render import CAPTION_LEGIBILITY_SHRINK_FLOOR
from .caption_scene_fit import (
    CAPTION_SCENE_FIT_VERSION,
    CAPTION_TOPIC_FIT_VERSION,
    caption_text_for_scene,
    evaluate_scene_compatibility,
    topic_caption_banks,
)
from .discoverability_safety import discoverability_safe_content_contract
from .manifest import Manifest
from .placement import PlacementSummary
from .reel_pipeline_support import (
    RECIPES,
    RECIPES_BY_NAME,
    CaptionSet,
    Recipe,
    find_caption_for,
    log,
)


def discover_pairs(raw_dir: Path, cap_dir: Path) -> list[tuple[Path, CaptionSet]]:
    pairs: list[tuple[Path, CaptionSet]] = []
    for video in sorted(raw_dir.glob("*.mp4")):
        cap_set = find_caption_for(video, cap_dir)
        if cap_set is None:
            log.warning(f"no caption for {video.name}; skipping")
            continue
        pairs.append((video, cap_set))
    return pairs


def caption_set_from_bank_selection(
    root: Path,
    *,
    caption_mix: str | None,
    caption_banks: list[str] | None,
    caption_topic: str | None = None,
    limit: int | None,
    seed: int,
) -> CaptionSet:
    store = load_or_build_caption_bank_store(root)
    if caption_banks:
        selected = store.resolve_banks(caption_banks, limit=limit, seed=seed)
        selected_mix = None
    elif caption_mix:
        selected = store.resolve_mix(caption_mix, limit=limit, seed=seed)
        selected_mix = caption_mix
    else:
        raise ValueError("caption_mix or caption_banks is required")
    topic_banks = topic_caption_banks(caption_topic)
    if topic_banks and not caption_banks:
        selected = [
            item
            for item in selected
            if set(item.get("selected_banks") or []) & set(topic_banks)
        ]
    if not selected:
        if topic_banks:
            raise ValueError(
                "caption bank selection produced no hooks for "
                f"caption_topic={caption_topic} banks={','.join(topic_banks)}"
            )
        raise ValueError("caption bank selection produced no hooks")
    unsafe_items = []
    for item in selected:
        contract = discoverability_safe_content_contract(item.get("text") or "")
        if not contract["discoverabilitySafe"]:
            unsafe_items.append((item, contract))
    if unsafe_items:
        item, contract = unsafe_items[0]
        raise ValueError(
            "caption bank selection contains discoverability unsafe caption "
            f"source={item.get('source_file')} terms={','.join(contract['blockedTerms'])}: "
            f"{item.get('text')}"
        )
    hooks = [item["text"] for item in selected]
    lineage = {
        idx: {
            **store.lineage_for(
                item,
                selected_mix=selected_mix,
                selected_banks=item.get("selected_banks") or [],
            ),
            **(
                {
                    "captionTopic": caption_topic,
                    "captionTopicBanks": topic_banks,
                    "captionTopicFitVersion": CAPTION_TOPIC_FIT_VERSION,
                }
                if topic_banks
                else {}
            ),
        }
        for idx, item in enumerate(selected)
    }
    notes = (
        f"caption_mix={caption_mix}"
        if caption_mix
        else f"caption_banks={','.join(caption_banks or [])}"
    )
    if topic_banks:
        notes = f"{notes}; caption_topic={caption_topic}"
    return CaptionSet(
        hooks=hooks,
        recipe_names=None,
        caption_color=None,
        notes=notes,
        hook_lineage=lineage,
    )


STATIC_ALLOWED_LENGTHS = {
    "closeup": {"very_short", "short", "medium", "long"},
    "halfbody": {"very_short", "short", "medium"},
    "mirror_fullbody": {"very_short", "short"},
    "wide_fullbody": {"very_short", "short"},
    "gym_body": {"very_short", "short", "medium"},
    "unknown": {"very_short", "short", "medium"},
}
CAPTION_FIT_VERSION = "v1"
CAPTION_LEGIBLE_MAX_LINES = 5
CAPTION_LEGIBLE_CHARS_PER_LINE = 30
STATIC_FALLBACK_LENGTHS = {
    "closeup": {"very_short", "short", "medium", "long"},
    "halfbody": {"very_short", "short", "medium"},
    "mirror_fullbody": {"very_short", "short", "medium"},
    "wide_fullbody": {"very_short", "short", "medium"},
    "gym_body": {"very_short", "short", "medium"},
    "unknown": {"very_short", "short", "medium"},
}


def _caption_legibility_capacity(
    hook: str | dict, *, format_class: str
) -> tuple[bool, str, int]:
    text = caption_text_for_scene(hook)
    lines = text.splitlines() or [text]
    estimated_lines = sum(
        max(1, math.ceil(len(line.strip()) / CAPTION_LEGIBLE_CHARS_PER_LINE))
        for line in lines
        if line.strip()
    )
    estimated_lines = max(1, estimated_lines)
    if estimated_lines <= CAPTION_LEGIBLE_MAX_LINES:
        return (
            True,
            f"estimated {estimated_lines} lines fits legible render capacity",
            estimated_lines,
        )
    return (
        False,
        "caption exceeds legible render capacity "
        f"({estimated_lines}>{CAPTION_LEGIBLE_MAX_LINES} lines at "
        f"{CAPTION_LEGIBILITY_SHRINK_FLOOR:.2f}x floor)",
        estimated_lines,
    )


def classify_frame_type_for_caption_fit(
    summary: PlacementSummary,
    *,
    src_dims: tuple[int, int],
    video_stem: str = "",
) -> str:
    stem = video_stem.lower()
    metadata = getattr(summary, "metadata", {}) or {}
    face_mean = float(metadata.get("face_coverage_mean") or 0.0)
    pose_mean = float(metadata.get("pose_coverage_mean") or 0.0)
    width, height = src_dims
    aspect = width / max(1, height)

    if "gym" in stem or "fitness" in stem or "workout" in stem:
        return "gym_body"
    if face_mean >= 0.12:
        return "closeup"
    if face_mean >= 0.035:
        return "halfbody"
    if pose_mean >= 0.08:
        return "mirror_fullbody"
    if aspect < 0.68 and face_mean < 0.025:
        return "wide_fullbody"
    return "unknown"


def _caption_sort_key_for_fit(
    index: int, hook: str | dict, lineage: dict
) -> tuple[int, int, int]:
    metadata = caption_static_metadata(
        json.dumps(hook, sort_keys=True, ensure_ascii=False)
        if isinstance(hook, dict)
        else str(hook)
    )
    length_rank = {"very_short": 0, "short": 1, "medium": 2, "long": 3}
    return (
        length_rank.get(lineage.get("lengthClass") or metadata["length_class"], 4),
        int(lineage.get("wordCount") or metadata["word_count"]),
        index,
    )


def _weighted_sample_caption_rows(
    rows: list[tuple[int, str | dict, dict]],
    *,
    limit: int,
    seed: int,
) -> list[tuple[int, str | dict, dict]]:
    rng = random.Random(seed)
    pool = list(rows)
    selected: list[tuple[int, str | dict, dict]] = []
    while pool and len(selected) < limit:
        weights = [max(1, int(row[2].get("selectedBankWeight") or 1)) for row in pool]
        pick = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        selected.append(pool.pop(pick))
    return sorted(selected, key=lambda row: row[0])


def apply_caption_fit_to_caption_set(
    cap_set: CaptionSet,
    *,
    frame_type: str,
    reel_scene_tags: list[str] | None = None,
    caption_topic: str | None = None,
    max_hooks: int | None,
    seed: int,
    fit_mode: str,
    scene_fit_mode: str = "auto",
) -> tuple[CaptionSet, list[dict]]:
    if fit_mode not in {"auto", "off"}:
        raise ValueError(f"unknown caption fit mode: {fit_mode}")
    if scene_fit_mode not in {"auto", "off"}:
        raise ValueError(f"unknown caption scene fit mode: {scene_fit_mode}")

    diagnostics: list[dict] = []
    if fit_mode == "off":
        for idx, hook in enumerate(cap_set.hooks):
            text = (
                json.dumps(hook, sort_keys=True, ensure_ascii=False)
                if isinstance(hook, dict)
                else str(hook)
            )
            lineage = dict(cap_set.hook_lineage.get(idx) or {})
            meta = caption_static_metadata(text)
            scene = evaluate_scene_compatibility(
                caption_text=caption_text_for_scene(hook),
                caption_lineage=lineage,
                reel_scene_tags=reel_scene_tags,
                scene_fit_mode="off",
            )
            diagnostics.append(
                {
                    "caption": text,
                    "bank": (
                        lineage.get("selectedBanks")
                        or lineage.get("sourceBanks")
                        or [None]
                    )[0],
                    "length_class": lineage.get("lengthClass") or meta["length_class"],
                    "format_class": lineage.get("formatClass") or meta["format_class"],
                    "frame_type": frame_type,
                    "captionFitVersion": CAPTION_FIT_VERSION,
                    "suitabilityDecision": "fit_disabled",
                    "reason": "caption fit disabled",
                    "captionSceneTags": scene.caption_scene_tags,
                    "reelSceneTags": scene.reel_scene_tags,
                    "sceneCompatibilityDecision": scene.decision,
                    "sceneCompatibilityReason": scene.reason,
                    "captionSceneFitVersion": CAPTION_SCENE_FIT_VERSION,
                }
            )
        return cap_set, diagnostics

    allowed_lengths = STATIC_ALLOWED_LENGTHS.get(
        frame_type, STATIC_ALLOWED_LENGTHS["unknown"]
    )
    fallback_lengths = STATIC_FALLBACK_LENGTHS.get(
        frame_type, STATIC_FALLBACK_LENGTHS["unknown"]
    )
    topic_banks = topic_caption_banks(caption_topic)
    allowed: list[tuple[int, str | dict, dict]] = []
    fallback: list[tuple[int, str | dict, dict]] = []

    for idx, hook in enumerate(cap_set.hooks):
        text = (
            json.dumps(hook, sort_keys=True, ensure_ascii=False)
            if isinstance(hook, dict)
            else str(hook)
        )
        lineage = dict(cap_set.hook_lineage.get(idx) or {})
        meta = caption_static_metadata(text)
        length_class = lineage.get("lengthClass") or meta["length_class"]
        format_class = lineage.get("formatClass") or meta["format_class"]
        bank = (lineage.get("selectedBanks") or lineage.get("sourceBanks") or [None])[0]
        selected_banks = {
            str(bank_name)
            for bank_name in (
                lineage.get("selectedBanks") or lineage.get("sourceBanks") or []
            )
        }
        topic_allowed = not topic_banks or bool(selected_banks & set(topic_banks))
        renderable, render_reason, estimated_render_lines = (
            _caption_legibility_capacity(hook, format_class=format_class)
        )
        readable = length_class in allowed_lengths and renderable
        scene = evaluate_scene_compatibility(
            caption_text=caption_text_for_scene(hook),
            caption_lineage=lineage,
            reel_scene_tags=reel_scene_tags,
            scene_fit_mode=scene_fit_mode,
        )
        if readable:
            decision = "allowed"
            reason = f"{length_class} static caption allowed for {frame_type}"
        elif not renderable:
            decision = "unrenderable"
            reason = render_reason
        else:
            decision = "skipped"
            reason = f"{length_class} static caption too long for {frame_type}"
        topic_decision = "fit_disabled"
        topic_reason = "caption topic fit disabled"
        if topic_banks:
            topic_decision = "allowed" if topic_allowed else "blocked"
            topic_reason = (
                f"caption banks match {caption_topic}"
                if topic_allowed
                else f"caption topic {caption_topic} requires one of "
                f"{','.join(topic_banks)}; got {','.join(sorted(selected_banks)) or 'unknown'}"
            )
            if not topic_allowed:
                decision = "topic_mismatch"
                reason = topic_reason
        row = {
            "caption": text,
            "bank": bank,
            "length_class": length_class,
            "format_class": format_class,
            "frame_type": frame_type,
            "captionFitVersion": CAPTION_FIT_VERSION,
            "suitabilityDecision": decision,
            "reason": reason,
            "estimatedRenderLines": estimated_render_lines,
            "renderLegibilityFloor": CAPTION_LEGIBILITY_SHRINK_FLOOR,
            "captionSceneTags": scene.caption_scene_tags,
            "reelSceneTags": scene.reel_scene_tags,
            "sceneCompatibilityDecision": scene.decision,
            "sceneCompatibilityReason": scene.reason,
            "captionSceneFitVersion": CAPTION_SCENE_FIT_VERSION,
            "captionTopic": caption_topic,
            "captionTopicBanks": topic_banks,
            "captionTopicDecision": topic_decision,
            "captionTopicReason": topic_reason,
            "captionTopicFitVersion": CAPTION_TOPIC_FIT_VERSION,
        }
        diagnostics.append(row)
        enriched_lineage = {
            **lineage,
            "lengthClass": length_class,
            "formatClass": format_class,
            "wordCount": lineage.get("wordCount") or meta["word_count"],
            "charCount": lineage.get("charCount") or meta["char_count"],
            "lineCount": lineage.get("lineCount") or meta["line_count"],
            "frameType": frame_type,
            "captionFitVersion": CAPTION_FIT_VERSION,
            "suitabilityDecision": decision,
            "suitabilityReason": reason,
            "estimatedRenderLines": estimated_render_lines,
            "renderLegibilityFloor": CAPTION_LEGIBILITY_SHRINK_FLOOR,
            "captionSceneTags": scene.caption_scene_tags,
            "reelSceneTags": scene.reel_scene_tags,
            "sceneCompatibilityDecision": scene.decision,
            "sceneCompatibilityReason": scene.reason,
            "captionSceneFitVersion": CAPTION_SCENE_FIT_VERSION,
            "captionTopic": caption_topic,
            "captionTopicBanks": topic_banks,
            "captionTopicDecision": topic_decision,
            "captionTopicReason": topic_reason,
            "captionTopicFitVersion": CAPTION_TOPIC_FIT_VERSION,
        }
        scene_allowed = scene.decision in {"allowed", "unknown_allowed", "fit_disabled"}
        if topic_allowed and readable and scene_allowed:
            allowed.append((idx, hook, enriched_lineage))
        elif topic_allowed and renderable and scene_allowed:
            fallback.append((idx, hook, enriched_lineage))

    target = max_hooks if max_hooks is not None else len(cap_set.hooks)
    target = min(target, len(cap_set.hooks))
    selected = list(allowed)
    if len(selected) < target:
        for item in sorted(fallback, key=lambda row: _caption_sort_key_for_fit(*row)):
            idx, hook, lineage = item
            if lineage.get("lengthClass") not in fallback_lengths:
                continue
            fallback_reason = (
                f"fallback shortest available caption after static fit for {frame_type}"
            )
            lineage = {
                **lineage,
                "suitabilityDecision": "fallback_short",
                "suitabilityReason": fallback_reason,
            }
            selected.append((idx, hook, lineage))
            for row in diagnostics:
                if row["caption"] == (
                    json.dumps(hook, sort_keys=True, ensure_ascii=False)
                    if isinstance(hook, dict)
                    else str(hook)
                ):
                    row["suitabilityDecision"] = "fallback_short"
                    row["reason"] = fallback_reason
                    break
            if len(selected) >= target:
                break

    if max_hooks is not None and len(selected) > max_hooks:
        sampled = _weighted_sample_caption_rows(selected, limit=max_hooks, seed=seed)
        kept_indices = {idx for idx, _, _ in sampled}
        selected = sampled
        for row_idx, row in enumerate(diagnostics):
            if row_idx not in kept_indices and row["suitabilityDecision"] == "allowed":
                row["suitabilityDecision"] = "downweighted"
                row["reason"] = (
                    f"readable for {frame_type}, but not selected by weighted sample"
                )

    hooks = [hook for _, hook, _ in selected]
    lineage = {
        new_idx: item_lineage for new_idx, (_, _, item_lineage) in enumerate(selected)
    }
    return CaptionSet(
        hooks=hooks,
        recipe_names=cap_set.recipe_names,
        caption_color=cap_set.caption_color,
        notes=f"{cap_set.notes}; caption_fit={fit_mode}; frame_type={frame_type}"
        + (f"; caption_topic={caption_topic}" if caption_topic else ""),
        hook_lineage=lineage,
        band=cap_set.band,
    ), diagnostics


def select_recipes(cap_set: CaptionSet, override: list[str] | None) -> list[Recipe]:
    if override:
        unknown = [n for n in override if n not in RECIPES_BY_NAME]
        if unknown:
            raise ValueError(f"unknown recipe(s): {', '.join(unknown)}")
        return [RECIPES_BY_NAME[n] for n in override]
    if cap_set.recipe_names:
        unknown = [n for n in cap_set.recipe_names if n not in RECIPES_BY_NAME]
        if unknown:
            raise ValueError(f"unknown recipe(s) in sidecar: {', '.join(unknown)}")
        return [RECIPES_BY_NAME[n] for n in cap_set.recipe_names]
    return RECIPES


def limit_render_pool(
    hooks_pool: list[tuple[int, str | dict]],
    recipes_pool: list[Recipe],
    *,
    per_clip: int | None,
    hook_select: str,
    seed: int,
    recipe_order: list[Recipe],
) -> tuple[list[tuple[int, str | dict]], list[Recipe]]:
    if per_clip is None:
        return hooks_pool, recipes_pool
    total = len(hooks_pool) * len(recipes_pool)
    if total <= per_clip or not recipes_pool:
        return hooks_pool, recipes_pool

    per_clip = max(1, int(per_clip))
    rng = random.Random(seed)
    if len(recipes_pool) >= per_clip:
        if hook_select == "first":
            selected_recipes = recipes_pool[:per_clip]
        else:
            selected_recipes = sorted(
                rng.sample(recipes_pool, per_clip),
                key=lambda r: [rr.name for rr in recipe_order].index(r.name),
            )
        return hooks_pool[:1], selected_recipes

    target_hooks = max(1, per_clip // len(recipes_pool))
    return hooks_pool[:target_hooks], recipes_pool


def reconcile_interrupted_temp_outputs(proc_dir: Path, manifest: Manifest) -> int:
    """Record temp render outputs left behind by a previous interrupted run."""
    count = 0
    for tmp_dir in proc_dir.glob("*/.tmp/*"):
        if not tmp_dir.is_dir():
            continue
        mp4s = list(tmp_dir.glob("*.mp4"))
        if not mp4s:
            try:
                tmp_dir.rmdir()
            except OSError:
                pass
            continue
        clip_dir = tmp_dir.parent.parent
        for temp_mp4 in mp4s:
            final_path = clip_dir / temp_mp4.name
            if final_path.exists():
                continue
            manifest.add_attempt(
                key=f"interrupted:{tmp_dir.name}",
                attempt_no=count,
                status="interrupted",
                temp_path=temp_mp4,
                final_path=final_path,
                ffmpeg_cmd=[],
                started_at=int(temp_mp4.stat().st_mtime),
                ended_at=int(time.time()),
                error_message="stale temp output found on startup",
            )
            count += 1
    if count:
        log.warning(f"startup recovery: recorded {count} stale temp output(s)")
    return count
