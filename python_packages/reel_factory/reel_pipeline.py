"""
reel_pipeline.py — caption burn-in + silent variation generation.
M4 Max optimized: h264_videotoolbox, configurable encodes, PNG caption overlays.

Audio is intentionally stripped (-an) — attach trending sounds in-app or via
your downstream Juno33 muxer. The orchestrator outputs silent, captioned MP4s.

Usage:
    python reel_pipeline.py --root .
    python reel_pipeline.py --root . --recipes v01_original v05_hflip
    python reel_pipeline.py --root . --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import shutil
import shlex
import sys
import time
from dataclasses import dataclass, asdict, field, replace
from datetime import datetime, timezone
from pathlib import Path

from asset_prompt_contract import AssetPromptSet, parse_asset_prompt_response
from campaign_store import link_campaign_output
from graph_builder import ENCODER_PROFILES, build_ffmpeg_cmd as build_graph_ffmpeg_cmd
from graph_builder import build_video_filter as build_graph_video_filter
from graph_builder import target_dimensions
from identity_verification import get_identity_provider
from media_metadata import normalize_media_metadata
from preflight import check_clip_readiness
from project_config import load_config
from placement import (
    CaptionSegmentPlan, PlacementSummary, mirror_side_band_for_recipe, pick_caption_color,
    probe_caption_layout, probe_caption_region_luminance, probe_dimensions,
    probe_duration, probe_source_bitrate, resolve_segment_bands,
)
from recipe_loader import load_recipes
from render_plan import RenderPlan, validate_account_scope
from variation_engine import get_pack_version, vary_caption_text
from caption_bank import CaptionBankStore, caption_static_metadata, load_or_build_caption_bank_store
from discoverability_safety import discoverability_safe_content_contract
from caption_scene_fit import (
    CAPTION_SCENE_FIT_VERSION,
    caption_text_for_scene,
    classify_reel_scene_tags,
    evaluate_scene_compatibility,
)

# ────────────────────────────────────────────────────────────────────────────
# Logging — line-delimited JSON to stdout, easy to grep / pipe to jq
# ────────────────────────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "ts": int(time.time() * 1000),
            "lvl": record.levelname,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False)


log = logging.getLogger("reel")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
log.addHandler(_handler)
log.setLevel(logging.INFO)


# ────────────────────────────────────────────────────────────────────────────
# Recipes — the variation matrix
# ────────────────────────────────────────────────────────────────────────────
DEFAULT_CAPTION_FONT = "Instagram Sans Condensed"
INSTAGRAM_BOLD_CAPTION_FONT = "Instagram Sans Condensed Bold"
INSTAGRAM_CAPTION_FONTS = {DEFAULT_CAPTION_FONT, INSTAGRAM_BOLD_CAPTION_FONT}
BOLD_CAPTION_STYLES = {"meme"}
CREATOR_STYLE_PRESETS = {"auto", "none", "stacey_static_center"}


def apply_creator_style_preset(args) -> str | None:
    preset = getattr(args, "creator_style_preset", "auto") or "auto"
    if preset == "auto":
        preset = "stacey_static_center" if args.caption_mix in {"Larissa", "Stacey"} else "none"
    if preset == "none":
        return None
    if preset != "stacey_static_center":
        raise ValueError(f"unknown creator style preset: {preset}")

    # ponytail: this is the whole Stacey/Larissa reel format; split presets only after another account needs different defaults.
    if args.band is None:
        args.band = "center"
    if args.style is None:
        args.style = "ig"
    if args.font is None:
        args.font = DEFAULT_CAPTION_FONT
    if args.color is None:
        args.color = "light"
    args._creator_style_preset_applied = preset
    return preset


def resolve_caption_font_policy(requested_font: str | None, caption_style: str) -> tuple[str, dict]:
    """Normalize production captions to the Instagram font family.

    Historical recipes and account profiles can still request older fonts.
    Keep that compatibility at the API boundary, but never let those fonts reach
    burn-in or render lineage for production reels.
    """
    requested = requested_font or DEFAULT_CAPTION_FONT
    decision = {
        "requestedFont": requested,
        "resolvedFont": DEFAULT_CAPTION_FONT,
        "captionStyle": caption_style,
        "policy": "instagram_caption_font_policy_v1",
        "reason": "default_regular",
    }
    if requested not in INSTAGRAM_CAPTION_FONTS:
        decision["reason"] = "non_instagram_font_coerced_to_regular"
        return DEFAULT_CAPTION_FONT, decision
    if requested == INSTAGRAM_BOLD_CAPTION_FONT:
        if caption_style in BOLD_CAPTION_STYLES:
            decision["resolvedFont"] = INSTAGRAM_BOLD_CAPTION_FONT
            decision["reason"] = "bold_allowed_for_meme_style"
            return INSTAGRAM_BOLD_CAPTION_FONT, decision
        decision["reason"] = "bold_downgraded_to_regular_for_non_meme_style"
        return DEFAULT_CAPTION_FONT, decision
    decision["resolvedFont"] = DEFAULT_CAPTION_FONT
    return DEFAULT_CAPTION_FONT, decision


# ffmpeg/ffprobe binary resolution
# ────────────────────────────────────────────────────────────────────────────
# Prefer ffmpeg-full when present, but the active caption path only needs
# regular ffmpeg overlays plus VideoToolbox encoding.
_FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin")
FFMPEG = str(_FFMPEG_FULL / "ffmpeg") if (_FFMPEG_FULL / "ffmpeg").exists() else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = str(_FFMPEG_FULL / "ffprobe") if (_FFMPEG_FULL / "ffprobe").exists() else shutil.which("ffprobe") or "ffprobe"
AVCONVERT = shutil.which("avconvert")


def reexec_with_homebrew_gi_env_if_needed() -> None:
    """Restart once so optional Pango/PyGObject can find Homebrew dylibs."""
    brew_lib = "/opt/homebrew/lib"
    if os.environ.get("REEL_FACTORY_GI_ENV_READY") == "1" or not Path(brew_lib).exists():
        return
    env = dict(os.environ)
    for key in ("DYLD_FALLBACK_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key, "")
        if brew_lib not in current.split(":"):
            env[key] = f"{brew_lib}:{current}" if current else brew_lib
    env["REEL_FACTORY_GI_ENV_READY"] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)


# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Recipe:
    name: str
    trim_head: float = 0.0          # seconds to drop from start
    trim_tail: float = 0.0          # seconds to drop from end
    speed: float = 1.0              # 1.05 = 5% faster, 0.95 = 5% slower
    zoom: float = 1.0               # 1.08 = 8% zoom-in (crop+rescale)
    tilt_deg: float = 0.0           # subtle fixed rotation before final scale
    hflip: bool = False             # mirror horizontally
    reverse: bool = False           # play backwards
    eq_contrast: float = 1.0
    eq_saturation: float = 1.0
    eq_brightness: float = 0.0      # -0.1..0.1 typical
    burn_caption: bool = True       # set False to skip the PNG caption overlay
    caption_color: str = "auto"     # "light" / "dark" / "auto" (sampled luminance)
    caption_style: str = "auto"     # "classic" / "meme" / "ig" / "thin" / "soft" / "bubble" / "auto" (frame busyness)
    caption_band:  str = "auto"     # "top" / "bottom" / "center" / "left" / "right" / "auto"
    font: str           = DEFAULT_CAPTION_FONT
    text_variation: str = "off"     # "off" → preserve original caption exactly; "auto" → slang/case mangle per recipe
    text_variation_pack: str = "default"
    text_variation_pack_version: str = "default@1"
    color_preset: str = "none"      # "none" / "bright_pop" / "warm" / "cool" / "cinematic"
    camera_variation: bool = True   # subtle crop, rotation, color, sharpening, and grain so outputs feel phone-native
    target_ratios: list[str] | None = None


RECIPES = load_recipes(Path(__file__).parent / "recipes" / "default.json", Recipe)
RECIPES_BY_NAME = {r.name: r for r in RECIPES}


# ────────────────────────────────────────────────────────────────────────────
# Caption → ASS file
# ────────────────────────────────────────────────────────────────────────────
# ASS color format is &HAABBGGRR (alpha-blue-green-red, AA=00 opaque)
COLORS = {
    "light": {  # white text + thick black stroke (default for dark/mixed bg)
        "primary":  "&H00FFFFFF",  # white fill
        "outline":  "&H00000000",  # black stroke
    },
    "dark": {   # black text + thick white stroke (for bright/light bg)
        "primary":  "&H00000000",  # black fill
        "outline":  "&H00FFFFFF",  # white stroke
    },
}

# ────────────────────────────────────────────────────────────────────────────
# Caption discovery — supports .txt (one hook) and .json (multi-hook sidecar)
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class CaptionSet:
    hooks: list[str | dict]                     # one or more hook variations; dict = timed segments
    recipe_names: list[str] | None = None       # None = use all RECIPES
    caption_color: str | None = None            # "light" | "dark" | "auto" | None (recipe default)
    notes: str = ""
    hook_lineage: dict[int, dict] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Path) -> "CaptionSet":
        if path.suffix == ".txt":
            hook = path.read_text(encoding="utf-8").strip()
            if not hook:
                raise ValueError(f"empty caption file: {path}")
            return cls(hooks=[hook])
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            hooks = data.get("hooks") or [data.get("caption", "")]
            if not isinstance(hooks, list):
                raise ValueError(f"hooks must be a list in {path}")
            parsed: list[str | dict] = []
            for h in hooks:
                _ensure_discoverability_safe_caption(h, source=str(path))
                if isinstance(h, dict):
                    if "segments" not in h:
                        raise ValueError(f"hook dict missing 'segments' key in {path}")
                    parsed.append(h)
                else:
                    s = str(h).strip()
                    if s:
                        parsed.append(s)
            if not parsed:
                raise ValueError(f"no hooks found in {path}")
            hooks = parsed
            caption_color = data.get("caption_color")
            if caption_color is not None and caption_color not in {"light", "dark", "auto"}:
                raise ValueError(f"caption_color must be light, dark, or auto in {path}")
            return cls(
                hooks=hooks,
                recipe_names=data.get("recipes"),
                caption_color=caption_color,
                notes=data.get("notes", ""),
            )
        raise ValueError(f"unknown caption format: {path}")




def find_caption_for(video: Path, cap_dir: Path) -> CaptionSet | None:
    """Resolution order: 01_captions/{stem}.json → 01_captions/{stem}.txt"""
    j = cap_dir / f"{video.stem}.json"
    if j.exists():
        return CaptionSet.from_path(j)
    t = cap_dir / f"{video.stem}.txt"
    if t.exists():
        return CaptionSet.from_path(t)
    return None


def _caption_contract_text(caption: str | dict) -> str:
    if isinstance(caption, str):
        return caption.strip()
    if isinstance(caption, dict):
        if isinstance(caption.get("text"), str):
            return caption["text"].strip()
        segments = caption.get("segments")
        if isinstance(segments, list):
            return "\n".join(
                str(segment.get("text") or "").strip()
                for segment in segments
                if isinstance(segment, dict) and str(segment.get("text") or "").strip()
            ).strip()
    return str(caption).strip()


def _ensure_discoverability_safe_caption(caption: str | dict, *, source: str) -> None:
    text = _caption_contract_text(caption)
    contract = discoverability_safe_content_contract(text)
    if contract["discoverabilitySafe"]:
        return
    raise ValueError(
        "discoverability unsafe caption blocked "
        f"source={source} terms={','.join(contract['blockedTerms'])}: {text}"
    )


def build_video_filter(recipe: Recipe, src_duration: float, ass_path: Path,
                       fonts_dir: Path, src_hash: str = "",
                       src_w: int = 1080, src_h: int = 1920,
                       account_scope: str = "local_review") -> str:
    plan = RenderPlan(
        src=Path("input.mp4"),
        caption_pngs=[],
        recipe=recipe,
        out=Path("out.mp4"),
        duration=src_duration,
        fonts_dir=fonts_dir,
        src_hash=src_hash,
        src_dims=(src_w, src_h),
        account_scope=account_scope,
    )
    return build_graph_video_filter(plan)


def build_ffmpeg_cmd(src: Path,
                     caption_pngs: list[tuple[Path, float, float | None]],
                     recipe: Recipe, out: Path,
                     duration: float, fonts_dir: Path,
                     src_hash: str = "",
                     src_dims: tuple[int, int] = (1080, 1920),
                     bitrate_mbps: int = 14,
                     src_bitrate_mbps: int | None = None,
                     output_profile: str = "mac_h264_videotoolbox",
                     target_ratio: str = "9:16",
                     account_scope: str = "local_review") -> list[str]:
    plan = RenderPlan(
        src=src,
        caption_pngs=caption_pngs,
        recipe=recipe,
        out=out,
        duration=duration,
        fonts_dir=fonts_dir,
        src_hash=src_hash,
        src_dims=src_dims,
        bitrate_mbps=bitrate_mbps,
        src_bitrate_mbps=src_bitrate_mbps,
        output_profile=output_profile,
        target_ratio=target_ratio,
        account_scope=account_scope,
    )
    return build_graph_ffmpeg_cmd(plan, FFMPEG)


def phone_creation_time() -> str:
    """Creation timestamp format used by mobile-authored MP4 metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_phone_finalize_cmd(src: Path, out: Path, creation_time: str, ffmpeg: str = FFMPEG) -> list[str]:
    """Build a stream-copy MP4 finalization command for social upload outputs."""
    return [
        ffmpeg,
        "-hide_banner", "-y", "-nostdin",
        "-i", str(src),
        "-map", "0:v:0",
        "-c:v", "copy",
        "-an",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-metadata", f"creation_time={creation_time}",
        "-metadata:s:v:0", f"creation_time={creation_time}",
        "-metadata:s:v:0", "language=und",
        "-metadata:s:v:0", "handler_name=Core Media Video",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-brand", "mp42",
        str(out),
    ]


