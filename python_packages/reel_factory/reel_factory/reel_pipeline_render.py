"""Single-output render execution for Reel Pipeline."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from pathlib import Path

from pipeline_contracts import (
    evaluate_overlay_semantic_completeness,
    evaluate_overlay_timing,
)

from .graph_builder import build_video_filter as build_graph_video_filter
from .graph_builder import caption_overlay_enable, target_dimensions
from .manifest import Manifest
from .placement import (
    CaptionSegmentPlan,
    PlacementSummary,
    mirror_side_band_for_recipe,
    pick_caption_color,
    probe_caption_layout,
    probe_caption_region_luminance,
    resolve_segment_bands,
)
from .reel_pipeline_support import (
    AVCONVERT,
    COLORS,
    FFMPEG,
    RECIPES,
    Recipe,
    approve_operator_band,
    build_avconvert_finalize_cmd,
    build_caption_outcome_context,
    build_ffmpeg_cmd,
    build_phone_finalize_cmd,
    centered_static_caption_band,
    compute_job_key,
    effective_placement_mode_for_caption,
    log,
    normalize_rendered_mp4_metadata,
    phone_creation_time,
    resolve_caption_font_policy,
    sha256_str,
    timed_caption_band,
    vary_band_within_lane,
    write_caption_lineage_sidecar,
    write_generated_asset_lineage_sidecar,
)
from .render_plan import RenderPlan
from .variation_engine import vary_caption_text


async def process_one(
    src: Path,
    caption: str | dict,
    hook_idx: int,
    recipe: Recipe,
    out_dir: Path,
    fonts_dir: Path,
    manifest: Manifest,
    src_hash: str,
    duration: float,
    auto_color_cache: dict[str, str],
    auto_band_cache: dict[str, tuple[str, str, str, PlacementSummary]],
    encode_sem: asyncio.Semaphore,
    dry_run: bool = False,
    src_dims: tuple[int, int] = (1080, 1920),
    src_bitrate_mbps: int | None = None,
    mezzanine: bool = False,
    caption_renderer: str = "pillow",
    output_profile: str = "mac_h264_videotoolbox",
    placement_signals: str = "basic",
    placement_mode: str = "source",
    caption_placement_policy: str = "focal-safe",
    target_ratio: str = "9:16",
    preview: bool = False,
    placement_debug: bool = False,
    phone_finalize: bool = True,
    rerender_all: bool = False,
    caption_lineage: dict | None = None,
    account_scope: str = "local_review",
    requested_band: str | None = None,
) -> dict:
    """Render one (video, caption_variant, recipe) combo."""
    placement_mode = effective_placement_mode_for_caption(caption, placement_mode)
    caption_for_manifest = (
        json.dumps(caption, sort_keys=True, ensure_ascii=False)
        if isinstance(caption, dict)
        else caption
    )
    overlay_semantic_qc = evaluate_overlay_semantic_completeness(
        caption if recipe.burn_caption else None,
        require_overlay=bool(recipe.burn_caption),
    )
    key = compute_job_key(
        src_hash,
        caption,
        recipe,
        placement_mode=placement_mode,
        target_ratio=target_ratio,
        caption_placement_policy=caption_placement_policy,
        account_scope=account_scope,
        requested_band=requested_band,
    )

    if overlay_semantic_qc.get("passed") is not True:
        failure_reasons = overlay_semantic_qc.get("failure_reasons") or [
            "overlay_semantic_qc_failed"
        ]
        error = "burned_overlay_semantic_incomplete:" + ",".join(failure_reasons)
        blocked_path = out_dir / (
            f"{src.stem}_h{hook_idx:02d}_{recipe.name}_semantic_blocked.mp4"
        )
        log.error(f"BLOCK {src.stem} h{hook_idx} {recipe.name}: {error}")
        if not dry_run:
            manifest.add_failure(
                src.stem,
                recipe,
                caption_for_manifest,
                blocked_path,
                key,
                duration,
                error,
                encoder=output_profile,
                target_ratio=target_ratio,
            )
        return {
            "status": "failed",
            "key": key,
            "error": error,
            "overlaySemanticQc": overlay_semantic_qc,
        }

    if not preview and not rerender_all and manifest.has_job(key):
        materialized = manifest.materialize_cached_job(src.stem, key)
        suffix = "materialized" if materialized else "cached"
        log.info(f"skip {src.stem} h{hook_idx} {recipe.name} ({suffix})")
        return {"status": "skipped", "key": key}

    # Decide caption color
    color = recipe.caption_color
    if color == "auto":
        # cache the luminance probe per source — same answer for every recipe
        cached = auto_color_cache.get(src_hash)
        if cached is None:
            lum = await probe_caption_region_luminance(src, duration)
            cached = pick_caption_color(lum)
            auto_color_cache[src_hash] = cached
            log.info(f"auto color for {src.stem}: luminance→{cached}")
        color = cached
    if color not in COLORS:
        log.warning(f"unknown caption_color '{color}', falling back to light")
        color = "light"

    # Decide layout (band/style/font). Cached per source — same probe answers for every recipe.
    auto_layout = auto_band_cache.get(src_hash)
    if auto_layout is None:
        auto_layout = await probe_caption_layout(
            src,
            duration,
            placement_signals=placement_signals,
            caption_placement_policy=caption_placement_policy,
            manifest=manifest,
            src_hash=src_hash,
        )
        auto_band_cache[src_hash] = auto_layout
        log.info(
            f"auto layout for {src.stem}: "
            f"band→{auto_layout[0]} style→{auto_layout[1]} font→{auto_layout[2]}"
        )
    auto_band, auto_style, auto_font, _placement_summary = auto_layout

    is_timed_caption = isinstance(caption, dict)
    if recipe.caption_band != "auto":
        band = recipe.caption_band
    else:
        # Side zones are stronger than lane cycling because they use empty
        # composition space. For mirrored recipes, mirror the caption side too.
        recipe_idx = next(
            (i for i, r in enumerate(RECIPES) if r.name == recipe.name), 0
        )
        if auto_band in {"left", "right"}:
            band = mirror_side_band_for_recipe(auto_band, recipe)
        elif caption_placement_policy != "legacy" and not is_timed_caption:
            band = auto_band
        else:
            opposite = "bottom" if auto_band == "top" else "top"
            band = [auto_band, "center", opposite][recipe_idx % 3]
    if not is_timed_caption:
        operator_band = approve_operator_band(requested_band, _placement_summary)
        if operator_band:
            log.info(f"operator band override for {src.stem}: {band} → {operator_band}")
            band = operator_band
        else:
            if requested_band:
                log.info(
                    f"operator band request '{requested_band}' refused for "
                    f"{src.stem}: not face-clear"
                )
            diversity_key = f"{src_hash}|{hook_idx}|{recipe.name}|{caption}"
            band = centered_static_caption_band(
                band, _placement_summary, diversity_key=diversity_key
            )
            band = vary_band_within_lane(
                band, _placement_summary, diversity_key=diversity_key
            )
    style = recipe.caption_style if recipe.caption_style != "auto" else auto_style

    requested_font = recipe.font if recipe.font != "auto" else auto_font
    font, font_decision = resolve_caption_font_policy(requested_font, style)
    if font_decision["requestedFont"] != font_decision["resolvedFont"]:
        log.info(
            f"caption font policy for {src.stem}: "
            f"{font_decision['requestedFont']} → {font_decision['resolvedFont']} "
            f"({font_decision['reason']})"
        )

    # Plan caption PNG paths, timing, band, and varied text.
    # seg_plans: caption PNG path, timing, rendered text, and placement zone.
    # Per-segment "band" enables persistent-header pattern: header segment uses
    # band="top" with no start/end (full duration) while body segments use
    # band="bottom" with their own timing — both overlay simultaneously since
    # each PNG is transparent outside its band.
    if isinstance(caption, dict):
        segments = caption["segments"]
        if not segments:
            log.warning(
                f"{src.stem} h{hook_idx} {recipe.name}: empty segments list, no caption overlay"
            )
        seg_plans: list[CaptionSegmentPlan] = []
        for i, seg in enumerate(segments):
            raw = seg["text"]
            seg_text = vary_caption_text(
                raw,
                seed_str=f"{recipe.name}|{raw}|{src_hash}|seg{i}",
                mode=recipe.text_variation,
                pack=recipe.text_variation_pack,
            )
            seg_png = out_dir / f"_cap_h{hook_idx:02d}_{recipe.name}_{color}_s{i}.png"
            start = float(seg.get("start", 0.0))
            end = float(seg["end"]) if "end" in seg else None
            explicit_band = "band" in seg
            seg_band = (
                str(seg["band"])
                if explicit_band
                else timed_caption_band(band, i, _placement_summary)
            )
            seg_plans.append(
                CaptionSegmentPlan(
                    seg_png, start, end, seg_text, seg_band, explicit_band
                )
            )
    else:
        text = vary_caption_text(
            caption,
            seed_str=f"{recipe.name}|{caption}|{src_hash}",
            mode=recipe.text_variation,
            pack=recipe.text_variation_pack,
        )
        single_png = out_dir / f"_cap_h{hook_idx:02d}_{recipe.name}_{color}.png"
        seg_plans = [CaptionSegmentPlan(single_png, 0.0, None, text, band)]

    # Dynamic segment timing: if any specified end exceeds the effective clip
    # duration (or no ends were specified), redistribute segments evenly.
    # Hardcoded timings like 2.5s/5.0s/7.5s break on short clips.
    n_segs = len(seg_plans)
    if n_segs > 1:
        effective_dur = max(0.1, duration - recipe.trim_head - recipe.trim_tail)
        raw_segs = caption.get("segments", []) if isinstance(caption, dict) else []
        max_end = max((float(s["end"]) for s in raw_segs if "end" in s), default=0.0)
        if max_end == 0.0 or max_end >= effective_dur * 0.9:
            seg_w = effective_dur / n_segs
            seg_plans = [
                CaptionSegmentPlan(
                    s.png_path,
                    i * seg_w,
                    (i + 1) * seg_w if i < n_segs - 1 else None,
                    s.text,
                    s.band,
                    s.explicit_band,
                )
                for i, s in enumerate(seg_plans)
            ]

    effective_dur = max(0.1, duration - recipe.trim_head - recipe.trim_tail)
    caption_timing_qc = evaluate_overlay_timing(
        [
            {
                "text": segment.text,
                "start": segment.start,
                "end": segment.end,
            }
            for segment in seg_plans
        ],
        duration_seconds=effective_dur,
    )
    if recipe.burn_caption and caption_timing_qc.get("passed") is not True:
        failure_reasons = caption_timing_qc.get("failure_reasons") or [
            "overlay_timing_qc_failed"
        ]
        error = "burned_overlay_timing_invalid:" + ",".join(failure_reasons)
        blocked_path = out_dir / (
            f"{src.stem}_h{hook_idx:02d}_{recipe.name}_timing_blocked.mp4"
        )
        log.error(f"BLOCK {src.stem} h{hook_idx} {recipe.name}: {error}")
        if not dry_run:
            manifest.add_failure(
                src.stem,
                recipe,
                caption_for_manifest,
                blocked_path,
                key,
                duration,
                error,
                encoder=output_profile,
                target_ratio=target_ratio,
            )
        return {
            "status": "failed",
            "key": key,
            "error": error,
            "overlaySemanticQc": overlay_semantic_qc,
            "captionTimingQc": caption_timing_qc,
        }

    seg_plans = await resolve_segment_bands(
        src,
        segments=seg_plans,
        source_band=band,
        placement_mode=placement_mode,
        placement_signals=placement_signals,
        caption_placement_policy=caption_placement_policy,
        recipe=recipe,
        duration=duration,
        placement_debug=placement_debug,
    )

    caption_pngs = [(s.png_path, s.start, s.end) for s in seg_plans]
    target_dims = target_dimensions(target_ratio)

    out_dir.mkdir(parents=True, exist_ok=True)
    ratio_suffix = (
        "" if target_ratio == "9:16" else f"_{target_ratio.replace(':', 'x')}"
    )
    ext = ".png" if preview else ".mp4"
    out_filename = (
        f"{src.stem}_h{hook_idx:02d}_{recipe.name}{ratio_suffix}_{color}_{key[:8]}{ext}"
    )
    out_path = out_dir / out_filename
    tmp_dir = out_dir / ".tmp" / key[:16]
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_out_path = tmp_dir / out_filename
    try:
        tmp_out_path.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = build_ffmpeg_cmd(
        src,
        caption_pngs,
        recipe,
        tmp_out_path,
        duration,
        fonts_dir,
        src_hash=src_hash,
        src_dims=src_dims,
        src_bitrate_mbps=src_bitrate_mbps,
        output_profile=output_profile,
        target_ratio=target_ratio,
        account_scope=account_scope,
    )
    mezz_out_path = (
        out_dir / f"{src.stem}_h{hook_idx:02d}_{recipe.name}_{color}_{key[:8]}_mezz.mov"
    )
    mezz_tmp_path = tmp_dir / mezz_out_path.name
    mezz_cmd = (
        build_ffmpeg_cmd(
            src,
            caption_pngs,
            recipe,
            mezz_tmp_path,
            duration,
            fonts_dir,
            src_hash=src_hash,
            src_dims=src_dims,
            src_bitrate_mbps=src_bitrate_mbps,
            output_profile="prores_lt",
            target_ratio=target_ratio,
            account_scope=account_scope,
        )
        if mezzanine
        else None
    )

    if dry_run:
        log.info(f"DRY {src.stem} h{hook_idx} {recipe.name} [{color}] → {out_filename}")
        log.info(f"CMD {' '.join(shlex.quote(c) for c in cmd)}")
        if mezz_cmd:
            log.info(f"MEZZ {' '.join(shlex.quote(c) for c in mezz_cmd)}")
        return {"status": "dry"}

    # Render each caption segment to a transparent 1080x1920 PNG via PIL+Pilmoji.
    from .caption_render import render_caption_png

    try:
        for seg in seg_plans:
            render_caption_png(
                seg.text,
                font_family=font,
                fonts_dir=fonts_dir,
                color_scheme=color,
                band=seg.band,
                style=style,
                out_path=seg.png_path,
                canvas_w=target_dims[0],
                canvas_h=target_dims[1],
                renderer=caption_renderer,
            )
    except Exception as e:
        msg = f"caption render failed: {e}"
        log.error(f"FAIL {src.stem} h{hook_idx} {recipe.name}: {msg}")
        for png_path, _, _ in caption_pngs:
            try:
                png_path.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
        manifest.add_failure(
            src.stem,
            recipe,
            caption_for_manifest,
            out_path,
            key,
            duration,
            msg,
            encoder=output_profile,
            target_ratio=target_ratio,
        )
        return {"status": "failed", "key": key}

    if preview:
        preview_dir = out_dir / "_previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / out_filename
        mid_t = max(0.05, min(duration - 0.05, duration * 0.5))
        vf = build_graph_video_filter(
            RenderPlan(
                src=src,
                caption_pngs=[],
                recipe=recipe,
                out=preview_path,
                duration=duration,
                fonts_dir=fonts_dir,
                src_hash=src_hash,
                src_dims=src_dims,
                target_ratio=target_ratio,
                account_scope=account_scope,
            )
        )
        fc_parts = [f"[0:v]{vf}[vs0]"]
        inputs = ["-ss", f"{mid_t:.3f}", "-i", str(src)]
        for i, (png_path, _, _) in enumerate(caption_pngs):
            inputs += ["-loop", "1", "-i", str(png_path)]
            fc_parts.append(f"[{i + 1}:v]format=rgba[cap{i}]")
        for i in range(len(caption_pngs)):
            in_s = f"vs{i}"
            out_s = f"vs{i + 1}" if i < len(caption_pngs) - 1 else "vsf"
            _, start, end = caption_pngs[i]
            fc_parts.append(
                f"[{in_s}][cap{i}]overlay=0:0"
                f":enable={caption_overlay_enable(start, end)}"
                f":eof_action=pass:format=auto[{out_s}]"
            )
        fc_parts.append("[vsf]format=rgba[v]")
        p = await asyncio.create_subprocess_exec(
            FFMPEG,
            "-hide_banner",
            "-y",
            "-nostdin",
            *inputs,
            "-filter_complex",
            ";".join(fc_parts),
            "-map",
            "[v]",
            "-frames:v",
            "1",
            str(preview_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await p.communicate()
        for png_path, _, _ in caption_pngs:
            png_path.unlink(missing_ok=True)
        if p.returncode != 0:
            msg = err.decode(errors="replace")[-800:]
            log.error(f"preview failed {src.stem} h{hook_idx} {recipe.name}: {msg}")
            return {"status": "failed", "key": key}
        caption_hash = sha256_str(caption_for_manifest)
        placement_decision = (
            _placement_summary.metadata.get("captionPlacementDecision")
            if isinstance(_placement_summary.metadata, dict)
            else {}
        )
        placement_policy = (
            _placement_summary.metadata.get("captionPlacementPolicy")
            if isinstance(_placement_summary.metadata, dict)
            else None
        ) or ("legacy" if caption_placement_policy == "legacy" else "focal_safe_v1")
        write_caption_lineage_sidecar(
            preview_path,
            {
                **(caption_lineage or {}),
                "captionBurnedIn": bool(recipe.burn_caption),
                "captionTimingQc": caption_timing_qc,
                "captionPlacementPolicy": placement_policy,
                "captionPlacementDecision": {
                    **(
                        placement_decision
                        if isinstance(placement_decision, dict)
                        else {}
                    ),
                    "selectedLane": ",".join(
                        dict.fromkeys([seg.band for seg in seg_plans])
                    )
                    or band,
                },
            },
            caption_text=caption_for_manifest,
            caption_hash=caption_hash,
            render_recipe=recipe.name,
            source_clip=src.stem,
            rendered_output=str(preview_path),
        )
        log.info(f"preview {src.stem} h{hook_idx} {recipe.name} → {preview_path.name}")
        return {"status": "ok", "key": key, "out": str(preview_path)}

    async with encode_sem:
        log.info(f"start {src.stem} h{hook_idx} {recipe.name} [{color}]")
        t0 = time.time()
        last_err = b""
        for attempt in (1, 2):
            attempt_started = int(time.time())
            p = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(out_dir),
            )
            _, last_err = await p.communicate()
            manifest.add_attempt(
                key=key,
                attempt_no=attempt,
                status="ok" if p.returncode == 0 else "failed",
                temp_path=tmp_out_path,
                final_path=out_path,
                ffmpeg_cmd=cmd,
                started_at=attempt_started,
                ended_at=int(time.time()),
                error_message=last_err.decode(errors="replace")
                if p.returncode != 0
                else None,
            )
            if p.returncode == 0:
                break
            log.warning(
                f"retry {src.stem} h{hook_idx} {recipe.name} "
                f"attempt={attempt} rc={p.returncode}"
            )

        if p.returncode != 0:
            elapsed = time.time() - t0
            msg = last_err.decode(errors="replace")[-2000:]
            log.error(f"FAIL {src.stem} h{hook_idx} {recipe.name}: {msg[-500:]}")
            manifest.add_failure(
                src.stem,
                recipe,
                caption_for_manifest,
                out_path,
                key,
                duration,
                msg,
                render_time_sec=round(elapsed, 3),
                encoder=output_profile,
                target_ratio=target_ratio,
            )
            for png_path, _, _ in caption_pngs:
                try:
                    png_path.unlink(missing_ok=True)
                except Exception:
                    pass
            return {"status": "failed", "key": key}

        elapsed = time.time() - t0
        if not tmp_out_path.exists() or tmp_out_path.stat().st_size == 0:
            msg = "ffmpeg reported success but temp output was missing or empty"
            log.error(f"FAIL {src.stem} h{hook_idx} {recipe.name}: {msg}")
            manifest.add_failure(
                src.stem,
                recipe,
                caption_for_manifest,
                out_path,
                key,
                duration,
                msg,
                render_time_sec=round(elapsed, 3),
                encoder=output_profile,
                target_ratio=target_ratio,
            )
            for png_path, _, _ in caption_pngs:
                try:
                    png_path.unlink(missing_ok=True)
                except Exception:
                    pass
            return {"status": "failed", "key": key}

        final_tmp_path = tmp_out_path
        if phone_finalize and output_profile != "prores_lt":
            finalized_tmp_path = tmp_dir / f"phone_{out_filename}"
            try:
                finalized_tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            finalize_cmd = build_phone_finalize_cmd(
                tmp_out_path,
                finalized_tmp_path,
                creation_time=phone_creation_time(),
            )
            finalize_started = int(time.time())
            p_finalize = await asyncio.create_subprocess_exec(
                *finalize_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(out_dir),
            )
            _, finalize_err = await p_finalize.communicate()
            finalize_ok = (
                p_finalize.returncode == 0
                and finalized_tmp_path.exists()
                and finalized_tmp_path.stat().st_size > 0
            )
            manifest.add_attempt(
                key=f"{key}:phone_finalize",
                attempt_no=1,
                status="ok" if finalize_ok else "failed",
                temp_path=finalized_tmp_path,
                final_path=out_path,
                ffmpeg_cmd=finalize_cmd,
                started_at=finalize_started,
                ended_at=int(time.time()),
                error_message=finalize_err.decode(errors="replace")
                if not finalize_ok
                else None,
            )
            if finalize_ok:
                final_tmp_path = finalized_tmp_path
                try:
                    tmp_out_path.unlink(missing_ok=True)
                except Exception:
                    pass

                if AVCONVERT:
                    avconvert_tmp_path = tmp_dir / f"avconvert_{out_filename}"
                    try:
                        avconvert_tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    avconvert_cmd = build_avconvert_finalize_cmd(
                        finalized_tmp_path, avconvert_tmp_path
                    )
                    avconvert_started = int(time.time())
                    p_avconvert = await asyncio.create_subprocess_exec(
                        *avconvert_cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(out_dir),
                    )
                    _, avconvert_err = await p_avconvert.communicate()
                    avconvert_ok = (
                        p_avconvert.returncode == 0
                        and avconvert_tmp_path.exists()
                        and avconvert_tmp_path.stat().st_size > 0
                    )
                    manifest.add_attempt(
                        key=f"{key}:avconvert_finalize",
                        attempt_no=1,
                        status="ok" if avconvert_ok else "failed",
                        temp_path=avconvert_tmp_path,
                        final_path=out_path,
                        ffmpeg_cmd=avconvert_cmd,
                        started_at=avconvert_started,
                        ended_at=int(time.time()),
                        error_message=avconvert_err.decode(errors="replace")
                        if not avconvert_ok
                        else None,
                    )
                    if avconvert_ok:
                        final_tmp_path = avconvert_tmp_path
                        try:
                            finalized_tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    else:
                        msg = (
                            avconvert_err.decode(errors="replace")[-500:]
                            or "missing avconvert temp output"
                        )
                        log.warning(
                            f"avconvert finalize failed {src.stem} h{hook_idx} {recipe.name}; using ffmpeg phone output: {msg}"
                        )
            else:
                msg = (
                    finalize_err.decode(errors="replace")[-500:]
                    or "missing finalized temp output"
                )
                log.warning(
                    f"phone finalize failed {src.stem} h{hook_idx} {recipe.name}; using encoded output: {msg}"
                )

        final_tmp_path.replace(out_path)
        try:
            metadata_normalization = normalize_rendered_mp4_metadata(out_path)
        except RuntimeError as e:
            msg = str(e)
            log.error(f"FAIL {src.stem} h{hook_idx} {recipe.name}: {msg}")
            manifest.add_failure(
                src.stem,
                recipe,
                caption_for_manifest,
                out_path,
                key,
                duration,
                msg,
                render_time_sec=round(elapsed, 3),
                encoder=output_profile,
                target_ratio=target_ratio,
            )
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
            return {"status": "failed", "key": key}
        caption_hash = sha256_str(caption_for_manifest)
        write_caption_lineage_sidecar(
            out_path,
            {
                **(caption_lineage or {}),
                "captionBurnedIn": bool(recipe.burn_caption),
                "captionTimingQc": caption_timing_qc,
            },
            caption_text=caption_for_manifest,
            caption_hash=caption_hash,
            render_recipe=recipe.name,
            source_clip=src.stem,
            rendered_output=str(out_path),
        )
        source_lineage_path = src.with_suffix(".generated_asset_lineage.json")
        write_generated_asset_lineage_sidecar(
            out_path,
            source_lineage_path=(
                source_lineage_path if source_lineage_path.is_file() else None
            ),
            render_job_key=key,
            source_hash=src_hash,
        )

        if mezz_cmd:
            try:
                mezz_tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            mezz_started = int(time.time())
            p_mezz = await asyncio.create_subprocess_exec(
                *mezz_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(out_dir),
            )
            _, mezz_err = await p_mezz.communicate()
            manifest.add_attempt(
                key=f"{key}:mezzanine",
                attempt_no=1,
                status="ok" if p_mezz.returncode == 0 else "failed",
                temp_path=mezz_tmp_path,
                final_path=mezz_out_path,
                ffmpeg_cmd=mezz_cmd,
                started_at=mezz_started,
                ended_at=int(time.time()),
                error_message=mezz_err.decode(errors="replace")
                if p_mezz.returncode != 0
                else None,
            )
            if (
                p_mezz.returncode == 0
                and mezz_tmp_path.exists()
                and mezz_tmp_path.stat().st_size > 0
            ):
                mezz_tmp_path.replace(mezz_out_path)
                log.info(
                    f"mezzanine {src.stem} h{hook_idx} {recipe.name} → {mezz_out_path.name}"
                )
            else:
                msg = (
                    mezz_err.decode(errors="replace")[-500:]
                    or "missing mezzanine temp output"
                )
                log.warning(
                    f"mezzanine failed {src.stem} h{hook_idx} {recipe.name}: {msg}"
                )

        log.info(
            f"done {src.stem} h{hook_idx} {recipe.name} [{color}] "
            f"({elapsed:.1f}s) → {out_filename}"
        )

    for png_path, _, _ in caption_pngs:
        try:
            png_path.unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"could not remove temp caption png {png_path.name}: {e}")
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    caption_position = ",".join(dict.fromkeys([seg.band for seg in seg_plans])) or band
    generation_id = (
        caption.get("generationId") or caption.get("generation_id")
        if isinstance(caption, dict)
        else None
    )
    placement_decision = (
        _placement_summary.metadata.get("captionPlacementDecision")
        if isinstance(_placement_summary.metadata, dict)
        else {}
    )
    placement_policy = (
        _placement_summary.metadata.get("captionPlacementPolicy")
        if isinstance(_placement_summary.metadata, dict)
        else None
    ) or ("legacy" if caption_placement_policy == "legacy" else "focal_safe_v1")
    placement_lineage = {
        **(caption_lineage or {}),
        "captionHash": caption_hash,
        "captionBurnedIn": bool(recipe.burn_caption),
        "overlaySemanticQc": overlay_semantic_qc,
        "captionTimingQc": caption_timing_qc,
        "captionPlacementPolicy": placement_policy,
        "captionPlacementDecision": {
            **(placement_decision if isinstance(placement_decision, dict) else {}),
            "selectedLane": caption_position,
        },
    }
    write_caption_lineage_sidecar(
        out_path,
        placement_lineage,
        caption_text=caption_for_manifest,
        caption_hash=caption_hash,
        render_recipe=recipe.name,
        source_clip=src.stem,
        rendered_output=str(out_path),
    )
    caption_context = build_caption_outcome_context(
        caption_text=caption_for_manifest,
        caption_lineage=placement_lineage,
        render_recipe=recipe.name,
        source_clip=src.stem,
        rendered_output=str(out_path),
    )
    caption_context["overlaySemanticQc"] = overlay_semantic_qc
    caption_context["overlay_semantic_qc"] = overlay_semantic_qc
    caption_context["captionTimingQc"] = caption_timing_qc
    caption_context["caption_timing_qc"] = caption_timing_qc
    manifest.add_variation(
        src.stem,
        recipe,
        caption_for_manifest,
        out_path,
        key,
        duration,
        render_time_sec=round(elapsed, 3),
        encoder=output_profile,
        target_ratio=target_ratio,
        lineage={
            "sourceHash": src_hash,
            "captionHash": caption_hash,
            "captionBank": placement_lineage,
            "captionOutcomeContext": caption_context,
            "recipe": recipe.name,
            "format": "reel_pack",
            "font": font,
            "captionFontDecision": font_decision,
            "captionStyle": style,
            "captionPosition": caption_position,
            "captionPlacementPolicy": placement_policy,
            "captionPlacementDecision": placement_lineage["captionPlacementDecision"],
            "captionTimingQc": caption_timing_qc,
            "metadataNormalization": metadata_normalization,
            "generationId": generation_id,
            "renderJobKey": key,
        },
    )
    return {"status": "ok", "key": key, "out": str(out_path)}


# ────────────────────────────────────────────────────────────────────────────
# Discovery + main
# ────────────────────────────────────────────────────────────────────────────
