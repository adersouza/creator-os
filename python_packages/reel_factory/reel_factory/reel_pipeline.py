"""
reel_pipeline.py — caption burn-in + silent variation generation.
M4 Max optimized: h264_videotoolbox, configurable encodes, PNG caption overlays.

Audio is intentionally stripped (-an) — attach trending sounds in-app or via
your downstream Juno33 muxer. The orchestrator outputs silent, captioned MP4s.

Usage:
    python -m reel_factory.reel_pipeline --root .
    python -m reel_factory.reel_pipeline --root . --recipes v01_original v05_hflip
    python -m reel_factory.reel_pipeline --root . --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys as sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import reel_pipeline_support as _pipeline_support
from .caption_scene_fit import (
    CAPTION_TOPIC_ORDER,
    classify_reel_scene_tags,
    infer_caption_topic_for_reel,
)
from .evidence_store import link_campaign_output
from .fileops import atomic_write_text
from .graph_builder import ENCODER_PROFILES
from .identity_verification import get_identity_provider
from .manifest import Manifest
from .media_metadata import normalize_media_metadata
from .perceptual import enrich_lineage_identity
from .placement import (
    CaptionSegmentPlan,
    PlacementSummary,
    pick_caption_color,
    probe_caption_layout,
    probe_caption_region_luminance,
    probe_dimensions,
    probe_duration,
    probe_source_bitrate,
    resolve_segment_bands,
)
from .preflight import check_clip_readiness
from .project_config import load_config
from .reel_pipeline_render import process_one
from .reel_pipeline_selection import (
    apply_caption_fit_to_caption_set,
    caption_set_from_bank_selection,
    classify_frame_type_for_caption_fit,
    discover_pairs,
    limit_render_pool,
    reconcile_interrupted_temp_outputs,
    select_recipes,
)
from .reel_pipeline_support import (
    AUDIO_SELECTION_PATH_KEYS,
    CREATOR_STYLE_PRESETS,
    DEFAULT_CAPTION_FONT,
    FFPROBE,
    INSTAGRAM_BOLD_CAPTION_FONT,
    CaptionSet,
    Recipe,
    apply_creator_style_preset,
    approve_operator_band,
    build_avconvert_finalize_cmd,
    build_caption_outcome_context,
    build_caption_placement_qc_row,
    build_phone_finalize_cmd,
    build_single_job_enqueue_cmd,
    centered_static_caption_band,
    compute_job_key,
    effective_placement_mode_for_caption,
    log,
    phone_creation_time,
    reexec_with_homebrew_gi_env_if_needed,
    resolve_caption_font_policy,
    sha256_file,
    timed_caption_band,
    vary_band_within_lane,
    write_caption_lineage_sidecar,
    write_required_similarity_audit,
)
from .render_plan import validate_account_scope
from .variation_engine import get_pack_version

__all__ = [
    "DEFAULT_CAPTION_FONT",
    "INSTAGRAM_BOLD_CAPTION_FONT",
    "CaptionSegmentPlan",
    "CaptionSet",
    "Manifest",
    "Recipe",
    "amain",
    "apply_caption_fit_to_caption_set",
    "apply_creator_style_preset",
    "approve_operator_band",
    "build_avconvert_finalize_cmd",
    "build_caption_outcome_context",
    "build_caption_placement_qc_row",
    "build_phone_finalize_cmd",
    "build_single_job_enqueue_cmd",
    "caption_set_from_bank_selection",
    "centered_static_caption_band",
    "compute_job_key",
    "effective_placement_mode_for_caption",
    "enforce_production_identity_provider",
    "limit_render_pool",
    "main",
    "normalize_rendered_mp4_metadata",
    "phone_creation_time",
    "process_one",
    "reconcile_interrupted_temp_outputs",
    "resolve_caption_font_policy",
    "resolve_segment_bands",
    "run_watch_mode",
    "timed_caption_band",
    "vary_band_within_lane",
    "write_caption_lineage_sidecar",
    "write_generated_asset_lineage_sidecar",
    "write_required_similarity_audit",
]


def normalize_rendered_mp4_metadata(path: Path) -> dict:
    """Keep the historical monkeypatch seam while delegating to its owner."""
    original = _pipeline_support.normalize_media_metadata
    _pipeline_support.normalize_media_metadata = normalize_media_metadata
    try:
        return _pipeline_support.normalize_rendered_mp4_metadata(path)
    finally:
        _pipeline_support.normalize_media_metadata = original


def enforce_production_identity_provider(production_render: bool) -> dict:
    """Keep the historical provider seam at the command boundary."""
    original = _pipeline_support.get_identity_provider
    _pipeline_support.get_identity_provider = get_identity_provider
    try:
        return _pipeline_support.enforce_production_identity_provider(production_render)
    finally:
        _pipeline_support.get_identity_provider = original


def write_generated_asset_lineage_sidecar(
    out_path: Path,
    *,
    source_lineage_path: Path | None,
    render_job_key: str,
    source_hash: str,
) -> Path:
    """Keep the historical lineage-enrichment seam for direct callers."""
    original = _pipeline_support.enrich_lineage_identity
    _pipeline_support.enrich_lineage_identity = enrich_lineage_identity
    try:
        return _pipeline_support.write_generated_asset_lineage_sidecar(
            out_path,
            source_lineage_path=source_lineage_path,
            render_job_key=render_job_key,
            source_hash=source_hash,
        )
    finally:
        _pipeline_support.enrich_lineage_identity = original


async def amain(args):
    root = Path(args.root).resolve()
    raw_dir = root / "00_source_videos"
    cap_dir = root / "01_captions"
    proc_dir = root / "02_processed"
    fonts_dir = root / "fonts"
    audio_dir = root / "03_audio_library"
    manifest_path = root / "manifest.json"
    config = load_config(root)
    if getattr(args, "_defaults_applied", False) is False:
        args.workers = (
            args.workers
            if args.workers != 3
            else int(config.get("workers", args.workers))
        )
        args.caption_renderer = args.caption_renderer or config.get(
            "caption_renderer", "pillow"
        )
        args.placement_mode = args.placement_mode or config.get(
            "placement_mode", "source"
        )
        args.output_profile = args.output_profile or config.get(
            "output_profile", "mac_h264_videotoolbox"
        )

    for d in (raw_dir, cap_dir, proc_dir, fonts_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest = Manifest(manifest_path)
    reconcile_interrupted_temp_outputs(proc_dir, manifest)
    # ── Load per-account profile (if --account set) ────────────────────
    account: dict = {}
    if args.account:
        acc_path = root / "accounts" / f"{args.account}.json"
        if acc_path.exists():
            account = json.loads(acc_path.read_text())
            log.info(
                f"account profile '{args.account}': "
                f"voice={account.get('voice')} "
                f"fonts={account.get('preferred_fonts')} "
                f"styles={account.get('preferred_styles')}"
            )
        else:
            log.warning(f"account profile not found: {acc_path}")
    try:
        account_scope = validate_account_scope(
            args.account,
            production_render=bool(getattr(args, "production_render", False)),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        identity_provider_check = enforce_production_identity_provider(
            bool(getattr(args, "production_render", False))
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if identity_provider_check.get("required"):
        log.info(
            "identity_provider_check "
            + json.dumps(identity_provider_check, ensure_ascii=False)
        )

    if args.caption_mix or args.caption_banks:
        try:
            bank_caption_set = caption_set_from_bank_selection(
                root,
                caption_mix=args.caption_mix,
                caption_banks=args.caption_banks,
                limit=None,
                seed=args.seed,
            )
        except ValueError as e:
            raise SystemExit(str(e)) from e
        pairs = [(video, bank_caption_set) for video in sorted(raw_dir.glob("*.mp4"))]
        log.info(
            f"caption bank mode: {bank_caption_set.notes}; "
            f"{len(bank_caption_set.hooks)} candidate hook(s)"
        )
    else:
        pairs = discover_pairs(raw_dir, cap_dir)
    if args.only_clip:
        pairs = [
            (video, cap_set) for video, cap_set in pairs if video.stem == args.only_clip
        ]
    log.info(f"discovered {len(pairs)} (video, caption) pairs")

    auto_color_cache: dict[str, str] = {}
    auto_band_cache: dict[str, tuple[str, str, str, PlacementSummary]] = {}
    placement_qc_rows: list[dict] = []
    src_dims_cache: dict[str, tuple[int, int]] = {}
    src_bitrate_cache: dict[str, int | None] = {}
    tasks = []
    encode_sem = asyncio.Semaphore(max(1, int(args.workers)))
    queued_keys: dict[str, str] = {}
    duplicate_aliases: list[tuple[str, str]] = []
    duplicate_jobs = 0
    for video, cap_set in pairs:
        try:
            duration = await probe_duration(video)
        except Exception as e:
            log.error(f"probe failed for {video.name}: {e}")
            continue
        warnings = check_clip_readiness(video, cap_set, ffprobe=FFPROBE)
        for warning in warnings:
            log.warning(f"preflight {video.stem}: {warning.code}: {warning.message}")
        if args.strict_preflight and warnings:
            log.error(
                f"strict preflight blocked {video.stem}: {len(warnings)} warning(s)"
            )
            continue

        src_hash = sha256_file(video)
        if src_hash not in src_dims_cache:
            src_dims_cache[src_hash] = await probe_dimensions(video)
            log.info(f"prewarm dims for {video.stem}: {src_dims_cache[src_hash]}")
        if src_hash not in src_bitrate_cache:
            src_bitrate_cache[src_hash] = await probe_source_bitrate(video)
            br = src_bitrate_cache[src_hash]
            log.info(
                f"prewarm bitrate for {video.stem}: "
                f"{f'{br} Mbps' if br else 'unknown (using floor)'}"
            )
        manifest.upsert_video(video.stem, video, src_hash, duration)
        out_dir = proc_dir / video.stem
        try:
            recipes = select_recipes(cap_set, args.recipes)
        except ValueError as e:
            log.error(f"{video.name}: {e}")
            continue

        # Pre-warm the per-source probes BEFORE spawning workers, so 30
        # concurrent tasks don't race on the same temp file or recompute
        # the same probe N times.
        if src_hash not in auto_color_cache:
            lum = await probe_caption_region_luminance(video, duration)
            auto_color_cache[src_hash] = pick_caption_color(lum)
            log.info(f"prewarm color for {video.stem}: → {auto_color_cache[src_hash]}")
        if src_hash not in auto_band_cache:
            band_, style_, font_, placement_summary = await probe_caption_layout(
                video,
                duration,
                placement_debug=args.placement_debug,
                placement_signals=args.placement_signals,
                caption_placement_policy=args.caption_placement_policy,
                manifest=manifest,
                src_hash=src_hash,
            )
            # Apply account preferences AFTER probing — bias the auto-pick
            # toward the account's voice without forcing a specific value
            # if the probe and account-pref both suggest different things.
            pref_fonts = account.get("preferred_fonts") or []
            pref_styles = account.get("preferred_styles") or []
            if pref_fonts and font_ not in pref_fonts:
                font_ = pref_fonts[0]
            if pref_styles and style_ not in pref_styles:
                style_ = pref_styles[0]
            auto_band_cache[src_hash] = (band_, style_, font_, placement_summary)
            qc_row = build_caption_placement_qc_row(
                source_clip=video.stem,
                placement_summary=placement_summary,
                scored_lane=band_,
                render_band=args.band,
                caption_style=style_,
                font=font_,
            )
            placement_qc_rows.append(qc_row)
            if args.caption_placement_qc or args.placement_debug:
                log.info(
                    "caption_placement_qc " + json.dumps(qc_row, ensure_ascii=False)
                )
            log.info(
                f"prewarm layout for {video.stem}: "
                f"band→{band_} style→{style_} font→{font_}"
            )

        video_cap_set = cap_set
        bank_caption_mode = bool(args.caption_mix or args.caption_banks)
        if bank_caption_mode:
            _, _, _, placement_summary = auto_band_cache[src_hash]
            frame_type = classify_frame_type_for_caption_fit(
                placement_summary,
                src_dims=src_dims_cache.get(src_hash, (1080, 1920)),
                video_stem=video.stem,
            )
            reel_scene_tags = classify_reel_scene_tags(
                frame_type=frame_type,
                video_stem=video.stem,
                prompt_text="",
            )
            if args.caption_topic == "off":
                caption_topic = None
            elif args.caption_topic == "auto":
                caption_topic = infer_caption_topic_for_reel(
                    frame_type=frame_type,
                    video_stem=video.stem,
                    prompt_text="",
                )
            else:
                caption_topic = args.caption_topic
            video_cap_set, fit_diagnostics = apply_caption_fit_to_caption_set(
                cap_set,
                frame_type=frame_type,
                reel_scene_tags=reel_scene_tags,
                caption_topic=caption_topic,
                max_hooks=args.max_hooks,
                seed=args.seed,
                fit_mode=args.caption_fit,
                scene_fit_mode=args.caption_scene_fit,
            )
            if args.dry_run or args.placement_debug:
                for row in fit_diagnostics:
                    log.info("caption_fit " + json.dumps(row, ensure_ascii=False))
            log.info(
                f"caption fit for {video.stem}: mode={args.caption_fit} "
                f"scene_fit={args.caption_scene_fit} frame_type={frame_type} "
                f"reel_scene_tags={','.join(reel_scene_tags)} "
                f"caption_topic={caption_topic or 'none'} hooks={len(video_cap_set.hooks)}"
            )

        # Per-clip color override from sidecar JSON, account profile, or CLI
        forced_color = args.color or cap_set.caption_color
        if (
            not forced_color
            and account.get("color_scheme")
            and account["color_scheme"] != "auto"
        ):
            forced_color = account["color_scheme"]
        if forced_color:
            recipes = [replace(r, caption_color=forced_color) for r in recipes]
        if args.style:
            recipes = [replace(r, caption_style=args.style) for r in recipes]
        if args.band:
            recipes = [replace(r, caption_band=args.band) for r in recipes]
        if args.font:
            recipes = [replace(r, font=args.font) for r in recipes]
        if args.text_variation:
            pack_version = get_pack_version(args.variation_pack)
            recipes = [
                replace(
                    r,
                    text_variation=args.text_variation,
                    text_variation_pack=args.variation_pack,
                    text_variation_pack_version=pack_version,
                )
                for r in recipes
            ]

        # ── Sampling: cap hooks/recipes per clip if requested ─────────
        # Preserve original hook_idx so output filenames stay stable across
        # runs (h00, h03, h07 ...). The manifest keys on caption/recipe
        # hashes, so partial sampling is cache-correct.
        rng = random.Random(args.seed)

        hooks_pool: list[tuple[int, str | dict]] = list(enumerate(video_cap_set.hooks))
        recipes_pool: list[Recipe] = list(recipes)
        if args.only_hook_index is not None:
            hooks_pool = [
                item for item in hooks_pool if item[0] == args.only_hook_index
            ]

        if args.max_recipes is not None and args.max_recipes < len(recipes_pool):
            if args.hook_select == "first":
                recipes_pool = recipes_pool[: args.max_recipes]
            else:
                recipes_pool = sorted(
                    rng.sample(recipes_pool, args.max_recipes),
                    key=lambda r: [rr.name for rr in recipes].index(r.name),
                )

        if (
            not bank_caption_mode
            and args.max_hooks is not None
            and args.max_hooks < len(hooks_pool)
        ):
            if args.hook_select == "first":
                hooks_pool = hooks_pool[: args.max_hooks]
            else:
                hooks_pool = sorted(
                    rng.sample(hooks_pool, args.max_hooks),
                    key=lambda x: x[0],
                )

        if args.per_clip is not None:
            hooks_pool, recipes_pool = limit_render_pool(
                hooks_pool,
                recipes_pool,
                per_clip=args.per_clip,
                hook_select=args.hook_select,
                seed=args.seed,
                recipe_order=recipes,
            )

        if args.max_hooks or args.max_recipes or args.per_clip:
            log.info(
                f"sample {video.stem}: {len(hooks_pool)} hooks × "
                f"{len(recipes_pool)} recipes = "
                f"{len(hooks_pool) * len(recipes_pool)} outputs "
                f"(select={args.hook_select}, seed={args.seed})"
            )

        for hook_idx, hook in hooks_pool:
            for recipe in recipes_pool:
                target_ratios = (
                    recipe.target_ratios
                    or args.target_ratios
                    or config.get("target_ratios", ["9:16"])
                )
                for target_ratio in target_ratios:
                    key = compute_job_key(
                        src_hash,
                        hook,
                        recipe,
                        placement_mode=args.placement_mode,
                        target_ratio=target_ratio,
                        caption_placement_policy=args.caption_placement_policy,
                        account_scope=account_scope,
                        requested_band=video_cap_set.band,
                    )
                    if key in queued_keys:
                        duplicate_jobs += 1
                        log.info(
                            f"skip {video.stem} h{hook_idx} {recipe.name} {target_ratio} (duplicate in this run)"
                        )
                        if (
                            queued_keys[key] != video.stem
                            and not args.dry_run
                            and not args.preview
                        ):
                            duplicate_aliases.append((video.stem, key))
                        continue
                    queued_keys[key] = video.stem
                    if args.enqueue_only:
                        from .render_queue import get_queue

                        queue = get_queue(root)
                        cmd = build_single_job_enqueue_cmd(
                            root=root,
                            video_stem=video.stem,
                            hook_idx=hook_idx,
                            recipe=recipe,
                            args=args,
                            target_ratio=target_ratio,
                        )
                        queue.enqueue(job_key=key, command=cmd, cwd=root)
                        continue
                    tasks.append(
                        process_one(
                            video,
                            hook,
                            hook_idx,
                            recipe,
                            out_dir,
                            fonts_dir,
                            manifest,
                            src_hash,
                            duration,
                            auto_color_cache,
                            auto_band_cache,
                            encode_sem,
                            args.dry_run,
                            src_dims=src_dims_cache[src_hash],
                            src_bitrate_mbps=src_bitrate_cache.get(src_hash),
                            mezzanine=args.mezzanine,
                            caption_renderer=args.caption_renderer,
                            output_profile=args.output_profile,
                            placement_signals=args.placement_signals,
                            placement_mode=args.placement_mode,
                            caption_placement_policy=args.caption_placement_policy,
                            target_ratio=target_ratio,
                            preview=args.preview,
                            placement_debug=args.placement_debug,
                            phone_finalize=args.phone_finalize,
                            rerender_all=args.rerender_all,
                            caption_lineage=video_cap_set.hook_lineage.get(hook_idx),
                            account_scope=account_scope,
                            requested_band=video_cap_set.band,
                        )
                    )

    if duplicate_jobs:
        log.info(f"deduped {duplicate_jobs} duplicate render task(s) before launch")
    if args.caption_placement_qc:
        qc_path = root / "caption_placement_qc.json"
        atomic_write_text(
            qc_path,
            json.dumps(
                {
                    "schema": "reel_factory.caption_placement_qc_report.v1",
                    "captionPlacementPolicy": "focal_safe_v1"
                    if args.caption_placement_policy != "legacy"
                    else "legacy",
                    "rows": placement_qc_rows,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        log.info(f"caption placement qc report → {qc_path}")
    log.info(f"queued {len(tasks)} render tasks")
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    if not args.dry_run and not args.preview:
        for video_id, key in duplicate_aliases:
            if manifest.materialize_cached_job(video_id, key):
                log.info(f"materialized duplicate cached render for {video_id}")
        manifest.save()
        if getattr(args, "campaign", None):
            for result in results:
                if isinstance(result, Exception) or result.get("status") != "ok":
                    continue
                try:
                    link_campaign_output(
                        root,
                        output_path=Path(result["out"]),
                        campaign=args.campaign,
                        asset_generation_id=getattr(args, "asset_generation_id", None),
                    )
                except Exception as e:
                    log.warning(
                        f"campaign output link failed for {result.get('out')}: {e}"
                    )

        # Per-clip summary artifacts: CSV/contact sheet are best-effort. SSCD is not.
        for video, _ in pairs:
            clip_out = proc_dir / video.stem
            if not (clip_out.exists() and any(clip_out.glob("*.mp4"))):
                continue
            try:
                from .post_render import summarize_clip_outputs

                info = summarize_clip_outputs(clip_out)
                log.info(
                    f"summarize {video.stem}: csv+sheet for {info['count']} outputs"
                )
            except Exception as e:
                log.warning(f"post-render summary failed for {video.stem}: {e}")
            similarity = write_required_similarity_audit(video, clip_out)
            log.info(f"sscd similarity {video.stem}: {len(similarity)} rows")
        if args.mux_audio:
            try:
                from .audio_mux import mux_root

                selected_audio_path, audio_selection = _selected_audio_for_mux(
                    root, seed=args.seed, explicit_audio_path=args.audio_path
                )
                mux_summary = mux_root(
                    root,
                    audio_tag=args.audio_tag,
                    seed=args.seed,
                    selected_audio_path=selected_audio_path,
                )
                _write_mux_audio_intents(mux_summary, audio_selection)
                log.info(f"audio mux: {json.dumps(mux_summary)}")
            except Exception as e:
                log.error(f"audio mux failed: {e}")
        if args.ai_qc:
            try:
                from .ai_visual_qc import run_ai_qc

                for video, _ in pairs:
                    clip_out = proc_dir / video.stem
                    if clip_out.exists() and any(clip_out.glob("*.mp4")):
                        qc_summary = run_ai_qc(root, clip=video.stem)
                        log.info(
                            f"ai_qc {video.stem}: {json.dumps(qc_summary.get('summary', {}))}"
                        )
            except Exception as e:
                log.warning(f"ai visual qc failed: {e}")
        if args.readiness:
            try:
                from .readiness_check import run_readiness

                for video, _ in pairs:
                    clip_out = proc_dir / video.stem
                    if clip_out.exists() and any(clip_out.glob("*.mp4")):
                        ready_summary = run_readiness(
                            root, clip=video.stem, platform="instagram_reels"
                        )
                        log.info(
                            f"readiness {video.stem}: {json.dumps(ready_summary.get('summary', {}))}"
                        )
            except Exception as e:
                log.warning(f"readiness check failed: {e}")

    # summary
    counts = {"ok": 0, "skipped": 0, "failed": 0, "dry": 0, "exception": 0}
    for r in results:
        if isinstance(r, Exception):
            counts["exception"] += 1
            log.error(f"task exception: {r}")
        else:
            counts[r.get("status", "exception")] += 1
    log.info(f"summary: {json.dumps(counts)}")

    # ── Optional QC pass on outputs ─────────────────────────────────────
    if getattr(args, "qc", False) and not args.dry_run:
        try:
            from .qc_check import run_qc

            qc_summary = run_qc(proc_dir, move_failed=True)
            log.info(f"qc: {json.dumps(qc_summary)}")
        except Exception as e:
            log.error(f"qc pass failed: {e}")


def _resolve_audio_path(root: Path, value: object) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root / path


def _audio_selection_local_path(
    root: Path, selection: dict[str, Any] | None
) -> Path | None:
    if not isinstance(selection, dict):
        return None
    containers: list[dict[str, Any]] = [selection]
    metadata = selection.get("metadata")
    if isinstance(metadata, dict):
        containers.append(metadata)
    for container in containers:
        for key in AUDIO_SELECTION_PATH_KEYS:
            path = _resolve_audio_path(root, container.get(key))
            if path:
                return path
    return None


def _manual_audio_selection(audio_path: str | Path) -> dict[str, Any]:
    path = Path(audio_path)
    return {
        "schema": "reel_factory.audio_provider.v1.selection",
        "track_id": f"manual_{path.stem}",
        "track_name": path.stem,
        "source": "manual_audio_path",
        "selected_reason": "manual_audio_path_override",
        "local_path": str(path),
    }


def _selected_audio_for_mux(
    root: Path, *, seed: int, explicit_audio_path: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    if explicit_audio_path:
        return explicit_audio_path, _manual_audio_selection(explicit_audio_path)
    try:
        from .audio_provider import select_audio as select_ranked_audio
    except ImportError:
        return None, None
    try:
        selection = select_ranked_audio(root, mode="AUTO_TRENDING", seed=seed)
    except FileNotFoundError:
        return None, None
    path = _audio_selection_local_path(root, selection)
    if not path or not path.exists():
        return None, selection
    selection.setdefault("local_path", str(path))
    return str(path), selection


def _write_mux_audio_intents(
    mux_summary: dict[str, Any], ranked_selection: dict[str, Any] | None
) -> None:
    try:
        from .audio_intent import write_audio_intent
    except ImportError:
        return
    for track in mux_summary.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        output = track.get("output")
        if not output:
            continue
        selection = dict(ranked_selection or {})
        if not selection:
            audio_path = str(track.get("audio_path") or "")
            selection = {
                "schema": "reel_factory.audio_provider.v1.selection",
                "track_id": str(track.get("track_id") or Path(audio_path).stem),
                "track_name": Path(audio_path).stem,
                "source": "local_audio_library",
                "selected_reason": "audio_mux_random_fallback",
                "local_path": audio_path,
            }
        try:
            write_audio_intent(
                Path(str(output)),
                mode="native_trending_audio",
                platform="instagram_reels",
                notes="Audio selected during local mux; live schedule remains blocked.",
                audio_selection=selection,
            )
        except Exception as exc:
            log.warning(f"audio intent write failed for {output}: {exc}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--root",
        default=".",
        help="project root containing 00_source_videos/, 01_captions/, etc.",
    )
    ap.add_argument(
        "--recipes",
        nargs="*",
        default=None,
        help="restrict to these recipe names (e.g. v01_original v05_hflip)",
    )
    ap.add_argument(
        "--color",
        choices=["light", "dark", "auto"],
        default=None,
        help="force caption color across all recipes (overrides sidecar + recipe defaults)",
    )
    ap.add_argument(
        "--style",
        choices=["classic", "meme", "ig", "thin", "soft", "bubble", "auto"],
        default=None,
        help="force caption style across all recipes (overrides recipe defaults)",
    )
    ap.add_argument(
        "--font",
        default=None,
        help="force caption font family: 'Instagram Sans Condensed' or 'Instagram Sans Condensed Bold' (bold is used only for meme style)",
    )
    ap.add_argument(
        "--band",
        choices=["top", "center", "bottom", "left", "right", "auto"],
        default=None,
        help="force caption placement band across all recipes",
    )
    ap.add_argument(
        "--text-variation",
        choices=["off", "auto"],
        default="off",
        help="caption text rewrite mode: off preserves exact text; auto applies deterministic slang/case variants",
    )
    ap.add_argument(
        "--variation-pack",
        default="default",
        help="named text variation pack to use with --text-variation auto (default: default)",
    )
    ap.add_argument(
        "--pack-render",
        action="store_true",
        help="operator preset for rendering a deterministic multi-variant reel pack",
    )
    ap.add_argument(
        "--account",
        default=None,
        help="apply preferences from accounts/<NAME>.json — biases auto-pick "
        "of font/style/color toward that account's voice",
    )
    ap.add_argument(
        "--production-render",
        action="store_true",
        help="require an explicit --account scope so production variants are account-aware",
    )
    ap.add_argument(
        "--caption-mix",
        choices=["Larissa", "Stacey", "Lola"],
        default=None,
        help="select hooks from a creator-weighted caption bank mix",
    )
    ap.add_argument(
        "--creator-style-preset",
        choices=sorted(CREATOR_STYLE_PRESETS),
        default="auto",
        help="creator/account visual defaults; auto centers Stacey/Larissa static-style captions",
    )
    ap.add_argument(
        "--caption-banks",
        nargs="+",
        default=None,
        help="select hooks from explicit caption bank names instead of a creator mix",
    )
    ap.add_argument(
        "--caption-fit",
        choices=["auto", "off"],
        default="auto",
        help="fit caption-bank hooks to the detected frame type before rendering (default: auto)",
    )
    ap.add_argument(
        "--caption-scene-fit",
        choices=["auto", "off"],
        default="auto",
        help="block obvious scene/location caption mismatches for caption-bank hooks (default: auto)",
    )
    ap.add_argument(
        "--caption-topic",
        choices=["auto", "off", *CAPTION_TOPIC_ORDER],
        default="auto",
        help="fit caption-bank hooks to source-specific topic cues before rendering (default: auto)",
    )
    ap.add_argument(
        "--campaign",
        default=None,
        help="link rendered outputs to a Campaign Factory campaign",
    )
    ap.add_argument(
        "--asset-generation-id",
        default=None,
        help="link rendered outputs to an existing Campaign Factory asset generation",
    )
    ap.add_argument(
        "--watch",
        action="store_true",
        help="watch 00_source_videos/ for new clips and auto-process",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print commands without encoding"
    )
    ap.add_argument(
        "--preview",
        action="store_true",
        help="render caption preview PNGs instead of full videos",
    )
    ap.add_argument(
        "--rerender-all",
        action="store_true",
        help="ignore cached successful jobs and render selected outputs again",
    )
    ap.add_argument(
        "--strict-preflight",
        action="store_true",
        help="block clips that produce preflight warnings",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=3,
        metavar="N",
        help="max concurrent ffmpeg encodes (default: 3)",
    )
    ap.add_argument(
        "--mezzanine",
        action="store_true",
        help="also export ProRes LT .mov mezzanine files beside social MP4s",
    )
    ap.add_argument(
        "--output-profile",
        choices=[
            name
            for name, profile in ENCODER_PROFILES.items()
            if profile.runnable and name != "prores_lt"
        ],
        default="mac_h264_videotoolbox",
        help="primary MP4 encoder profile (default: mac_h264_videotoolbox)",
    )
    ap.add_argument(
        "--phone-finalize",
        dest="phone_finalize",
        action="store_true",
        default=True,
        help="stream-copy final MP4 with mobile-style metadata and faststart (default)",
    )
    ap.add_argument(
        "--no-phone-finalize",
        dest="phone_finalize",
        action="store_false",
        help="skip final MP4 metadata/finalization remux",
    )
    ap.add_argument(
        "--caption-renderer",
        choices=["pillow", "pango"],
        default="pillow",
        help="caption rasterizer; pango is experimental and falls back to Pillow",
    )
    ap.add_argument(
        "--placement-debug",
        action="store_true",
        help="log top/center/bottom caption lane scores during source analysis",
    )
    ap.add_argument(
        "--placement-signals",
        choices=["basic", "pose"],
        default="basic",
        help="placement analysis signals: basic or pose (optional MediaPipe)",
    )
    ap.add_argument(
        "--placement-mode",
        choices=["source", "segment"],
        default="source",
        help="caption placement mode: source-level stable placement; timed captions auto-use segment placement",
    )
    ap.add_argument(
        "--caption-placement-policy",
        choices=["focal-safe", "legacy"],
        default="focal-safe",
        help="caption placement policy: focal-safe avoids face/body focal zones; legacy preserves old lane behavior",
    )
    ap.add_argument(
        "--caption-placement-qc",
        action="store_true",
        help="write caption_placement_qc.json with lane scores and placement reasons",
    )
    ap.add_argument(
        "--target-ratios",
        nargs="+",
        choices=["9:16", "4:5"],
        default=["9:16"],
        help="output aspect ratios to render (default: 9:16)",
    )

    # ── Sampling controls (cap how many videos come back per run) ─────────
    ap.add_argument(
        "--max-hooks",
        type=int,
        default=None,
        metavar="N",
        help="cap hooks per clip (default: use all)",
    )
    ap.add_argument(
        "--max-recipes",
        type=int,
        default=None,
        metavar="M",
        help="cap recipes per clip (default: use all)",
    )
    ap.add_argument(
        "--per-clip",
        type=int,
        default=None,
        metavar="K",
        help="overall cap on outputs per clip (reduces hooks first, keeps recipes)",
    )
    ap.add_argument(
        "--hook-select",
        choices=["first", "random"],
        default="random",
        help="how to pick hooks/recipes when limited "
        "(default: random with --seed for reproducibility)",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=42,
        metavar="N",
        help="RNG seed for random selection (default: 42 — bump it for fresh picks)",
    )
    ap.add_argument("--only-hook-index", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--only-clip", default=None, help=argparse.SUPPRESS)

    # ── Quality control ───────────────────────────────────────────────────
    ap.add_argument(
        "--qc",
        action="store_true",
        help="run technical QC pass on outputs after rendering "
        "(ffprobe: dims, fps, codec, audio absent, file size)",
    )
    ap.add_argument(
        "--qc-only",
        action="store_true",
        help="skip rendering, only run QC on existing outputs",
    )
    ap.add_argument(
        "--mux-audio",
        action="store_true",
        help="after rendering, create separate audio-muxed derivatives",
    )
    ap.add_argument(
        "--audio-tag", default=None, help="audio library tag used with --mux-audio"
    )
    ap.add_argument(
        "--audio-path",
        default=None,
        help="specific local audio file to use with --mux-audio",
    )
    ap.add_argument(
        "--enqueue-only",
        action="store_true",
        help="enqueue render commands into render_queue.sqlite instead of running locally",
    )
    ap.add_argument(
        "--ai-qc",
        action="store_true",
        help="run heuristic AI visual QA on rendered outputs after rendering",
    )
    ap.add_argument(
        "--readiness",
        action="store_true",
        help="run warn-only platform readiness aggregation after rendering",
    )

    args = ap.parse_args()
    if args.pack_render:
        if args.recipes is None:
            args.recipes = ["v01_original", "v05_hflip", "v06_zoom", "v09_caption_bg"]
        if args.text_variation == "off":
            args.text_variation = "auto"
        if args.max_hooks is None:
            args.max_hooks = 20
        if args.style is None:
            args.style = "ig"
        if args.font is None:
            args.font = DEFAULT_CAPTION_FONT
        if args.color is None:
            args.color = "light"
    applied_preset = apply_creator_style_preset(args)
    if applied_preset:
        log.info(f"creator style preset applied: {applied_preset}")
    if args.caption_renderer == "pango":
        reexec_with_homebrew_gi_env_if_needed()
    if args.watch:
        run_watch_mode(args)
    else:
        asyncio.run(amain(args))


def run_watch_mode(args) -> None:
    """Watch 00_source_videos/ for new clips and auto-process when one
    appears. Debounced so partial uploads don't trigger early. Captions
    are picked up from 01_captions/<stem>.json or .txt as usual.

    Press Ctrl-C to stop.
    """
    import threading

    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    root = Path(args.root).resolve()
    raw_dir = root / "00_source_videos"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"watch mode: monitoring {raw_dir}/ for new .mp4 files")

    pending: dict[str, threading.Timer] = {}
    debounce_secs = 3.0

    def kick_pipeline():
        log.info("watch: triggering pipeline run")
        try:
            asyncio.run(amain(args))
        except Exception as e:
            log.error(f"watch run failed: {e}")

    def schedule(path: str):
        if path in pending:
            pending[path].cancel()
        t = threading.Timer(
            debounce_secs, lambda: (pending.pop(path, None), kick_pipeline())
        )
        t.daemon = True
        t.start()
        pending[path] = t

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory and event.src_path.lower().endswith(".mp4"):
                log.info(f"watch: new clip detected → {event.src_path}")
                schedule(event.src_path)

        def on_modified(self, event):
            # Re-debounce on writes (large file uploads finish gradually)
            if not event.is_directory and event.src_path.lower().endswith(".mp4"):
                schedule(event.src_path)

    observer = Observer()
    observer.schedule(Handler(), str(raw_dir), recursive=False)
    observer.start()
    try:
        # Run once on startup to catch anything already there
        kick_pipeline()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("watch mode: stopping")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