def build_avconvert_finalize_cmd(src: Path, out: Path, avconvert: str = AVCONVERT or "avconvert") -> list[str]:
    """Build a macOS AVFoundation passthrough finalizer command."""
    return [
        avconvert,
        "--source", str(src),
        "--preset", "PresetPassthrough",
        "--output", str(out),
        "--replace",
    ]


def normalize_rendered_mp4_metadata(path: Path) -> dict:
    if path.suffix.lower() != ".mp4":
        return {"metadataNormalized": True, "metadataWarnings": [], "skipped": "non_mp4"}
    result = normalize_media_metadata(path, dry_run=False)
    if not result.get("metadataNormalized"):
        warnings = result.get("metadataWarnings") or ["metadata_not_normalized"]
        raise RuntimeError(f"metadata_normalization_failed:{','.join(str(item) for item in warnings)}")
    return result


def enforce_production_identity_provider(production_render: bool) -> dict:
    if not production_render:
        return {"required": False, "provider": "", "providerAvailable": None}
    executable = Path(sys.executable).resolve()
    if ".venv" not in executable.parts:
        raise RuntimeError("production_render_requires_venv_python")
    provider = get_identity_provider()
    ok, reason = provider.available()
    if not ok or provider.name != "insightface_arcface":
        raise RuntimeError(f"production_render_identity_provider_unavailable:{provider.name}:{reason}")
    return {"required": True, "provider": provider.name, "providerAvailable": True}


