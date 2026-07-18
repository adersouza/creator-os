"""Shared models, policies, lineage, and render helpers for Reel Pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pipeline_contracts import validate_generated_asset_lineage

from .discoverability_safety import discoverability_safe_content_contract
from .fileops import atomic_write_text
from .graph_builder import build_ffmpeg_cmd as build_graph_ffmpeg_cmd
from .graph_builder import build_video_filter as build_graph_video_filter
from .identity_verification import get_identity_provider
from .media_metadata import normalize_media_metadata
from .perceptual import enrich_lineage_identity, load_json
from .placement import (
    PlacementSummary,
)
from .recipe_loader import load_recipes
from .render_plan import RenderPlan

AUDIO_SELECTION_PATH_KEYS = ("local_path", "localPath", "path", "file_path", "filePath")


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
        preset = (
            "stacey_static_center"
            if args.caption_mix in {"Larissa", "Stacey"}
            else "none"
        )
    if preset == "none":
        return None
    if preset != "stacey_static_center":
        raise ValueError(f"unknown creator style preset: {preset}")

    # ponytail: this is the whole Stacey/Larissa reel format; split presets only after another account needs different defaults.
    if args.band is None:
        args.band = "lower_center"
    if args.style is None:
        args.style = "ig"
    if args.font is None:
        args.font = DEFAULT_CAPTION_FONT
    if args.color is None:
        args.color = "light"
    args._creator_style_preset_applied = preset
    return preset


def resolve_caption_font_policy(
    requested_font: str | None, caption_style: str
) -> tuple[str, dict]:
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
FFMPEG = (
    str(_FFMPEG_FULL / "ffmpeg")
    if (_FFMPEG_FULL / "ffmpeg").exists()
    else shutil.which("ffmpeg") or "ffmpeg"
)
FFPROBE = (
    str(_FFMPEG_FULL / "ffprobe")
    if (_FFMPEG_FULL / "ffprobe").exists()
    else shutil.which("ffprobe") or "ffprobe"
)
AVCONVERT = shutil.which("avconvert")


def reexec_with_homebrew_gi_env_if_needed() -> None:
    """Restart once so optional Pango/PyGObject can find Homebrew dylibs."""
    brew_lib = "/opt/homebrew/lib"
    if (
        os.environ.get("REEL_FACTORY_GI_ENV_READY") == "1"
        or not Path(brew_lib).exists()
    ):
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
    trim_head: float = 0.0  # seconds to drop from start
    trim_tail: float = 0.0  # seconds to drop from end
    speed: float = 1.0  # 1.05 = 5% faster, 0.95 = 5% slower
    zoom: float = 1.0  # 1.08 = 8% zoom-in (crop+rescale)
    tilt_deg: float = 0.0  # subtle fixed rotation before final scale
    hflip: bool = False  # mirror horizontally
    reverse: bool = False  # play backwards
    eq_contrast: float = 1.0
    eq_saturation: float = 1.0
    eq_brightness: float = 0.0  # -0.1..0.1 typical
    burn_caption: bool = True  # set False to skip the PNG caption overlay
    caption_color: str = "auto"  # "light" / "dark" / "auto" (sampled luminance)
    caption_style: str = "auto"  # "classic" / "meme" / "ig" / "thin" / "soft" / "bubble" / "auto" (frame busyness)
    caption_band: str = (
        "auto"  # "top" / "bottom" / "center" / "left" / "right" / "auto"
    )
    font: str = DEFAULT_CAPTION_FONT
    text_variation: str = "off"  # "off" → preserve original caption exactly; "auto" → slang/case mangle per recipe
    text_variation_pack: str = "default"
    text_variation_pack_version: str = "default@1"
    color_preset: str = "none"  # "none" / "bright_pop" / "warm" / "cool" / "cinematic"
    camera_variation: bool = True  # subtle crop, rotation, color, sharpening, and grain so outputs feel phone-native
    target_ratios: list[str] | None = None


RECIPES = load_recipes(Path(__file__).parent / "recipes" / "default.json", Recipe)
RECIPES_BY_NAME = {r.name: r for r in RECIPES}


# ────────────────────────────────────────────────────────────────────────────
# Caption → ASS file
# ────────────────────────────────────────────────────────────────────────────
# ASS color format is &HAABBGGRR (alpha-blue-green-red, AA=00 opaque)
COLORS = {
    "light": {  # white text + thick black stroke (default for dark/mixed bg)
        "primary": "&H00FFFFFF",  # white fill
        "outline": "&H00000000",  # black stroke
    },
    "dark": {  # black text + thick white stroke (for bright/light bg)
        "primary": "&H00000000",  # black fill
        "outline": "&H00FFFFFF",  # white stroke
    },
}


# ────────────────────────────────────────────────────────────────────────────
# Caption discovery — supports .txt (one hook) and .json (multi-hook sidecar)
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class CaptionSet:
    hooks: list[str | dict]  # one or more hook variations; dict = timed segments
    recipe_names: list[str] | None = None  # None = use all RECIPES
    caption_color: str | None = (
        None  # "light" | "dark" | "auto" | None (recipe default)
    )
    notes: str = ""
    hook_lineage: dict[int, dict] = field(default_factory=dict)
    band: str | None = None  # operator band request; honored only if face-clear

    @classmethod
    def from_path(cls, path: Path) -> CaptionSet:
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
            lineage = {
                int(k): v
                for k, v in (
                    data.get("hookLineage") or data.get("hook_lineage") or {}
                ).items()
                if str(k).isdigit() and isinstance(v, dict)
            }
            parsed: list[str | dict] = []
            for idx, h in enumerate(hooks):
                _ensure_discoverability_safe_caption(h, source=str(path))
                if isinstance(h, dict):
                    if "segments" not in h:
                        raise ValueError(f"hook dict missing 'segments' key in {path}")
                    parsed.append(h)
                else:
                    s = str(h).strip()
                    source_text = str(
                        lineage.get(idx, {}).get("rawSourceCaptionText") or ""
                    ).strip()
                    if source_text and source_text != s and source_text.startswith(s):
                        raise ValueError(
                            f"caption hook is a clipped prefix of rawSourceCaptionText in {path}: {s}"
                        )
                    if s:
                        parsed.append(s)
            if not parsed:
                raise ValueError(f"no hooks found in {path}")
            hooks = parsed
            caption_color = data.get("caption_color")
            if caption_color is not None and caption_color not in {
                "light",
                "dark",
                "auto",
            }:
                raise ValueError(
                    f"caption_color must be light, dark, or auto in {path}"
                )
            band = data.get("band")
            if band is not None and band not in CAPTION_BAND_OVERRIDES:
                raise ValueError(
                    f"band must be one of {sorted(CAPTION_BAND_OVERRIDES)} in {path}"
                )
            return cls(
                hooks=hooks,
                recipe_names=data.get("recipes"),
                caption_color=caption_color,
                notes=data.get("notes", ""),
                hook_lineage=lineage,
                band=band,
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


def build_video_filter(
    recipe: Recipe,
    src_duration: float,
    ass_path: Path,
    fonts_dir: Path,
    src_hash: str = "",
    src_w: int = 1080,
    src_h: int = 1920,
    account_scope: str = "local_review",
) -> str:
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


def build_ffmpeg_cmd(
    src: Path,
    caption_pngs: list[tuple[Path, float, float | None]],
    recipe: Recipe,
    out: Path,
    duration: float,
    fonts_dir: Path,
    src_hash: str = "",
    src_dims: tuple[int, int] = (1080, 1920),
    bitrate_mbps: int = 14,
    src_bitrate_mbps: int | None = None,
    output_profile: str = "mac_h264_videotoolbox",
    target_ratio: str = "9:16",
    account_scope: str = "local_review",
) -> list[str]:
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
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_phone_finalize_cmd(
    src: Path, out: Path, creation_time: str, ffmpeg: str = FFMPEG
) -> list[str]:
    """Build a stream-copy MP4 finalization command for social upload outputs."""
    return [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        "-metadata",
        f"creation_time={creation_time}",
        "-metadata:s:v:0",
        f"creation_time={creation_time}",
        "-metadata:s:v:0",
        "language=und",
        "-metadata:s:v:0",
        "handler_name=Core Media Video",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-brand",
        "mp42",
        str(out),
    ]


def build_avconvert_finalize_cmd(
    src: Path, out: Path, avconvert: str = AVCONVERT or "avconvert"
) -> list[str]:
    """Build a macOS AVFoundation passthrough finalizer command."""
    return [
        avconvert,
        "--source",
        str(src),
        "--preset",
        "PresetPassthrough",
        "--output",
        str(out),
        "--replace",
    ]


def normalize_rendered_mp4_metadata(path: Path) -> dict:
    if path.suffix.lower() != ".mp4":
        return {
            "metadataNormalized": True,
            "metadataWarnings": [],
            "skipped": "non_mp4",
        }
    result = normalize_media_metadata(path, dry_run=False)
    if not result.get("metadataNormalized"):
        warnings = result.get("metadataWarnings") or ["metadata_not_normalized"]
        raise RuntimeError(
            f"metadata_normalization_failed:{','.join(str(item) for item in warnings)}"
        )
    return result


def enforce_production_identity_provider(production_render: bool) -> dict:
    if not production_render:
        return {"required": False, "provider": "", "providerAvailable": None}
    # Keep the invoked path: uv and standard virtualenvs commonly symlink their
    # Python executable to a shared runtime outside `.venv`.
    executable = Path(sys.executable)
    if ".venv" not in executable.parts:
        raise RuntimeError("production_render_requires_venv_python")
    provider = get_identity_provider()
    ok, reason = provider.available()
    if not ok or provider.name != "insightface_arcface":
        raise RuntimeError(
            f"production_render_identity_provider_unavailable:{provider.name}:{reason}"
        )
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


def effective_placement_mode_for_caption(
    caption: str | dict, placement_mode: str
) -> str:
    """Timed captions should use segment-aware placement by default."""
    if isinstance(caption, dict) and placement_mode == "source":
        return "segment"
    return placement_mode


def compute_job_key(
    video_hash: str,
    caption: str | dict,
    recipe: Recipe,
    placement_mode: str = "source",
    target_ratio: str = "9:16",
    caption_placement_policy: str = "focal-safe",
    account_scope: str = "local_review",
    requested_band: str | None = None,
) -> str:
    placement_mode = effective_placement_mode_for_caption(caption, placement_mode)
    cap_str = (
        json.dumps(caption, sort_keys=True, ensure_ascii=False)
        if isinstance(caption, dict)
        else caption
    )
    cap_h = sha256_str(cap_str)
    rec_params = asdict(recipe)
    if not isinstance(caption, dict):
        rec_params["_static_caption_centered_policy"] = "v2"
    else:
        rec_params["_timed_caption_centered_policy"] = "v2"
    if caption_placement_policy != "legacy":
        rec_params["_caption_placement_policy"] = "focal_safe_v1"
    if placement_mode != "source":
        rec_params["_placement_mode"] = placement_mode
    if target_ratio != "9:16":
        rec_params["_target_ratio"] = target_ratio
    scope = (account_scope or "local_review").strip() or "local_review"
    if scope != "local_review":
        rec_params["_account_scope"] = scope
    if requested_band:
        rec_params["_requested_band"] = requested_band
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
    decision = (
        summary.metadata.get("captionPlacementDecision")
        if isinstance(summary.metadata, dict)
        else None
    )
    rejected = (
        {str(zone) for zone in (decision or {}).get("rejectedLanes", [])}
        if isinstance(decision, dict)
        else set()
    )
    candidates = [
        zone
        for zone in ("top", "center", "bottom")
        if zone in summary.scores and zone not in rejected
    ]
    if not candidates:
        return "center"
    if diversity_key:
        best_score = min(float(summary.scores[zone]) for zone in candidates)
        eligible = [
            zone
            for zone in candidates
            if float(summary.scores[zone]) <= best_score + 12.0
            or float(summary.scores[zone]) <= best_score * 1.35
        ]
        ranked = sorted(
            eligible or candidates, key=lambda zone: (summary.scores[zone], zone)
        )
        start = int(
            hashlib.sha256(diversity_key.encode("utf-8")).hexdigest()[:8], 16
        ) % len(ranked)
        return ranked[start]
    return min(candidates, key=lambda zone: summary.scores[zone])


def timed_caption_band(
    base_band: str, segment_index: int, summary: PlacementSummary
) -> str:
    if base_band != "lower_center":
        return base_band
    return "lower_center" if segment_index % 2 == 0 else "lower_center_alt"


# Sub-band ladder: finer vertical stops inside each scored lane so
# similar-composition clips don't all snap to the same y (owner: "all in the
# exact same spot"). Each sub-band lists the scored lanes it physically sits
# inside; it's only offered when NONE of those lanes were rejected by the
# scorer, so variety never nudges text onto the subject.
_SUBBAND_SUPPORT = {
    "top": ("top",),
    "center": ("center",),
    "lower_center": ("center", "bottom"),
    "lower_center_alt": ("center", "bottom"),
    "bottom": ("bottom",),
}
_LANE_SUBBANDS = {
    "top": ("top",),
    "center": ("center", "lower_center"),
    "bottom": ("bottom", "lower_center_alt"),
}


CAPTION_BAND_OVERRIDES = {"top", "center", "lower_center", "lower_center_alt", "bottom"}

_FACE_CLEAR_HEAD_CEILING = 110.0  # full head-blocker weight; partial hits allowed


def approve_operator_band(
    requested: str | None, summary: PlacementSummary
) -> str | None:
    """Approve an operator's per-clip band request only when it is face-clear.

    The scorer stays authoritative for faces: any face penalty (or a full
    head-blocker hit) in a lane supporting the requested band vetoes the
    request. Operators can move text off the scorer's pick — e.g. accept a
    focal/body overlap on their own judgement — but never onto the face.
    """
    if requested not in CAPTION_BAND_OVERRIDES:
        return None
    decision = (
        summary.metadata.get("captionPlacementDecision")
        if isinstance(summary.metadata, dict)
        else None
    )
    components = (decision or {}).get("components")
    if not isinstance(components, dict):
        return None
    for lane in _SUBBAND_SUPPORT.get(requested, ()):
        lane_scores = components.get(lane)
        if not isinstance(lane_scores, dict):
            return None
        if float(lane_scores.get("face") or 0.0) > 0.0:
            return None
        if float(lane_scores.get("head") or 0.0) >= _FACE_CLEAR_HEAD_CEILING:
            return None
    return requested


def vary_band_within_lane(
    band: str, summary: PlacementSummary, *, diversity_key: str
) -> str:
    """Jitter a static caption vertically within its scored lane, per clip.

    Picks among sub-bands inside the winning lane, skipping any whose supporting
    lanes the scorer rejected. Deterministic per clip via diversity_key. Bands
    outside the ladder (left/right/lower_center/explicit presets) pass through.
    """
    options = _LANE_SUBBANDS.get(band)
    if not options:
        return band
    decision = (
        summary.metadata.get("captionPlacementDecision")
        if isinstance(summary.metadata, dict)
        else None
    )
    rejected = (
        {str(zone) for zone in (decision or {}).get("rejectedLanes", [])}
        if isinstance(decision, dict)
        else set()
    )
    eligible = [
        sub
        for sub in options
        if not any(lane in rejected for lane in _SUBBAND_SUPPORT[sub])
    ]
    if len(eligible) <= 1:
        return eligible[0] if eligible else band
    idx = int(hashlib.sha256(diversity_key.encode("utf-8")).hexdigest()[:8], 16) % len(
        eligible
    )
    return eligible[idx]


def build_caption_placement_qc_row(
    *,
    source_clip: str,
    placement_summary: PlacementSummary,
    scored_lane: str,
    render_band: str | None,
    caption_style: str,
    font: str,
) -> dict:
    """Record both the scorer lane and the band actually used by rendering."""
    decision = (
        placement_summary.metadata.get("captionPlacementDecision")
        if isinstance(placement_summary.metadata, dict)
        else {}
    )
    final_band = render_band or scored_lane
    return {
        "schema": "reel_factory.caption_placement_qc_row.v2",
        "sourceClip": source_clip,
        "captionPlacementPolicy": placement_summary.metadata.get(
            "captionPlacementPolicy", "legacy"
        ),
        "scoredLane": scored_lane,
        "selectedLane": scored_lane,
        "renderBand": final_band,
        "finalBand": final_band,
        "captionStyle": caption_style,
        "font": font,
        "scores": placement_summary.scores,
        "decision": decision,
        "reason": placement_summary.reason,
    }


def write_generated_asset_lineage_sidecar(
    out_path: Path,
    *,
    source_lineage_path: Path | None,
    render_job_key: str,
    source_hash: str,
) -> Path:
    sidecar = out_path.with_suffix(out_path.suffix + ".generated_asset_lineage.json")
    payload = {
        "schema": "reel_factory.generated_asset_lineage.v1",
        "pipelineTraceId": f"trace_reel_render_{hashlib.sha256(f'{source_hash}:{render_job_key}'.encode()).hexdigest()[:16]}",
        "source": {
            "sourceLineagePath": str(source_lineage_path)
            if source_lineage_path
            else None,
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
        "createdAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    payload = enrich_lineage_identity(
        payload,
        out_path,
        source_lineage=load_json(source_lineage_path),
    )
    validate_generated_asset_lineage(payload)
    atomic_write_text(
        sidecar, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
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
    selected_banks = _text_list(
        lineage.get("selectedBanks")
        or lineage.get("selected_banks")
        or lineage.get("sourceBanks")
        or lineage.get("source_banks")
    )
    caption_hash = _first_text(
        lineage.get("captionHash"),
        lineage.get("caption_hash"),
        sha256_str(caption_text),
    )
    primary_bank = _first_text(
        lineage.get("selectedBank"),
        lineage.get("selected_bank"),
        selected_banks[0] if selected_banks else None,
    )
    return {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "bank_caption_hash": _first_text(
            lineage.get("bankCaptionHash"), lineage.get("bank_caption_hash")
        ),
        "caption_text": _first_text(
            lineage.get("rawCaptionText"), lineage.get("raw_caption_text"), caption_text
        ),
        "caption_bank": primary_bank,
        "caption_banks": selected_banks or ([primary_bank] if primary_bank else []),
        "creator_mix": _first_text(
            lineage.get("selectedMix"), lineage.get("selected_mix")
        ),
        "creator_model": _first_text(
            lineage.get("creatorModel"), lineage.get("creator_model"), creator_model
        ),
        "frame_type": _first_text(lineage.get("frameType"), lineage.get("frame_type")),
        "length_class": _first_text(
            lineage.get("lengthClass"), lineage.get("length_class")
        ),
        "format_class": _first_text(
            lineage.get("formatClass"), lineage.get("format_class")
        ),
        "caption_fit_version": _first_text(
            lineage.get("captionFitVersion"), lineage.get("caption_fit_version")
        ),
        "suitability_decision": _first_text(
            lineage.get("suitabilityDecision"), lineage.get("suitability_decision")
        ),
        "suitability_reason": _first_text(
            lineage.get("suitabilityReason"), lineage.get("suitability_reason")
        ),
        "captionSceneTags": lineage.get("captionSceneTags")
        if isinstance(lineage.get("captionSceneTags"), list)
        else [],
        "reelSceneTags": lineage.get("reelSceneTags")
        if isinstance(lineage.get("reelSceneTags"), list)
        else [],
        "sceneCompatibilityDecision": _first_text(
            lineage.get("sceneCompatibilityDecision")
        ),
        "sceneCompatibilityReason": _first_text(
            lineage.get("sceneCompatibilityReason")
        ),
        "captionSceneFitVersion": _first_text(lineage.get("captionSceneFitVersion")),
        "captionPlacementPolicy": _first_text(lineage.get("captionPlacementPolicy")),
        "captionPlacementDecision": lineage.get("captionPlacementDecision")
        if isinstance(lineage.get("captionPlacementDecision"), dict)
        else None,
        "render_recipe": render_recipe,
        "source_clip": _first_text(
            lineage.get("sourceClip"), lineage.get("source_clip"), source_clip
        ),
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
        selected_hash = _first_text(enriched.get("captionHash"))
        if selected_hash and selected_hash != caption_hash:
            enriched.setdefault("bankCaptionHash", selected_hash)
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
    payload = (
        _caption_lineage_with_outcome_context(
            lineage,
            caption_text=caption_text,
            caption_hash=caption_hash,
            render_recipe=render_recipe,
            source_clip=source_clip,
            rendered_output=rendered_output or str(out_path),
            creator_model=creator_model,
        )
        or lineage
    )
    sidecar = out_path.with_suffix(out_path.suffix + ".caption_lineage.json")
    atomic_write_text(
        sidecar, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return sidecar


SELF_SOURCE_SCHEMA = "reel_factory.self_source.v1"


def self_generated_source_lineage(source_video: Path) -> dict | None:
    """Return generation lineage when the source clip is our own generated asset.

    A source qualifies only when a `<stem>.self_source.json` sidecar points at
    a generation lineage file that records a completed Higgsfield image job.
    Imported/external reference clips never carry this sidecar, so they keep
    the hard SSCD copy failure.
    """
    sidecar = source_video.parent / f"{source_video.stem}.self_source.json"
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != SELF_SOURCE_SCHEMA:
        return None
    lineage_path = Path(str(payload.get("generationLineagePath") or ""))
    if not lineage_path.is_absolute():
        lineage_path = source_video.parent / lineage_path
    try:
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    generation = lineage.get("generation") or {}
    if not (generation.get("imageJobId") or generation.get("imageResultUrl")):
        return None
    return lineage


def operator_owned_source_attestation(source_video: Path) -> dict | None:
    sidecar = source_video.parent / f"{source_video.stem}.owned_source.json"
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != "reel_factory.operator_owned_source.v1":
        return None
    if not payload.get("sourceAssetId") or not payload.get("sourceContentHash"):
        return None
    original_path = Path(str(payload.get("originalPath") or ""))
    library_root = Path(str(payload.get("libraryRoot") or ""))
    try:
        if not original_path.resolve(strict=True).is_relative_to(
            library_root.resolve(strict=True)
        ):
            return None
        expected_hash = str(payload["sourceContentHash"])
        if sha256_file(source_video) != expected_hash:
            return None
        if sha256_file(original_path) != expected_hash:
            return None
    except OSError:
        return None
    return payload


def write_required_similarity_audit(
    source_video: Path, clip_out: Path, audit_func=None
):
    """Run real SSCD similarity and fail loud on copy-detection failures.

    Self-generated sources (see self_generated_source_lineage) are exempt from
    the hard failure: a locked-still reel of our own generated image matches
    its source by design, and the copy gate exists to catch near-copies of
    external content, not of our own assets. Similarity rows are still written
    for audit, downgraded to informational.
    """
    owned_source = operator_owned_source_attestation(source_video)
    if owned_source:
        rows = [
            {
                "schema": "reel_factory.sscd_similarity_row.v1",
                "filename": output.name,
                "recipe": None,
                "mean_similarity": None,
                "max_similarity": None,
                "status": "info",
                "verdict": "INFO (operator-owned source)",
                "operatorOwnedSourceExempt": True,
                "sourceAssetId": owned_source["sourceAssetId"],
                "similarityAuditSkipped": True,
            }
            for output in sorted(clip_out.glob("*.mp4"))
        ]
    elif audit_func is None:
        from .sscd_video import audit_video_dir

        audit_func = audit_video_dir
        rows = audit_func(source_video, clip_out)
    else:
        rows = audit_func(source_video, clip_out)
    if self_generated_source_lineage(source_video):
        for row in rows:
            if row.get("status") == "fail" or str(row.get("verdict", "")).startswith(
                "FAIL"
            ):
                row["status"] = "info"
                row["verdict"] = "INFO (self-generated source)"
                row["selfSourceExempt"] = True
    if rows:
        atomic_write_text(
            (clip_out / "_similarity.json"),
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    failed = [
        row
        for row in rows
        if row.get("status") == "fail" or str(row.get("verdict", "")).startswith("FAIL")
    ]
    if failed:
        names = ", ".join(str(row.get("filename")) for row in failed[:5])
        raise RuntimeError(f"SSCD copy gate failed for {clip_out.name}: {names}")
    return rows


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
        sys.executable,
        "-m",
        "reel_factory.reel_pipeline",
        "--root",
        str(root),
        "--only-clip",
        video_stem,
        "--recipes",
        recipe.name,
        "--only-hook-index",
        str(hook_idx),
        "--output-profile",
        args.output_profile,
        "--caption-renderer",
        args.caption_renderer,
        "--placement-signals",
        args.placement_signals,
        "--placement-mode",
        args.placement_mode,
        "--caption-placement-policy",
        args.caption_placement_policy,
        "--target-ratios",
        target_ratio,
        "--color",
        recipe.caption_color,
        "--style",
        recipe.caption_style,
        "--band",
        recipe.caption_band,
        "--font",
        recipe.font,
        "--text-variation",
        recipe.text_variation,
        "--variation-pack",
        recipe.text_variation_pack,
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
    if getattr(args, "ai_qc", False):
        cmd.append("--ai-qc")
    if getattr(args, "readiness", False):
        cmd.append("--readiness")
    return cmd


# ────────────────────────────────────────────────────────────────────────────
# Manifest storage lives in manifest.py
# ────────────────────────────────────────────────────────────────────────────