# ────────────────────────────────────────────────────────────────────────────
# Hashing — content-addressed job keys
# ────────────────────────────────────────────────────────────────────────────
def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def effective_placement_mode_for_caption(caption: str | dict, placement_mode: str) -> str:
    """Timed captions should use segment-aware placement by default."""
    if isinstance(caption, dict) and placement_mode == "source":
        return "segment"
    return placement_mode


def compute_job_key(video_hash: str, caption: str | dict, recipe: Recipe,
                    placement_mode: str = "source",
                    target_ratio: str = "9:16",
                    caption_placement_policy: str = "focal-safe",
                    account_scope: str = "local_review") -> str:
    placement_mode = effective_placement_mode_for_caption(caption, placement_mode)
    cap_str = json.dumps(caption, sort_keys=True, ensure_ascii=False) if isinstance(caption, dict) else caption
    cap_h = sha256_str(cap_str)
    rec_params = asdict(recipe)
    if not isinstance(caption, dict):
        rec_params["_static_caption_centered_policy"] = "v2"
    if caption_placement_policy != "legacy":
        rec_params["_caption_placement_policy"] = "focal_safe_v1"
    if placement_mode != "source":
        rec_params["_placement_mode"] = placement_mode
    if target_ratio != "9:16":
        rec_params["_target_ratio"] = target_ratio
    scope = (account_scope or "local_review").strip() or "local_review"
    if scope != "local_review":
        rec_params["_account_scope"] = scope
    rec_h = sha256_str(json.dumps(rec_params, sort_keys=True))
    return hashlib.sha256(f"{video_hash}|{cap_h}|{rec_h}".encode()).hexdigest()


def centered_static_caption_band(
    band: str,
    summary: PlacementSummary,
    *,
    diversity_key: str | None = None,
) -> str:
    """Static captions should stay horizontally centered.

    Left/right placement is reserved for timed captions where movement is
    intentional. For single static hooks, choose among top/center/bottom so
    repeated mirror clips do not all collapse into the same visual position.
    """
    if band not in {"left", "right"}:
        return band
    decision = summary.metadata.get("captionPlacementDecision") if isinstance(summary.metadata, dict) else None
    rejected = {str(zone) for zone in (decision or {}).get("rejectedLanes", [])} if isinstance(decision, dict) else set()
    candidates = [zone for zone in ("top", "center", "bottom") if zone in summary.scores and zone not in rejected]
    if not candidates:
        return "center"
    if diversity_key:
        best_score = min(float(summary.scores[zone]) for zone in candidates)
        eligible = [
            zone for zone in candidates
            if float(summary.scores[zone]) <= best_score + 12.0
            or float(summary.scores[zone]) <= best_score * 1.35
        ]
        ranked = sorted(eligible or candidates, key=lambda zone: (summary.scores[zone], zone))
        start = int(hashlib.sha256(diversity_key.encode("utf-8")).hexdigest()[:8], 16) % len(ranked)
        return ranked[start]
    return min(candidates, key=lambda zone: summary.scores[zone])


def load_asset_prompt_set(path: Path | None) -> tuple[AssetPromptSet, Path] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    return parse_asset_prompt_response(resolved.read_text(encoding="utf-8")), resolved


def write_generated_asset_lineage_sidecar(
    out_path: Path,
    *,
    source_lineage_path: Path | None,
    render_job_key: str,
    source_hash: str,
) -> Path:
    sidecar = out_path.with_suffix(out_path.suffix + ".generated_asset_lineage.json")
    payload = {
        "schema": "campaign_factory.generated_asset_lineage.v1",
        "pipelineTraceId": f"trace_reel_render_{hashlib.sha256(f'{source_hash}:{render_job_key}'.encode('utf-8')).hexdigest()[:16]}",
        "source": {
            "sourceLineagePath": str(source_lineage_path) if source_lineage_path else None,
            "sourceVideoHash": source_hash,
        },
        "generation": {
            "tool": "reel_factory.reel_pipeline",
        },
        "render": {
            "renderJobKey": render_job_key,
            "outputPath": str(out_path),
        },
        "review": {
            "humanReviewRequired": True,
        },
        "createdAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return sidecar


def build_caption_outcome_context(
    *,
    caption_text: str,
    caption_lineage: dict | None,
    render_recipe: str | None,
    source_clip: str | None,
    rendered_output: str | None,
    creator_model: str | None = None,
) -> dict:
    lineage = caption_lineage if isinstance(caption_lineage, dict) else {}
    selected_banks = _text_list(lineage.get("selectedBanks") or lineage.get("selected_banks") or lineage.get("sourceBanks") or lineage.get("source_banks"))
    caption_hash = _first_text(lineage.get("captionHash"), lineage.get("caption_hash"), sha256_str(caption_text))
    primary_bank = _first_text(lineage.get("selectedBank"), lineage.get("selected_bank"), selected_banks[0] if selected_banks else None)
    return {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_text": _first_text(lineage.get("rawCaptionText"), lineage.get("raw_caption_text"), caption_text),
        "caption_bank": primary_bank,
        "caption_banks": selected_banks or ([primary_bank] if primary_bank else []),
        "creator_mix": _first_text(lineage.get("selectedMix"), lineage.get("selected_mix")),
        "creator_model": _first_text(lineage.get("creatorModel"), lineage.get("creator_model"), creator_model),
        "frame_type": _first_text(lineage.get("frameType"), lineage.get("frame_type")),
        "length_class": _first_text(lineage.get("lengthClass"), lineage.get("length_class")),
        "format_class": _first_text(lineage.get("formatClass"), lineage.get("format_class")),
        "caption_fit_version": _first_text(lineage.get("captionFitVersion"), lineage.get("caption_fit_version")),
        "suitability_decision": _first_text(lineage.get("suitabilityDecision"), lineage.get("suitability_decision")),
        "suitability_reason": _first_text(lineage.get("suitabilityReason"), lineage.get("suitability_reason")),
        "captionSceneTags": lineage.get("captionSceneTags") if isinstance(lineage.get("captionSceneTags"), list) else [],
        "reelSceneTags": lineage.get("reelSceneTags") if isinstance(lineage.get("reelSceneTags"), list) else [],
        "sceneCompatibilityDecision": _first_text(lineage.get("sceneCompatibilityDecision")),
        "sceneCompatibilityReason": _first_text(lineage.get("sceneCompatibilityReason")),
        "captionSceneFitVersion": _first_text(lineage.get("captionSceneFitVersion")),
        "captionPlacementPolicy": _first_text(lineage.get("captionPlacementPolicy")),
        "captionPlacementDecision": lineage.get("captionPlacementDecision") if isinstance(lineage.get("captionPlacementDecision"), dict) else None,
        "render_recipe": render_recipe,
        "source_clip": _first_text(lineage.get("sourceClip"), lineage.get("source_clip"), source_clip),
        "rendered_output": rendered_output,
    }


def _caption_lineage_with_outcome_context(
    lineage: dict | None,
    *,
    caption_text: str | None = None,
    caption_hash: str | None = None,
    render_recipe: str | None = None,
    source_clip: str | None = None,
    rendered_output: str | None = None,
    creator_model: str | None = None,
) -> dict | None:
    if not lineage:
        return None
    enriched = dict(lineage)
    if caption_hash:
        enriched["captionHash"] = caption_hash
        enriched.pop("captionOutcomeContext", None)
    if not isinstance(enriched.get("captionOutcomeContext"), dict):
        enriched["captionOutcomeContext"] = build_caption_outcome_context(
            caption_text=caption_text or str(enriched.get("rawCaptionText") or ""),
            caption_lineage=enriched,
            render_recipe=render_recipe,
            source_clip=source_clip,
            rendered_output=rendered_output,
            creator_model=creator_model,
        )
    return enriched


def _first_text(*values) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def write_caption_lineage_sidecar(
    out_path: Path,
    lineage: dict | None,
    *,
    caption_text: str | None = None,
    caption_hash: str | None = None,
    render_recipe: str | None = None,
    source_clip: str | None = None,
    rendered_output: str | None = None,
    creator_model: str | None = None,
) -> Path | None:
    if not lineage:
        return None
    payload = _caption_lineage_with_outcome_context(
        lineage,
        caption_text=caption_text,
        caption_hash=caption_hash,
        render_recipe=render_recipe,
        source_clip=source_clip,
        rendered_output=rendered_output or str(out_path),
        creator_model=creator_model,
    ) or lineage
    sidecar = out_path.with_suffix(out_path.suffix + ".caption_lineage.json")
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return sidecar


def source_lineage_path_for(src: Path) -> Path:
    return src.with_suffix(".generated_asset_lineage.json")


def ensure_source_asset_lineage(
    src: Path,
    *,
    prompt_set: AssetPromptSet,
    prompt_source_path: Path,
) -> Path:
    path = source_lineage_path_for(src)
    if path.exists():
        return path
    payload = {
        "schema": "campaign_factory.generated_asset_lineage.v2",
        "createdAt": int(time.time()),
        "source": {
            "stem": src.stem,
            "promptSourcePath": str(prompt_source_path),
            "sourceVideoPath": str(src),
        },
        "generation": {
            "tool": "higgsfield_kling_manual",
            "workflow": "manual_prompt_to_imported_video",
            "models": {
                "image": "text2image_soul_v2",
                "video": "kling3_0",
            },
            "prompts": asdict(prompt_set),
        },
        "assets": {
            "localPaths": {
                "video": str(src),
            },
        },
        "review": {
            "humanReviewRequired": True,
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_single_job_enqueue_cmd(
    *,
    root: Path,
    video_stem: str,
    hook_idx: int,
    recipe: Recipe,
    args,
    target_ratio: str,
) -> list[str]:
    cmd = [
        sys.executable, "reel_pipeline.py",
        "--root", str(root),
        "--only-clip", video_stem,
        "--recipes", recipe.name,
        "--only-hook-index", str(hook_idx),
        "--output-profile", args.output_profile,
        "--caption-renderer", args.caption_renderer,
        "--placement-signals", args.placement_signals,
        "--placement-mode", args.placement_mode,
        "--caption-placement-policy", args.caption_placement_policy,
        "--target-ratios", target_ratio,
        "--color", recipe.caption_color,
        "--style", recipe.caption_style,
        "--band", recipe.caption_band,
        "--font", recipe.font,
        "--text-variation", recipe.text_variation,
        "--variation-pack", recipe.text_variation_pack,
    ]
    if args.mezzanine:
        cmd.append("--mezzanine")
    if not args.phone_finalize:
        cmd.append("--no-phone-finalize")
    if args.rerender_all:
        cmd.append("--rerender-all")
    account_scope = getattr(args, "account", None)
    if account_scope:
        cmd += ["--account", account_scope]
    if args.strict_preflight:
        cmd.append("--strict-preflight")
    if args.asset_prompt_json:
        cmd += ["--asset-prompt-json", str(Path(args.asset_prompt_json).expanduser().resolve())]
    if getattr(args, "ai_qc", False):
        cmd.append("--ai-qc")
    if getattr(args, "readiness", False):
        cmd.append("--readiness")
    return cmd


# ────────────────────────────────────────────────────────────────────────────
# Manifest storage lives in manifest.py
# ────────────────────────────────────────────────────────────────────────────
from manifest import Manifest


# ────────────────────────────────────────────────────────────────────────────
async def process_one(src: Path, caption: str | dict, hook_idx: int, recipe: Recipe,
                      out_dir: Path, fonts_dir: Path, manifest: Manifest,
                      src_hash: str, duration: float,
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
                      asset_prompt_info: tuple[AssetPromptSet, Path] | None = None,
                      caption_lineage: dict | None = None,
                      account_scope: str = "local_review") -> dict:
    """Render one (video, caption_variant, recipe) combo."""
    placement_mode = effective_placement_mode_for_caption(caption, placement_mode)
    key = compute_job_key(src_hash, caption, recipe, placement_mode=placement_mode,
                          target_ratio=target_ratio,
                          caption_placement_policy=caption_placement_policy,
                          account_scope=account_scope)

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
            src, duration,
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
        recipe_idx = next((i for i, r in enumerate(RECIPES) if r.name == recipe.name), 0)
        if auto_band in {"left", "right"}:
            band = mirror_side_band_for_recipe(auto_band, recipe)
        elif caption_placement_policy != "legacy" and not is_timed_caption:
            band = auto_band
        else:
            opposite = "bottom" if auto_band == "top" else "top"
            band = [auto_band, "center", opposite][recipe_idx % 3]
    if not is_timed_caption:
        diversity_key = f"{src_hash}|{hook_idx}|{recipe.name}|{caption}"
        band = centered_static_caption_band(band, _placement_summary, diversity_key=diversity_key)
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
            log.warning(f"{src.stem} h{hook_idx} {recipe.name}: empty segments list, no caption overlay")
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
            # Per-segment explicit band wins; otherwise cycle top→center→bottom
            # across segments so each caption appears in a different screen zone —
            # drives retention by keeping the viewer's eye moving.
            explicit_band = "band" in seg
            seg_band = str(seg["band"]) if explicit_band else band
            seg_plans.append(CaptionSegmentPlan(seg_png, start, end, seg_text, seg_band, explicit_band))
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
    ratio_suffix = "" if target_ratio == "9:16" else f"_{target_ratio.replace(':', 'x')}"
    ext = ".png" if preview else ".mp4"
    out_filename = f"{src.stem}_h{hook_idx:02d}_{recipe.name}{ratio_suffix}_{color}_{key[:8]}{ext}"
    out_path = out_dir / out_filename
    tmp_dir = out_dir / ".tmp" / key[:16]
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_out_path = tmp_dir / out_filename
    try:
        tmp_out_path.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = build_ffmpeg_cmd(src, caption_pngs, recipe, tmp_out_path, duration,
                            fonts_dir, src_hash=src_hash, src_dims=src_dims,
                            src_bitrate_mbps=src_bitrate_mbps,
                            output_profile=output_profile,
                            target_ratio=target_ratio,
                            account_scope=account_scope)
    mezz_out_path = out_dir / f"{src.stem}_h{hook_idx:02d}_{recipe.name}_{color}_{key[:8]}_mezz.mov"
    mezz_tmp_path = tmp_dir / mezz_out_path.name
    mezz_cmd = build_ffmpeg_cmd(
        src, caption_pngs, recipe, mezz_tmp_path, duration,
        fonts_dir, src_hash=src_hash, src_dims=src_dims,
        src_bitrate_mbps=src_bitrate_mbps,
        output_profile="prores_lt",
        target_ratio=target_ratio,
        account_scope=account_scope,
    ) if mezzanine else None

    if dry_run:
        log.info(f"DRY {src.stem} h{hook_idx} {recipe.name} [{color}] → {out_filename}")
        log.info(f"CMD {' '.join(shlex.quote(c) for c in cmd)}")
        if mezz_cmd:
            log.info(f"MEZZ {' '.join(shlex.quote(c) for c in mezz_cmd)}")
        return {"status": "dry"}

    caption_for_manifest = (
        json.dumps(caption, sort_keys=True, ensure_ascii=False)
        if isinstance(caption, dict) else caption
    )

    # Render each caption segment to a transparent 1080x1920 PNG via PIL+Pilmoji.
    from caption_render import caption_alpha_box, render_caption_png
    caption_render_boxes = []
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
            caption_render_boxes.append({
                "text": seg.text,
                "band": seg.band,
                "start": seg.start,
                "end": seg.end,
                "box": caption_alpha_box(seg.png_path),
            })
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
            src.stem, recipe, caption_for_manifest, out_path, key, duration, msg,
            encoder=output_profile,
            target_ratio=target_ratio,
        )
        return {"status": "failed", "key": key}

    if preview:
        preview_dir = out_dir / "_previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / out_filename
        mid_t = max(0.05, min(duration - 0.05, duration * 0.5))
        vf = build_graph_video_filter(RenderPlan(
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
        ))
        fc_parts = [f"[0:v]{vf}[vs0]"]
        inputs = ["-ss", f"{mid_t:.3f}", "-i", str(src)]
        for i, (png_path, _, _) in enumerate(caption_pngs):
            inputs += ["-loop", "1", "-i", str(png_path)]
            fc_parts.append(f"[{i + 1}:v]format=rgba[cap{i}]")
        for i in range(len(caption_pngs)):
            in_s = f"vs{i}"
            out_s = f"vs{i + 1}" if i < len(caption_pngs) - 1 else "vsf"
            fc_parts.append(f"[{in_s}][cap{i}]overlay=0:0:eof_action=pass:format=auto[{out_s}]")
        fc_parts.append("[vsf]format=rgba[v]")
        p = await asyncio.create_subprocess_exec(
            FFMPEG, "-hide_banner", "-y", "-nostdin",
            *inputs, "-filter_complex", ";".join(fc_parts),
            "-map", "[v]", "-frames:v", "1", str(preview_path),
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
            if isinstance(_placement_summary.metadata, dict) else {}
        )
        placement_policy = (
            _placement_summary.metadata.get("captionPlacementPolicy")
            if isinstance(_placement_summary.metadata, dict) else None
        ) or ("legacy" if caption_placement_policy == "legacy" else "focal_safe_v1")
        write_caption_lineage_sidecar(
            preview_path,
            {
                **(caption_lineage or {}),
                "captionRenderBoxes": caption_render_boxes,
                "captionPlacementPolicy": placement_policy,
                "captionPlacementDecision": {
                    **(placement_decision if isinstance(placement_decision, dict) else {}),
                    "selectedLane": ",".join(dict.fromkeys([seg.band for seg in seg_plans])) or band,
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
                error_message=last_err.decode(errors="replace") if p.returncode != 0 else None,
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
            log.error(
                f"FAIL {src.stem} h{hook_idx} {recipe.name}: "
                f"{msg[-500:]}"
            )
            manifest.add_failure(
                src.stem, recipe, caption_for_manifest, out_path, key, duration,
                msg, render_time_sec=round(elapsed, 3),
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
                src.stem, recipe, caption_for_manifest, out_path, key, duration,
                msg, render_time_sec=round(elapsed, 3),
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
                error_message=finalize_err.decode(errors="replace") if not finalize_ok else None,
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
                    avconvert_cmd = build_avconvert_finalize_cmd(finalized_tmp_path, avconvert_tmp_path)
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
                        error_message=avconvert_err.decode(errors="replace") if not avconvert_ok else None,
                    )
                    if avconvert_ok:
                        final_tmp_path = avconvert_tmp_path
                        try:
                            finalized_tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    else:
                        msg = avconvert_err.decode(errors="replace")[-500:] or "missing avconvert temp output"
                        log.warning(f"avconvert finalize failed {src.stem} h{hook_idx} {recipe.name}; using ffmpeg phone output: {msg}")
            else:
                msg = finalize_err.decode(errors="replace")[-500:] or "missing finalized temp output"
                log.warning(f"phone finalize failed {src.stem} h{hook_idx} {recipe.name}; using encoded output: {msg}")

        final_tmp_path.replace(out_path)
        try:
            metadata_normalization = normalize_rendered_mp4_metadata(out_path)
        except RuntimeError as e:
            msg = str(e)
            log.error(f"FAIL {src.stem} h{hook_idx} {recipe.name}: {msg}")
            manifest.add_failure(
                src.stem, recipe, caption_for_manifest, out_path, key, duration,
                msg, render_time_sec=round(elapsed, 3),
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
            caption_lineage,
            caption_text=caption_for_manifest,
            caption_hash=caption_hash,
            render_recipe=recipe.name,
            source_clip=src.stem,
            rendered_output=str(out_path),
        )
        if asset_prompt_info:
            prompt_set, prompt_source_path = asset_prompt_info
            source_lineage_path = ensure_source_asset_lineage(
                src,
                prompt_set=prompt_set,
                prompt_source_path=prompt_source_path,
            )
            write_generated_asset_lineage_sidecar(
                out_path,
                source_lineage_path=source_lineage_path,
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
                error_message=mezz_err.decode(errors="replace") if p_mezz.returncode != 0 else None,
            )
            if p_mezz.returncode == 0 and mezz_tmp_path.exists() and mezz_tmp_path.stat().st_size > 0:
                mezz_tmp_path.replace(mezz_out_path)
                log.info(f"mezzanine {src.stem} h{hook_idx} {recipe.name} → {mezz_out_path.name}")
            else:
                msg = mezz_err.decode(errors="replace")[-500:] or "missing mezzanine temp output"
                log.warning(f"mezzanine failed {src.stem} h{hook_idx} {recipe.name}: {msg}")

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
    generation_id = caption.get("generationId") or caption.get("generation_id") if isinstance(caption, dict) else None
    placement_decision = (
        _placement_summary.metadata.get("captionPlacementDecision")
        if isinstance(_placement_summary.metadata, dict) else {}
    )
    placement_policy = (
        _placement_summary.metadata.get("captionPlacementPolicy")
        if isinstance(_placement_summary.metadata, dict) else None
    ) or ("legacy" if caption_placement_policy == "legacy" else "focal_safe_v1")
    placement_lineage = {
        **(caption_lineage or {}),
        "captionHash": caption_hash,
        "captionRenderBoxes": caption_render_boxes,
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
            "metadataNormalization": metadata_normalization,
            "generationId": generation_id,
            "renderJobKey": key,
        },
    )
    return {"status": "ok", "key": key, "out": str(out_path)}


# ────────────────────────────────────────────────────────────────────────────
# Discovery + main
# ────────────────────────────────────────────────────────────────────────────
def discover_pairs(raw_dir: Path, cap_dir: Path
                   ) -> list[tuple[Path, CaptionSet]]:
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
    if not selected:
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
        idx: store.lineage_for(
            item,
            selected_mix=selected_mix,
            selected_banks=item.get("selected_banks") or [],
        )
        for idx, item in enumerate(selected)
    }
    notes = (
        f"caption_mix={caption_mix}" if caption_mix
        else f"caption_banks={','.join(caption_banks or [])}"
    )
    return CaptionSet(hooks=hooks, recipe_names=None, caption_color=None, notes=notes, hook_lineage=lineage)


STATIC_ALLOWED_LENGTHS = {
    "closeup": {"very_short", "short", "medium", "long"},
    "halfbody": {"very_short", "short", "medium"},
    "mirror_fullbody": {"very_short", "short"},
    "wide_fullbody": {"very_short", "short"},
    "gym_body": {"very_short", "short", "medium"},
    "unknown": {"very_short", "short", "medium"},
}
CAPTION_FIT_VERSION = "v1"
STATIC_FALLBACK_LENGTHS = {
    "closeup": {"very_short", "short", "medium", "long"},
    "halfbody": {"very_short", "short", "medium"},
    "mirror_fullbody": {"very_short", "short", "medium"},
    "wide_fullbody": {"very_short", "short", "medium"},
    "gym_body": {"very_short", "short", "medium"},
    "unknown": {"very_short", "short", "medium"},
}


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


def _caption_sort_key_for_fit(index: int, hook: str | dict, lineage: dict) -> tuple[int, int, int]:
    metadata = caption_static_metadata(
        json.dumps(hook, sort_keys=True, ensure_ascii=False) if isinstance(hook, dict) else str(hook)
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
            text = json.dumps(hook, sort_keys=True, ensure_ascii=False) if isinstance(hook, dict) else str(hook)
            lineage = dict(cap_set.hook_lineage.get(idx) or {})
            meta = caption_static_metadata(text)
            scene = evaluate_scene_compatibility(
                caption_text=caption_text_for_scene(hook),
                caption_lineage=lineage,
                reel_scene_tags=reel_scene_tags,
                scene_fit_mode="off",
            )
            diagnostics.append({
                "caption": text,
                "bank": (lineage.get("selectedBanks") or lineage.get("sourceBanks") or [None])[0],
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
            })
        return cap_set, diagnostics

    allowed_lengths = STATIC_ALLOWED_LENGTHS.get(frame_type, STATIC_ALLOWED_LENGTHS["unknown"])
    fallback_lengths = STATIC_FALLBACK_LENGTHS.get(frame_type, STATIC_FALLBACK_LENGTHS["unknown"])
    allowed: list[tuple[int, str | dict, dict]] = []
    fallback: list[tuple[int, str | dict, dict]] = []

    for idx, hook in enumerate(cap_set.hooks):
        text = json.dumps(hook, sort_keys=True, ensure_ascii=False) if isinstance(hook, dict) else str(hook)
        lineage = dict(cap_set.hook_lineage.get(idx) or {})
        meta = caption_static_metadata(text)
        length_class = lineage.get("lengthClass") or meta["length_class"]
        format_class = lineage.get("formatClass") or meta["format_class"]
        bank = (lineage.get("selectedBanks") or lineage.get("sourceBanks") or [None])[0]
        readable = length_class in allowed_lengths
        scene = evaluate_scene_compatibility(
            caption_text=caption_text_for_scene(hook),
            caption_lineage=lineage,
            reel_scene_tags=reel_scene_tags,
            scene_fit_mode=scene_fit_mode,
        )
        decision = "allowed" if readable else "skipped"
        reason = (
            f"{length_class} static caption allowed for {frame_type}"
            if readable else f"{length_class} static caption too long for {frame_type}"
        )
        row = {
            "caption": text,
            "bank": bank,
            "length_class": length_class,
            "format_class": format_class,
            "frame_type": frame_type,
            "captionFitVersion": CAPTION_FIT_VERSION,
            "suitabilityDecision": decision,
            "reason": reason,
            "captionSceneTags": scene.caption_scene_tags,
            "reelSceneTags": scene.reel_scene_tags,
            "sceneCompatibilityDecision": scene.decision,
            "sceneCompatibilityReason": scene.reason,
            "captionSceneFitVersion": CAPTION_SCENE_FIT_VERSION,
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
            "captionSceneTags": scene.caption_scene_tags,
            "reelSceneTags": scene.reel_scene_tags,
            "sceneCompatibilityDecision": scene.decision,
            "sceneCompatibilityReason": scene.reason,
            "captionSceneFitVersion": CAPTION_SCENE_FIT_VERSION,
        }
        scene_allowed = scene.decision in {"allowed", "unknown_allowed", "fit_disabled"}
        if readable and scene_allowed:
            allowed.append((idx, hook, enriched_lineage))
        elif scene_allowed:
            fallback.append((idx, hook, enriched_lineage))

    target = max_hooks if max_hooks is not None else len(cap_set.hooks)
    target = min(target, len(cap_set.hooks))
    selected = list(allowed)
    if len(selected) < target:
        for item in sorted(fallback, key=lambda row: _caption_sort_key_for_fit(*row)):
            idx, hook, lineage = item
            if lineage.get("lengthClass") not in fallback_lengths:
                continue
            fallback_reason = f"fallback shortest available caption after static fit for {frame_type}"
            lineage = {
                **lineage,
                "suitabilityDecision": "fallback_short",
                "suitabilityReason": fallback_reason,
            }
            selected.append((idx, hook, lineage))
            for row in diagnostics:
                if row["caption"] == (json.dumps(hook, sort_keys=True, ensure_ascii=False) if isinstance(hook, dict) else str(hook)):
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
                row["reason"] = f"readable for {frame_type}, but not selected by weighted sample"

    hooks = [hook for _, hook, _ in selected]
    lineage = {new_idx: item_lineage for new_idx, (_, _, item_lineage) in enumerate(selected)}
    return CaptionSet(
        hooks=hooks,
        recipe_names=cap_set.recipe_names,
        caption_color=cap_set.caption_color,
        notes=f"{cap_set.notes}; caption_fit={fit_mode}; frame_type={frame_type}",
        hook_lineage=lineage,
    ), diagnostics


def select_recipes(cap_set: CaptionSet,
                   override: list[str] | None) -> list[Recipe]:
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


async def amain(args):
    root = Path(args.root).resolve()
    raw_dir   = root / "00_source_videos"
    cap_dir   = root / "01_captions"
    proc_dir  = root / "02_processed"
    fonts_dir = root / "fonts"
    audio_dir = root / "03_audio_library"
    manifest_path = root / "manifest.json"
    config = load_config(root)
    if getattr(args, "_defaults_applied", False) is False:
        args.workers = args.workers if args.workers != 3 else int(config.get("workers", args.workers))
        args.caption_renderer = args.caption_renderer or config.get("caption_renderer", "pillow")
        args.placement_mode = args.placement_mode or config.get("placement_mode", "source")
        args.output_profile = args.output_profile or config.get("output_profile", "mac_h264_videotoolbox")

    for d in (raw_dir, cap_dir, proc_dir, fonts_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest = Manifest(manifest_path)
    reconcile_interrupted_temp_outputs(proc_dir, manifest)
    asset_prompt_info = load_asset_prompt_set(Path(args.asset_prompt_json)) if args.asset_prompt_json else None

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
        account_scope = validate_account_scope(args.account, production_render=bool(getattr(args, "production_render", False)))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        identity_provider_check = enforce_production_identity_provider(bool(getattr(args, "production_render", False)))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if identity_provider_check.get("required"):
        log.info("identity_provider_check " + json.dumps(identity_provider_check, ensure_ascii=False))

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
        pairs = [(video, cap_set) for video, cap_set in pairs if video.stem == args.only_clip]
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
            log.error(f"strict preflight blocked {video.stem}: {len(warnings)} warning(s)")
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
                video, duration,
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
            decision = (
                placement_summary.metadata.get("captionPlacementDecision")
                if isinstance(placement_summary.metadata, dict) else {}
            )
            qc_row = {
                "schema": "reel_factory.caption_placement_qc_row.v1",
                "sourceClip": video.stem,
                "captionPlacementPolicy": placement_summary.metadata.get("captionPlacementPolicy", "legacy"),
                "selectedLane": band_,
                "captionStyle": style_,
                "font": font_,
                "scores": placement_summary.scores,
                "decision": decision,
                "reason": placement_summary.reason,
            }
            placement_qc_rows.append(qc_row)
            if args.caption_placement_qc or args.placement_debug:
                log.info("caption_placement_qc " + json.dumps(qc_row, ensure_ascii=False))
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
            prompt_text = ""
            if asset_prompt_info:
                prompt_set, _prompt_source_path = asset_prompt_info
                prompt_text = "\n".join([
                    prompt_set.higgsfieldGridPrompt,
                    prompt_set.klingMotionPrompt,
                    prompt_set.notes,
                ])
            reel_scene_tags = classify_reel_scene_tags(
                frame_type=frame_type,
                video_stem=video.stem,
                prompt_text=prompt_text,
            )
            video_cap_set, fit_diagnostics = apply_caption_fit_to_caption_set(
                cap_set,
                frame_type=frame_type,
                reel_scene_tags=reel_scene_tags,
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
                f"reel_scene_tags={','.join(reel_scene_tags)} hooks={len(video_cap_set.hooks)}"
            )

        # Per-clip color override from sidecar JSON, account profile, or CLI
        forced_color = args.color or cap_set.caption_color
        if not forced_color and account.get("color_scheme") and account["color_scheme"] != "auto":
            forced_color = account["color_scheme"]
        if forced_color:
            recipes = [
                replace(r, caption_color=forced_color) for r in recipes
            ]
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
            hooks_pool = [item for item in hooks_pool if item[0] == args.only_hook_index]

        if args.max_recipes is not None and args.max_recipes < len(recipes_pool):
            if args.hook_select == "first":
                recipes_pool = recipes_pool[:args.max_recipes]
            else:
                recipes_pool = sorted(
                    rng.sample(recipes_pool, args.max_recipes),
                    key=lambda r: [rr.name for rr in recipes].index(r.name),
                )

        if not bank_caption_mode and args.max_hooks is not None and args.max_hooks < len(hooks_pool):
            if args.hook_select == "first":
                hooks_pool = hooks_pool[:args.max_hooks]
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

        if (args.max_hooks or args.max_recipes or args.per_clip):
            log.info(
                f"sample {video.stem}: {len(hooks_pool)} hooks × "
                f"{len(recipes_pool)} recipes = "
                f"{len(hooks_pool) * len(recipes_pool)} outputs "
                f"(select={args.hook_select}, seed={args.seed})"
            )

        for hook_idx, hook in hooks_pool:
            for recipe in recipes_pool:
                target_ratios = recipe.target_ratios or args.target_ratios or config.get("target_ratios", ["9:16"])
                for target_ratio in target_ratios:
                    key = compute_job_key(
                        src_hash, hook, recipe,
                        placement_mode=args.placement_mode,
                        target_ratio=target_ratio,
                        caption_placement_policy=args.caption_placement_policy,
                        account_scope=account_scope,
                    )
                    if key in queued_keys:
                        duplicate_jobs += 1
                        log.info(f"skip {video.stem} h{hook_idx} {recipe.name} {target_ratio} (duplicate in this run)")
                        if queued_keys[key] != video.stem and not args.dry_run and not args.preview:
                            duplicate_aliases.append((video.stem, key))
                        continue
                    queued_keys[key] = video.stem
                    if args.enqueue_only:
                        from render_queue import get_queue
                        queue = get_queue(root, args.queue_backend)
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
                    tasks.append(process_one(
                        video, hook, hook_idx, recipe,
                        out_dir, fonts_dir, manifest,
                        src_hash, duration,
                        auto_color_cache, auto_band_cache, encode_sem, args.dry_run,
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
                        asset_prompt_info=asset_prompt_info,
                        caption_lineage=video_cap_set.hook_lineage.get(hook_idx),
                        account_scope=account_scope,
                    ))

    if duplicate_jobs:
        log.info(f"deduped {duplicate_jobs} duplicate render task(s) before launch")
    if args.caption_placement_qc:
        qc_path = root / "caption_placement_qc.json"
        qc_path.write_text(json.dumps({
            "schema": "reel_factory.caption_placement_qc_report.v1",
            "captionPlacementPolicy": "focal_safe_v1" if args.caption_placement_policy != "legacy" else "legacy",
            "rows": placement_qc_rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
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
                    log.warning(f"campaign output link failed for {result.get('out')}: {e}")

        # Per-clip summary artifacts: CSV index + contact sheet PNG.
        try:
            from post_render import summarize_clip_outputs
            for video, _ in pairs:
                clip_out = proc_dir / video.stem
                if clip_out.exists() and any(clip_out.glob("*.mp4")):
                    info = summarize_clip_outputs(clip_out)
                    log.info(f"summarize {video.stem}: csv+sheet for "
                             f"{info['count']} outputs")
                    try:
                        from sscd_check import audit_clip_dir
                        novelty = audit_clip_dir(clip_out)
                        if novelty:
                            (clip_out / "_similarity.json").write_text(
                                json.dumps(novelty, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            log.info(f"similarity {video.stem}: {len(novelty)} rows")
                    except Exception as e:
                        log.warning(f"similarity audit failed for {video.stem}: {e}")
        except Exception as e:
            log.warning(f"post-render summary failed: {e}")
        if args.mux_audio:
            try:
                from audio_mux import mux_root
                mux_summary = mux_root(root, audio_tag=args.audio_tag, seed=args.seed)
                log.info(f"audio mux: {json.dumps(mux_summary)}")
            except Exception as e:
                log.error(f"audio mux failed: {e}")
        if args.ai_qc:
            try:
                from ai_visual_qc import run_ai_qc
                for video, _ in pairs:
                    clip_out = proc_dir / video.stem
                    if clip_out.exists() and any(clip_out.glob("*.mp4")):
                        qc_summary = run_ai_qc(root, clip=video.stem)
                        log.info(f"ai_qc {video.stem}: {json.dumps(qc_summary.get('summary', {}))}")
            except Exception as e:
                log.warning(f"ai visual qc failed: {e}")
        if args.readiness:
            try:
                from readiness_check import run_readiness
                for video, _ in pairs:
                    clip_out = proc_dir / video.stem
                    if clip_out.exists() and any(clip_out.glob("*.mp4")):
                        ready_summary = run_readiness(root, clip=video.stem, platform="instagram_reels")
                        log.info(f"readiness {video.stem}: {json.dumps(ready_summary.get('summary', {}))}")
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
            from qc_check import run_qc
            qc_summary = run_qc(proc_dir, move_failed=True)
            log.info(f"qc: {json.dumps(qc_summary)}")
        except Exception as e:
            log.error(f"qc pass failed: {e}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", default=".",
                    help="project root containing 00_source_videos/, 01_captions/, etc.")
    ap.add_argument("--recipes", nargs="*", default=None,
                    help="restrict to these recipe names (e.g. v01_original v05_hflip)")
    ap.add_argument("--color", choices=["light", "dark", "auto"], default=None,
                    help="force caption color across all recipes (overrides sidecar + recipe defaults)")
    ap.add_argument("--style", choices=["classic", "meme", "ig", "thin", "soft", "bubble", "auto"], default=None,
                    help="force caption style across all recipes (overrides recipe defaults)")
    ap.add_argument("--font", default=None,
                    help="force caption font family: 'Instagram Sans Condensed' or 'Instagram Sans Condensed Bold' (bold is used only for meme style)")
    ap.add_argument("--band", choices=["top", "center", "bottom", "left", "right", "auto"], default=None,
                    help="force caption placement band across all recipes")
    ap.add_argument("--text-variation", choices=["off", "auto"], default="off",
                    help="caption text rewrite mode: off preserves exact text; auto applies deterministic slang/case variants")
    ap.add_argument("--variation-pack", default="default",
                    help="named text variation pack to use with --text-variation auto (default: default)")
    ap.add_argument("--pack-render", action="store_true",
                    help="operator preset for rendering a deterministic multi-variant reel pack")
    ap.add_argument("--account", default=None,
                    help="apply preferences from accounts/<NAME>.json — biases auto-pick "
                         "of font/style/color toward that account's voice")
    ap.add_argument("--production-render", action="store_true",
                    help="require an explicit --account scope so production variants are account-aware")
    ap.add_argument("--caption-mix", choices=["Larissa", "Stacey", "Lola"], default=None,
                    help="select hooks from a creator-weighted caption bank mix")
    ap.add_argument("--creator-style-preset", choices=sorted(CREATOR_STYLE_PRESETS), default="auto",
                    help="creator/account visual defaults; auto centers Stacey/Larissa static-style captions")
    ap.add_argument("--caption-banks", nargs="+", default=None,
                    help="select hooks from explicit caption bank names instead of a creator mix")
    ap.add_argument("--caption-fit", choices=["auto", "off"], default="auto",
                    help="fit caption-bank hooks to the detected frame type before rendering (default: auto)")
    ap.add_argument("--caption-scene-fit", choices=["auto", "off"], default="auto",
                    help="block obvious scene/location caption mismatches for caption-bank hooks (default: auto)")
    ap.add_argument("--campaign", default=None,
                    help="link rendered outputs to a Campaign Factory campaign")
    ap.add_argument("--asset-generation-id", default=None,
                    help="link rendered outputs to an existing Campaign Factory asset generation")
    ap.add_argument("--watch", action="store_true",
                    help="watch 00_source_videos/ for new clips and auto-process")
    ap.add_argument("--dry-run", action="store_true",
                    help="print commands without encoding")
    ap.add_argument("--preview", action="store_true",
                    help="render caption preview PNGs instead of full videos")
    ap.add_argument("--rerender-all", action="store_true",
                    help="ignore cached successful jobs and render selected outputs again")
    ap.add_argument("--strict-preflight", action="store_true",
                    help="block clips that produce preflight warnings")
    ap.add_argument("--workers", type=int, default=3, metavar="N",
                    help="max concurrent ffmpeg encodes (default: 3)")
    ap.add_argument("--mezzanine", action="store_true",
                    help="also export ProRes LT .mov mezzanine files beside social MP4s")
    ap.add_argument("--output-profile",
                    choices=[name for name, profile in ENCODER_PROFILES.items() if profile.runnable and name != "prores_lt"],
                    default="mac_h264_videotoolbox",
                    help="primary MP4 encoder profile (default: mac_h264_videotoolbox)")
    ap.add_argument("--phone-finalize", dest="phone_finalize", action="store_true", default=True,
                    help="stream-copy final MP4 with mobile-style metadata and faststart (default)")
    ap.add_argument("--no-phone-finalize", dest="phone_finalize", action="store_false",
                    help="skip final MP4 metadata/finalization remux")
    ap.add_argument("--caption-renderer", choices=["pillow", "pango"], default="pillow",
                    help="caption rasterizer; pango is experimental and falls back to Pillow")
    ap.add_argument("--placement-debug", action="store_true",
                    help="log top/center/bottom caption lane scores during source analysis")
    ap.add_argument("--placement-signals", choices=["basic", "pose"], default="basic",
                    help="placement analysis signals: basic or pose (optional MediaPipe)")
    ap.add_argument("--placement-mode", choices=["source", "segment"], default="source",
                    help="caption placement mode: source-level stable placement; timed captions auto-use segment placement")
    ap.add_argument("--caption-placement-policy", choices=["focal-safe", "legacy"], default="focal-safe",
                    help="caption placement policy: focal-safe avoids face/body focal zones; legacy preserves old lane behavior")
    ap.add_argument("--caption-placement-qc", action="store_true",
                    help="write caption_placement_qc.json with lane scores and placement reasons")
    ap.add_argument("--target-ratios", nargs="+", choices=["9:16", "4:5"], default=["9:16"],
                    help="output aspect ratios to render (default: 9:16)")

    # ── Sampling controls (cap how many videos come back per run) ─────────
    ap.add_argument("--max-hooks", type=int, default=None, metavar="N",
                    help="cap hooks per clip (default: use all)")
    ap.add_argument("--max-recipes", type=int, default=None, metavar="M",
                    help="cap recipes per clip (default: use all)")
    ap.add_argument("--per-clip", type=int, default=None, metavar="K",
                    help="overall cap on outputs per clip "
                         "(reduces hooks first, keeps recipes)")
    ap.add_argument("--hook-select", choices=["first", "random"], default="random",
                    help="how to pick hooks/recipes when limited "
                         "(default: random with --seed for reproducibility)")
    ap.add_argument("--seed", type=int, default=42, metavar="N",
                    help="RNG seed for random selection (default: 42 — bump it for fresh picks)")
    ap.add_argument("--only-hook-index", type=int, default=None,
                    help=argparse.SUPPRESS)
    ap.add_argument("--only-clip", default=None,
                    help=argparse.SUPPRESS)

    # ── Quality control ───────────────────────────────────────────────────
    ap.add_argument("--qc", action="store_true",
                    help="run technical QC pass on outputs after rendering "
                         "(ffprobe: dims, fps, codec, audio absent, file size)")
    ap.add_argument("--qc-only", action="store_true",
                    help="skip rendering, only run QC on existing outputs")
    ap.add_argument("--mux-audio", action="store_true",
                    help="after rendering, create separate audio-muxed derivatives")
    ap.add_argument("--audio-tag", default=None,
                    help="audio library tag used with --mux-audio")
    ap.add_argument("--enqueue-only", action="store_true",
                    help="enqueue render commands into render_queue.sqlite instead of running locally")
    ap.add_argument("--queue-backend", choices=["sqlite", "redis", "rq"], default="sqlite",
                    help="queue backend for --enqueue-only (rq uses the Redis-compatible backend)")
    ap.add_argument("--asset-prompt-json", default=None,
                    help="Optional clean Grok prompt JSON to validate and write as generated asset lineage sidecars.")
    ap.add_argument("--ai-qc", action="store_true",
                    help="run heuristic AI visual QA on rendered outputs after rendering")
    ap.add_argument("--readiness", action="store_true",
                    help="run warn-only platform readiness aggregation after rendering")

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
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

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
        t = threading.Timer(debounce_secs, lambda: (pending.pop(path, None), kick_pipeline()))
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
