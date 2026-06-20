from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
import zlib
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .caption_outcome import build_caption_outcome_context, load_context_json
from .config import Settings
from .contentforge_visual_qc import ContentForgeVisualQCRepository
from .cost_tracker import ensure_cost_table, record_ai_cost
from .creative_planning import CREATIVE_PLAN_STATUSES, DEFAULT_STYLE_LANES
from .db import connect, init_db
from .fresh_reel_production import FreshReelProductionRepository
from .learning_score import account_reward_baselines
from .multi_blocker_unlock import MultiBlockerUnlockRepository
from .perceptual import compute_pdq_fingerprint, pdq_hamming_distance
from .persistence import json_load, row_to_dict, utc_now
from .services import CoreServices

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
RECOMMENDATION_ITEM_STATUSES = {
    "proposed",
    "accepted",
    "rejected",
    "executed",
    "posted",
    "measured",
    "proved",
    "disproved",
}
RECOMMENDATION_STATUS_TRANSITIONS = {
    "proposed": {"accepted", "rejected"},
    "accepted": {"executed", "posted", "rejected"},
    "rejected": set(),
    "executed": {"posted", "measured", "proved", "disproved"},
    "posted": {"measured", "proved", "disproved"},
    "measured": {"proved", "disproved"},
    "proved": set(),
    "disproved": set(),
}
RECOMMENDATION_MEASUREMENT_VERSION = "recommendation_measurement.v1"
RECOMMENDATION_MEASUREMENT_THRESHOLD = 5
RECOMMENDATION_EXECUTION_STATUSES = {"not_started", "running", "completed", "blocked", "failed"}
AUTONOMY_LEVELS = {"level_1", "level_2", "level_3"}
DEFAULT_AUTONOMY_LEVEL = "level_2"
EXCEPTION_STATUSES = {"open", "snoozed", "resolved"}
EXCEPTION_SEVERITIES = {"low", "medium", "high", "critical"}
DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS = 14
DEFAULT_INVENTORY_RESERVATION_TTL_DAYS = 7
ACCOUNT_TRUST_STATES = {
    "warming",
    "normal",
    "growth",
    "winner",
    "resting",
    "restricted",
    "blocked",
    "manual_review_required",
}
RECOMMENDATION_ELIGIBILITY_STATES = {
    "eligible",
    "unknown",
    "limited",
    "not_recommended",
    "manual_review_required",
}
WARMING_STAGES = {"day_0_3", "day_4_7", "week_2", "week_3_4", "mature", "unknown"}
CREATIVE_RISK_BLOCK_THRESHOLD = 51
CREATIVE_RISK_CAUTION_THRESHOLD = 21
CONTENTFORGE_VARIANT_PRESETS = {"caption_safe", "caption_safe_v2", "strong_safe", "subtle", "balanced", "strong"}
CONTENTFORGE_VARIANT_PACK_SCHEMAS = {"contentforge.variant_pack.v1", "contentforge.variant_pack.v2"}
CONTENT_SURFACES = ("reel", "story", "feed_single", "feed_carousel")
CONTENT_SURFACE_ALIASES = {
    "regular_reel": "reel",
    "trial_reel": "reel",
    "reels": "reel",
    "ig_reel": "reel",
    "image": "feed_single",
    "single_image": "feed_single",
    "feed_image": "feed_single",
    "feed_single_image": "feed_single",
    "feed-single": "feed_single",
    "carousel": "feed_carousel",
    "feed-carousel": "feed_carousel",
    "carousel_album": "feed_carousel",
    "stories": "story",
    "ig_story": "story",
}
IG_MEDIA_TYPE_BY_SURFACE = {
    "reel": "REELS",
    "story": "STORIES",
    "feed_single": "IMAGE",
    "feed_carousel": "CAROUSEL",
}
TRIAL_GRADUATION_STRATEGIES = {"MANUAL", "SS_PERFORMANCE"}
STORY_INTENTS = {
    "snapchat_promo",
    "reel_teaser",
    "casual_selfie",
    "mirror_selfie",
    "outfit_check",
    "gym_selfie",
    "bedroom_selfie",
    "lifestyle",
    "behind_the_scenes",
    "engagement",
    "profile_visit",
}
STORY_GOALS = {
    "traffic",
    "engagement",
    "retention",
    "profile_visit",
    "audience_warming",
    "reel_support",
}
STORY_STYLES = {
    "amateur",
    "casual",
    "casual_selfie",
    "selfie",
    "mirror",
    "lifestyle",
    "high_quality",
    "raw_phone",
}
STORY_NATIVE_PROOF_STYLES = {"amateur", "casual", "casual_selfie", "selfie", "mirror", "raw_phone"}
DEFAULT_STORY_MIX = {
    "casual_selfie": 30,
    "reel_teaser": 25,
    "snapchat_promo": 25,
    "lifestyle": 10,
    "engagement": 10,
}
DEFAULT_STORY_CALENDAR = {
    "Monday": "reel_teaser",
    "Tuesday": "snapchat_promo",
    "Wednesday": "casual_selfie",
    "Thursday": "reel_teaser",
    "Friday": "snapchat_promo",
    "Saturday": "lifestyle",
    "Sunday": "casual_selfie",
}
SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL = (
    "new fit today",
    "which one wins?",
    "felt cute",
    "mirror check",
    "simple today",
    "pick one",
    "soft launch",
    "posting this one",
)
CAPTION_PLACEMENT_QC_WARNING_CODES = {
    "caption_too_close_to_edge",
    "caption_overlaps_ui_safe_zone",
    "caption_low_confidence",
    "text_hidden",
    "safe_zone_violation",
}
OFM_AUDIO_CONTEXT_TAGS = {
    "ofm",
    "ofm_reels",
    "onlyfans",
    "onlyfans_ig_reels",
    "ig_reels",
    "instagram_reels",
    "tiktok",
    "creator_fit",
    "glam",
    "mirror",
    "fit_check",
    "thirst_trap",
    "lifestyle",
    "soft_glam",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_graph_id(entity_type: str) -> str:
    clean = slugify(entity_type).replace("-", "_")
    return f"cg_{clean}_{uuid.uuid4().hex[:12]}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "untitled"


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def media_type_for_path(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in VIDEO_EXTS:
        return "video"
    return "other"


def probe_image_shape(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": type(exc).__name__}
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return _image_shape_payload(width, height)
    if len(data) >= 10 and data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index:index + 2], "big")
            if segment_length < 2:
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if index + 7 <= len(data):
                    height = int.from_bytes(data[index + 3:index + 5], "big")
                    width = int.from_bytes(data[index + 5:index + 7], "big")
                    return _image_shape_payload(width, height)
                break
            index += segment_length
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _image_shape_payload(width, height)
    return {"ok": False, "error": "unsupported_or_invalid_image"}


def read_png_rgb_pixels(path: Path, *, max_pixels: int = 3_000_000) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": type(exc).__name__}
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"ok": False, "error": "not_png"}
    offset = 8
    width = height = color_type = bit_depth = None
    idat = bytearray()
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR" and len(payload) >= 13:
            width = int.from_bytes(payload[0:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            bit_depth = payload[8]
            color_type = payload[9]
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in {2, 6}:
        return {"ok": False, "error": "unsupported_png_format"}
    if width * height > max_pixels:
        return {"ok": False, "error": "image_too_large_for_pixel_gate"}
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except Exception:
        return {"ok": False, "error": "png_decompress_failed"}
    rows: list[list[tuple[int, int, int]]] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        if cursor >= len(raw):
            return {"ok": False, "error": "png_truncated"}
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor:cursor + stride])
        cursor += stride
        if len(row) != stride:
            return {"ok": False, "error": "png_truncated"}
        recon = _png_unfilter_row(row, previous, filter_type, channels)
        previous = recon
        rows.append([
            (recon[index], recon[index + 1], recon[index + 2])
            for index in range(0, len(recon), channels)
        ])
    return {"ok": True, "width": width, "height": height, "pixels": rows}


def _png_unfilter_row(row: bytearray, previous: bytearray, filter_type: int, bpp: int) -> bytearray:
    recon = bytearray(row)
    if filter_type == 0:
        return recon
    for index in range(len(recon)):
        left = recon[index - bpp] if index >= bpp else 0
        up = previous[index] if index < len(previous) else 0
        up_left = previous[index - bpp] if index >= bpp and index - bpp < len(previous) else 0
        if filter_type == 1:
            recon[index] = (recon[index] + left) & 0xFF
        elif filter_type == 2:
            recon[index] = (recon[index] + up) & 0xFF
        elif filter_type == 3:
            recon[index] = (recon[index] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            recon[index] = (recon[index] + _png_paeth(left, up, up_left)) & 0xFF
    return recon


def _png_paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_delta = abs(estimate - left)
    up_delta = abs(estimate - up)
    up_left_delta = abs(estimate - up_left)
    if left_delta <= up_delta and left_delta <= up_left_delta:
        return left
    if up_delta <= up_left_delta:
        return up
    return up_left


def _image_shape_payload(width: int, height: int) -> dict[str, Any]:
    aspect_ratio = (width / height) if width and height else None
    return {
        "ok": bool(width > 0 and height > 0),
        "width": width,
        "height": height,
        "effectiveWidth": width,
        "effectiveHeight": height,
        "effectiveAspectRatio": aspect_ratio,
    }


def ratio_label_from_shape(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    ratio = float(width) / float(height)
    common = [
        ("1:1", 1.0),
        ("4:5", 4 / 5),
        ("9:16", 9 / 16),
        ("1.91:1", 1.91),
    ]
    for label, target in common:
        if abs(ratio - target) <= 0.025:
            return label
    divisor = math.gcd(int(width), int(height))
    return f"{int(width) // divisor}:{int(height) // divisor}"


def normalize_content_surface(value: str | None) -> str:
    normalized = (value or "reel").strip().lower().replace(" ", "_")
    normalized = CONTENT_SURFACE_ALIASES.get(normalized, normalized.replace("-", "_"))
    if normalized in CONTENT_SURFACES:
        return normalized
    if normalized == "story_cta":
        return "story_cta"
    return "reel"


def probe_video_shape(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return {}
    if result.returncode != 0:
        return {}
    parsed = json_load(result.stdout, {})
    streams = parsed.get("streams") if isinstance(parsed, dict) else []
    if not streams:
        return {}
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rotation = int(((stream.get("tags") or {}).get("rotate") or 0) or 0)
    for side_data in stream.get("side_data_list") or []:
        if isinstance(side_data, dict) and side_data.get("rotation") is not None:
            rotation = int(side_data.get("rotation") or 0)
            break
    effective_width, effective_height = width, height
    if abs(rotation) in {90, 270}:
        effective_width, effective_height = height, width
    aspect_ratio = (effective_width / effective_height) if effective_width and effective_height else None
    return {
        "width": width,
        "height": height,
        "rotation": rotation,
        "effectiveWidth": effective_width,
        "effectiveHeight": effective_height,
        "effectiveAspectRatio": aspect_ratio,
    }


def probe_video_metadata(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate:stream_tags=rotate:stream_side_data=rotation:format=duration,bit_rate",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    if result.returncode != 0:
        return {"ok": False, "error": "probe_failed", "stderr": result.stderr.strip()}
    parsed = json_load(result.stdout, {})
    streams = parsed.get("streams") if isinstance(parsed, dict) else []
    if not isinstance(streams, list) or not streams:
        return {"ok": False, "error": "no_streams"}
    video_stream = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"), None)
    if not video_stream:
        return {"ok": False, "error": "no_video_stream"}
    audio_stream = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"), None)
    shape = probe_video_shape(path)
    fmt = parsed.get("format") if isinstance(parsed, dict) else {}
    duration = None
    try:
        duration = float((fmt or {}).get("duration")) if (fmt or {}).get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None
    bitrate = None
    try:
        bitrate = int((fmt or {}).get("bit_rate")) if (fmt or {}).get("bit_rate") is not None else None
    except (TypeError, ValueError):
        bitrate = None
    return {
        "ok": True,
        **shape,
        "durationSeconds": duration,
        "bitrate": bitrate,
        "videoCodec": video_stream.get("codec_name"),
        "frameRate": video_stream.get("avg_frame_rate"),
        "audioPresent": audio_stream is not None,
        "audioCodec": audio_stream.get("codec_name") if audio_stream else None,
    }


def reel_factory_python(reel_factory_root: Path) -> str:
    venv_python = reel_factory_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _normalize_distribution_surface(value: str | None) -> str:
    normalized = (value or "regular_reel").strip().lower().replace("-", "_")
    aliases = {
        "reel": "regular_reel",
        "regular": "regular_reel",
        "ig_reel": "regular_reel",
        "trial": "trial_reel",
        "trial_reels": "trial_reel",
        "stories": "story",
        "ig_story": "story",
        "cta_story": "story_cta",
        "single_image": "feed_single",
        "feed_image": "feed_single",
        "feed_single_image": "feed_single",
        "carousel": "feed_carousel",
        "carousel_album": "feed_carousel",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"regular_reel", "trial_reel", "story", "story_cta", "feed_single", "feed_carousel"} else "regular_reel"


def _normalize_schedule_mode(value: str | None) -> str:
    normalized = (value or "draft").strip().lower().replace("-", "_")
    return normalized if normalized in {"draft", "preview", "live"} else "draft"


SECRET_KEY_PARTS = ("secret", "service_role", "serviceRole", "token", "apikey", "api_key", "password", "key")


def sanitize_for_storage(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part.lower() in key_text.lower() for part in SECRET_KEY_PARTS):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitize_for_storage(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class CampaignFactory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = connect(settings.db_path)
        init_db(self.conn)
        self.services = CoreServices(
            self.conn,
            self.settings,
            factory_context=self,
            new_id=new_id,
            new_graph_id=new_graph_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            probe_image_shape=probe_image_shape,
            probe_video_shape=lambda *args, **kwargs: probe_video_shape(*args, **kwargs),
            probe_video_metadata=lambda *args, **kwargs: probe_video_metadata(*args, **kwargs),
            read_png_rgb_pixels=read_png_rgb_pixels,
            ratio_label_from_shape=ratio_label_from_shape,
            rendered_for_campaign=self.rendered_for_campaign,
            dashboard_rendered_asset=lambda *args, **kwargs: self._dashboard_rendered_asset(*args, **kwargs),
            audio_recommendations_for_asset=lambda *args, **kwargs: self._audio_recommendations_for_asset(*args, **kwargs),
            generated_asset_lineage=lambda *args, **kwargs: self._generated_asset_lineage(*args, **kwargs),
            prepare_reel_inputs=self.prepare_reel_inputs,
            reel_factory_python=reel_factory_python,
            make_batch=lambda *args, **kwargs: self.make_batch(*args, **kwargs),
            load_source_lineage=lambda *args, **kwargs: self._load_source_lineage(*args, **kwargs),
            discoverability_generation_gate=self.discoverability_generation_gate,
            discoverability_pre_render_gate=self.discoverability_pre_render_gate,
            discoverability_safe_content_contract=self.discoverability_safe_content_contract,
            capture_discoverability_gate_rejection_evidence=lambda *args, **kwargs: self._capture_discoverability_gate_rejection_evidence(*args, **kwargs),
            reference_hook_fallbacks=SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL,
            normalize_content_surface=normalize_content_surface,
            urlopen=lambda *args, **kwargs: urlopen(*args, **kwargs),
            campaign_dirs=self.campaign_dirs,
            concept_for_parent_asset=self._concept_for_parent_asset,
            explain_publishability=self.explain_publishability,
            capture_publishability_rejection_evidence_from_result=lambda *args, **kwargs: self._capture_publishability_rejection_evidence_from_result(*args, **kwargs),
            distribution_plan_payload=self._distribution_plan_payload,
            verification_id=self._verification_id,
            caption_lineage_sidecar=self._caption_lineage_sidecar,
            active_quarantine_for_asset=self._active_quarantine_for_asset,
            audio_segment_for_asset=self._audio_segment_for_asset,
            cover_frame_for_asset=self._cover_frame_for_asset,
            audio_intent_claims_embedded_media=self._audio_intent_claims_embedded_media,
            embedded_audio_verified=self._embedded_audio_verified,
            discoverability_evidence_for_fields=self._discoverability_evidence_for_fields,
            reference_hook_is_schedule_safe=self._reference_hook_is_schedule_safe,
            audio_intent_is_attached=self._audio_intent_is_attached,
            requires_operator_visual_review_for_handoff=self._requires_operator_visual_review_for_handoff,
            ig_media_type_for_surface=self._ig_media_type_for_surface,
            surface_handoff_readiness_report=self.surface_handoff_readiness_report,
            ensure_graph_edge_strict=self.ensure_graph_edge_strict,
            performance_summary=self.performance_summary,
            recommend_audio=self.recommend_audio,
            select_audio_for_recommendation=self.select_audio_for_recommendation,
            surface_handoff_readiness_for_asset=self._surface_handoff_readiness_for_asset,
            audio_selection_for_asset=lambda *args, **kwargs: self._audio_selection_for_asset(*args, **kwargs),
            surface_report_assets=self._surface_report_assets,
            build_surface_readiness=lambda *args, **kwargs: self._build_surface_readiness(*args, **kwargs),
            asset_matches_creator=self._asset_matches_creator,
            latest_audit_for_asset=self._latest_audit_for_asset,
            content_trust_status_blockers=lambda *args, **kwargs: self._content_trust_status_blockers(*args, **kwargs),
            compute_pdq_fingerprint=lambda *args, **kwargs: compute_pdq_fingerprint(*args, **kwargs),
            pdq_hamming_distance=lambda left, right: pdq_hamming_distance(left, right),
            surface_draft_proof=self.surface_draft_proof,
            asset_components=self._asset_components,
            instagram_post_caption_for_asset=self._instagram_post_caption_for_asset,
            register_variant_asset=lambda *args, **kwargs: self.register_variant_asset(*args, **kwargs),
            suggest_simple_instagram_post_caption=lambda *args, **kwargs: self._suggest_simple_instagram_post_caption(*args, **kwargs),
            text_hash=self._text_hash,
            validate_instagram_trial_reel_intent=self._validate_instagram_trial_reel_intent,
            variant_lineage_for_asset=self._variant_lineage_for_asset,
            story_quality_gate_for_asset=self._story_quality_gate_for_asset,
            story_style_value=self._story_style_value,
            story_intent_value=self._story_intent_value,
            ranking=lambda *args, **kwargs: self.ranking(*args, **kwargs),
            dashboard=lambda *args, **kwargs: self.dashboard(*args, **kwargs),
            creator_label=self._creator_label,
            creator_os_draft_items=self._creator_os_draft_items,
            creator_os_local_schedule_safe_assets=self._creator_os_local_schedule_safe_assets,
            creator_os_schedule_safe_drafts=self._creator_os_schedule_safe_drafts,
            creator_os_draft_exclusion_reason=self._creator_os_draft_exclusion_reason,
            creator_os_execution_draft_blockers=self._creator_os_execution_draft_blockers,
            creator_os_gap_blocking_reason=self._creator_os_gap_blocking_reason,
            creator_os_account_health_report=lambda *args, **kwargs: self.creator_os_account_health_report(*args, **kwargs),
            creator_os_account_health_decision=lambda *args, **kwargs: self._creator_os_account_health_decision(*args, **kwargs),
            creator_os_tier_posting_guidance=lambda *args, **kwargs: self._creator_os_tier_posting_guidance(*args, **kwargs),
            creator_os_account_surface_status=lambda *args, **kwargs: self._creator_os_account_surface_status(*args, **kwargs),
            creator_os_draft_has_instagram_post_caption=lambda *args, **kwargs: self._creator_os_draft_has_instagram_post_caption(*args, **kwargs),
            creator_os_post_time=lambda *args, **kwargs: self._creator_os_post_time(*args, **kwargs),
            creator_os_recommended_post_count=lambda *args, **kwargs: self._creator_os_recommended_post_count(*args, **kwargs),
            creator_os_account_tier_summary=lambda *args, **kwargs: self._creator_os_account_tier_summary(*args, **kwargs),
            creator_os_account_health_summary=lambda *args, **kwargs: self._creator_os_account_health_summary(*args, **kwargs),
            creator_os_surface_summary_for_creator=lambda *args, **kwargs: self._creator_os_surface_summary_for_creator(*args, **kwargs),
            creator_os_inventory_for_creator=lambda *args, **kwargs: self._creator_os_inventory_for_creator(*args, **kwargs),
            creator_os_draft_exclusion_counts=lambda *args, **kwargs: self._creator_os_draft_exclusion_counts(*args, **kwargs),
            creator_os_winner_recommendations=lambda *args, **kwargs: self._creator_os_winner_recommendations(*args, **kwargs),
            creator_os_manager_decision=lambda *args, **kwargs: self._creator_os_manager_decision(*args, **kwargs),
            creator_os_blocked_account_breakdown=lambda *args, **kwargs: self._creator_os_blocked_account_breakdown(*args, **kwargs),
            creator_os_recommended_inventory=lambda *args, **kwargs: self._creator_os_recommended_inventory(*args, **kwargs),
            recommendation_explainability=lambda *args, **kwargs: self._recommendation_explainability(*args, **kwargs),
            build_creative_performance_analysis=lambda *args, **kwargs: self._build_creative_performance_analysis(*args, **kwargs),
            first_lineage_value=lambda *args, **kwargs: self._first_lineage_value(*args, **kwargs),
            surface_from_pattern=lambda *args, **kwargs: self._surface_from_pattern(*args, **kwargs),
            build_creative_knowledge_base=lambda *args, **kwargs: self._build_creative_knowledge_base(*args, **kwargs),
            creative_knowledge_rows=lambda *args, **kwargs: self._creative_knowledge_rows(*args, **kwargs),
            creative_knowledge_result=lambda *args, **kwargs: self._creative_knowledge_result(*args, **kwargs),
            creator_os_target_date=self._creator_os_target_date,
            creator_os_daily_plan=self.creator_os_daily_plan,
            creator_os_execution_readiness=lambda *args, **kwargs: self.creator_os_execution_readiness(*args, **kwargs),
            inventory_slo_report=self.inventory_slo_report,
            exception_queue_priority_report=self.exception_queue_priority_report,
            parent_factory_autopilot_plan=self.parent_factory_autopilot_plan,
            inventory_autopilot_plan=self.inventory_autopilot_plan,
            inventory_stage_counts=self._inventory_stage_counts,
            inventory_production_requirements=self.inventory_production_requirements,
            exception_queue_report=self.exception_queue_report,
            reel_factory_parent_metrics=self._reel_factory_parent_metrics,
            parent_factory_production_scorecard=self.parent_factory_production_scorecard,
            build_surface_inventory=lambda *args, **kwargs: self._build_surface_inventory(*args, **kwargs),
            truthy=self._truthy,
            surface_readiness_scorecard=self.surface_readiness_scorecard,
            certification_asset_for_surface=self._certification_asset_for_surface,
            latest_proof_run_for_asset=self._latest_proof_run_for_asset,
            latest_surface_metric_for_asset=self._latest_surface_metric_for_asset,
            empty_surface_certification_audit=self._empty_surface_certification_audit,
            surface_certification_audit=self._surface_certification_audit,
            performance_snapshot_payload=self._performance_snapshot_payload,
            account_reward_baselines=account_reward_baselines,
            aggregate_performance=self._aggregate_performance,
            performance_quality_score=self._performance_quality_score,
            performance_planning_score=self._performance_planning_score,
            audio_selection_payload=self._audio_selection_payload,
            audio_workflow_summary=self.audio_workflow_summary,
            events_for_asset=self.events_for_asset,
            performance_for_asset=self._performance_for_asset,
            audit_report_payload=self._audit_report_payload,
            recommended_story_intent_for_date=self._recommended_story_intent_for_date,
            recommended_story_style_for_intent=self._recommended_story_style_for_intent,
            story_mix_plan=self.story_mix_plan,
            story_calendar_plan=self.story_calendar_plan,
            json_load=json_load,
            parent_factory_yield_waterfall=self.parent_factory_yield_waterfall,
            ratio=self._ratio,
            score_fraction=self._score_fraction,
            road_to_accounts_payload=self._road_to_accounts_payload,
            exception_next_action=self._exception_next_action,
            wilson_lower_bound=self._wilson_lower_bound,
            story_source_blockers=self._story_source_blockers,
            normalize_story_enum=self._normalize_story_enum,
            story_intents=STORY_INTENTS,
            story_goals=STORY_GOALS,
            story_styles=STORY_STYLES,
            story_native_proof_styles=STORY_NATIVE_PROOF_STYLES,
            default_story_mix=DEFAULT_STORY_MIX,
            default_story_calendar=DEFAULT_STORY_CALENDAR,
            ig_media_type_by_surface=IG_MEDIA_TYPE_BY_SURFACE,
            image_exts=IMAGE_EXTS,
            video_exts=VIDEO_EXTS,
            autonomy_levels=AUTONOMY_LEVELS,
            default_autonomy_level=DEFAULT_AUTONOMY_LEVEL,
            recommendation_proof_summary=self._recommendation_proof_summary,
            multi_blocker_inventory_unlock_report=lambda *args, **kwargs: self.multi_blocker_inventory_unlock_report(*args, **kwargs),
            multi_blocker_repair_minutes=self.MULTI_BLOCKER_REPAIR_MINUTES,
            account_trust_states=ACCOUNT_TRUST_STATES,
            recommendation_eligibility_states=RECOMMENDATION_ELIGIBILITY_STATES,
            warming_stages=WARMING_STAGES,
            content_surfaces=CONTENT_SURFACES,
            creative_risk_block_threshold=CREATIVE_RISK_BLOCK_THRESHOLD,
            creative_risk_caution_threshold=CREATIVE_RISK_CAUTION_THRESHOLD,
        )
        self.settings.campaigns_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.conn.close()

    def ensure_graph_node(
        self,
        entity_type: str,
        *,
        local_table: str | None = None,
        local_id: str | None = None,
        external_system: str | None = None,
        external_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str:
        return self.services.ensure_graph_node(
            entity_type,
            local_table=local_table,
            local_id=local_id,
            external_system=external_system,
            external_id=external_id,
            payload=payload,
            commit=commit,
        )

    def graph_id_for(
        self,
        local_table: str,
        local_id: str | None,
        *,
        entity_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        return self.services.graph_id_for(
            local_table,
            local_id,
            entity_type=entity_type,
            payload=payload,
        )

    def ensure_graph_edge(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str | None:
        return self.services.ensure_graph_edge(
            from_global_id,
            to_global_id,
            relation_type,
            evidence=evidence,
            commit=commit,
        )

    def ensure_graph_edge_strict(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        campaign_id: str | None = None,
        account_id: str | None = None,
        recommendation_item_id: str | None = None,
        source_operation: str = "content_graph",
        commit: bool = False,
    ) -> str | None:
        if from_global_id and to_global_id:
            return self.ensure_graph_edge(
                from_global_id,
                to_global_id,
                relation_type,
                evidence=evidence,
                commit=commit,
            )
        missing = []
        if not from_global_id:
            missing.append("from_global_id")
        if not to_global_id:
            missing.append("to_global_id")
        reason_code = "graph_edge_missing_endpoint"
        self.create_exception(
            reason_code=f"{reason_code}:{slugify(source_operation)}:{slugify(relation_type)}:{'_'.join(missing)}",
            severity="high",
            campaign_id=campaign_id,
            account_id=account_id,
            entity_graph_id=from_global_id or to_global_id,
            recommendation_item_id=recommendation_item_id,
            payload={
                "relationType": relation_type,
                "sourceOperation": source_operation,
                "missing": missing,
                "fromGlobalId": from_global_id,
                "toGlobalId": to_global_id,
                "evidence": sanitize_for_storage(evidence or {}),
            },
            commit=commit,
        )
        return None

    def set_graph_sync_state(self, system: str, cursor: dict[str, Any]) -> None:
        self.services.set_graph_sync_state(system, cursor)

    def campaign_dirs(self, model_slug: str, campaign_slug: str) -> dict[str, Path]:
        root = self.settings.campaigns_dir / model_slug / campaign_slug
        dirs = {
            "root": root,
            "sources": root / "00_sources",
            "reel_inputs": root / "01_reel_inputs",
            "rendered": root / "02_rendered",
            "audits": root / "03_contentforge_audits",
            "approved": root / "04_approved",
            "exports": root / "05_threadsdash_exports",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def record_event(
        self,
        event_type: str,
        *,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        render_job_id: str | None = None,
        audit_report_id: str | None = None,
        threadsdash_export_id: str | None = None,
        pipeline_job_id: str | None = None,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.services.record_event(
            event_type,
            campaign_id=campaign_id,
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_asset_id,
            render_job_id=render_job_id,
            audit_report_id=audit_report_id,
            threadsdash_export_id=threadsdash_export_id,
            pipeline_job_id=pipeline_job_id,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def create_creative_plan(
        self,
        *,
        name: str,
        platform: str = "instagram",
        target_account: str,
        daily_base_video_target: int = 10,
        style_lanes: list[str] | None = None,
        model_profile: str = "",
        source_accounts: list[str] | None = None,
        goal: str = "views_reach",
        linked_campaign: str | None = None,
    ) -> dict[str, Any]:
        return self.services.create_creative_plan(
            name=name,
            platform=platform,
            target_account=target_account,
            daily_base_video_target=daily_base_video_target,
            style_lanes=style_lanes,
            model_profile=model_profile,
            source_accounts=source_accounts,
            goal=goal,
            linked_campaign=linked_campaign,
        )

    def creative_plan(self, name: str) -> dict[str, Any]:
        return self.services.creative_plan(name)

    def update_creative_plan_status(self, *, name: str, status: str) -> dict[str, Any]:
        return self.services.update_creative_plan_status(name=name, status=status)

    def sync_creative_plan_progress(self, *, name: str, prompt_export_path: Path) -> dict[str, Any]:
        return self.services.sync_creative_plan_progress(name=name, prompt_export_path=prompt_export_path)

    def creative_plan_for_campaign(self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.services.creative_plan_for_campaign(campaign_slug, dashboard=dashboard)

    def _record_creative_plan_event(
        self,
        plan_id: str,
        event_type: str,
        *,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        self.services.record_creative_plan_event(
            plan_id,
            event_type,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def _creative_plan_payload(self, row: dict[str, Any], *, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.creative_plan_payload(row, dashboard=dashboard)

    def _source_prompt_creative_plan_id(self, source: dict[str, Any]) -> str | None:
        return self.services.source_prompt_creative_plan_id(source)

    def _asset_creative_plan_id(self, asset: dict[str, Any]) -> str | None:
        return self.services.asset_creative_plan_id(asset)

    def event_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.event_payload(row)

    def events_for_campaign(self, campaign_slug: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.services.events_for_campaign(campaign_slug, limit=limit)

    def events_for_asset(self, rendered_asset_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.services.events_for_asset(rendered_asset_id, limit=limit)

    def create_pipeline_job(self, job_type: str, campaign_id: str | None, input_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.create_pipeline_job(job_type, campaign_id, input_payload)

    def start_pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.services.start_pipeline_job(job_id)

    def finish_pipeline_job(self, job_id: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.finish_pipeline_job(job_id, result_payload)

    def fail_pipeline_job(self, job_id: str, error: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.fail_pipeline_job(job_id, error, result_payload)

    def set_pipeline_job_campaign(self, job_id: str, campaign_id: str) -> dict[str, Any]:
        return self.services.set_pipeline_job_campaign(job_id, campaign_id)

    def pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.services.pipeline_job(job_id)

    def pipeline_job_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.pipeline_job_payload(row)

    def autonomy_level(self) -> str:
        return self.services.autonomy_level()

    def set_autonomy_level(self, level: str) -> dict[str, Any]:
        return self.services.set_autonomy_level(level)

    def autonomy_policy(self) -> dict[str, Any]:
        return self.services.autonomy_policy()

    def rebuild_account_memory(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.rebuild_account_memory(campaign_slug)

    def account_memory(self, campaign_slug: str, account: str | None = None) -> dict[str, Any]:
        return self.services.account_memory_report(campaign_slug, account=account)

    def create_exception(
        self,
        *,
        reason_code: str,
        severity: str = "medium",
        campaign_id: str | None = None,
        account_id: str | None = None,
        entity_graph_id: str | None = None,
        recommendation_item_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.services.create_exception(
            reason_code=reason_code,
            severity=severity,
            campaign_id=campaign_id,
            account_id=account_id,
            entity_graph_id=entity_graph_id,
            recommendation_item_id=recommendation_item_id,
            payload=payload,
            commit=commit,
        )

    def exception(self, exception_id: str) -> dict[str, Any]:
        return self.services.exception(exception_id)

    def exceptions(self, campaign_slug: str | None = None, *, status: str = "open") -> dict[str, Any]:
        return self.services.exceptions_report(campaign_slug, status=status)

    def trust_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.trust_summary(campaign_slug)

    def recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
        persist: bool = True,
    ) -> dict[str, Any]:
        return self.services.recommendation_accuracy(
            campaign_slug,
            account=account,
            window_days=window_days,
            persist=persist,
        )

    def rebuild_recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        return self.services.rebuild_recommendation_accuracy(campaign_slug, account=account, window_days=window_days)

    def _recommendation_proof_summary(self, campaign_id: str) -> dict[str, Any]:
        return self.services.recommendation_proof_summary(campaign_id)

    def _rebuild_recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        return self.services.rebuild_recommendation_accuracy_observations(campaign_id, account=account, commit=commit)

    def _upsert_recommendation_accuracy_observation(self, row: dict[str, Any], *, commit: bool = False) -> dict[str, Any]:
        return self.services.upsert_recommendation_accuracy_observation(row, commit=commit)

    def _recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        window_days: int | None = None,
        before_window_days: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.recommendation_accuracy_observations(
            campaign_id,
            account=account,
            window_days=window_days,
            before_window_days=before_window_days,
        )

    def _recommendation_accuracy_report_payload(
        self,
        campaign: dict[str, Any],
        observations: list[dict[str, Any]],
        prior_observations: list[dict[str, Any]],
        *,
        account: str | None,
        window_days: int,
    ) -> dict[str, Any]:
        return self.services.recommendation_accuracy_report_payload(
            campaign,
            observations,
            prior_observations,
            account=account,
            window_days=window_days,
        )

    def _persist_recommendation_accuracy_report(
        self,
        report: dict[str, Any],
        campaign_id: str,
        *,
        account: str | None,
        window_days: int,
    ) -> str:
        return self.services.persist_recommendation_accuracy_report(
            report,
            campaign_id,
            account=account,
            window_days=window_days,
        )

    def _accuracy_segment(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.accuracy_segment(observations)

    def _accuracy_grouped(self, observations: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        return self.services.accuracy_grouped(observations, key)

    def _recommendation_accuracy_drift(
        self,
        recent: list[dict[str, Any]],
        prior: list[dict[str, Any]],
        *,
        min_sample: int = 5,
        drop_threshold: float = 0.15,
    ) -> list[dict[str, Any]]:
        return self.services.recommendation_accuracy_drift(
            recent,
            prior,
            min_sample=min_sample,
            drop_threshold=drop_threshold,
        )

    def _recommendation_trust_score(self, observations: list[dict[str, Any]], drift: list[dict[str, Any]]) -> int:
        return self.services.recommendation_trust_score(observations, drift)

    def _recommendation_trust_confidence(self, measured_count: int) -> str:
        return self.services.recommendation_trust_confidence(measured_count)

    def _recommendation_confidence_bucket(self, confidence: str, data_quality_level: str) -> str:
        return self.services.recommendation_confidence_bucket(confidence, data_quality_level)

    def _recommendation_audio_selection(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.services.recommendation_audio_selection(recommendation_item_id)

    def _recommendation_audio_match_status(self, output: dict[str, Any], selection: dict[str, Any]) -> str:
        return self.services.recommendation_audio_match_status(output, selection)

    def _recommendation_outcome_snapshot_ids(self, outcome: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
        return self.services.recommendation_outcome_snapshot_ids(outcome, evidence)

    def _parse_datetime(self, value: Any) -> datetime | None:
        return self.services.parse_datetime(value)

    def resolve_exception(self, exception_id: str, *, resolution: str | None = None, operator: str | None = None) -> dict[str, Any]:
        return self.services.resolve_exception(exception_id, resolution=resolution, operator=operator)

    def snooze_exception(self, exception_id: str, *, until: str | None = None, reason: str | None = None, operator: str | None = None) -> dict[str, Any]:
        return self.services.snooze_exception(exception_id, until=until, reason=reason, operator=operator)

    def reopen_exception(self, exception_id: str, *, reason: str | None = None, operator: str | None = None) -> dict[str, Any]:
        return self.services.reopen_exception(exception_id, reason=reason, operator=operator)

    def _update_exception_status(
        self,
        exception_id: str,
        status: str,
        *,
        resolution: dict[str, Any] | None = None,
        snoozed_until: str | None = None,
    ) -> dict[str, Any]:
        return self.services.update_exception_status(
            exception_id,
            status,
            resolution=resolution,
            snoozed_until=snoozed_until,
        )

    def _exception_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.exception_payload(row)

    def jobs_for_campaign(self, campaign_slug: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.services.jobs_for_campaign(campaign_slug, limit=limit)

    def import_reference_bank(self, bank_path: Path, prompt_pack_path: Path | None = None) -> dict[str, Any]:
        return self.services.import_reference_bank(bank_path, prompt_pack_path)

    def import_audio_catalog(self, catalog_path: Path) -> dict[str, Any]:
        return self.services.import_audio_catalog(catalog_path)

    def import_audio_memory(self, catalog_path: Path) -> dict[str, Any]:
        return self.services.import_audio_memory(catalog_path)

    def audio_catalog(self, platform: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self.services.audio_catalog(platform=platform, limit=limit)

    def audio_memory(self, platform: str | None = None, account: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self.services.audio_memory(platform=platform, account=account, limit=limit)

    def recommend_audio(
        self,
        *,
        platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        return self.services.recommend_audio(
            platform=platform,
            content_tags=content_tags,
            account_tags=account_tags,
            campaign_slug=campaign_slug,
            recommendation_item_id=recommendation_item_id,
            account=account,
            visual_signal=visual_signal,
            limit=limit,
        )

    def decide_audio(
        self,
        *,
        platform: str = "instagram",
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 5,
        select: bool = False,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.services.decide_audio(
            platform=platform,
            campaign_slug=campaign_slug,
            recommendation_item_id=recommendation_item_id,
            account=account,
            content_tags=content_tags,
            account_tags=account_tags,
            visual_signal=visual_signal,
            limit=limit,
            select=select,
            operator=operator,
        )

    def decide_audio_from_recommendations(
        self,
        recommendations: list[dict[str, Any]],
        *,
        requested_platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.services.decide_audio_from_recommendations(
            recommendations,
            requested_platform=requested_platform,
            content_tags=content_tags,
            account_tags=account_tags,
        )

    def _audio_decision_score(self, item: dict[str, Any], *, requested_platform: str) -> tuple[float, list[str], list[str]]:
        return self.services.audio_decision_score(item, requested_platform=requested_platform)

    def _audio_decision_confidence(self, primary: dict[str, Any] | None) -> str:
        return self.services.audio_decision_confidence(primary)

    def _audio_when_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        return self.services.audio_when_to_use(item, risks)

    def _audio_when_not_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        return self.services.audio_when_not_to_use(item, risks)

    def _audio_operator_instruction(self, primary: dict[str, Any] | None) -> str:
        return self.services.audio_operator_instruction(primary)

    def _is_generic_audio_title(self, title: str, platform: str | None = None) -> bool:
        return self.services.is_generic_audio_title(title, platform)

    def _reference_prompt_pack_by_cluster(self, prompt_pack_path: Path | None) -> dict[str, dict[str, Any]]:
        return self.services.reference_prompt_pack_by_cluster(prompt_pack_path)

    def reference_patterns(self, limit: int = 50) -> dict[str, Any]:
        return self.services.reference_patterns(limit=limit)

    def _reference_pattern_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.reference_pattern_payload(row)

    def _audio_catalog_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.audio_catalog_payload(row)

    def _audio_performance_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        return self.services.audio_performance_summary(item, campaign_id=campaign_id, account=account)

    def _audio_fatigue_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        return self.services.audio_fatigue_summary(item, campaign_id=campaign_id, account=account)

    def _audio_key(self, item: dict[str, Any]) -> str:
        return self.services.audio_key(item)

    def attach_audio_to_distribution_plan(
        self,
        distribution_plan_id: str,
        *,
        track_id: str | None = None,
        track_name: str | None = None,
        source: str | None = None,
        audio_url: str | None = None,
        native_audio_id: str | None = None,
        local_winner_audio_id: str | None = None,
        selected_reason: str | None = None,
        segment_start_seconds: float | None = None,
        segment_duration_seconds: float | None = None,
        segment_label: str | None = None,
        segment_reason: str | None = None,
        operator: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.attach_audio_to_distribution_plan(
            distribution_plan_id,
            track_id=track_id,
            track_name=track_name,
            source=source,
            audio_url=audio_url,
            native_audio_id=native_audio_id,
            local_winner_audio_id=local_winner_audio_id,
            selected_reason=selected_reason,
            segment_start_seconds=segment_start_seconds,
            segment_duration_seconds=segment_duration_seconds,
            segment_label=segment_label,
            segment_reason=segment_reason,
            operator=operator,
            notes=notes,
        )

    def attach_cover_frame_to_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        seconds: float,
        cover_image_path: str | None = None,
        cover_image_url: str | None = None,
        cover_image_hash: str | None = None,
        reason: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.services.attach_cover_frame_to_rendered_asset(
            rendered_asset_id,
            seconds=seconds,
            cover_image_path=cover_image_path,
            cover_image_url=cover_image_url,
            cover_image_hash=cover_image_hash,
            reason=reason,
            operator=operator,
        )

    def select_audio_for_recommendation(
        self,
        recommendation_item_id: str,
        audio_id: str,
        *,
        operator: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.select_audio_for_recommendation(recommendation_item_id, audio_id, operator=operator, notes=notes)

    def verify_audio_for_post(
        self,
        post_id: str,
        *,
        proof_url: str,
        proof_note: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.services.verify_audio_for_post(post_id, proof_url=proof_url, proof_note=proof_note, operator=operator)

    def _audio_catalog_row(self, audio_id: str, *, allow_locator: bool = False) -> dict[str, Any]:
        return self.services.audio_catalog_row(audio_id, allow_locator=allow_locator)

    def _audio_selection_payload(self, selection_id: str) -> dict[str, Any]:
        return self.services.audio_selection_payload(selection_id)

    def _link_audio_selection_graph(
        self,
        *,
        selection_id: str,
        recommendation_item_id: str | None = None,
        recommendation_graph_id: str | None = None,
        audio_catalog_id: str,
        post_id: str | None = None,
        performance_snapshot_id: str | None = None,
        campaign_id: str | None = None,
    ) -> None:
        return self.services.link_audio_selection_graph(
            selection_id=selection_id,
            recommendation_item_id=recommendation_item_id,
            recommendation_graph_id=recommendation_graph_id,
            audio_catalog_id=audio_catalog_id,
            post_id=post_id,
            performance_snapshot_id=performance_snapshot_id,
            campaign_id=campaign_id,
        )

    def _resolve_audio_exception_for_recommendation(self, recommendation_item_id: str, *, operator: str | None, proof_url: str | None) -> None:
        return self.services.resolve_audio_exception_for_recommendation(recommendation_item_id, operator=operator, proof_url=proof_url)

    def record_audio_performance_snapshot(self, snapshot: dict[str, Any], *, commit: bool = True) -> dict[str, Any] | None:
        return self.services.record_audio_performance_snapshot(snapshot, commit=commit)

    def _performance_snapshot_score(self, snapshot: dict[str, Any]) -> float:
        return self.services.performance_snapshot_score(snapshot)

    def _score_audio_catalog_item(self, item: dict[str, Any], tags: set[str], accounts: set[str]) -> tuple[float, list[str]]:
        return self.services.score_audio_catalog_item(item, tags, accounts)

    def _score_audio_catalog_item_v2(
        self,
        item: dict[str, Any],
        tags: set[str],
        accounts: set[str],
        *,
        account: str | None = None,
    ) -> tuple[float, list[str], dict[str, float], str]:
        return self.services.score_audio_catalog_item_v2(item, tags, accounts, account=account)

    def _audio_trend_component(self, item: dict[str, Any]) -> float:
        return self.services.audio_trend_component(item)

    def _audio_velocity_component(self, item: dict[str, Any]) -> float:
        return self.services.audio_velocity_component(item)

    def _audio_performance_component(self, item: dict[str, Any]) -> float:
        return self.services.audio_performance_component(item)

    def _audio_account_fit_component(self, item: dict[str, Any], accounts: set[str]) -> float:
        return self.services.audio_account_fit_component(item, accounts)

    def _audio_creator_fit_component(self, item: dict[str, Any], tags: set[str]) -> float:
        return self.services.audio_creator_fit_component(item, tags)

    def _audio_fatigue_safety_component(self, item: dict[str, Any]) -> float:
        return self.services.audio_fatigue_safety_component(item)

    def _audio_recommendation_confidence(self, item: dict[str, Any], components: dict[str, float]) -> str:
        return self.services.audio_recommendation_confidence(item, components)

    def _latest_audio_trend_snapshot_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.services.latest_audio_trend_snapshot_payload(item)

    def _audio_memory_trust_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.audio_memory_trust_summary(items)

    def _contentforge_audio_fit_for_item(self, item: dict[str, Any], tags: set[str], *, visual_signal: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.services.contentforge_audio_fit_for_item(item, tags, visual_signal=visual_signal)

    def _audio_catalog_recommendation(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.services.audio_catalog_recommendation(item)

    def _norm_tag(self, value: Any) -> str:
        return self.services.norm_tag(value)

    def select_reference_pattern(
        self,
        campaign_slug: str,
        *,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.select_reference_pattern(
            campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            notes=notes,
        )

    def campaign_reference_plan(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.campaign_reference_plan(campaign_slug)

    def prepare_reel_from_reference(
        self,
        *,
        campaign_slug: str,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        recipes: list[str] | None = None,
        caption_color: str | None = "auto",
        notes: str | None = None,
        force_new: bool = True,
    ) -> dict[str, Any]:
        return self.services.prepare_reel_from_reference(
            campaign_slug=campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes,
            force_new=force_new,
        )

    def active_reference_pattern_for_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self.services.active_reference_pattern_for_campaign(campaign_id)

    def reference_hooks(self, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        return self.services.reference_hooks(pattern, count=count)

    def _reference_hook_is_schedule_safe(self, text: str) -> bool:
        return self.services.reference_hook_is_schedule_safe(text)

    def finished_video_hooks(self, format_type: str, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        return self.services.finished_video_hooks(format_type, pattern, count=count)

    def upsert_model(self, slug: str, name: str | None = None, notes: str | None = None) -> dict[str, Any]:
        return self.services.upsert_model(slug, name=name, notes=notes)

    def upsert_campaign(self, slug: str, model_slug: str, name: str | None = None, platform: str = "instagram") -> dict[str, Any]:
        return self.services.upsert_campaign(slug, model_slug, name=name, platform=platform)

    def upsert_account(self, handle: str, platform: str = "instagram", external_id: str | None = None, model_id: str | None = None) -> dict[str, Any]:
        return self.services.upsert_account(handle, platform=platform, external_id=external_id, model_id=model_id)

    def upsert_model_account_profile(
        self,
        model_slug: str,
        *,
        label: str | None = None,
        allowed_instagram_account_ids: list[str] | None = None,
        allowed_account_group_names: list[str] | None = None,
        allowed_handle_patterns: list[str] | None = None,
        default_smart_link: str | None = None,
        story_cta_text: str | None = None,
    ) -> dict[str, Any]:
        return self.services.upsert_model_account_profile(
            model_slug,
            label=label,
            allowed_instagram_account_ids=allowed_instagram_account_ids,
            allowed_account_group_names=allowed_account_group_names,
            allowed_handle_patterns=allowed_handle_patterns,
            default_smart_link=default_smart_link,
            story_cta_text=story_cta_text,
        )

    def model_account_profile(self, model_slug: str) -> dict[str, Any] | None:
        return self.services.model_account_profile(model_slug)

    def _model_account_profile_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.models._model_account_profile_payload(row)

    def account_compatible_with_model(
        self,
        model_slug: str,
        *,
        instagram_account_id: str | None = None,
        account_handle: str | None = None,
        account_group_name: str | None = None,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        return self.services.account_compatible_with_model(
            model_slug,
            instagram_account_id=instagram_account_id,
            account_handle=account_handle,
            account_group_name=account_group_name,
        )

    def create_distribution_plan(
        self,
        rendered_asset_id: str,
        *,
        surface: str = "regular_reel",
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        paired_rendered_asset_id: str | None = None,
        reason_code: str | None = None,
        smart_link: str | None = None,
        cta_text: str | None = None,
        instagram_trial_reels: bool = False,
        trial_graduation_strategy: str | None = None,
    ) -> dict[str, Any]:
        return self.services.create_distribution_plan(
            rendered_asset_id,
            surface=surface,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_window_start=planned_window_start,
            planned_window_end=planned_window_end,
            paired_rendered_asset_id=paired_rendered_asset_id,
            reason_code=reason_code,
            smart_link=smart_link,
            cta_text=cta_text,
            instagram_trial_reels=instagram_trial_reels,
            trial_graduation_strategy=trial_graduation_strategy,
        )

    def _validate_instagram_trial_reel_intent(
        self,
        *,
        content_surface: str,
        distribution_surface: str,
        media_type: str,
        instagram_trial_reels: bool,
        trial_graduation_strategy: str | None,
    ) -> str | None:
        strategy = (trial_graduation_strategy or "").strip().upper() or None
        if not instagram_trial_reels:
            if strategy:
                raise ValueError("trial_graduation_strategy requires instagram_trial_reels=true")
            return None
        if content_surface != "reel":
            raise ValueError("Instagram Trial Reels require reel content")
        ig_media_type = self._ig_media_type_for_surface(content_surface, media_type)
        if ig_media_type != "REELS":
            raise ValueError("Instagram Trial Reels require ig_media_type=REELS")
        if not strategy:
            raise ValueError("trial_graduation_strategy is required for Instagram Trial Reels")
        if strategy not in TRIAL_GRADUATION_STRATEGIES:
            allowed = ", ".join(sorted(TRIAL_GRADUATION_STRATEGIES))
            raise ValueError(f"trial_graduation_strategy must be one of: {allowed}")
        return strategy

    def distribution_plan(self, plan_id: str) -> dict[str, Any] | None:
        return self.services.distribution_plan(plan_id)

    def distribution_plans_for_asset(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.services.distribution_plans_for_asset(rendered_asset_id)

    def distribution_plans_for_campaign(self, campaign_slug: str) -> list[dict[str, Any]]:
        return self.services.distribution_plans_for_campaign(campaign_slug)

    def clear_distribution_plans_for_campaign(self, campaign_slug: str) -> int:
        return self.services.clear_distribution_plans_for_campaign(campaign_slug)

    def _distribution_plan_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.distribution_plan_payload(row)

    def plan_distribution(
        self,
        campaign_slug: str,
        *,
        user_id: str,
        mode: str = "preview",
        strategy: str = "trial-heavy",
        replace: bool = True,
        fallback_hours: list[int] | None = None,
    ) -> dict[str, Any]:
        return self.services.plan_distribution(
            campaign_slug,
            user_id=user_id,
            mode=mode,
            strategy=strategy,
            replace=replace,
            fallback_hours=fallback_hours,
        )

    def _next_distribution_account(
        self,
        profile: dict[str, Any] | None,
        model_slug: str,
        cursors: dict[str, int],
    ) -> str | None:
        return self.services.next_distribution_account(profile, model_slug, cursors)

    def _distribution_slots(self, hours: list[int], count: int) -> list[datetime]:
        return self.services.distribution_slots(hours, count)

    def _next_valid_distribution_slot(
        self,
        slots: list[datetime],
        start_index: int,
        account_id: str,
        asset: dict[str, Any],
        account_day_counts: dict[tuple[str, str], int],
        account_last_time: dict[str, datetime],
        caption_day_counts: dict[tuple[str, str], int],
        source_week_counts: dict[tuple[str, str], int],
        warnings: list[dict[str, Any]],
    ) -> tuple[datetime | None, int]:
        return self.services.next_valid_distribution_slot(
            slots,
            start_index,
            account_id,
            asset,
            account_day_counts,
            account_last_time,
            caption_day_counts,
            source_week_counts,
            warnings,
        )

    def import_folder(
        self,
        folder: Path,
        *,
        campaign_slug: str,
        model_slug: str,
        model_name: str | None = None,
        platform: str = "instagram",
        account_handles: list[str] | None = None,
        source_prompt: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.import_folder(
            folder,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            model_name=model_name,
            platform=platform,
            account_handles=account_handles,
            source_prompt=source_prompt,
            notes=notes,
        )

    def list_campaigns(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM campaigns ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def campaign_by_slug(self, slug: str) -> dict[str, Any]:
        return self.services.campaign_by_slug(slug)

    def assets_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        return self.services.assets_for_campaign(campaign_id)

    def rendered_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at DESC", (campaign_id,)).fetchall()
        return [dict(r) for r in rows]

    def rendered_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.services.rendered_asset(rendered_asset_id)

    def register_parent_reel(
        self,
        rendered_asset_id: str,
        *,
        operator: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.register_parent_reel(
            rendered_asset_id,
            operator=operator,
            status=status,
            metadata=metadata,
        )

    def caption_family_plan(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.services.caption_family_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def caption_family_create(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.services.caption_family_create(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def _planned_caption_version(
        self,
        *,
        caption_family_id: str,
        parent: dict[str, Any],
        concept: dict[str, Any] | None,
        index: int,
        angle: str,
        base_burned: str,
        base_hashtags: list[str],
        style: str,
        caption_source: str,
    ) -> dict[str, Any]:
        return self.services.planned_caption_version(
            caption_family_id=caption_family_id,
            parent=parent,
            concept=concept,
            index=index,
            angle=angle,
            base_burned=base_burned,
            base_hashtags=base_hashtags,
            style=style,
            caption_source=caption_source,
        )

    def _caption_family_hashtags(self, raw_tags: Any) -> list[str]:
        return self.services.caption_family_hashtags(raw_tags)

    def variant_plan(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        cooldown_days: int = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
    ) -> dict[str, Any]:
        return self.services.variant_plan(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            contentforge_preset=contentforge_preset,
            cooldown_days=cooldown_days,
        )

    def generate_variants(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        contentforge_base_url: str | None = None,
        source_media_path: str | None = None,
        contentforge_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        return self.services.generate_variants(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            contentforge_preset=contentforge_preset,
            contentforge_base_url=contentforge_base_url,
            source_media_path=source_media_path,
            contentforge_timeout_seconds=contentforge_timeout_seconds,
        )

    def _contentforge_variant_pack_blocked_result(
        self,
        *,
        plan: dict[str, Any],
        blocking_reason: str,
        endpoint: str,
        staged_source: str,
        timeout_seconds: int,
        error: BaseException,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.contentforge_variant_pack_blocked_result(
            plan=plan,
            blocking_reason=blocking_reason,
            endpoint=endpoint,
            staged_source=staged_source,
            timeout_seconds=timeout_seconds,
            error=error,
            extra=extra,
        )

    def register_variant_asset(
        self,
        *,
        parent_asset_id: str,
        variant_asset_id: str,
        variant_family_id: str,
        variant_index: int,
        operations: list[dict[str, Any]],
        caption_family_id: str | None = None,
        caption_version_id: str | None = None,
        contentforge_run_id: str | None = None,
        contentforge_preset: str = "caption_safe",
        qc_status: str = "passed",
        cooldown_days: int = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.services.register_variant_asset(
            parent_asset_id=parent_asset_id,
            variant_asset_id=variant_asset_id,
            variant_family_id=variant_family_id,
            variant_index=variant_index,
            operations=operations,
            caption_family_id=caption_family_id,
            caption_version_id=caption_version_id,
            contentforge_run_id=contentforge_run_id,
            contentforge_preset=contentforge_preset,
            qc_status=qc_status,
            cooldown_days=cooldown_days,
            commit=commit,
        )

    def parent_variant_inventory(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.parent_variant_inventory(campaign_slug)

    def variant_metrics_rollup(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.variant_metrics_rollup(campaign_slug)

    def creator_os_daily_plan(
        self,
        *,
        creators: list[str] | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_daily_plan(
            creators=creators,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_metrics_rollup=variant_metrics_rollup,
            date=date,
            generated_at=generated_at,
        )

    def creator_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_surface_summary(creator=creator, date=date, generated_at=generated_at)

    def account_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        account_id: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.account_surface_summary(
            creator=creator,
            date=date,
            account_id=account_id,
            generated_at=generated_at,
        )

    def creator_surface_gap_report(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_surface_gap_report(creator=creator, date=date, generated_at=generated_at)

    def story_inventory_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.story_inventory_report(creator=creator, campaign_slug=campaign_slug)

    def story_intent_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.story_intent_report(creator=creator, campaign_slug=campaign_slug)

    def story_mix_plan(self, *, creator: str) -> dict[str, Any]:
        return self.services.story_mix_plan(creator=creator)

    def story_calendar_plan(self, *, creator: str) -> dict[str, Any]:
        return self.services.story_calendar_plan(creator=creator)

    def story_intent_summary(self, *, creator: str, campaign_slug: str | None = None) -> dict[str, Any]:
        return self.services.story_intent_summary(creator=creator, campaign_slug=campaign_slug)

    def _story_metadata_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.story_metadata_payload(asset)

    def _story_intent_value(self, asset: dict[str, Any]) -> str | None:
        return self.services.story_intent_value(asset)

    def _story_goal_value(self, asset: dict[str, Any]) -> str | None:
        return self.services.story_goal_value(asset)

    def _story_style_value(self, asset: dict[str, Any]) -> str | None:
        return self.services.story_style_value(asset)

    def _normalize_story_enum(self, value: Any, allowed: set[str]) -> str | None:
        return self.services.normalize_story_enum(value, allowed)

    def story_quality_gate_v1(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.services.story_quality_gate_v1(rendered_asset_id)

    def story_quality_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.story_quality_report(creator=creator, campaign_slug=campaign_slug)

    def _story_quality_gate_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.story_quality_gate_for_asset(asset)

    def _story_quality_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.story_quality_metadata(asset)

    def _bounded_score(self, value: Any, *, default: int) -> int:
        return self.services.bounded_score(value, default=default)

    def _story_black_bar_check(self, media_path: Path, *, media_type: str) -> dict[str, Any]:
        return self.services.story_black_bar_check(media_path, media_type=media_type)

    def _story_no_text_check(self, media_path: Path, *, media_type: str, quality: dict[str, Any]) -> dict[str, Any]:
        return self.services.story_no_text_check(media_path, media_type=media_type, quality=quality)

    def _story_ocr_frame_paths(self, media_path: Path, *, media_type: str) -> list[Path]:
        return self.services.story_ocr_frame_paths(media_path, media_type=media_type)

    def _story_ocr_detect_text(self, image_path: Path, *, frame_index: int) -> list[dict[str, Any]]:
        return self.services.story_ocr_detect_text(image_path, frame_index=frame_index)

    def _pixel_region_black(self, rows: list[list[tuple[int, int, int]]], *, x0: int, x1: int, y0: int, y1: int) -> bool:
        return self.services.pixel_region_black(rows, x0=x0, x1=x1, y0=y0, y1=y1)

    def story_gap_report(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.story_gap_report(creator=creator, date=date)

    def account_story_status(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        return self.services.account_story_status(account_id=account_id, creator=creator, date=date)

    def creator_story_summary(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.creator_story_summary(creator=creator, date=date)

    def creator_os_account_tiers(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_account_tiers(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )

    def creator_os_account_health_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_account_health_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )

    def creator_os_restricted_account_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_restricted_account_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )

    def creator_os_manual_review_queue(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_manual_review_queue(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )

    def creator_os_account_warmup_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_account_warmup_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )

    def creator_os_draft_inventory_gap(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_draft_inventory_gap(
            creator=creator,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            generated_at=generated_at,
        )

    def creator_os_execution_readiness(
        self,
        *,
        creator: str,
        requested_count: int,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_execution_readiness(
            creator=creator,
            requested_count=requested_count,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            generated_at=generated_at,
        )

    def decision_ledger_preview(
        self,
        *,
        creator: str,
        date: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        account_tiers: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.decision_ledger_preview(
            creator=creator,
            date=date,
            threadsdash_report=threadsdash_report or {},
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_inventory_plan=variant_inventory_plan,
            variant_metrics_rollup=variant_metrics_rollup,
            account_tiers=account_tiers,
            generated_at=generated_at,
        )

    def decision_ledger_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_report(**kwargs)

    def decision_ledger_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_summary(**kwargs)

    def creator_os_200_account_acceptance_suite(
        self,
        *,
        accounts: int = 200,
        creators: int = 3,
        daily_obligations: int = 600,
        draft_inventory: int = 1800,
        warming_accounts: int = 30,
        restricted_accounts: int = 15,
        manual_review_accounts: int = 10,
        mixed_surfaces: bool = True,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_200_account_acceptance_suite(
            accounts=accounts,
            creators=creators,
            daily_obligations=daily_obligations,
            draft_inventory=draft_inventory,
            warming_accounts=warming_accounts,
            restricted_accounts=restricted_accounts,
            manual_review_accounts=manual_review_accounts,
            mixed_surfaces=mixed_surfaces,
            generated_at=generated_at,
        )

    def inventory_slo_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        creators: int = 3,
        minimum_inventory_days: int = 3,
        current_validated_drafts: int = 0,
        current_drafts_by_surface: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_slo_report(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            creators=creators,
            minimum_inventory_days=minimum_inventory_days,
            current_validated_drafts=current_validated_drafts,
            current_drafts_by_surface=current_drafts_by_surface,
        )

    def inventory_buffer_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_buffer_report(**kwargs)

    def inventory_factory_audit(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        return self.services.inventory_factory_audit(
            creator=creator,
            campaign_slug=campaign_slug,
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
        )

    def inventory_yield_analysis(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_yield_analysis(creator=creator, campaign_slug=campaign_slug)

    def inventory_buffer_policy_plan(
        self,
        *,
        creator: str,
        surface: str,
        daily_demand: int,
        buffer_target_days: int = 3,
        available_inventory: int | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_buffer_policy_plan(
            creator=creator,
            surface=surface,
            daily_demand=daily_demand,
            buffer_target_days=buffer_target_days,
            available_inventory=available_inventory,
        )

    def inventory_slo_enforcement_audit(
        self,
        *,
        creators: list[str] | None = None,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        minimum_inventory_days: int = 3,
        available_by_creator_surface: dict[str, dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_slo_enforcement_audit(
            creators=creators,
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            minimum_inventory_days=minimum_inventory_days,
            available_by_creator_surface=available_by_creator_surface,
        )

    def inventory_consumption_simulation(
        self,
        *,
        available_inventory: int = 0,
        account_tiers: list[int] | None = None,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        return self.services.inventory_consumption_simulation(
            available_inventory=available_inventory,
            account_tiers=account_tiers,
            posts_per_account_per_day=posts_per_account_per_day,
        )

    def inventory_production_requirements(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        variants_per_parent: int = 15,
        variant_to_validated_yield: float = 0.85,
        validated_to_schedule_safe_yield: float = 0.90,
    ) -> dict[str, Any]:
        return self.services.inventory_production_requirements(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            variants_per_parent=variants_per_parent,
            variant_to_validated_yield=variant_to_validated_yield,
            validated_to_schedule_safe_yield=validated_to_schedule_safe_yield,
        )

    def road_to_200_accounts(self) -> dict[str, Any]:
        return self.services.road_to_200_accounts()

    def inventory_exception_audit(
        self,
        *,
        execution_readiness: dict[str, Any] | None = None,
        surface_readiness_report: dict[str, Any] | None = None,
        publishability_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_exception_audit(
            execution_readiness=execution_readiness,
            surface_readiness_report=surface_readiness_report,
            publishability_report=publishability_report,
        )

    def inventory_recovery_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = None,
        required_inventory: int | None = None,
        account_target: int = 25,
        posts_per_account_per_day: int = 3,
        buffer_days: int = 3,
    ) -> dict[str, Any]:
        return self.services.inventory_recovery_report(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            account_target=account_target,
            posts_per_account_per_day=posts_per_account_per_day,
            buffer_days=buffer_days,
        )

    def inventory_recovery_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_recovery_priority_report(**kwargs)

    def inventory_recovery_by_blocker(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_recovery_by_blocker(**kwargs)

    def inventory_recovery_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_recovery_master_report(**kwargs)

    def schedule_safe_production_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        lookback_days: int = 1,
        required_inventory: int | None = None,
        current_inventory: int | None = None,
    ) -> dict[str, Any]:
        return self.services.schedule_safe_production_report(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            lookback_days=lookback_days,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
        )

    def schedule_safe_production_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.schedule_safe_production_waterfall(**kwargs)

    def schedule_safe_production_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.schedule_safe_production_loss_analysis(**kwargs)

    def schedule_safe_production_capacity_model(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.schedule_safe_production_capacity_model(**kwargs)

    def schedule_safe_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.schedule_safe_production_master_report(**kwargs)

    FRESH_REEL_PARENT_YIELD_EVIDENCE = FreshReelProductionRepository.FRESH_REEL_PARENT_YIELD_EVIDENCE
    FRESH_REEL_STAGE_YIELDS = FreshReelProductionRepository.FRESH_REEL_STAGE_YIELDS
    FRESH_REEL_GATES_TO_VERIFY = FreshReelProductionRepository.FRESH_REEL_GATES_TO_VERIFY

    def fresh_schedule_safe_production_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        target_schedule_safe_inventory: int = 270,
        current_inventory: int | None = None,
        caption_versions_per_parent: int = 5,
        variants_per_caption: int = 3,
        batch_schedule_safe_target: int = 90,
    ) -> dict[str, Any]:
        return self.services.fresh_schedule_safe_production_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            target_schedule_safe_inventory=target_schedule_safe_inventory,
            current_inventory=current_inventory,
            caption_versions_per_parent=caption_versions_per_parent,
            variants_per_caption=variants_per_caption,
            batch_schedule_safe_target=batch_schedule_safe_target,
        )

    def fresh_reel_production_batch_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.fresh_reel_production_batch_plan(**kwargs)

    def fresh_reel_production_capacity_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.fresh_reel_production_capacity_plan(**kwargs)

    def fresh_reel_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.fresh_reel_production_master_report(**kwargs)

    CONTENTFORGE_VISUAL_QC_CATEGORIES = ContentForgeVisualQCRepository.CONTENTFORGE_VISUAL_QC_CATEGORIES
    CONTENTFORGE_VISUAL_QC_MINUTES = ContentForgeVisualQCRepository.CONTENTFORGE_VISUAL_QC_MINUTES
    CONTENTFORGE_VISUAL_QC_REPAIRABLE = ContentForgeVisualQCRepository.CONTENTFORGE_VISUAL_QC_REPAIRABLE

    def contentforge_visual_qc_failure_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        lookback_days: int = 1,
        current_inventory: int | None = None,
        required_inventory: int = 225,
    ) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_failure_report(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            lookback_days=lookback_days,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
        )

    def contentforge_visual_qc_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_waterfall(**kwargs)

    def contentforge_visual_qc_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_loss_analysis(**kwargs)

    def contentforge_visual_qc_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_repair_plan(**kwargs)

    def contentforge_visual_qc_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_master_report(**kwargs)

    MULTI_BLOCKER_REPAIR_CLASSES = MultiBlockerUnlockRepository.MULTI_BLOCKER_REPAIR_CLASSES
    MULTI_BLOCKER_REPAIR_MINUTES = MultiBlockerUnlockRepository.MULTI_BLOCKER_REPAIR_MINUTES
    MULTI_BLOCKER_REPAIR_DIFFICULTY = MultiBlockerUnlockRepository.MULTI_BLOCKER_REPAIR_DIFFICULTY

    def multi_blocker_inventory_unlock_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
    ) -> dict[str, Any]:
        return self.services.multi_blocker_inventory_unlock_report(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
        )

    def multi_blocker_inventory_unlock_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.multi_blocker_inventory_unlock_plan(**kwargs)

    def inventory_unlock_minimal_fix_set(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_unlock_minimal_fix_set(**kwargs)

    def inventory_unlock_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_unlock_master_report(**kwargs)

    def operator_inventory_review_batch_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
        target_unlock: int | None = None,
        max_batch_size: int | None = None,
    ) -> dict[str, Any]:
        return self.services.operator_inventory_review_batch_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
            target_unlock=target_unlock,
            max_batch_size=max_batch_size,
        )

    def operator_inventory_review_batch_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.operator_inventory_review_batch_summary(**kwargs)

    def operator_review_simulator(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
        approval_rates: list[int] | None = None,
    ) -> dict[str, Any]:
        return self.services.operator_review_simulator(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
            approval_rates=approval_rates,
        )

    def operator_review_scenarios(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.operator_review_scenarios(**kwargs)

    def operator_review_efficiency_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.operator_review_efficiency_report(**kwargs)

    def operator_review_minimum_certification_path(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.operator_review_minimum_certification_path(**kwargs)

    def operator_review_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.operator_review_master_report(**kwargs)

    def _operator_review_execution_order(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.operator_review_execution_order(rows)

    def _operator_review_batch_priority(self, repair_classes: list[str]) -> int:
        return self.services.operator_review_batch_priority(repair_classes)

    def _operator_review_batch_type(self, repair_classes: list[str]) -> str:
        return self.services.operator_review_batch_type(repair_classes)

    def _operator_review_scenario(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
        approval_rate: int,
    ) -> dict[str, Any]:
        return self.services.operator_review_scenario(
            ordered_rows,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
            approval_rate=approval_rate,
        )

    def _operator_review_minimum_path(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> dict[str, Any]:
        return self.services.operator_review_minimum_path(
            ordered_rows,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
        )

    def _operator_review_highest_roi_batch_type(self, rows: list[dict[str, Any]]) -> str:
        return self.services.operator_review_highest_roi_batch_type(rows)

    def _operator_review_lowest_risk_batch_type(self, rows: list[dict[str, Any]]) -> str:
        return self.services.operator_review_lowest_risk_batch_type(rows)

    def _operator_review_batch_order_labels(self, rows: list[dict[str, Any]]) -> list[str]:
        return self.services.operator_review_batch_order_labels(rows)

    def _operator_review_candidate_eligible(self, asset: dict[str, Any]) -> bool:
        return self.services.operator_review_candidate_eligible(asset)

    def _operator_review_candidate_row(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.operator_review_candidate_row(asset)

    def _operator_review_actions(self, repair_classes: list[str]) -> list[str]:
        return self.services.operator_review_actions(repair_classes)

    def _multi_blocker_asset_row(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.services.multi_blocker_asset_row(readiness)

    def _multi_blocker_repair_class(self, reason: str) -> str:
        return self.services.multi_blocker_repair_class(reason)

    def _multi_blocker_combo_rows(
        self,
        blocked_assets: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> list[dict[str, Any]]:
        return self.services.multi_blocker_combo_rows(
            blocked_assets,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
        )

    def _multi_blocker_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        return self.services.multi_blocker_assets_unlocked(blocked_assets, repair_classes)

    def _multi_blocker_estimated_minutes(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        return self.services.multi_blocker_estimated_minutes(blocked_assets, repair_classes)

    def _multi_blocker_combo_difficulty(self, repair_classes: list[str]) -> str:
        return self.services.multi_blocker_combo_difficulty(repair_classes)

    def _multi_blocker_best_combo(self, combo_rows: list[dict[str, Any]], size: int) -> dict[str, Any]:
        return self.services.multi_blocker_best_combo(combo_rows, size)

    def _multi_blocker_minimal_fix_set(
        self,
        combo_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> dict[str, Any]:
        return self.services.multi_blocker_minimal_fix_set(
            combo_rows,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
        )

    def _contentforge_visual_qc_failure_for_asset(self, asset: dict[str, Any], surface: str) -> dict[str, Any]:
        return self.services.contentforge_visual_qc_failure_for_asset(asset, surface)

    def _contentforge_visual_qc_failure_category(
        self,
        asset: dict[str, Any],
        blockers: list[str],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
    ) -> str:
        return self.services.contentforge_visual_qc_failure_category(asset, blockers, readiness, publishability)

    def _contentforge_non_visual_gates_pass(
        self,
        checks: dict[str, Any],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
        non_visual_blockers: list[str],
    ) -> bool:
        return self.services.contentforge_non_visual_gates_pass(
            checks,
            readiness,
            publishability,
            non_visual_blockers,
        )

    def _contentforge_visual_qc_category_rows(self, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.contentforge_visual_qc_category_rows(failures)

    def _contentforge_visual_qc_recovered_inventory(self, failures: list[dict[str, Any]], categories: list[str]) -> int:
        return self.services.contentforge_visual_qc_recovered_inventory(failures, categories)

    def _contentforge_visual_qc_answer(self, top: dict[str, Any], total_failures: int) -> str:
        return self.services.contentforge_visual_qc_answer(top, total_failures)

    def _schedule_safe_production_assets(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
        content_surface: str,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        return self.services.schedule_safe_production_assets(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            lookback_days=lookback_days,
        )

    def _schedule_safe_asset_created_at(self, asset: dict[str, Any]) -> datetime:
        return self.services.schedule_safe_asset_created_at(asset)

    def _schedule_safe_production_waterfall_rows(self, assets: list[dict[str, Any]], surface: str) -> list[dict[str, Any]]:
        return self.services.schedule_safe_production_waterfall_rows(assets, surface)

    def _schedule_safe_is_variant_asset(self, asset: dict[str, Any]) -> bool:
        return self.services.schedule_safe_is_variant_asset(asset)

    def _schedule_safe_related_count(self, table: str, column: str, asset_ids: set[str]) -> int:
        return self.services.schedule_safe_related_count(table, column, asset_ids)

    def _schedule_safe_production_variant_checks(self, asset: dict[str, Any], surface: str) -> dict[str, Any]:
        return self.services.schedule_safe_production_variant_checks(asset, surface)

    def _schedule_safe_production_largest_loss(self, waterfall: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.schedule_safe_production_largest_loss(waterfall)

    def _schedule_safe_production_capacity(
        self,
        *,
        current_inventory: int,
        daily_production: float,
        required_for_25: int,
    ) -> dict[str, Any]:
        return self.services.schedule_safe_production_capacity(
            current_inventory=current_inventory,
            daily_production=daily_production,
            required_for_25=required_for_25,
        )

    def _schedule_safe_required_parents_per_day(self, produced_per_day: float, produced: int, parent_count: int) -> int:
        return self.services.schedule_safe_required_parents_per_day(produced_per_day, produced, parent_count)

    def _schedule_safe_required_variants_per_day(self, produced_per_day: float, produced: int, variant_count: int) -> int:
        return self.services.schedule_safe_required_variants_per_day(produced_per_day, produced, variant_count)

    def _schedule_safe_production_summary_key(self, stage: str) -> str:
        return self.services.schedule_safe_production_summary_key(stage)

    def _fresh_reel_current_schedule_safe_inventory(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
    ) -> int:
        return self.services.fresh_reel_current_schedule_safe_inventory(
            creator=creator,
            campaign_slug=campaign_slug,
        )

    def _fresh_reel_downstream_schedule_safe_yield_pct(self) -> float:
        return self.services.fresh_reel_downstream_schedule_safe_yield_pct()

    def _fresh_reel_expected_stage_rows(
        self,
        *,
        raw_parent_candidates_needed: int,
        parents_needed: int,
        caption_families_needed: int,
        caption_versions_needed: int,
        variants_needed: int,
    ) -> list[dict[str, Any]]:
        return self.services.fresh_reel_expected_stage_rows(
            raw_parent_candidates_needed=raw_parent_candidates_needed,
            parents_needed=parents_needed,
            caption_families_needed=caption_families_needed,
            caption_versions_needed=caption_versions_needed,
            variants_needed=variants_needed,
        )

    def _fresh_reel_stage_evidence(self, stage: str) -> str:
        return self.services.fresh_reel_stage_evidence(stage)

    def _fresh_reel_execution_batches(
        self,
        *,
        fresh_needed: int,
        downstream_yield_pct: float,
        variants_per_parent: int,
        batch_target: int,
    ) -> list[dict[str, Any]]:
        return self.services.fresh_reel_execution_batches(
            fresh_needed=fresh_needed,
            downstream_yield_pct=downstream_yield_pct,
            variants_per_parent=variants_per_parent,
            batch_target=batch_target,
        )

    def _inventory_recovery_blocked_asset(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.services.inventory_recovery_blocked_asset(readiness)

    def _inventory_recovery_class_for_blocker(self, reason: str) -> str:
        return self.services.inventory_recovery_class_for_blocker(reason)

    def _inventory_recovery_class_rows(self, blocked_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.inventory_recovery_class_rows(blocked_assets)

    def _inventory_recovery_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repaired_classes: list[str]) -> int:
        return self.services.inventory_recovery_assets_unlocked(blocked_assets, repaired_classes)

    def _inventory_recovery_priorities(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.inventory_recovery_priorities(rows)

    def inventory_factory_readiness_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        execution_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_factory_readiness_report(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            available_inventory=available_inventory,
            execution_readiness=execution_readiness,
        )

    def inventory_factory_master_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        execution_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.inventory_factory_master_report(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            available_inventory=available_inventory,
            execution_readiness=execution_readiness,
        )

    def reel_factory_parent_throughput_proof(
        self,
        *,
        required_parents_per_day: int = 53,
        lookback_days: int = 1,
    ) -> dict[str, Any]:
        return self.services.reel_factory_parent_throughput_proof(
            required_parents_per_day=required_parents_per_day,
            lookback_days=lookback_days,
        )

    def reel_factory_yield_analysis(self, *, metrics: dict[str, int] | None = None) -> dict[str, Any]:
        return self.services.reel_factory_yield_analysis(metrics=metrics)

    def reel_factory_failure_analysis(self) -> dict[str, Any]:
        return self.services.reel_factory_failure_analysis()

    def reel_factory_capacity_model(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        return self.services.reel_factory_capacity_model(required_parents_per_day=required_parents_per_day)

    def reel_factory_200_account_readiness(self) -> dict[str, Any]:
        return self.services.reel_factory_200_account_readiness()

    def reel_factory_master_report(self) -> dict[str, Any]:
        return self.services.reel_factory_master_report()

    def parent_factory_yield_waterfall(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        return self.services.parent_factory_yield_waterfall(required_parents_per_day=required_parents_per_day)

    def parent_factory_loss_analysis(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        return self.services.parent_factory_loss_analysis(required_parents_per_day=required_parents_per_day)

    def parent_factory_rejection_report(self, *, waterfall: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.parent_factory_rejection_report(waterfall=waterfall)

    def parent_factory_discoverability_loss_analysis(self, *, waterfall: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.parent_factory_discoverability_loss_analysis(waterfall=waterfall)

    def parent_factory_quality_gate_analysis(self) -> dict[str, Any]:
        return self.services.parent_factory_quality_gate_analysis()

    def parent_factory_optimization_plan(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        return self.services.parent_factory_optimization_plan(required_parents_per_day=required_parents_per_day)

    def parent_factory_master_optimization_report(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        return self.services.parent_factory_master_optimization_report(required_parents_per_day=required_parents_per_day)

    def discoverability_intake_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.services.discoverability_intake_gate(payload)

    def discoverability_generation_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.services.discoverability_generation_gate(payload)

    def discoverability_pre_render_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.services.discoverability_pre_render_gate(payload)

    def discoverability_violation_origin_map(self) -> dict[str, Any]:
        return self.services.discoverability_violation_origin_map()

    def parent_factory_recoverable_yield(self) -> dict[str, Any]:
        return self.services.parent_factory_recoverable_yield()

    def parent_factory_throughput_recovery_plan(self) -> dict[str, Any]:
        return self.services.parent_factory_throughput_recovery_plan()

    def parent_factory_53_parent_feasibility(self) -> dict[str, Any]:
        return self.services.parent_factory_53_parent_feasibility()

    def parent_factory_secondary_loss_analysis(self) -> dict[str, Any]:
        return self.services.parent_factory_secondary_loss_analysis()

    def parent_factory_waterfall_after_discoverability(self) -> dict[str, Any]:
        return self.services.parent_factory_waterfall_after_discoverability()

    def parent_factory_true_yield_model(self) -> dict[str, Any]:
        return self.services.parent_factory_true_yield_model()

    def parent_factory_realistic_53_parent_plan(self) -> dict[str, Any]:
        return self.services.parent_factory_realistic_53_parent_plan()

    def exception_queue_report(
        self,
        *,
        daily_plan: dict[str, Any] | None = None,
        execution_readiness: dict[str, Any] | None = None,
        publishability_report: dict[str, Any] | None = None,
        surface_readiness_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.exception_queue_report(
            daily_plan=daily_plan,
            execution_readiness=execution_readiness,
            publishability_report=publishability_report,
            surface_readiness_report=surface_readiness_report,
        )

    def exception_queue_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.exception_queue_summary(**kwargs)

    def exception_queue_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.exception_queue_priority_report(**kwargs)

    def exception_queue_owner_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.exception_queue_owner_report(**kwargs)

    def parent_factory_autopilot_plan(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        return self.services.parent_factory_autopilot_plan(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
        )

    def parent_factory_shortfall_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.parent_factory_shortfall_report(**kwargs)

    def parent_factory_production_targets(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.parent_factory_production_targets(**kwargs)

    def inventory_autopilot_plan(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        buffer_target_days: int = 3,
        surface: str = "reel",
    ) -> dict[str, Any]:
        return self.services.inventory_autopilot_plan(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            available_inventory=available_inventory,
            buffer_target_days=buffer_target_days,
            surface=surface,
        )

    def inventory_shortage_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_shortage_repair_plan(**kwargs)

    def inventory_buffer_protection_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.services.inventory_buffer_protection_report(**kwargs)

    def creator_os_100_account_proof(self) -> dict[str, Any]:
        return self.services.creator_os_100_account_proof()

    def creator_os_volume_acceptance_suite(self) -> dict[str, Any]:
        return self.services.creator_os_volume_acceptance_suite()

    def surface_readiness_scorecard(self) -> dict[str, Any]:
        return self.services.surface_readiness_scorecard()

    def creator_os_10_0_readiness_report(self) -> dict[str, Any]:
        return self.services.creator_os_10_0_readiness_report()

    def creator_os_live_100_account_readiness(self) -> dict[str, Any]:
        return self.services.creator_os_live_100_account_readiness()

    def creator_os_live_scale_runbook(self) -> dict[str, Any]:
        return self.services.creator_os_live_scale_runbook()

    def creator_os_live_scale_scorecard(self) -> dict[str, Any]:
        return self.services.creator_os_live_scale_scorecard()

    def reserve_inventory_asset(
        self,
        asset_id: str,
        *,
        account_id: str | None = None,
        surface: str | None = None,
        reserved_by: str = "campaign_factory",
        expires_at: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        reuse_cooldown_days: int = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.reserve_inventory_asset(
            asset_id,
            account_id=account_id,
            surface=surface,
            reserved_by=reserved_by,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
            reuse_cooldown_days=reuse_cooldown_days,
            override_reason=override_reason,
        )

    def _expire_inventory_reservations(self, *, now: str | None = None, commit: bool = True) -> int:
        return self.services.expire_inventory_reservations(now=now, commit=commit)

    def release_inventory_reservation(
        self,
        reservation_id: str,
        *,
        status: str = "released",
    ) -> dict[str, Any]:
        return self.services.release_inventory_reservation(reservation_id, status=status)

    def _asset_uniqueness_values(self, asset: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> dict[str, str]:
        return self.services.asset_uniqueness_values(asset, metadata=metadata)

    def ensure_rendered_asset_perceptual_metadata(self, rendered_asset_id: str, *, commit: bool = True) -> dict[str, Any]:
        return self.services.ensure_rendered_asset_perceptual_metadata(rendered_asset_id, commit=commit)

    def _pdq_cluster_id_for_fingerprint(self, *, campaign_id: str, rendered_asset_id: str, fingerprint: str) -> str:
        return self.services.pdq_cluster_id_for_fingerprint(
            campaign_id=campaign_id,
            rendered_asset_id=rendered_asset_id,
            fingerprint=fingerprint,
        )

    def _inventory_uniqueness_conflicts(
        self,
        asset: dict[str, Any],
        *,
        uniqueness: dict[str, str],
        surface: str,
        cooldown_days: int,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.inventory_uniqueness_conflicts(
            asset,
            uniqueness=uniqueness,
            surface=surface,
            cooldown_days=cooldown_days,
            account_id=account_id,
        )

    def _reservation_adjusted_inventory(
        self,
        readiness_rows: list[dict[str, Any]],
        *,
        content_surface: str | None = None,
    ) -> dict[str, int]:
        return self.services.reservation_adjusted_inventory(readiness_rows, content_surface=content_surface)

    def creator_os_live_account_acceptance(
        self,
        *,
        account_target: int,
        posts_per_account_per_day: int = 3,
        buffer_days: int = 3,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_live_account_acceptance(
            account_target=account_target,
            posts_per_account_per_day=posts_per_account_per_day,
            buffer_days=buffer_days,
            content_surface=content_surface,
            threadsdash_report=threadsdash_report,
        )

    def creator_os_staged_live_acceptance(
        self,
        *,
        stages: list[int] | None = None,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_staged_live_acceptance(
            stages=stages,
            content_surface=content_surface,
            threadsdash_report=threadsdash_report,
        )

    def _live_acceptance_actuals(
        self,
        *,
        account_target: int,
        threadsdash_report: dict[str, Any],
        required_inventory: int,
        available_inventory: int,
        exception_count: int,
    ) -> dict[str, Any]:
        return self.services.live_acceptance_actuals(
            account_target=account_target,
            threadsdash_report=threadsdash_report,
            required_inventory=required_inventory,
            available_inventory=available_inventory,
            exception_count=exception_count,
        )

    def _live_acceptance_missed_dispatches(self, report: dict[str, Any]) -> int:
        return self.services.live_acceptance_missed_dispatches(report)

    def _live_acceptance_duplicate_publishes(self, report: dict[str, Any]) -> int:
        return self.services.live_acceptance_duplicate_publishes(report)

    def _live_acceptance_restricted_scheduled(self, report: dict[str, Any]) -> int:
        return self.services.live_acceptance_restricted_scheduled(report)

    def _live_acceptance_surface_contract_violations(self, report: dict[str, Any]) -> int:
        return self.services.live_acceptance_surface_contract_violations(report)

    def _live_acceptance_metrics_imported(self) -> bool:
        return self.services.live_acceptance_metrics_imported()

    def _live_acceptance_blocker_for(self, key: str) -> str:
        return self.services.live_acceptance_blocker_for(key)

    def parent_factory_production_trial(self) -> dict[str, Any]:
        return self.services.parent_factory_production_trial()

    def _latest_measured_53_parent_production_trial(self) -> dict[str, Any] | None:
        return self.services.latest_measured_53_parent_production_trial()

    def parent_factory_53_parent_trial(self) -> dict[str, Any]:
        return self.services.parent_factory_53_parent_trial()

    def parent_factory_trial_results(self) -> dict[str, Any]:
        return self.services.parent_factory_trial_results()

    def parent_factory_trial_analysis(self) -> dict[str, Any]:
        return self.services.parent_factory_trial_analysis()

    def parent_factory_post_gate_fresh_batch_proof(self) -> dict[str, Any]:
        return self.services.parent_factory_post_gate_fresh_batch_proof()

    def parent_factory_production_scorecard(self) -> dict[str, Any]:
        return self.services.parent_factory_production_scorecard()

    def parent_factory_real_yield_report(self) -> dict[str, Any]:
        return self.services.parent_factory_real_yield_report()

    def discoverability_prevention_audit(self) -> dict[str, Any]:
        return self.services.discoverability_prevention_audit()

    def discoverability_prevention_scorecard(self) -> dict[str, Any]:
        return self.services.discoverability_prevention_scorecard()

    def story_certification_proof(self, *, rendered_asset_id: str | None = None) -> dict[str, Any]:
        return self.services.story_certification_proof(rendered_asset_id=rendered_asset_id)

    def carousel_certification_proof(self, *, rendered_asset_id: str | None = None) -> dict[str, Any]:
        return self.services.carousel_certification_proof(rendered_asset_id=rendered_asset_id)

    def _certification_asset_for_surface(self, surface: str, *, rendered_asset_id: str | None = None) -> dict[str, Any] | None:
        return self.services.certification_asset_for_surface(surface, rendered_asset_id=rendered_asset_id)

    def _latest_proof_run_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.services.latest_proof_run_for_asset(rendered_asset_id)

    def _latest_surface_metric_for_asset(self, rendered_asset_id: str, surface: str) -> dict[str, Any] | None:
        return self.services.latest_surface_metric_for_asset(rendered_asset_id, surface)

    def _empty_surface_certification_audit(self, surface: str) -> dict[str, Any]:
        return self.services.empty_surface_certification_audit(surface)

    def _surface_certification_audit(
        self,
        *,
        asset: dict[str, Any],
        readiness: dict[str, Any],
        draft_payload: dict[str, Any],
        proof_run: dict[str, Any] | None,
        metrics: dict[str, Any] | None,
        carousel_integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.surface_certification_audit(
            asset=asset,
            readiness=readiness,
            draft_payload=draft_payload,
            proof_run=proof_run,
            metrics=metrics,
            carousel_integrity=carousel_integrity,
        )

    def story_production_readiness(self) -> dict[str, Any]:
        return self.services.story_production_readiness()

    def story_proof_gap_analysis(self) -> dict[str, Any]:
        return self.services.story_proof_gap_analysis()

    def carousel_production_readiness(self) -> dict[str, Any]:
        return self.services.carousel_production_readiness()

    def carousel_proof_gap_analysis(self) -> dict[str, Any]:
        return self.services.carousel_proof_gap_analysis()

    def creator_os_certification_report(self) -> dict[str, Any]:
        return self.services.creator_os_certification_report()

    def failure_injection_suite(self) -> dict[str, Any]:
        return self.services.failure_injection_suite()

    def idempotency_proof(self) -> dict[str, Any]:
        return self.services.idempotency_proof()

    def surface_maturity_audit(self) -> dict[str, Any]:
        return self.services.surface_maturity_audit()

    def operator_load_audit(self) -> dict[str, Any]:
        return self.services.operator_load_audit()

    def single_source_of_truth_audit(self) -> dict[str, Any]:
        return self.services.single_source_of_truth_audit()

    def core_complexity_reduction_plan(self) -> dict[str, Any]:
        return self.services.core_complexity_reduction_plan()

    def creator_os_9_5_readiness_report(self) -> dict[str, Any]:
        return self.services.creator_os_9_5_readiness_report()

    def _inventory_slo_surface_targets(self, minimum_buffer: int) -> dict[str, int]:
        return self.services.inventory_slo_surface_targets(minimum_buffer)

    def _inventory_health(self, *, current: int, minimum: int) -> str:
        return self.services.inventory_health(current=current, minimum=minimum)

    def _inventory_stage_counts(self, *, creator: str | None = None, campaign_slug: str | None = None) -> dict[str, int]:
        return self.services.inventory_stage_counts(creator=creator, campaign_slug=campaign_slug)

    def _inventory_count_related(self, table: str, column: str, asset_ids: set[str]) -> int:
        return self.services.inventory_count_related(table, column, asset_ids)

    def _inventory_limiting_stage(self, counts: dict[str, int]) -> str:
        return self.services.inventory_limiting_stage(counts)

    def _inventory_loss_by_stage(self, counts: dict[str, int]) -> dict[str, int]:
        return self.services.inventory_loss_by_stage(counts)

    def _ratio(self, numerator: Any, denominator: Any) -> float:
        denom = float(denominator or 0)
        if denom <= 0:
            return 0
        return round(float(numerator or 0) / denom, 3)

    def _score_fraction(self, numerator: Any, denominator: Any) -> float:
        denom = float(denominator or 0)
        if denom <= 0:
            return 0.0
        return round(10 * min(1.0, max(0.0, float(numerator or 0) / denom)), 1)

    def _road_to_accounts_payload(self, *, accounts: int, production: dict[str, Any]) -> dict[str, Any]:
        posts = int(production.get("postsPerDay") or 0)
        return {
            "schema": f"creator_os.road_to_{accounts}_accounts.v1",
            "accounts": accounts,
            "requiredInventoryBuffer": f"{posts * 3} schedule-safe drafts",
            "requiredDailyProduction": f"{posts} schedule-safe drafts/day",
            "requiredValidatedDrafts": f"{production.get('requiredValidatedDraftsPerDay')} validated drafts/day",
            "requiredParentAssetsPerDay": int(production.get("requiredParentsPerDay") or 0),
            "requiredCaptionFamiliesPerDay": int(production.get("requiredCaptionFamiliesPerDay") or 0),
            "requiredVariantsPerDay": int(production.get("requiredVariantsPerDay") or 0),
            "requiredExceptionRate": "<=2.0% inventory-blocking exceptions",
            "requiredOperatorLoad": "<=25 inventory exceptions/day per operator queue",
            "wouldWrite": False,
        }

    def _reel_factory_parent_metrics(self) -> dict[str, int]:
        return self.services.reel_factory_parent_metrics()

    def _reel_factory_parent_qc_pass(self, asset: dict[str, Any]) -> bool:
        return self.services.reel_factory_parent_qc_pass(asset)

    def _reel_factory_confidence(self, metrics: dict[str, int]) -> str:
        return self.services.reel_factory_confidence(metrics)

    def _operator_review_minutes_per_parent(self, metrics: dict[str, int]) -> float:
        return self.services.operator_review_minutes_per_parent(metrics)

    def _reel_factory_intake_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.services.reel_factory_intake_metrics(metrics)

    def _reel_factory_parent_creation_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.services.reel_factory_parent_creation_metrics(metrics)

    def _reel_factory_quality_gate_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return self.services.reel_factory_quality_gate_metrics(yield_report)

    def _reel_factory_operational_readiness_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return self.services.reel_factory_operational_readiness_metrics(yield_report)

    def _reel_factory_human_cost(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.services.reel_factory_human_cost(metrics)

    def _reel_factory_rating(self, proof: dict[str, Any]) -> float:
        return self.services.reel_factory_rating(proof)

    def _parent_factory_stage_order(self) -> list[str]:
        return self.services.parent_factory_stage_order()

    def _parent_factory_detailed_stage_counts(self, metrics: dict[str, int]) -> dict[str, int]:
        return self.services.parent_factory_detailed_stage_counts(metrics)

    def _parent_factory_highest_roi(self, reasons: list[dict[str, Any]]) -> str:
        return self.services.parent_factory_highest_roi(reasons)

    def _parent_factory_top_fixes(self, reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.parent_factory_top_fixes(reasons)

    def _parent_factory_observed_discoverability_terms(self) -> list[dict[str, str]]:
        return self.services.parent_factory_observed_discoverability_terms()

    def _parent_factory_captured_discoverability_evidence(self) -> list[dict[str, str]]:
        return self.services.parent_factory_captured_discoverability_evidence()

    def _discoverability_text_values(self, payload: dict[str, Any]) -> list[str]:
        return self.services.discoverability_text_values(payload)

    def _discoverability_loss_category(self, reason: str, matched_text: str) -> str:
        return self.services.discoverability_loss_category(reason, matched_text)

    def _discoverability_prevention_stage(self, category: str) -> str:
        return self.services.discoverability_prevention_stage(category)

    def _parent_factory_human_bottleneck(self, *, required: int, rejection: dict[str, Any]) -> dict[str, Any]:
        return self.services.parent_factory_human_bottleneck(required=required, rejection=rejection)

    def _parent_factory_yield_explanation(self, waterfall: dict[str, Any], loss: dict[str, Any]) -> str:
        return self.services.parent_factory_yield_explanation(waterfall, loss)

    def _discoverability_gate_fields(self, payload: dict[str, Any], allowed_fields: set[str]) -> list[tuple[str, str]]:
        return self.services.discoverability_gate_fields(payload, allowed_fields)

    def _discoverability_gate_result(self, gate: str, fields: list[tuple[str, str]]) -> dict[str, Any]:
        return self.services.discoverability_gate_result(gate, fields)

    def _discoverability_origin_stage(self, source_field: str, reason: str) -> str:
        return self.services.discoverability_origin_stage(source_field, reason)

    def _post_discoverability_downstream_confidence(self) -> dict[str, Any]:
        return self.services.post_discoverability_downstream_confidence()

    def _wilson_lower_bound(self, *, successes: int, trials: int, z: float = 1.96) -> float:
        if trials <= 0:
            return 0.0
        phat = successes / trials
        denominator = 1 + (z * z / trials)
        centre = phat + (z * z / (2 * trials))
        margin = z * math.sqrt((phat * (1 - phat) + (z * z / (4 * trials))) / trials)
        return max(0.0, (centre - margin) / denominator)

    def _secondary_loss_reason(self, stage: str, loss_count: int) -> str:
        return self.services.secondary_loss_reason(stage, loss_count)

    def _parent_factory_trial_loss_buckets(self, waterfall: dict[str, Any]) -> dict[str, int]:
        return self.services.parent_factory_trial_loss_buckets(waterfall)

    def _parent_factory_trial_stage_repairable(self, stage: str) -> bool:
        return self.services.parent_factory_trial_stage_repairable(stage)

    def _post_gate_fresh_batch_candidates(self) -> list[dict[str, str]]:
        return self.services.post_gate_fresh_batch_candidates()

    def _post_gate_blocked_candidate_evidence(self, sandbox: CampaignFactory, result: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.post_gate_blocked_candidate_evidence(sandbox, result)

    def _exception_queue_item(
        self,
        *,
        severity: str,
        system: str,
        account: Any,
        asset: Any,
        reason: str,
        next_action: str,
        count: int | None = None,
    ) -> dict[str, Any]:
        return self.services.exception_queue_item(
            severity=severity,
            system=system,
            account=account,
            asset=asset,
            reason=reason,
            next_action=next_action,
            count=count,
        )

    def _exception_severity_for_reason(self, reason: str) -> str:
        return self.services.exception_severity_for_reason(reason)

    def _exception_next_action(self, reason: str) -> str:
        return self.services.exception_next_action(reason)

    def _exception_category_for_reason(self, reason: str, system: str) -> str:
        return self.services.exception_category_for_reason(reason, system)

    def _exception_owner_for_category(self, category: str, system: str) -> str:
        return self.services.exception_owner_for_category(category, system)

    def _exception_repairable(self, reason: str) -> bool:
        return self.services.exception_repairable(reason)

    def _exception_resolution_minutes(self, reason: str, *, count: int | None = None) -> int:
        return self.services.exception_resolution_minutes(reason, count=count)

    def _inventory_repair_actions(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        return self.services.inventory_repair_actions(policy)

    def _actual_account_operational_counts(self) -> dict[str, int]:
        return self.services.actual_account_operational_counts()

    def _live_100_exact_shortfall(
        self,
        *,
        accounts: dict[str, int],
        available_inventory: int,
        required_inventory: int,
        available_parents: int,
        required_parents: int,
    ) -> str:
        return self.services.live_100_exact_shortfall(
            accounts=accounts,
            available_inventory=available_inventory,
            required_inventory=required_inventory,
            available_parents=available_parents,
            required_parents=required_parents,
        )

    def _idempotency_evidence_for_path(self, name: str) -> str:
        return self.services.idempotency_evidence_for_path(name)

    def _largest_project_files(self) -> list[dict[str, Any]]:
        return self.services.largest_project_files()

    def decision_ledger_by_creator(self, *, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_by_creator(creator=creator, **kwargs)

    def decision_ledger_by_account(self, *, account_id: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_by_account(account_id=account_id, creator=creator, **kwargs)

    def decision_ledger_by_surface(self, *, surface: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_by_surface(surface=surface, creator=creator, **kwargs)

    def decision_ledger_by_decision_type(self, *, decision_type: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.services.decision_ledger_by_decision_type(decision_type=decision_type, creator=creator, **kwargs)

    def _query_decision_ledger(
        self,
        *,
        creator: str,
        account_id: str | None = None,
        surface: str | None = None,
        decision_type: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.services.query_decision_ledger(
            creator=creator,
            account_id=account_id,
            surface=surface,
            decision_type=decision_type,
            **kwargs,
        )

    def _manager_decision_filtered_report(
        self,
        *,
        schema: str,
        report: dict[str, Any],
        decisions: list[dict[str, Any]],
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        return self.services.decision_ledger.manager_decision_filtered_report(
            schema=schema,
            report=report,
            decisions=decisions,
            extra=extra,
        )

    def _decision_entries_from_account_content_needs(
        self,
        *,
        creator: str,
        date: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        return self.services.decision_ledger.decision_entries_from_account_content_needs(
            creator=creator,
            date=date,
            timestamp=timestamp,
        )

    def _decision_entries_from_daily_plan_accounts(
        self,
        *,
        daily: dict[str, Any],
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        return self.services.decision_ledger.decision_entries_from_daily_plan_accounts(
            daily=daily,
            creator=creator,
            timestamp=timestamp,
        )

    def _decision_entries_from_winner_expansion_report(
        self,
        *,
        report: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        return self.services.decision_ledger.decision_entries_from_winner_expansion_report(
            report=report,
            creator=creator,
            timestamp=timestamp,
        )

    def _decision_entries_from_variant_inventory_plan(
        self,
        *,
        plan: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        return self.services.decision_ledger.decision_entries_from_variant_inventory_plan(
            plan=plan,
            creator=creator,
            timestamp=timestamp,
        )

    def _decision_entries_from_winner_expansion_plan(
        self,
        *,
        plan: dict[str, Any] | None,
        creator: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        return self.services.decision_ledger.decision_entries_from_winner_expansion_plan(
            plan=plan,
            creator=creator,
            timestamp=timestamp,
        )

    def _manager_decision_entry(
        self,
        *,
        decision_type: str,
        reason: str,
        timestamp: str,
        source_system: str,
        explanation: str,
        creator: str | None = None,
        account_id: str | None = None,
        surface: str | None = None,
        rendered_asset_id: str | None = None,
        parent_asset_id: str | None = None,
        variant_id: str | None = None,
        payload: dict[str, Any] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.decision_ledger.manager_decision_entry(
            decision_type=decision_type,
            reason=reason,
            timestamp=timestamp,
            source_system=source_system,
            explanation=explanation,
            creator=creator,
            account_id=account_id,
            surface=surface,
            rendered_asset_id=rendered_asset_id,
            parent_asset_id=parent_asset_id,
            variant_id=variant_id,
            payload=payload,
            context_snapshot=context_snapshot,
        )

    def _dedupe_manager_decisions(self, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.decision_ledger.dedupe_manager_decisions(decisions)

    def _manager_decision_types_supported(self) -> list[str]:
        return self.services.decision_ledger.manager_decision_types_supported()

    def _manager_obligation_reason(self, obligation: dict[str, Any]) -> str:
        return self.services.decision_ledger.manager_obligation_reason(obligation)

    def _manager_obligation_explanation(self, obligation: dict[str, Any]) -> str:
        return self.services.decision_ledger.manager_obligation_explanation(obligation)

    def _story_goal_for_intent(self, intent: str) -> str:
        return self.services.decision_ledger.story_goal_for_intent(intent)

    def _creator_os_local_schedule_safe_assets(self, creator: str) -> list[dict[str, Any]]:
        items = []
        for asset in self._surface_report_assets(creator=creator):
            readiness = self._surface_handoff_readiness_for_asset(asset)
            if not readiness.get("canHandoff"):
                continue
            items.append({
                "renderedAssetId": asset["id"],
                "campaign": asset.get("campaign_slug"),
                "contentSurface": readiness.get("contentSurface"),
                "latestDistributionPlanId": (
                    readiness.get("handoffManifest", {}).get("distribution_plan_id")
                    if isinstance(readiness.get("handoffManifest"), dict)
                    else None
                ),
            })
        return items

    def _creator_os_target_date(self, *, date: str | None = None, generated_at: str | None = None) -> str:
        raw = (date or generated_at or "").strip()
        if raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return raw[:10]
        return datetime.fromisoformat(utc_now().replace("Z", "+00:00")).date().isoformat()

    def _creator_os_account_surface_status(self, account: dict[str, Any], *, reel_needed: bool) -> dict[str, dict[str, Any]]:
        status = {
            surface: {"needed": False, "scheduled": False, "completed": False, "blockedReason": ""}
            for surface in CONTENT_SURFACES
        }
        raw_status = account.get("surfaceStatus")
        raw_needs = account.get("surfaceNeeds") or account.get("needsBySurface")
        if isinstance(raw_status, dict):
            for raw_surface, raw_value in raw_status.items():
                surface = normalize_content_surface(str(raw_surface))
                if surface not in status:
                    continue
                value = raw_value if isinstance(raw_value, dict) else {"needed": bool(raw_value)}
                status[surface] = {
                    "needed": bool(value.get("needed")),
                    "scheduled": bool(value.get("scheduled")),
                    "completed": bool(value.get("completed")),
                    "blockedReason": str(value.get("blockedReason") or ""),
                }
            return status
        if isinstance(raw_needs, dict):
            for raw_surface, raw_value in raw_needs.items():
                surface = normalize_content_surface(str(raw_surface))
                if surface not in status:
                    continue
                if isinstance(raw_value, dict):
                    needed = bool(raw_value.get("needed") or int(raw_value.get("remaining") or 0) > 0)
                    blocked = str(raw_value.get("blockedReason") or "")
                else:
                    try:
                        needed = int(raw_value or 0) > 0
                    except (TypeError, ValueError):
                        needed = bool(raw_value)
                    blocked = ""
                status[surface]["needed"] = needed
                status[surface]["blockedReason"] = blocked
            return status
        status["reel"]["needed"] = bool(reel_needed)
        return status

    def _creator_os_surface_summary_for_creator(
        self,
        *,
        creator: str,
        date: str,
        report: dict[str, Any],
        creator_accounts: list[dict[str, Any]],
        draft_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inventory_report = self.multi_surface_inventory_audit(creator=creator)
        local_inventory = inventory_report.get("inventoryBySurface") or {}
        schedule_safe_drafts = self._creator_os_schedule_safe_drafts(creator, draft_items)
        thread_dash_inventory = {surface: 0 for surface in CONTENT_SURFACES}
        for item in schedule_safe_drafts:
            surface = normalize_content_surface(
                str(item.get("contentSurface") or item.get("content_surface") or item.get("surface") or item.get("distributionSurface") or "reel")
            )
            if surface in thread_dash_inventory:
                thread_dash_inventory[surface] += 1

        needs_by_surface = {surface: 0 for surface in CONTENT_SURFACES}
        try:
            needs_report = self.creator_content_needs(creator=creator, date=date)
        except Exception:
            needs_report = {}
        totals_by_surface = needs_report.get("totalsBySurface") if isinstance(needs_report, dict) else None
        has_requirement_data = bool(needs_report.get("accountsAnalyzed")) if isinstance(needs_report, dict) else False
        if isinstance(totals_by_surface, dict) and has_requirement_data:
            for surface in CONTENT_SURFACES:
                needs_by_surface[surface] = int((totals_by_surface.get(surface) or {}).get("remaining") or 0)
        else:
            for account in creator_accounts:
                surface_status = account.get("surfaceNeeds") if isinstance(account.get("surfaceNeeds"), dict) else {}
                for surface in CONTENT_SURFACES:
                    if (surface_status.get(surface) or {}).get("needed"):
                        needs_by_surface[surface] += 1

        surface_inventory: dict[str, dict[str, int]] = {}
        surface_shortfalls: dict[str, dict[str, Any]] = {}
        surface_readiness: dict[str, dict[str, Any]] = {}
        for surface in CONTENT_SURFACES:
            local = local_inventory.get(surface) or {}
            schedule_safe = int(thread_dash_inventory.get(surface) or 0)
            needed = int(needs_by_surface.get(surface) or 0)
            shortfall = max(0, needed - schedule_safe)
            surface_inventory[surface] = {
                "localTotal": int(local.get("total") or 0),
                "localScheduleSafe": int(local.get("scheduleSafe") or 0),
                "threadDashScheduleSafeDrafts": schedule_safe,
            }
            surface_shortfalls[surface] = {
                "needed": needed,
                "scheduleSafeDraftsAvailable": schedule_safe,
                "shortfall": shortfall,
            }
            surface_readiness[surface] = {
                "needed": needed,
                "scheduleSafeDraftsAvailable": schedule_safe,
                "ready": needed == 0 or schedule_safe >= needed,
                "blockedReason": "surface_inventory_shortfall" if shortfall else "",
                "wouldWrite": False,
            }
        return {
            "accountsNeedingReels": needs_by_surface["reel"],
            "accountsNeedingStories": needs_by_surface["story"],
            "accountsNeedingFeedSingles": needs_by_surface["feed_single"],
            "accountsNeedingCarousels": needs_by_surface["feed_carousel"],
            "surfaceInventory": surface_inventory,
            "surfaceShortfalls": surface_shortfalls,
            "surfaceScheduleReadiness": surface_readiness,
            "wouldWrite": False,
        }

    def _creator_os_gap_blocking_reason(self, reason: str, blockers: list[str], item: dict[str, Any]) -> str:
        if reason == "missingInstagramPostCaption":
            return "missing_instagram_post_caption"
        if reason == "missingHandoffManifest":
            return "missing_handoff_manifest"
        if reason == "notPlatformDraftValidated":
            return "platform_draft_not_validated"
        if reason == "quarantined":
            return "quarantined"
        if reason == "publishabilityFailed":
            return "publishability_failed"
        if reason == "variantCooldownBlocked":
            return str(item.get("variantCooldownCheck") or "variant_cooldown_blocked")
        duplicate = str(item.get("duplicateCheck") or "clear")
        if duplicate and duplicate != "clear":
            return duplicate
        if blockers:
            return blockers[0]
        if item.get("qstashEligible") is not True:
            return "not_qstash_eligible"
        return "unknown_not_schedule_safe"

    def _recommended_story_intent_for_date(self, target_date: str, *, creator: str | None = None) -> str:
        if creator:
            try:
                intent_counts = self.story_intent_report(creator=creator).get("intentCounts") or {}
            except Exception:
                intent_counts = {}
            if intent_counts:
                return sorted(intent_counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))[0][0]
        try:
            day_name = datetime.fromisoformat(target_date).strftime("%A")
        except ValueError:
            day_name = "Monday"
        return DEFAULT_STORY_CALENDAR.get(day_name, "casual_selfie")

    def _recommended_story_style_for_intent(self, intent: str) -> str:
        return {
            "snapchat_promo": "casual_selfie",
            "reel_teaser": "raw_phone",
            "casual_selfie": "casual_selfie",
            "mirror_selfie": "mirror",
            "outfit_check": "mirror",
            "gym_selfie": "selfie",
            "bedroom_selfie": "selfie",
            "lifestyle": "lifestyle",
            "behind_the_scenes": "raw_phone",
            "engagement": "casual",
            "profile_visit": "casual",
        }.get(intent, "casual_selfie")

    def _creator_label(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "unknown"
        return text[:1].upper() + text[1:]

    def _creator_os_draft_items(self, planner_inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for plan in planner_inputs:
            for raw in plan.get("items") or plan.get("inventory") or []:
                if not isinstance(raw, dict):
                    continue
                post_id = str(raw.get("postId") or raw.get("draftPostId") or "")
                key = post_id or json.dumps(sanitize_for_storage(raw), sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                items.append(dict(raw))
        return items

    def _creator_os_draft_has_instagram_post_caption(self, draft: dict[str, Any]) -> bool:
        explicit_keys = {
            "instagram_post_caption",
            "instagramPostCaption",
            "post_caption",
            "postCaption",
            "content",
        }
        metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
        campaign_meta = metadata.get("campaign_factory") if isinstance(metadata.get("campaign_factory"), dict) else {}
        manifest = campaign_meta.get("handoff_manifest") if isinstance(campaign_meta.get("handoff_manifest"), dict) else {}
        containers = [draft, metadata, campaign_meta, manifest]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in explicit_keys:
                if key in container and str(container.get(key) or "").strip():
                    return True
        return False

    def _creator_os_draft_exclusion_reason(self, draft: dict[str, Any]) -> str:
        if not self._creator_os_draft_has_instagram_post_caption(draft):
            return "missingInstagramPostCaption"
        if draft.get("handoffManifestOk") is not True:
            return "missingHandoffManifest"
        if draft.get("platformDraftValidated") is not True:
            return "notPlatformDraftValidated"
        if self._truthy(draft.get("quarantined") or draft.get("assetQuarantined") or draft.get("campaignFactoryQuarantined")):
            return "quarantined"
        publishability_state = str(draft.get("publishabilityState") or draft.get("assetState") or "").strip()
        if publishability_state not in {"exportable", "publishable_candidate", "platform_draft_validated"}:
            return "publishabilityFailed"
        cooldown_reason = str(draft.get("variantCooldownCheck") or "clear")
        if cooldown_reason and cooldown_reason != "clear":
            return "variantCooldownBlocked"
        return ""

    def _truthy(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _creator_os_draft_exclusion_counts(self, creator: str, draft_items: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "missingInstagramPostCaption": 0,
            "missingHandoffManifest": 0,
            "notPlatformDraftValidated": 0,
            "quarantined": 0,
            "publishabilityFailed": 0,
            "variantCooldownBlocked": 0,
        }
        for item in draft_items:
            if self._creator_label(item.get("creator")) not in {creator, "unknown"}:
                continue
            reason = self._creator_os_draft_exclusion_reason(item)
            if reason in counts:
                counts[reason] += 1
        return counts

    def _creator_os_schedule_safe_drafts(self, creator: str, draft_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item
            for item in draft_items
            if self._creator_label(item.get("creator")) in {creator, "unknown"}
            and item.get("qstashEligible") is True
            and not self._creator_os_draft_exclusion_reason(item)
            and not self._creator_os_execution_draft_blockers(creator, [item])
        ]

    def _creator_os_execution_account_health_blockers(self, account_health: dict[str, Any]) -> list[str]:
        return self.services.creator_os_execution_account_health_blockers(account_health)

    def _creator_os_execution_account_health_warnings(self, account_health: dict[str, Any]) -> list[str]:
        return self.services.creator_os_execution_account_health_warnings(account_health)

    def _creator_os_execution_draft_blockers(self, creator: str, draft_items: list[dict[str, Any]]) -> list[str]:
        blockers: set[str] = set()
        for item in draft_items:
            if self._creator_label(item.get("creator")) not in {creator, "unknown"}:
                continue
            reason = self._creator_os_draft_exclusion_reason(item)
            if reason == "missingInstagramPostCaption":
                blockers.add("missing_instagram_post_caption")
            elif reason == "missingHandoffManifest":
                blockers.add("missing_handoff_manifest")
            elif reason == "notPlatformDraftValidated":
                blockers.add("platform_draft_not_validated")
            elif reason == "quarantined":
                blockers.add("quarantined_draft_present")
            elif reason == "publishabilityFailed":
                blockers.add("publishability_failed_draft_present")
            elif reason == "variantCooldownBlocked":
                blockers.add("variant_cooldown_violation")
            if not (item.get("renderedAssetId") or item.get("campaignFactoryAssetId") or item.get("campaign_factory_asset_id")):
                blockers.add("missing_campaign_factory_asset_id")
            if not (item.get("distributionPlanId") or item.get("campaignFactoryDistributionPlanId") or item.get("campaign_factory_distribution_plan_id")):
                blockers.add("missing_campaign_factory_distribution_plan_id")
            duplicate_reason = str(item.get("duplicateCheck") or "clear")
            if duplicate_reason and duplicate_reason != "clear":
                blockers.add("duplicate_schedule_risk")
            if self._creator_os_explicit_false(item, "burnedCaptionTextPresent", "burned_caption_text_present", "burnedCaptionPresent"):
                blockers.add("missing_burned_caption_text")
            placement_status = str(item.get("captionPlacementQcStatus") or item.get("captionPlacementStatus") or item.get("caption_placement_qc_status") or "").lower()
            if placement_status and placement_status not in {"passed", "pass", "ok"}:
                blockers.add("caption_placement_qc_failed")
            audio_status = str(item.get("audioValidity") or item.get("audio_validity") or item.get("audioStatus") or "").lower()
            if audio_status in {"failed", "invalid", "mismatch"}:
                blockers.add("embedded_audio_invalid")
            creative_risk = int(self._creator_os_numeric(item.get("creativeRiskScore") or item.get("creative_risk_score") or ((item.get("creativeRisk") or {}).get("score") if isinstance(item.get("creativeRisk"), dict) else 0)))
            if creative_risk >= CREATIVE_RISK_BLOCK_THRESHOLD:
                blockers.add("creative_risk_score_exceeded")
            budget = item.get("similarityBudget") if isinstance(item.get("similarityBudget"), dict) else {}
            if budget.get("blocked") or item.get("similarityBudgetExceeded") or item.get("similarity_budget_exceeded"):
                blockers.add("similarity_budget_exceeded")
        return sorted(blockers)

    def _creator_os_explicit_false(self, item: dict[str, Any], *keys: str) -> bool:
        for key in keys:
            if key not in item:
                continue
            value = item.get(key)
            if isinstance(value, bool):
                return value is False
            if str(value).strip().lower() in {"0", "false", "no"}:
                return True
        return False

    def _creator_os_inventory_for_creator(
        self,
        creator: str,
        planner_inputs: list[dict[str, Any]],
        draft_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        matching_plans = [plan for plan in planner_inputs if self._creator_label(plan.get("creator")) == creator or not plan.get("creator")]
        validated = 0
        for plan in matching_plans:
            validated = max(validated, int(plan.get("validatedDraftsAvailable") or 0))
        item_validated = sum(
            1
            for item in draft_items
            if item.get("qstashEligible") is True
            and self._creator_label(item.get("creator")) in {creator, "unknown"}
            and not self._creator_os_draft_exclusion_reason(item)
        )
        if draft_items:
            validated = item_validated
        elif not validated:
            validated = sum(
                1
                for item in draft_items
                if item.get("qstashEligible") is True
                and self._creator_label(item.get("creator")) in {creator, "unknown"}
                and not self._creator_os_draft_exclusion_reason(item)
            )
        variant = sum(
            1
            for item in draft_items
            if item.get("qstashEligible") is True
            and (item.get("variantId") or item.get("variantFamilyId"))
            and self._creator_label(item.get("creator")) in {creator, "unknown"}
            and not self._creator_os_draft_exclusion_reason(item)
        )
        return {"validatedDraftsAvailable": validated, "variantDraftsAvailable": variant}

    def _creator_os_blocked_account_breakdown(self, blocked_accounts: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for account in blocked_accounts:
            reason = str(account.get("blockedReason") or "blocked_unknown")
            counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))

    def _creator_os_account_tier_summary(self, accounts: list[dict[str, Any]], *, key: str = "accountTier") -> dict[str, int]:
        return self.services.creator_os_account_tier_summary(accounts, key=key)

    def _creator_os_account_health_decision(self, account: dict[str, Any], *, missed: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.creator_os_account_health_decision(account, missed=missed)

    def _creator_os_account_health_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.creator_os_account_health_summary(rows)

    def _creator_os_account_trust_state(self, account: dict[str, Any]) -> str:
        return self.services.creator_os_account_trust_state(account)

    def _creator_os_recommendation_eligibility(self, account: dict[str, Any]) -> str:
        return self.services.creator_os_recommendation_eligibility(account)

    def _creator_os_restriction_status(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.services.creator_os_restriction_status(account)

    def _creator_os_maturity_score(self, account: dict[str, Any]) -> int:
        return self.services.creator_os_maturity_score(account)

    def _creator_os_warming_stage(self, account: dict[str, Any], *, maturity_score: int) -> str:
        return self.services.creator_os_warming_stage(account, maturity_score=maturity_score)

    def _creator_os_creative_risk(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.services.creator_os_creative_risk(account)

    def _creator_os_similarity_budget(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.services.creator_os_similarity_budget(account)

    def _creator_os_account_tier_from_health(self, account: dict[str, Any], *, trust_state: str, maturity_score: int) -> str:
        return self.services.creator_os_account_tier_from_health(account, trust_state=trust_state, maturity_score=maturity_score)

    def _creator_os_cadence_overrides(self, account: dict[str, Any], *, warming_stage: str, maturity_score: int) -> dict[str, Any]:
        return self.services.creator_os_cadence_overrides(account, warming_stage=warming_stage, maturity_score=maturity_score)

    def _creator_os_account_over_cadence(self, account: dict[str, Any], guidance: dict[str, Any]) -> bool:
        return self.services.creator_os_account_over_cadence(account, guidance)

    def _creator_os_account_tier(self, account: dict[str, Any], *, state: str, blocked_reason: str) -> str:
        return self.services.creator_os_account_tier(account, state=state, blocked_reason=blocked_reason)

    def _creator_os_numeric(self, value: Any) -> float:
        return self.services.creator_os_numeric(value)

    def _creator_os_tier_posting_guidance(self, tier: str) -> dict[str, Any]:
        return self.services.creator_os_tier_posting_guidance(tier)

    def _creator_os_winner_recommendations(
        self,
        *,
        creator: str,
        inventory_shortfall: int,
        variant_available: int,
        winner_expansion_report: dict[str, Any] | None,
        winner_expansion_plan: dict[str, Any] | None,
        variant_metrics_rollup: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return self.services.creator_os_winner_recommendations(
            creator=creator,
            inventory_shortfall=inventory_shortfall,
            variant_available=variant_available,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_metrics_rollup=variant_metrics_rollup,
        )

    def _creator_os_winner_action(self, value: Any) -> str:
        return self.services.creator_os_winner_action(value)

    def _creator_os_best_rollup_family(self, variant_metrics_rollup: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.creator_os_best_rollup_family(variant_metrics_rollup)

    def _creator_os_recommended_inventory(self, *, creator: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.services.creator_os_recommended_inventory(creator=creator, limit=limit)

    def _creator_os_lineage_posting_window(self, pattern: dict[str, Any]) -> str:
        return self.services.creator_os_lineage_posting_window(pattern)

    def recommended_inventory_request_plan(
        self,
        *,
        creator: str,
        target_count: int | None = None,
        daily_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.recommended_inventory_request_plan(
            creator=creator,
            target_count=target_count,
            daily_plan=daily_plan,
            variant_inventory_plan=variant_inventory_plan,
        )

    def _recommended_inventory_creator_row(self, daily_plan: dict[str, Any], creator: str) -> dict[str, Any]:
        return self.services.recommended_inventory_creator_row(daily_plan, creator)

    def _recommended_inventory_existing_by_parent(self, variant_inventory_plan: dict[str, Any] | None) -> dict[str, int]:
        return self.services.recommended_inventory_existing_by_parent(variant_inventory_plan)

    def _recommended_inventory_variant_batch(self, parent_asset_id: str, variant_inventory_plan: dict[str, Any]) -> dict[str, Any]:
        return self.services.recommended_inventory_variant_batch(parent_asset_id, variant_inventory_plan)

    def _recommended_inventory_action(self, *, surface: str, story_intent: Any = None) -> str:
        return self.services.recommended_inventory_action(surface=surface, story_intent=story_intent)

    def _creator_os_manager_decision(
        self,
        *,
        safe_accounts: int,
        needs_posts: int,
        validated_available: int,
        shortfall: int,
        missed_dispatches: list[dict[str, Any]],
        winner_recommendations: list[dict[str, Any]],
    ) -> dict[str, str]:
        if missed_dispatches:
            return {
                "managerDecision": "blocked",
                "managerReason": "missed_dispatches_must_be_resolved_before_new_scheduling",
            }
        if needs_posts and safe_accounts <= 0:
            return {
                "managerDecision": "blocked",
                "managerReason": "no_safe_accounts_available",
            }
        if needs_posts and shortfall <= 0 and validated_available >= needs_posts:
            return {
                "managerDecision": "ready_to_schedule",
                "managerReason": "enough_validated_drafts_and_safe_accounts_exist",
            }
        if shortfall > 0 and winner_recommendations:
            return {
                "managerDecision": "needs_variants",
                "managerReason": "validated_draft_inventory_short_and_winner_family_can_expand",
            }
        if shortfall > 0:
            return {
                "managerDecision": "needs_reel_factory_inventory",
                "managerReason": "validated_draft_inventory_short_and_no_winner_expansion_available",
            }
        return {
            "managerDecision": "ready_to_schedule" if needs_posts else "blocked",
            "managerReason": "no_accounts_need_posts_today" if not needs_posts else "ready",
        }

    def _creator_os_blocked_reason(self, account: dict[str, Any], missed: list[dict[str, Any]]) -> str:
        return self.services.creator_os_blocked_reason(account, missed)

    def _creator_os_account_state(self, account: dict[str, Any], blocked_reason: str) -> str:
        if blocked_reason:
            return "blocked"
        raw = str(account.get("accountState") or account.get("state") or "").strip().lower()
        if raw in {"warming", "resting", "high-performing", "blocked"}:
            return raw
        bucket = str(account.get("bucket") or "").strip().lower()
        if bucket == "blocked_recent_failure":
            return "resting"
        if bucket.startswith("blocked_"):
            return "blocked"
        if bucket in {"safe_to_schedule_today", "already_scheduled_today"}:
            return "safe"
        if account.get("safeToSchedule") is False and not account.get("nextScheduledPost"):
            return "blocked"
        return "safe"

    def _creator_os_post_time(self, value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        return str(value.get("scheduledFor") or value.get("scheduled_for") or value.get("publishedAt") or value.get("published_at") or "")

    def _creator_os_recommended_post_count(self, state: str, needs_post_today: bool) -> int:
        if not needs_post_today:
            return 0
        if state == "high-performing":
            return 2
        if state in {"safe", "warming"}:
            return 1
        return 0

    def winner_expansion_plan(
        self,
        *,
        creator: str | None = None,
        parent_asset_id: str,
        target_variants: int = 10,
        preset: str = "caption_safe_v2",
    ) -> dict[str, Any]:
        return self.services.winner_expansion_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            target_variants=target_variants,
            preset=preset,
        )

    def variant_inventory_plan(
        self,
        *,
        creator: str,
        campaign: str,
        target_draft_shortfall: int,
        preset: str = "caption_safe_v2",
        max_variants_per_parent: int = 10,
        minimum_recommended_per_parent: int = 3,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.services.variant_inventory_plan(
            creator=creator,
            campaign=campaign,
            target_draft_shortfall=target_draft_shortfall,
            preset=preset,
            max_variants_per_parent=max_variants_per_parent,
            minimum_recommended_per_parent=minimum_recommended_per_parent,
            dry_run=dry_run,
        )

    def winner_expansion_report(
        self,
        campaign_slug: str,
        *,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.services.winner_expansion_report(
            campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.services.winner_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def concept_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.services.concept_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_patterns(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.services.winner_patterns(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.services.winner_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def _winner_memory_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        return self.services.winner_memory_rows(creator=creator, campaign_slug=campaign_slug)

    def _winner_memory_item(
        self,
        row: dict[str, Any],
        *,
        min_views: int,
        min_reach: int,
        min_followers: int,
    ) -> dict[str, Any] | None:
        return self.services.winner_memory_item(
            row,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def _winner_concept_name(self, row: dict[str, Any]) -> str:
        return self.services.winner_concept_name(row)

    def _posting_window_label(self, published_at: Any) -> str:
        return self.services.posting_window_label(published_at)

    def _winner_pattern_group(
        self,
        items: list[dict[str, Any]],
        *,
        key_field: str,
        label_field: str | None,
        output_key: str,
        output_label: str | None,
    ) -> list[dict[str, Any]]:
        return self.services.winner_pattern_group(
            items,
            key_field=key_field,
            label_field=label_field,
            output_key=output_key,
            output_label=output_label,
        )

    def creative_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_knowledge_base.v1",
            "creator": built["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": built["sampleSize"],
            "minimumSampleSize": built["minimumSampleSize"],
            "insufficientData": built["insufficientData"],
            "reason": built["reason"],
            "scoreFormula": "views*0.35 + reach*0.25 + saves*4 + shares*5 + followers*10",
            "scoreWeights": self._creative_knowledge_score_weights(),
            "metricsContract": {
                "revenueExcluded": True,
                "visibleMetricFields": ["views", "reach", "likes", "comments", "shares", "saves", "followers", "profile_visits"],
                "optionalStoryMetricFields": ["exits", "replies", "taps_forward", "taps_back"],
            },
            "topConcepts": built["topConcepts"],
            "topCaptionAngles": built["topCaptionAngles"],
            "topCaptionVersions": built["topCaptionVersions"],
            "topAudioIds": built["topAudioIds"],
            "topSurfaces": built["topSurfaces"],
            "topStoryIntents": built["topStoryIntents"],
            "topAccountTiers": built["topAccountTiers"],
            "topPostingWindows": built["topPostingWindows"],
            "wouldWrite": False,
        }

    def _build_creative_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        rows = self._creative_knowledge_rows(creator=creator_label, campaign_slug=campaign_slug)
        results = [self._creative_knowledge_result(row) for row in rows]
        minimum = max(1, int(minimum_sample_size or 1))
        insufficient = len(results) < minimum
        reason = "not_enough_published_metrics" if insufficient else ""
        top_concepts = self._creative_result_group(results, "conceptId", limit=limit)
        top_caption_angles = self._creative_result_group(results, "captionAngle", limit=limit)
        top_caption_versions = self._creative_result_group(results, "captionVersionId", limit=limit)
        top_audio_ids = self._creative_result_group(results, "audioId", limit=limit)
        top_surfaces = self._creative_result_group(results, "contentSurface", limit=limit)
        top_story_intents = self._creative_result_group(results, "storyIntent", limit=limit)
        top_account_tiers = self._creative_result_group(results, "accountTier", limit=limit)
        top_posting_windows = self._creative_result_group(results, "postingWindow", limit=limit)
        if insufficient:
            top_concepts = []
            top_caption_angles = []
            top_caption_versions = []
            top_audio_ids = []
            top_surfaces = []
            top_story_intents = []
            top_account_tiers = []
            top_posting_windows = []
        return {
            "creator": creator_label,
            "rows": rows,
            "results": results,
            "sampleSize": len(results),
            "minimumSampleSize": minimum,
            "insufficientData": insufficient,
            "reason": reason,
            "topConcepts": top_concepts,
            "topCaptionAngles": top_caption_angles,
            "topCaptionVersions": top_caption_versions,
            "topAudioIds": top_audio_ids,
            "topSurfaces": top_surfaces,
            "topStoryIntents": top_story_intents,
            "topAccountTiers": top_account_tiers,
            "topPostingWindows": top_posting_windows,
            "wouldWrite": False,
        }

    def tribev2_reel_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.services.tribev2_reel_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )

    def tribev2_reel_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        sort_by: str = "meanAbsActivation",
        bucket: str = "top",
        limit: int = 12,
        contact_sheet: bool = False,
        show_metrics: bool | None = None,
        show_tribe_score: bool = True,
        blind_mode: bool = False,
    ) -> dict[str, Any]:
        return self.services.tribev2_reel_review(
            creator=creator,
            campaign_slug=campaign_slug,
            sort_by=sort_by,
            bucket=bucket,
            limit=limit,
            contact_sheet=contact_sheet,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
            blind_mode=blind_mode,
        )

    def _tribev2_review_both_bucket(self, ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self.services.tribev2_review_both_bucket(ranked, limit)

    def _tribev2_review_item(
        self,
        row: dict[str, Any],
        *,
        rank: int,
        sort_field: str,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> dict[str, Any]:
        return self.services.tribev2_review_item(
            row,
            rank=rank,
            sort_field=sort_field,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def tribev2_holdout_pilot_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
        contact_sheet: bool = False,
    ) -> dict[str, Any]:
        return self.services.tribev2_holdout_pilot_review(
            creator=creator,
            campaign_slug=campaign_slug,
            limit=limit,
            contact_sheet=contact_sheet,
        )

    def _tribev2_holdout_bucket_rows(self, ranked: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return self.services.tribev2_holdout_bucket_rows(ranked)

    def _tribev2_holdout_bucket_summary(self, name: str, rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
        return self.services.tribev2_holdout_bucket_summary(name, rows, limit=limit)

    def _tribev2_average_metrics(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return self.services.tribev2_average_metrics(rows)

    def _tribev2_average_scores(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return self.services.tribev2_average_scores(rows)

    def _average_row_field(self, rows: list[dict[str, Any]], field: str) -> float:
        return self.services.average_row_field(rows, field)

    def _tribev2_preview_path(self, row: dict[str, Any]) -> str:
        return self.services.tribev2_preview_path(row)

    def _write_tribev2_review_contact_sheet(
        self,
        items: list[dict[str, Any]],
        *,
        creator: str,
        title: str = "TRIBE v2 Review",
        blind_mode: bool = False,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> str:
        return self.services.write_tribev2_review_contact_sheet(
            items,
            creator=creator,
            title=title,
            blind_mode=blind_mode,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def _write_tribev2_holdout_contact_sheet(self, buckets: dict[str, Any], *, creator: str) -> str:
        return self.services.write_tribev2_holdout_contact_sheet(buckets, creator=creator)

    def _tribev2_contact_sheet_cards(
        self,
        items: list[dict[str, Any]],
        root: Path,
        *,
        show_metrics: bool,
        show_tribe_score: bool,
    ) -> list[str]:
        return self.services.tribev2_contact_sheet_cards(
            items,
            root,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def _tribev2_contact_sheet_html(self, *, title: str, body: str) -> str:
        return self.services.tribev2_contact_sheet_html(title=title, body=body)

    def _tribev2_extract_thumbnail(self, preview_path: str, output_dir: Path, item: dict[str, Any]) -> str:
        return self.services.tribev2_extract_thumbnail(preview_path, output_dir, item)

    def _tribev2_reel_analysis_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        return self.services.tribev2_reel_analysis_rows(creator=creator, campaign_slug=campaign_slug)

    def _tribev2_score_for_snapshot(self, row: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.tribev2_score_for_snapshot(row)

    def _pearson_correlation(self, xs: list[float], ys: list[float]) -> float | None:
        return self.services.pearson_correlation(xs, ys)

    def _tribev2_bucket_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.tribev2_bucket_summary(rows)

    def _tribev2_bucket_lift(self, top: dict[str, Any], bottom: dict[str, Any]) -> dict[str, Any]:
        return self.services.tribev2_bucket_lift(top, bottom)

    def _tribev2_metric_quality(self, rows: list[dict[str, Any]], metric_fields: list[str]) -> dict[str, Any]:
        return self.services.tribev2_metric_quality(rows, metric_fields)

    def _tribev2_signal_summary(
        self,
        correlations: dict[str, dict[str, float | None]],
        *,
        sample_size: int,
        metric_quality: dict[str, Any],
    ) -> dict[str, Any]:
        return self.services.tribev2_signal_summary(
            correlations,
            sample_size=sample_size,
            metric_quality=metric_quality,
        )

    def _tribev2_confidence_level(self, sample_size: int, statistically_interesting: bool) -> str:
        return self.services.tribev2_confidence_level(sample_size, statistically_interesting)

    def creative_pattern_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        return {
            "schema": "campaign_factory.creative_pattern_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "concepts": kb.get("topConcepts") or [],
            "captionAngles": kb.get("topCaptionAngles") or [],
            "postingWindows": kb.get("topPostingWindows") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_caption_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        rows = [] if kb["insufficientData"] else [
            self._creative_result_group(self._creative_knowledge_results_for_report(kb, creator, campaign_slug), "captionHash", limit=limit),
            self._creative_result_group(self._creative_knowledge_results_for_report(kb, creator, campaign_slug), "instagramPostCaptionHash", limit=limit),
        ]
        caption_hashes = rows[0] if rows else []
        instagram_post_caption_hashes = rows[1] if len(rows) > 1 else []
        return {
            "schema": "campaign_factory.creative_caption_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "captionAngles": kb.get("topCaptionAngles") or [],
            "captionVersions": kb.get("topCaptionVersions") or [],
            "captionHashes": caption_hashes,
            "instagramPostCaptionHashes": instagram_post_caption_hashes,
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_audio_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        return {
            "schema": "campaign_factory.creative_audio_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "audioIds": kb.get("topAudioIds") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_surface_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        return {
            "schema": "campaign_factory.creative_surface_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "surfaces": kb.get("topSurfaces") or [],
            "storyIntents": kb.get("topStoryIntents") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_account_tier_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        return {
            "schema": "campaign_factory.creative_account_tier_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "accountTiers": kb.get("topAccountTiers") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_window_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        kb = self.creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=minimum_sample_size, limit=limit)
        return {
            "schema": "campaign_factory.creative_window_report.v1",
            "creator": kb["creator"],
            "campaign": kb.get("campaign"),
            "generatedAt": kb["generatedAt"],
            "insufficientData": kb["insufficientData"],
            "reason": kb.get("reason", ""),
            "postingWindows": kb.get("topPostingWindows") or [],
            "scoreWeights": kb.get("scoreWeights") or {},
            "wouldWrite": False,
        }

    def creative_performance_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.creative_performance_analysis.v1",
            "creator": analysis["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": analysis["sampleSize"],
            "minimumSampleSize": analysis["minimumSampleSize"],
            "confidence": analysis["confidence"],
            "creatorBaseline": analysis["creatorBaseline"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "bestPerformingPatterns": analysis["bestPerformingPatterns"],
            "underperformingPatterns": analysis["underperformingPatterns"],
            "recommendedMoreOf": analysis["recommendedMoreOf"],
            "recommendedLessOf": analysis["recommendedLessOf"],
            "surfacesAnalyzed": ["reel", "story", "feed_single", "feed_carousel"],
            "wouldWrite": False,
        }

    def creator_learning_summary(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        summary: list[str] = []
        if analysis["insufficientData"]:
            summary.append("Not enough published Instagram-visible metrics yet to identify reliable creative patterns.")
        else:
            for item in analysis["bestPerformingPatterns"][:3]:
                label = self._creative_dimension_label(str(item.get("dimension") or ""))
                summary.append(f"{item.get('key')} {label} is performing above the creator baseline.")
            if analysis["underperformingPatterns"]:
                weak = analysis["underperformingPatterns"][0]
                label = self._creative_dimension_label(str(weak.get("dimension") or ""))
                summary.append(f"{weak.get('key')} {label} is below the creator baseline and should be reworked or used carefully.")
        return {
            "schema": "campaign_factory.creator_learning_summary.v1",
            "creator": analysis["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "summary": summary,
            "recommendations": analysis.get("recommendedMoreOf") or [],
            "confidence": analysis["confidence"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "wouldWrite": False,
        }

    def next_content_recommendations(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        return {
            "schema": "campaign_factory.next_content_recommendations.v1",
            "creator": analysis["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "recommendations": analysis["recommendedMoreOf"],
            "confidence": analysis["confidence"],
            "insufficientData": analysis["insufficientData"],
            "reason": analysis["reason"],
            "wouldWrite": False,
        }

    def _build_creative_performance_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 10,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=max(limit, 25),
        )
        results = list(built.get("results") or [])
        minimum = max(1, int(minimum_sample_size or 1))
        baseline = self._creative_performance_baseline(results)
        insufficient = len(results) < minimum
        reason = "not_enough_published_metrics" if insufficient else ""
        best: list[dict[str, Any]] = []
        weak: list[dict[str, Any]] = []
        if not insufficient:
            for dimension, key_field in [
                ("concept", "conceptId"),
                ("contentSurface", "contentSurface"),
                ("captionAngle", "captionAngle"),
                ("audioId", "audioId"),
                ("storyIntent", "storyIntent"),
                ("storyStyle", "storyStyle"),
                ("accountTier", "accountTier"),
                ("postingWindow", "postingWindow"),
            ]:
                for group in self._creative_result_group(results, key_field, limit=max(limit, 25)):
                    assessment = self._creative_performance_assessment(group, baseline, dimension=dimension)
                    if assessment["comparison"] == "above_creator_baseline":
                        best.append(assessment)
                    elif assessment["comparison"] == "below_creator_baseline":
                        weak.append(assessment)
        best = sorted(best, key=lambda item: (self._creative_pattern_priority(str(item.get("dimension") or "")), -float(item.get("scoreLiftPct") or 0), -float(item.get("score") or 0), str(item.get("key") or "")))[: max(1, int(limit or 10))]
        weak = sorted(weak, key=lambda item: (self._creative_pattern_priority(str(item.get("dimension") or "")), float(item.get("scoreLiftPct") or 0), float(item.get("score") or 0), str(item.get("key") or "")))[: max(1, int(limit or 10))]
        confidence = self._creative_analysis_confidence(len(results))
        return {
            "creator": built["creator"],
            "sampleSize": len(results),
            "minimumSampleSize": minimum,
            "confidence": confidence,
            "creatorBaseline": baseline,
            "insufficientData": insufficient,
            "reason": reason,
            "bestPerformingPatterns": [] if insufficient else best,
            "underperformingPatterns": [] if insufficient else weak,
            "recommendedMoreOf": [] if insufficient else self._creative_more_recommendations(best, confidence, limit=limit),
            "recommendedLessOf": [] if insufficient else self._creative_less_recommendations(weak, confidence, limit=limit),
            "wouldWrite": False,
        }

    def _creative_performance_baseline(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(results)
        totals = {
            "views": sum(int((item.get("metrics") or {}).get("views") or 0) for item in results),
            "reach": sum(int((item.get("metrics") or {}).get("reach") or 0) for item in results),
            "saves": sum(int((item.get("metrics") or {}).get("saves") or 0) for item in results),
            "shares": sum(int((item.get("metrics") or {}).get("shares") or 0) for item in results),
            "followers": sum(int((item.get("metrics") or {}).get("followers") or 0) for item in results),
        }
        averages = {key: (value / count if count else 0) for key, value in totals.items()}
        return {
            "postCount": count,
            "avgViews": round(averages["views"], 2),
            "avgReach": round(averages["reach"], 2),
            "avgSaves": round(averages["saves"], 2),
            "avgShares": round(averages["shares"], 2),
            "avgFollowers": round(averages["followers"], 2),
            "score": self._creative_knowledge_score(averages),
        }

    def _creative_performance_assessment(self, group: dict[str, Any], baseline: dict[str, Any], *, dimension: str) -> dict[str, Any]:
        base_score = float(baseline.get("score") or 0)
        score = float(group.get("score") or 0)
        lift_pct = ((score - base_score) / base_score * 100.0) if base_score > 0 else (100.0 if score > 0 else 0.0)
        if lift_pct >= 15.0:
            comparison = "above_creator_baseline"
            reason = f"{group.get('key')} is {round(lift_pct, 1)}% above creator baseline using Instagram-visible metrics."
        elif lift_pct <= -15.0:
            comparison = "below_creator_baseline"
            reason = f"{group.get('key')} is {abs(round(lift_pct, 1))}% below creator baseline using Instagram-visible metrics."
        else:
            comparison = "near_creator_baseline"
            reason = f"{group.get('key')} is near creator baseline using Instagram-visible metrics."
        return {
            **group,
            "dimension": dimension,
            "comparison": comparison,
            "sampleSize": int(group.get("sampleSize") or 0),
            "baselineMetric": "score",
            "observedMetric": "score",
            "baselineValue": round(base_score, 2),
            "observedValue": round(score, 2),
            "scoreLiftPct": round(lift_pct, 2),
            "reason": reason,
        }

    def _creative_more_recommendations(self, best: list[dict[str, Any]], confidence: str, *, limit: int = 10) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for item in best:
            lineage = item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
            surface = self._surface_from_pattern(item, lineage)
            recommendation = "make_more_variants" if surface == "reel" else "make_more_similar_assets"
            if surface == "story" and item.get("dimension") == "storyIntent" and item.get("key") == "snapchat_promo":
                recommendation = "make_more_snapchat_promo_stories"
            payload = {
                "surface": surface,
                "recommendation": recommendation,
                "reason": item.get("reason") or "Pattern outperformed creator baseline.",
                "parentAssetId": self._first_lineage_value(lineage, "parentAssetIds"),
                "captionAngle": item.get("key") if item.get("dimension") == "captionAngle" else self._first_lineage_value(lineage, "captionAngles", fallback=""),
                "audioId": item.get("key") if item.get("dimension") == "audioId" else self._first_lineage_value(lineage, "audioIds"),
                "storyIntent": item.get("key") if item.get("dimension") == "storyIntent" else "",
                "confidence": confidence,
                "sampleSize": int(item.get("sampleSize") or 0),
                "baselineMetric": item.get("baselineMetric") or "score",
                "observedMetric": item.get("observedMetric") or "score",
                "scoreLiftPct": item.get("scoreLiftPct") or 0,
            }
            payload["explainability"] = self._recommendation_explainability(payload, item=item, confidence=confidence)
            recommendations.append(payload)
        recommendations = sorted(
            recommendations,
            key=lambda item: (
                0 if item.get("recommendation") == "make_more_snapchat_promo_stories" else 1,
                0 if item.get("recommendation") == "make_more_variants" else 1,
                str(item.get("surface") or ""),
            ),
        )
        return recommendations[: max(1, int(limit or 10))]

    def _creative_less_recommendations(self, weak: list[dict[str, Any]], confidence: str, *, limit: int = 10) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for item in weak:
            lineage = item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
            payload = {
                "surface": self._surface_from_pattern(item, lineage),
                "recommendation": "avoid_or_rework_pattern",
                "reason": item.get("reason") or "Pattern underperformed creator baseline.",
                "patternDimension": item.get("dimension") or "",
                "patternKey": item.get("key") or "",
                "confidence": confidence,
                "sampleSize": int(item.get("sampleSize") or 0),
                "baselineMetric": item.get("baselineMetric") or "score",
                "observedMetric": item.get("observedMetric") or "score",
                "scoreLiftPct": item.get("scoreLiftPct") or 0,
            }
            payload["explainability"] = self._recommendation_explainability(payload, item=item, confidence=confidence)
            recommendations.append(payload)
        return recommendations[: max(1, int(limit or 10))]

    def creative_learning_confidence_model(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=1,
            limit=100,
        )
        results = list(built.get("results") or [])
        classification = self._learning_confidence_classification(results)
        return {
            "schema": "campaign_factory.creative_learning_confidence_model.v1",
            "creator": built["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "sampleSize": len(results),
            "minimumSampleSize": max(1, int(minimum_sample_size or 1)),
            "confidenceModel": {
                "lowConfidenceSignals": ["small_sample_size", "new_surface", "new_concept", "new_caption_angle", "single_account_evidence"],
                "mediumConfidenceSignals": ["ten_or_more_posts", "repeated_pattern", "multiple_surface_or_account_evidence"],
                "highConfidenceSignals": ["fifty_or_more_posts", "repeated_wins", "consistent_metrics", "multiple_accounts", "multiple_posts"],
                "scoringRule": "simple measured coverage only; no ML and no predictions",
            },
            "currentConfidence": classification,
            "wouldWrite": False,
        }

    def creative_fatigue_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=1, limit=100)
        results = list(built.get("results") or [])
        signals: list[dict[str, Any]] = []
        for fatigue_type, field in [
            ("concept_fatigue", "conceptId"),
            ("caption_fatigue", "captionAngle"),
            ("audio_fatigue", "audioId"),
            ("posting_window_fatigue", "postingWindow"),
        ]:
            signals.extend(self._creative_fatigue_signals(results, field=field, fatigue_type=fatigue_type))
        signals = sorted(signals, key=lambda item: (float(item.get("reachDeclinePct") or 0), str(item.get("key") or "")))[: max(1, int(limit or 20))]
        return {
            "schema": "campaign_factory.creative_fatigue_report.v1",
            "creator": built["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "fatigueSignals": signals,
            "signalRules": ["reach_decline", "impression_decline", "engagement_decline"],
            "wouldWrite": False,
        }

    def creative_surface_comparison_report(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        built = self._build_creative_knowledge_base(creator=creator, campaign_slug=campaign_slug, minimum_sample_size=1, limit=100)
        results = list(built.get("results") or [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            concept_id = str(item.get("conceptId") or "").strip()
            if concept_id:
                grouped.setdefault(concept_id, []).append(item)
        concepts: list[dict[str, Any]] = []
        for concept_id, items in grouped.items():
            surfaces = self._creative_surface_rows(items)
            concepts.append({
                "conceptId": concept_id,
                "sampleSize": len(items),
                "surfaces": surfaces,
                "bestSurface": surfaces[0]["surface"] if surfaces else "",
                "wouldWrite": False,
            })
        concepts = sorted(concepts, key=lambda item: (-int(item.get("sampleSize") or 0), str(item.get("conceptId") or "")))[: max(1, int(limit or 20))]
        return {
            "schema": "campaign_factory.creative_surface_comparison_report.v1",
            "creator": built["creator"],
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "concepts": concepts,
            "wouldWrite": False,
        }

    def recommendation_quality_audit(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 20,
    ) -> dict[str, Any]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )
        recommendations = list(analysis.get("recommendedMoreOf") or []) + list(analysis.get("recommendedLessOf") or [])
        rows = []
        buckets = {"high_confidence": 0, "medium_confidence": 0, "low_confidence": 0, "insufficient_data": 0}
        if analysis.get("insufficientData"):
            buckets["insufficient_data"] += 1
        for rec in recommendations:
            explainability = rec.get("explainability") if isinstance(rec.get("explainability"), dict) else self._recommendation_explainability(rec, confidence=analysis.get("confidence"))
            classification = self._recommendation_quality_bucket(explainability)
            buckets[classification] = buckets.get(classification, 0) + 1
            rows.append({
                "recommendation": rec.get("recommendation") or rec.get("recommendedAction") or "",
                "surface": rec.get("surface") or "",
                "reason": explainability.get("reason") or "",
                "classification": classification,
                "explainability": explainability,
                "wouldWrite": False,
            })
        return {
            "schema": "campaign_factory.recommendation_quality_audit.v1",
            "creator": self._creator_label(creator),
            "campaign": slugify(campaign_slug) if campaign_slug else None,
            "generatedAt": utc_now(),
            "recommendationsAudited": len(rows),
            "qualityBuckets": buckets,
            "recommendations": rows,
            "wouldWrite": False,
        }

    def _recommendation_explainability(
        self,
        recommendation: dict[str, Any],
        *,
        item: dict[str, Any] | None = None,
        confidence: Any = None,
    ) -> dict[str, Any]:
        source = item if isinstance(item, dict) else recommendation
        return {
            "reason": str(recommendation.get("reason") or source.get("reason") or ""),
            "confidence": self._confidence_score(confidence if confidence is not None else recommendation.get("confidence")),
            "confidenceLabel": str(confidence if confidence is not None else recommendation.get("confidence") or "low"),
            "sampleSize": int(recommendation.get("sampleSize") or source.get("sampleSize") or 0),
            "baselineMetric": str(recommendation.get("baselineMetric") or source.get("baselineMetric") or "score"),
            "observedMetric": str(recommendation.get("observedMetric") or source.get("observedMetric") or "score"),
            "baselineValue": round(float(source.get("baselineValue") or recommendation.get("baselineValue") or 0), 2),
            "observedValue": round(float(source.get("observedValue") or recommendation.get("observedValue") or source.get("score") or 0), 2),
            "scoreLiftPct": round(float(recommendation.get("scoreLiftPct") or source.get("scoreLiftPct") or 0), 2),
        }

    def _confidence_score(self, confidence: Any) -> int:
        if isinstance(confidence, (int, float)):
            return max(0, min(100, int(confidence)))
        return {"high": 90, "medium": 65, "low": 35}.get(str(confidence or "low"), 35)

    def _learning_confidence_classification(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        sample_size = len(results)
        account_count = len({str(item.get("accountId") or "") for item in results if item.get("accountId")})
        surface_count = len({str(item.get("contentSurface") or "") for item in results if item.get("contentSurface")})
        concept_count = len({str(item.get("conceptId") or "") for item in results if item.get("conceptId")})
        caption_angle_count = len({str(item.get("captionAngle") or "") for item in results if item.get("captionAngle")})
        signals: list[str] = []
        if sample_size < 10:
            signals.append("small_sample_size")
        if surface_count <= 1:
            signals.append("new_surface_or_single_surface")
        if concept_count <= 1:
            signals.append("new_concept_or_single_concept")
        if caption_angle_count <= 1:
            signals.append("new_caption_angle_or_single_angle")
        if account_count <= 1:
            signals.append("single_account_evidence")
        if sample_size >= 50 and account_count >= 3:
            classification = "high_confidence"
            score = 90
        elif sample_size >= 10 and account_count >= 2:
            classification = "medium_confidence"
            score = 65
        else:
            classification = "low_confidence"
            score = 35
        return {
            "classification": classification,
            "confidence": score,
            "sampleSize": sample_size,
            "accountCount": account_count,
            "surfaceCount": surface_count,
            "conceptCount": concept_count,
            "captionAngleCount": caption_angle_count,
            "limitingSignals": signals,
        }

    def _creative_fatigue_signals(self, results: list[dict[str, Any]], *, field: str, fatigue_type: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            key = str(item.get(field) or "").strip()
            if key:
                grouped.setdefault(key, []).append(item)
        signals: list[dict[str, Any]] = []
        for key, items in grouped.items():
            if len(items) < 3:
                continue
            ordered = sorted(items, key=lambda item: str(item.get("publishedAt") or ""))
            midpoint = max(1, len(ordered) // 2)
            early = ordered[:midpoint]
            recent = ordered[midpoint:]
            if not recent:
                continue
            reach_decline = self._metric_decline_pct(early, recent, "reach")
            view_decline = self._metric_decline_pct(early, recent, "views")
            engagement_decline = self._engagement_decline_pct(early, recent)
            if min(reach_decline, view_decline, engagement_decline) <= -20:
                signals.append({
                    "fatigueType": fatigue_type,
                    "key": key,
                    "sampleSize": len(items),
                    "reachDeclinePct": reach_decline,
                    "impressionDeclinePct": view_decline,
                    "engagementDeclinePct": engagement_decline,
                    "reason": f"{key} shows measured decline across recent posts.",
                    "wouldWrite": False,
                })
        return signals

    def _metric_decline_pct(self, early: list[dict[str, Any]], recent: list[dict[str, Any]], metric: str) -> float:
        early_avg = self._avg_result_metric(early, metric)
        recent_avg = self._avg_result_metric(recent, metric)
        if early_avg <= 0:
            return 0.0
        return round((recent_avg - early_avg) / early_avg * 100.0, 2)

    def _engagement_decline_pct(self, early: list[dict[str, Any]], recent: list[dict[str, Any]]) -> float:
        def engagement(items: list[dict[str, Any]]) -> float:
            if not items:
                return 0.0
            total = 0
            for item in items:
                metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                total += int(metrics.get("likes") or 0) + int(metrics.get("comments") or 0) + int(metrics.get("shares") or 0) + int(metrics.get("saves") or 0)
            return total / len(items)
        early_avg = engagement(early)
        recent_avg = engagement(recent)
        if early_avg <= 0:
            return 0.0
        return round((recent_avg - early_avg) / early_avg * 100.0, 2)

    def _avg_result_metric(self, items: list[dict[str, Any]], metric: str) -> float:
        if not items:
            return 0.0
        return sum(int((item.get("metrics") or {}).get(metric) or 0) for item in items) / len(items)

    def _creative_surface_rows(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            surface = normalize_content_surface(item.get("contentSurface") or "reel")
            grouped.setdefault(surface, []).append(item)
        rows = []
        for surface, surface_items in grouped.items():
            metric_totals = {
                "views": self._avg_result_metric(surface_items, "views"),
                "reach": self._avg_result_metric(surface_items, "reach"),
                "saves": self._avg_result_metric(surface_items, "saves"),
                "shares": self._avg_result_metric(surface_items, "shares"),
                "followers": self._avg_result_metric(surface_items, "followers"),
            }
            rows.append({
                "surface": surface,
                "sampleSize": len(surface_items),
                "avgViews": round(metric_totals["views"], 2),
                "avgReach": round(metric_totals["reach"], 2),
                "avgSaves": round(metric_totals["saves"], 2),
                "avgShares": round(metric_totals["shares"], 2),
                "score": self._creative_knowledge_score(metric_totals),
                "sourcePostIds": sorted({str(item.get("postId") or "") for item in surface_items if item.get("postId")}),
            })
        return sorted(rows, key=lambda item: (-float(item.get("score") or 0), str(item.get("surface") or "")))

    def _recommendation_quality_bucket(self, explainability: dict[str, Any]) -> str:
        sample_size = int(explainability.get("sampleSize") or 0)
        confidence = int(explainability.get("confidence") or 0)
        if sample_size <= 0:
            return "insufficient_data"
        if confidence >= 80 and sample_size >= 10:
            return "high_confidence"
        if confidence >= 60 and sample_size >= 3:
            return "medium_confidence"
        return "low_confidence"

    def _surface_from_pattern(self, item: dict[str, Any], lineage: dict[str, Any]) -> str:
        if item.get("dimension") == "contentSurface":
            return str(item.get("key") or "reel")
        surfaces = lineage.get("contentSurfaces") if isinstance(lineage.get("contentSurfaces"), list) else []
        if surfaces:
            return str(surfaces[0] or "reel")
        if item.get("dimension") in {"storyIntent", "storyStyle"}:
            return "story"
        return "reel"

    def _first_lineage_value(self, lineage: dict[str, Any], key: str, *, fallback: str = "") -> str:
        values = lineage.get(key) if isinstance(lineage.get(key), list) else []
        return str(values[0]) if values else fallback

    def _creative_analysis_confidence(self, sample_size: int) -> str:
        if sample_size >= 50:
            return "high"
        if sample_size >= 10:
            return "medium"
        return "low"

    def _creative_dimension_label(self, dimension: str) -> str:
        return {
            "concept": "concept",
            "contentSurface": "surface",
            "captionAngle": "caption angle",
            "audioId": "audio family",
            "storyIntent": "story intent",
            "storyStyle": "story style",
            "accountTier": "account tier",
            "postingWindow": "posting window",
        }.get(dimension, "pattern")

    def _creative_pattern_priority(self, dimension: str) -> int:
        return {
            "concept": 0,
            "storyIntent": 1,
            "captionAngle": 2,
            "audioId": 3,
            "storyStyle": 4,
            "contentSurface": 5,
            "accountTier": 6,
            "postingWindow": 7,
        }.get(dimension, 99)

    def _creative_knowledge_results_for_report(self, kb: dict[str, Any], creator: str, campaign_slug: str | None) -> list[dict[str, Any]]:
        if kb.get("insufficientData"):
            return []
        return [self._creative_knowledge_result(row) for row in self._creative_knowledge_rows(creator=kb["creator"] or self._creator_label(creator), campaign_slug=campaign_slug)]

    def _creative_knowledge_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        clauses = ["p.metrics_eligible = 1"]
        params: list[Any] = []
        if campaign_slug:
            campaign = self.campaign_by_slug(campaign_slug)
            clauses.append("p.campaign_id = ?")
            params.append(campaign["id"])
        clauses.append(
            """
            (
              LOWER(COALESCE(p.creator_mix, '')) = LOWER(?)
              OR LOWER(COALESCE(p.creator_model, '')) = LOWER(?)
              OR LOWER(COALESCE(c.creator, '')) = LOWER(?)
              OR LOWER(COALESCE(m.name, '')) = LOWER(?)
              OR LOWER(COALESCE(m.slug, '')) = LOWER(?)
            )
            """
        )
        params.extend([creator, creator, creator, creator, slugify(creator)])
        rows = self.conn.execute(
            f"""
            SELECT p.*, campaigns.slug AS campaign_slug, campaigns.platform AS campaign_platform,
                   c.metadata_json AS concept_metadata_json, c.creator AS concept_creator,
                   c.parent_asset_id AS concept_parent_asset_id,
                   a.handle AS account_username, a.external_id AS account_external_id,
                   m.slug AS model_slug, m.name AS model_name
            FROM performance_snapshots p
            JOIN campaigns ON campaigns.id = p.campaign_id
            LEFT JOIN concepts c ON c.id = p.concept_id
            LEFT JOIN accounts a ON a.id = p.account_id OR a.external_id = p.instagram_account_id
            LEFT JOIN models m ON m.id = a.model_id
            WHERE {" AND ".join(clauses)}
            ORDER BY p.snapshot_at DESC, p.created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def _creative_knowledge_result(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row.get("raw_json"), {})
        if not isinstance(raw, dict):
            raw = {}
        context = load_context_json(row.get("caption_outcome_context_json"))
        metrics = {
            "views": int(row.get("views") or 0),
            "reach": int(row.get("reach") or 0),
            "likes": int(row.get("likes") or 0),
            "comments": int(row.get("comments") or 0),
            "shares": int(row.get("shares") or 0),
            "saves": int(row.get("saves") or 0),
            "followers": int(raw.get("followers") or raw.get("follows") or 0),
            "profile_visits": int(raw.get("profile_visits") or raw.get("profileVisits") or 0),
            "story_exits": int(raw.get("story_exits") or raw.get("exits") or 0),
            "story_replies": int(raw.get("story_replies") or raw.get("replies") or 0),
            "story_taps": int(raw.get("story_taps") or raw.get("taps") or raw.get("taps_forward") or 0),
        }
        content_surface = normalize_content_surface(row.get("content_surface"))
        published_at = row.get("published_at")
        instagram_hash = (
            context.get("instagram_post_caption_hash")
            or context.get("instagramPostCaptionHash")
            or raw.get("instagram_post_caption_hash")
            or raw.get("instagramPostCaptionHash")
            or ""
        )
        story_intent = (
            context.get("storyIntent")
            or context.get("story_intent")
            or raw.get("story_intent")
            or raw.get("storyIntent")
            or ""
        )
        story_style = (
            context.get("storyStyle")
            or context.get("story_style")
            or raw.get("story_style")
            or raw.get("storyStyle")
            or ""
        )
        story_goal = (
            context.get("storyGoal")
            or context.get("story_goal")
            or raw.get("story_goal")
            or raw.get("storyGoal")
            or ""
        )
        return {
            "creator": self._creator_label(row.get("creator_mix") or row.get("creator_model") or row.get("concept_creator") or row.get("model_name") or row.get("model_slug")),
            "campaign": row.get("campaign_slug") or "",
            "contentSurface": content_surface,
            "igMediaType": raw.get("ig_media_type") or raw.get("igMediaType") or self._ig_media_type_for_surface(content_surface, "video"),
            "accountId": row.get("account_id") or "",
            "accountUsername": row.get("account_username") or raw.get("account_username") or raw.get("accountUsername") or "",
            "accountTier": raw.get("account_tier") or raw.get("accountTier") or "",
            "conceptId": row.get("concept_id") or "",
            "parentAssetId": row.get("concept_parent_asset_id") or row.get("rendered_asset_id") or "",
            "parentReelId": row.get("parent_reel_id") or "",
            "variantFamilyId": row.get("variant_family_id") or "",
            "variantId": row.get("variant_id") or "",
            "captionFamilyId": context.get("caption_family_id") or context.get("captionFamilyId") or "",
            "captionVersionId": context.get("caption_version_id") or context.get("captionVersionId") or "",
            "captionAngle": row.get("caption_angle") or context.get("caption_angle") or context.get("captionAngle") or "",
            "captionHash": row.get("caption_hash") or "",
            "instagramPostCaptionHash": instagram_hash,
            "audioId": row.get("audio_id") or "",
            "storyIntent": str(story_intent or ""),
            "storyStyle": str(story_style or ""),
            "storyGoal": str(story_goal or ""),
            "postingWindow": self._posting_window_label(published_at),
            "publishedAt": published_at,
            "postId": row.get("post_id") or "",
            "metrics": metrics,
            "metricsContract": self._performance_metric_contract(row),
            "score": self._creative_knowledge_score(metrics),
        }

    def _creative_knowledge_score_weights(self) -> dict[str, float]:
        return {"views": 0.35, "reach": 0.25, "saves": 4.0, "shares": 5.0, "followers": 10.0}

    def _creative_knowledge_score(self, metrics: dict[str, Any]) -> float:
        weights = self._creative_knowledge_score_weights()
        score = sum(float(metrics.get(key) or 0) * weight for key, weight in weights.items())
        return round(score, 2)

    def _creative_result_group(self, results: list[dict[str, Any]], key_field: str, *, limit: int = 10) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for result in results:
            key = str(result.get(key_field) or "").strip()
            if not key:
                continue
            entry = grouped.setdefault(key, {"key": key, "items": []})
            entry["items"].append(result)
        output: list[dict[str, Any]] = []
        for key, entry in grouped.items():
            items = entry["items"]
            sample_size = len(items)
            metric_totals = {
                "views": sum(int((item.get("metrics") or {}).get("views") or 0) for item in items),
                "reach": sum(int((item.get("metrics") or {}).get("reach") or 0) for item in items),
                "saves": sum(int((item.get("metrics") or {}).get("saves") or 0) for item in items),
                "shares": sum(int((item.get("metrics") or {}).get("shares") or 0) for item in items),
                "followers": sum(int((item.get("metrics") or {}).get("followers") or 0) for item in items),
            }
            avg_metrics = {name: (value / sample_size if sample_size else 0) for name, value in metric_totals.items()}
            output.append({
                "key": key,
                "sampleSize": sample_size,
                "avgViews": round(avg_metrics["views"], 2),
                "avgReach": round(avg_metrics["reach"], 2),
                "avgSaves": round(avg_metrics["saves"], 2),
                "avgShares": round(avg_metrics["shares"], 2),
                "avgFollowers": round(avg_metrics["followers"], 2),
                "score": self._creative_knowledge_score(avg_metrics),
                "sourcePostIds": sorted({str(item.get("postId") or "") for item in items if item.get("postId")}),
                "lineage": self._creative_result_lineage(items),
            })
        return sorted(
            output,
            key=lambda item: (-float(item.get("score") or 0), -int(item.get("sampleSize") or 0), str(item.get("key") or "")),
        )[: max(1, int(limit or 10))]

    def _creative_result_lineage(self, items: list[dict[str, Any]]) -> dict[str, list[str]]:
        fields = {
            "campaigns": "campaign",
            "accountIds": "accountId",
            "accountUsernames": "accountUsername",
            "conceptIds": "conceptId",
            "parentAssetIds": "parentAssetId",
            "parentReelIds": "parentReelId",
            "variantFamilyIds": "variantFamilyId",
            "variantIds": "variantId",
            "captionFamilyIds": "captionFamilyId",
            "captionVersionIds": "captionVersionId",
            "captionAngles": "captionAngle",
            "captionHashes": "captionHash",
            "instagramPostCaptionHashes": "instagramPostCaptionHash",
            "audioIds": "audioId",
            "contentSurfaces": "contentSurface",
            "postingWindows": "postingWindow",
        }
        return {
            output_key: sorted({str(item.get(field) or "") for item in items if item.get(field)})
            for output_key, field in fields.items()
        }

    def _winner_variant_candidate(self, variant_payload: dict[str, Any], rendered: dict[str, Any]) -> dict[str, Any]:
        return self.services.winner_variant_candidate(variant_payload, rendered)

    def _winner_variant_candidate_decision(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self.services.winner_variant_candidate_decision(candidate)

    def _latest_variant_audit_result(self, variant_asset_id: str) -> dict[str, Any]:
        return self.services.latest_variant_audit_result(variant_asset_id)

    def _contentforge_result_from_operations(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.contentforge_result_from_operations(operations)

    def _operation_family_from_operations(self, operations: list[dict[str, Any]]) -> str | None:
        return self.services.operation_family_from_operations(operations)

    def _score_value(self, value: Any) -> int:
        return self.services.score_value(value)

    def _variant_inventory_primary_blocking_reason(self, failures: list[str]) -> str:
        return self.services.variant_inventory_primary_blocking_reason(failures)

    def _variant_inventory_quality_risk(self, parent_asset_id: str) -> str:
        return self.services.variant_inventory_quality_risk(parent_asset_id)

    def _variant_inventory_winner_rank(
        self,
        *,
        campaign_id: str,
        parent_asset_id: str,
        parent_reel_id: str,
    ) -> dict[str, Any]:
        return self.services.variant_inventory_winner_rank(
            campaign_id=campaign_id,
            parent_asset_id=parent_asset_id,
            parent_reel_id=parent_reel_id,
        )

    def _caption_version_by_id(self, caption_version_id: str | None) -> dict[str, Any] | None:
        return self.services.caption_version_by_id(caption_version_id)

    def _concept_for_parent_asset(self, parent_asset_id: str) -> dict[str, Any] | None:
        return self.services.concept_for_parent_asset(parent_asset_id)

    def _variant_lineage_for_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.services.variant_lineage_for_asset(rendered_asset_id)

    def _concept_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.services.concept_payload(row)

    def _variant_family_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return self.services.variant_family_payload(row)

    def _caption_version_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.services.caption_version_payload(row)

    def _variant_asset_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.services.variant_lineage_asset_payload(row)

    def _variant_usage_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return self.services.variant_usage_payload(row)

    def _variant_rollup_group(self, snapshots: list[dict[str, Any]], key: str, output_key: str) -> list[dict[str, Any]]:
        return self.services.variant_rollup_group(snapshots, key, output_key)

    def audit_report(self, audit_report_id: str) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload.audit_report(self, audit_report_id)

    def prepare_reel_inputs(
        self,
        *,
        campaign_slug: str,
        hooks: list[str | dict[str, Any]],
        recipes: list[str] | None = None,
        caption_color: str | None = None,
        notes: str | None = None,
        force_new: bool = False,
    ) -> dict[str, Any]:
        return self.services.prepare_reel_inputs(
            campaign_slug=campaign_slug,
            hooks=hooks,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes,
            force_new=force_new,
        )

    def _rotate_hooks_for_source(self, hooks: list[str | dict[str, Any]], source_index: int) -> list[str | dict[str, Any]]:
        return self.services.rotate_hooks_for_source(hooks, source_index)

    def _reel_sidecar_hooks(self, hooks: list[str | dict[str, Any]]) -> tuple[list[str | dict[str, Any]], list[dict[str, Any]]]:
        return self.services.reel_sidecar_hooks(hooks)

    def _next_reel_clip_number(self, raw_dir: Path) -> int:
        return self.services.next_reel_clip_number(raw_dir)

    def run_reel_factory(
        self,
        *,
        campaign_slug: str,
        workers: int = 3,
        dry_run: bool = False,
        caption_band: str = "auto",
        caption_color: str = "light",
        caption_style: str = "ig",
        caption_font: str = "Instagram Sans Condensed",
        caption_placement_qc: bool = True,
        phone_finalize: bool = True,
        rerender_all: bool = False,
        max_outputs_per_clip: int | None = None,
    ) -> dict[str, Any]:
        return self.services.run_reel_factory(
            campaign_slug=campaign_slug,
            workers=workers,
            dry_run=dry_run,
            caption_band=caption_band,
            caption_color=caption_color,
            caption_style=caption_style,
            caption_font=caption_font,
            caption_placement_qc=caption_placement_qc,
            phone_finalize=phone_finalize,
            rerender_all=rerender_all,
            max_outputs_per_clip=max_outputs_per_clip,
        )

    def sync_reel_outputs(self, *, campaign_slug: str) -> dict[str, Any]:
        return self.services.sync_reel_outputs(campaign_slug=campaign_slug)

    def _model_slug_for_campaign(self, campaign_id: str) -> str:
        return self.services.model_slug_for_campaign(campaign_id)

    def _ratio_from_filename(self, filename: str) -> str:
        return self.services.ratio_from_filename(filename)

    def _caption_generation_for_clip(self, clip_stem: str) -> dict[str, Any]:
        return self.services.caption_generation_for_clip(clip_stem)

    def _caption_outcome_context_for_reel_output(
        self,
        *,
        clip_stem: str,
        caption_text: str,
        caption_hash: str | None,
        recipe: str,
        source_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        return self.services.caption_outcome_context_for_reel_output(
            clip_stem=clip_stem,
            caption_text=caption_text,
            caption_hash=caption_hash,
            recipe=recipe,
            source_path=source_path,
            rendered_path=rendered_path,
            creator_model=creator_model,
            lineage=lineage,
        )

    def _lineage_first_present(self, lineage: dict[str, Any] | None, key: str) -> Any:
        return self.services.lineage_first_present(lineage, key)

    def _lineage_placement_decision(self, lineage: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.services.lineage_placement_decision(lineage)

    def _caption_lane_from_render_recipe(self, recipe: str | None) -> str:
        return self.services.caption_lane_from_render_recipe(recipe)

    def _audio_intent_from_reference_recommendations(self, payload: dict[str, Any], *, now: str) -> dict[str, Any]:
        return self.services.audio_intent_from_reference_recommendations(payload, now=now)

    def _backfill_synced_reel_output_lineage(
        self,
        *,
        asset: dict[str, Any],
        clip_stem: str,
        caption_text: str,
        recipe: str,
        output_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any] | None = None,
    ) -> bool:
        return self.services.backfill_synced_reel_output_lineage(
            asset=asset,
            clip_stem=clip_stem,
            caption_text=caption_text,
            recipe=recipe,
            output_path=output_path,
            rendered_path=rendered_path,
            creator_model=creator_model,
            lineage=lineage,
        )

    def review_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        decision: str,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        return self.services.review_rendered_asset(
            rendered_asset_id,
            decision=decision,
            notes=notes,
            require_safe_audit=require_safe_audit,
        )

    def approve_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        return self.services.approve_rendered_asset(
            rendered_asset_id,
            notes=notes,
            require_safe_audit=require_safe_audit,
        )

    def make_batch(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        model_slug: str,
        output_format: str = "auto",
        variant_count: int = 20,
        reference_pattern: str | None = "auto",
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        workers: int = 3,
        recipes: list[str] | None = None,
        auto_approve_warning_only: bool = True,
        source_prompt: str | None = None,
        import_notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.make_batch(
            folder=folder,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            output_format=output_format,
            variant_count=variant_count,
            reference_pattern=reference_pattern,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            workers=workers,
            recipes=recipes,
            auto_approve_warning_only=auto_approve_warning_only,
            source_prompt=source_prompt,
            import_notes=import_notes,
        )

    def intake_finished_video(
        self,
        *,
        input_path: Path,
        model_slug: str,
        platform: str = "instagram",
        goal: str = "reach",
        reference_pattern: str | None = "auto",
        campaign_slug: str | None = None,
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        variant_count: int = 10,
        workers: int = 3,
        recipes: list[str] | None = None,
        creative_plan: str | None = None,
        style_lane: str | None = None,
        source_lineage_path: Path | None = None,
    ) -> dict[str, Any]:
        return self.services.intake_finished_video(
            input_path=input_path,
            model_slug=model_slug,
            platform=platform,
            goal=goal,
            reference_pattern=reference_pattern,
            campaign_slug=campaign_slug,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            variant_count=variant_count,
            workers=workers,
            recipes=recipes,
            creative_plan=creative_plan,
            style_lane=style_lane,
            source_lineage_path=source_lineage_path,
        )

    def register_surface_asset(
        self,
        *,
        input_path: Path | list[Path] | tuple[Path, ...],
        surface: str,
        creator: str,
        campaign_slug: str,
        instagram_post_caption: str | None = None,
        target_ratio: str | None = None,
        model_slug: str | None = None,
        operator: str | None = None,
        alt_text: list[str] | None = None,
        story_asset_class: str | None = None,
        story_cta_type: str | None = None,
        story_cta_text: str | None = None,
        story_cta_target_url: str | None = None,
        story_intent: str | None = None,
        story_goal: str | None = None,
        story_style: str | None = None,
        snapchat_username: str | None = None,
        snapchat_display_name: str | None = None,
        snapchat_cta_text: str | None = None,
    ) -> dict[str, Any]:
        return self.services.register_surface_asset(
            input_path=input_path,
            surface=surface,
            creator=creator,
            campaign_slug=campaign_slug,
            instagram_post_caption=instagram_post_caption,
            target_ratio=target_ratio,
            model_slug=model_slug,
            operator=operator,
            alt_text=alt_text,
            story_asset_class=story_asset_class,
            story_cta_type=story_cta_type,
            story_cta_text=story_cta_text,
            story_cta_target_url=story_cta_target_url,
            story_intent=story_intent,
            story_goal=story_goal,
            story_style=story_style,
            snapchat_username=snapchat_username,
            snapchat_display_name=snapchat_display_name,
            snapchat_cta_text=snapchat_cta_text,
        )

    def _surface_registration_components(
        self,
        *,
        input_path: Path | list[Path] | tuple[Path, ...],
        surface: str,
        target_ratio: str | None,
    ) -> list[dict[str, Any]]:
        return self.services.surface_registration_components(
            input_path=input_path,
            surface=surface,
            target_ratio=target_ratio,
        )

    def _surface_registration_component(self, path: Path, *, surface: str, target_ratio: str | None) -> dict[str, Any]:
        return self.services.surface_registration_component(path, surface=surface, target_ratio=target_ratio)

    def _story_source_blockers(self, components: list[dict[str, Any]]) -> list[str]:
        return self.services.story_source_blockers(components)

    def _story_existing_asset_source_blockers(self, asset: dict[str, Any]) -> list[str]:
        return self.services.story_existing_asset_source_blockers(asset)

    def _stage_surface_registration_file(
        self,
        path: Path,
        rendered_dir: Path,
        *,
        content_surface: str,
        content_hash: str,
        component_index: int,
    ) -> Path:
        return self.services.stage_surface_registration_file(
            path,
            rendered_dir,
            content_surface=content_surface,
            content_hash=content_hash,
            component_index=component_index,
        )

    def register_finished_video(
        self,
        *,
        input_path: Path,
        campaign_slug: str,
        model_slug: str,
        caption: str,
        instagram_post_caption: str | None = None,
        caption_hash: str | None = None,
        caption_bank: str | None = None,
        creator_mix: str | None = None,
        creator_model: str | None = None,
        track_id: str | None = None,
        track_name: str | None = None,
        audio_source: str | None = None,
        selected_reason: str | None = None,
        operator: str | None = None,
        approval_reason: str | None = None,
        review_batch: str | None = None,
        caption_placement_policy: str | None = None,
        caption_placement_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.register_finished_video(
            input_path=input_path,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            caption=caption,
            instagram_post_caption=instagram_post_caption,
            caption_hash=caption_hash,
            caption_bank=caption_bank,
            creator_mix=creator_mix,
            creator_model=creator_model,
            track_id=track_id,
            track_name=track_name,
            audio_source=audio_source,
            selected_reason=selected_reason,
            operator=operator,
            approval_reason=approval_reason,
            review_batch=review_batch,
            caption_placement_policy=caption_placement_policy,
            caption_placement_decision=caption_placement_decision,
        )

    def _load_source_lineage(self, source_lineage_path: Path | None) -> dict[str, Any]:
        if not source_lineage_path:
            return {}
        path = Path(source_lineage_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"source lineage not found: {path}")
        payload = json_load(path.read_text(encoding="utf-8"), {})
        if not isinstance(payload, dict):
            raise ValueError(f"source lineage must be a JSON object: {path}")
        self._record_lineage_costs(payload)
        return payload

    def _record_lineage_costs(self, lineage: dict[str, Any]) -> None:
        """Extract AI cost data from imported lineage and record it."""
        try:
            ensure_cost_table(self.conn)
            lineage_hash = hashlib.sha256(
                json.dumps(lineage, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:24]
            # Grok prompt generation costs (from reel_factory lineage)
            usage = lineage.get("usage")
            if isinstance(usage, dict):
                record_ai_cost(
                    self.conn,
                    provider="grok",
                    operation="image_prompt",
                    campaign_id=lineage.get("campaign"),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    metadata={"lineage_schema": lineage.get("schema"), "model": lineage.get("model")},
                    source_event_key=f"lineage:{lineage_hash}:grok:image_prompt",
                )
            # Higgsfield/Kling generation costs (from generation block)
            gen = lineage.get("generation")
            if isinstance(gen, dict):
                tool = gen.get("tool", "")
                if "higgsfield" in tool or "soul" in tool:
                    record_ai_cost(
                        self.conn,
                        provider="higgsfield",
                        operation="soul_grid",
                        campaign_id=lineage.get("campaign"),
                        generations=1,
                        metadata={"tool": tool, "modelProfile": gen.get("modelProfile")},
                        source_event_key=f"lineage:{lineage_hash}:higgsfield:soul_grid",
                    )
                if "kling" in tool:
                    record_ai_cost(
                        self.conn,
                        provider="kling",
                        operation="video_animate",
                        campaign_id=lineage.get("campaign"),
                        generations=1,
                        metadata={"tool": tool, "modelProfile": gen.get("modelProfile")},
                        source_event_key=f"lineage:{lineage_hash}:kling:video_animate",
                    )
        except Exception:
            pass  # Cost tracking is best-effort; never block the import pipeline

    def _finished_video_preflight(self, probe: dict[str, Any]) -> list[dict[str, str]]:
        return self.services.finished_video_preflight(probe)

    def archive_inventory_report(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        creator: str = "Stacey",
        requested_count: int = 25,
        model_slug: str | None = None,
        recent_days: int = 30,
    ) -> dict[str, Any]:
        return self.services.archive_inventory_report(
            folder=folder,
            campaign_slug=campaign_slug,
            creator=creator,
            requested_count=requested_count,
            model_slug=model_slug,
            recent_days=recent_days,
        )

    def _archive_existing_content_duplicate(self, digest: str) -> dict[str, Any] | None:
        return self.services.archive_existing_content_duplicate(digest)

    def _archive_recent_publish_duplicate(self, digest: str, recent_cutoff: datetime) -> dict[str, Any] | None:
        return self.services.archive_recent_publish_duplicate(digest, recent_cutoff)

    def archive_candidate_quality_report(
        self,
        *,
        inventory_report_path: Path,
        requested_count: int = 25,
        exclude_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        return self.services.archive_candidate_quality_report(
            inventory_report_path=inventory_report_path,
            requested_count=requested_count,
            exclude_indices=exclude_indices,
        )

    def _archive_crop_severity(self, probe: dict[str, Any]) -> tuple[str, int, float | None]:
        return self.services.archive_crop_severity(probe)

    def _archive_visual_quality_score(self, probe: dict[str, Any], warnings: list[Any], crop_score: int) -> int:
        return self.services.archive_visual_quality_score(probe, warnings, crop_score)

    def _archive_duplicate_confidence(self, item: dict[str, Any]) -> str:
        return self.services.archive_duplicate_confidence(item)

    def _finished_video_style_lane_format(self, style_lane: str | None) -> str | None:
        return self.services.finished_video_style_lane_format(style_lane)

    def _finished_video_caption_band(self, format_type: str) -> str:
        return self.services.finished_video_caption_band(format_type)

    def _finished_video_caption_font(self, format_type: str) -> str:
        return self.services.finished_video_caption_font(format_type)

    def _classify_finished_video_format(self, path: Path) -> str:
        return self.services.classify_finished_video_format(path)

    def _run_slideshow_pack(
        self,
        *,
        campaign_slug: str,
        variant_count: int,
        title: str,
        cluster_key: str | None = None,
        media_types: set[str] | None = None,
    ) -> dict[str, Any]:
        return self.services.run_slideshow_pack(
            campaign_slug=campaign_slug,
            variant_count=variant_count,
            title=title,
            cluster_key=cluster_key,
            media_types=media_types,
        )

    def _campaign_source_media_summary(self, campaign_id: str) -> dict[str, int]:
        return self.services.campaign_source_media_summary(campaign_id)

    def _formats_for_batch(self, selected_format: str, source_mix: dict[str, int]) -> list[str]:
        return self.services.formats_for_batch(selected_format, source_mix)

    def batch_summary(self, campaign_slug: str) -> dict[str, Any]:
        from . import exports as _exports

        return _exports.batch_summary(self, campaign_slug)

    def daily_production_counters(self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
        from . import exports as _exports

        return _exports.daily_production_counters(self, campaign_slug, dashboard=dashboard)

    def _variant_pack_groups(self, rendered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from . import exports as _exports

        return _exports._variant_pack_groups(self, rendered)

    def export_manifest(self, *, campaign_slug: str) -> dict[str, Any]:
        from . import exports as _exports

        return _exports.export_manifest(self, campaign_slug=campaign_slug)

    def dashboard(self, campaign_slug: str | None = None) -> dict[str, Any]:
        campaigns = self.list_campaigns()
        selected = self.campaign_by_slug(campaign_slug) if campaign_slug else self._default_dashboard_campaign(campaigns)
        if not selected:
            return {"campaigns": [], "campaign": None, "sources": [], "rendered": [], "health": None, "ranking": []}
        rendered = [self._dashboard_rendered_asset(asset) for asset in self.rendered_for_campaign(selected["id"])]
        ranking = self.ranking(selected["slug"])
        audio_workflow = self.audio_workflow_summary(rendered)
        sources = self.assets_for_campaign(selected["id"])
        summary_dashboard = {"campaign": selected, "sources": sources, "rendered": rendered}
        daily_production = self.daily_production_counters(selected["slug"], dashboard=summary_dashboard)
        creative_plan = self.creative_plan_for_campaign(selected["slug"], dashboard=summary_dashboard)
        return {
            "campaigns": campaigns,
            "campaign": selected,
            "sources": sources,
            "rendered": sorted(rendered, key=lambda asset: (ranking["byAsset"].get(asset["id"], {}) or {}).get("score", 0), reverse=True),
            "activity": self.events_for_campaign(selected["slug"], limit=50),
            "jobs": self.jobs_for_campaign(selected["slug"], limit=50),
            "health": self.campaign_health(selected["slug"]),
            "audioWorkflow": audio_workflow,
            "dailyProduction": daily_production,
            "creativePlan": creative_plan,
            "distribution": self.distribution_summary(selected["slug"]),
            "trust": self.trust_summary(selected["slug"]),
            "ranking": ranking["assets"],
        }

    def audio_workflow_summary(self, rendered: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.audio_workflow_summary(rendered)

    def _dashboard_audio_intent_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.dashboard_audio_intent_for_asset(asset)

    def _audio_task_for_dashboard_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        return self.services.audio_task_for_dashboard_intent(intent)

    def distribution_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.distribution_summary(campaign_slug)

    def multi_surface_inventory_audit(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.multi_surface_inventory_audit(creator=creator, campaign_slug=campaign_slug)

    def account_surface_obligations_plan(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.account_surface_obligations_plan(creator=creator, date=date)

    def account_content_needs(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        return self.services.account_content_needs(account_id=account_id, creator=creator, date=date)

    def account_surface_status(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        return self.services.account_surface_status(account_id=account_id, creator=creator, date=date)

    def creator_content_needs(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.creator_content_needs(creator=creator, date=date)

    def surface_gap_report(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.surface_gap_report(creator=creator, date=date)

    def surface_handoff_readiness_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.surface_handoff_readiness_report(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def surface_draft_proof(
        self,
        *,
        creator: str | None = None,
        campaign: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.surface_draft_proof(
            creator=creator,
            campaign=campaign,
            rendered_asset_id=rendered_asset_id,
        )

    def carousel_integrity_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.carousel_integrity_report(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def carousel_child_metrics_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.carousel_child_metrics_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def _carousel_report_assets(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
        rendered_asset_id: str | None,
    ) -> list[dict[str, Any]]:
        return self.services.carousel_report_assets(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def _carousel_integrity_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.carousel_integrity_for_asset(asset)

    def _carousel_component_signature(self, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.carousel_component_signature(components)

    def _carousel_media_item_signature(self, media_items: Any) -> list[dict[str, Any]]:
        return self.services.carousel_media_item_signature(media_items)

    def _carousel_signature_payload(self, signature: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.carousel_signature_payload(signature, extra=extra)

    def _carousel_boundary_result(self, boundary: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.carousel_boundary_result(boundary, before, after)

    def _carousel_meta_child_payload_preview(self, *, asset: dict[str, Any], draft: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.carousel_meta_child_payload_preview(asset=asset, draft=draft, components=components)

    def _build_surface_inventory(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.services.build_surface_inventory(creator=creator, campaign_slug=campaign_slug)

    def _build_surface_status(
        self,
        *,
        creator: str,
        date: str,
    ) -> dict[str, Any]:
        return self.services.build_surface_status(creator=creator, date=date)

    def _build_surface_readiness(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.build_surface_readiness(assets)

    def _surface_report_assets(self, *, creator: str | None = None, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        return self.services.surface_report_assets(creator=creator, campaign_slug=campaign_slug)

    def _requires_operator_visual_review_for_handoff(self, asset: dict[str, Any]) -> bool:
        return self.services.requires_operator_visual_review_for_handoff(asset)

    def _content_trust_status_blockers(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None,
        caption_context: dict[str, Any] | None,
    ) -> tuple[list[str], dict[str, str]]:
        return self.services.content_trust_status_blockers(asset, latest_audit, caption_context)

    def _asset_matches_creator(self, asset: dict[str, Any], creator: str) -> bool:
        return self.services.asset_matches_creator(asset, creator)

    def _surface_handoff_readiness_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.surface_handoff_readiness_for_asset(asset)

    def _surface_draft_payload_for_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.services.surface_draft_payload_for_readiness(readiness)

    def _latest_distribution_plan_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.services.latest_distribution_plan_for_asset(rendered_asset_id)

    def _asset_components(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.services.asset_components(rendered_asset_id)

    def _ig_media_type_for_surface(self, surface: str, media_type: str) -> str:
        return self.services.surface_handoff_ig_media_type_for_surface(surface, media_type)

    def _aspect_ratio_safe(self, ratio: Any, surface: str) -> bool:
        return self.services.surface_handoff_aspect_ratio_safe(ratio, surface)

    def _allows_blank_instagram_post_caption(self, asset: dict[str, Any]) -> bool:
        return self.services.allows_blank_instagram_post_caption(asset)

    def _account_content_requirement_rows(
        self,
        *,
        creator: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.account_content_requirement_rows(creator=creator, account_id=account_id)

    def _account_row_for_requirement_account(self, account_id: str) -> dict[str, Any] | None:
        return self.services.account_row_for_requirement_account(account_id)

    def _content_obligation_for_requirement(self, requirement: dict[str, Any], target_date: datetime.date) -> dict[str, Any]:
        return self.services.content_obligation_for_requirement(requirement, target_date)

    def _required_content_count(self, requirement: dict[str, Any], target_date: datetime.date) -> int:
        return self.services.required_content_count(requirement, target_date)

    def _empty_surface_totals(self) -> dict[str, dict[str, int]]:
        return self.services.empty_surface_totals()

    def _add_obligation_to_totals(self, totals: dict[str, dict[str, int]], obligation: dict[str, Any]) -> None:
        self.services.add_obligation_to_totals(totals, obligation)

    def _requirement_active_on_date(self, requirement: dict[str, Any], target_date: datetime.date) -> bool:
        return self.services.requirement_active_on_date(requirement, target_date)

    def _surface_scheduled_count(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: datetime.date) -> int:
        return self.services.surface_scheduled_count(account_id, instagram_account_id, surface, target_date)

    def _surface_completed_count(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: datetime.date) -> int:
        return self.services.surface_completed_count(account_id, instagram_account_id, surface, target_date)

    def _last_surface_posted_at(
        self,
        *,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        before_date: datetime.date,
    ) -> str | None:
        return self.services.last_surface_posted_at(
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            surface=surface,
            before_date=before_date,
        )

    def _surface_scheduled_for_account(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: datetime.date) -> bool:
        return self.services.surface_scheduled_for_account(account_id, instagram_account_id, surface, target_date)

    def _surface_completed_for_account(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: datetime.date) -> bool:
        return self.services.surface_completed_for_account(account_id, instagram_account_id, surface, target_date)

    def _default_dashboard_campaign(self, campaigns: list[dict[str, Any]]) -> dict[str, Any] | None:
        for campaign in campaigns:
            row = self.conn.execute(
                "SELECT 1 FROM rendered_assets WHERE campaign_id = ? LIMIT 1",
                (campaign["id"],),
            ).fetchone()
            if row:
                return campaign
        return campaigns[0] if campaigns else None

    def campaign_health(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.campaign_health(campaign_slug)

    def _unresolved_failed_jobs(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.campaign_overview.unresolved_failed_jobs(jobs)

    def asset_detail(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.services.asset_detail(rendered_asset_id)

    def assign_asset_account(
        self,
        rendered_asset_id: str,
        *,
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.services.assign_asset_account(
            rendered_asset_id,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_window_start=planned_window_start,
            planned_window_end=planned_window_end,
            notes=notes,
        )

    def assignments_for_asset(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.services.assignments_for_asset(rendered_asset_id)

    def assignments_for_campaign(self, campaign_slug: str) -> list[dict[str, Any]]:
        return self.services.assignments_for_campaign(campaign_slug)

    def recommend_next_batch(
        self,
        campaign_slug: str,
        *,
        count: int = 20,
        account: str | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        return self.services.recommend_next_batch(campaign_slug, count=count, account=account, persist=persist)

    def recommendation_runs(self, campaign_slug: str, *, limit: int = 10) -> dict[str, Any]:
        return self.services.recommendation_runs(campaign_slug, limit=limit)

    def _top_reference_pattern(self) -> dict[str, Any] | None:
        return self.services.top_reference_pattern()

    def _ranked_reference_patterns_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        return self.services.ranked_reference_patterns_for_campaign(campaign_id)

    def _ranked_variation_presets_for_campaign(self, campaign_id: str, *, account: str | None = None) -> list[dict[str, Any]]:
        return self.services.ranked_variation_presets_for_campaign(campaign_id, account=account)

    def _compact_recommendation_rankings(self, rankings: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
        return self.services.compact_recommendation_rankings(rankings, limit=limit)

    def _recommendation_reference_pattern_evidence(
        self,
        rankings: list[dict[str, Any]],
        selected_pattern: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self.services.recommendation_reference_pattern_evidence(rankings, selected_pattern)

    def _recommendation_variation_preset_evidence(
        self,
        rankings: list[dict[str, Any]],
        selected_preset: str | None,
    ) -> dict[str, Any]:
        return self.services.recommendation_variation_preset_evidence(rankings, selected_preset)

    def _latest_recommendation_trust_context(self, campaign_id: str, *, account: str | None) -> dict[str, Any]:
        return self.services.latest_recommendation_trust_context(campaign_id, account=account)

    def _apply_recommendation_trust(
        self,
        *,
        score: int | float,
        confidence: str,
        confidence_reason: str,
        recommendation_trust: dict[str, Any],
    ) -> tuple[int, str, str, list[str]]:
        return self.services.apply_recommendation_trust(score=score, confidence=confidence, confidence_reason=confidence_reason, recommendation_trust=recommendation_trust)

    def _recommendation_item_payload(
        self,
        *,
        campaign: dict[str, Any],
        campaign_graph_id: str | None,
        run_graph_id: str | None,
        rank: int,
        account: str | None,
        candidate: dict[str, Any],
        asset: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
        reference_pattern_graph_id: str | None,
        reference_pattern_rankings: list[dict[str, Any]],
        variation_preset_rankings: list[dict[str, Any]],
        recommendation_trust: dict[str, Any],
        persist: bool,
        run_id: str,
    ) -> dict[str, Any]:
        return self.services.recommendation_item_payload(campaign=campaign, campaign_graph_id=campaign_graph_id, run_graph_id=run_graph_id, rank=rank, account=account, candidate=candidate, asset=asset, reference_pattern=reference_pattern, reference_pattern_graph_id=reference_pattern_graph_id, reference_pattern_rankings=reference_pattern_rankings, variation_preset_rankings=variation_preset_rankings, recommendation_trust=recommendation_trust, persist=persist, run_id=run_id)

    def _reference_only_recommendation_item(
        self,
        *,
        campaign: dict[str, Any],
        campaign_graph_id: str | None,
        run_graph_id: str | None,
        account: str | None,
        reference_pattern: dict[str, Any] | None,
        reference_pattern_graph_id: str | None,
        reference_pattern_rankings: list[dict[str, Any]],
        variation_preset_rankings: list[dict[str, Any]],
        recommendation_trust: dict[str, Any],
        persist: bool,
        run_id: str,
    ) -> dict[str, Any] | None:
        return self.services.reference_only_recommendation_item(campaign=campaign, campaign_graph_id=campaign_graph_id, run_graph_id=run_graph_id, account=account, reference_pattern=reference_pattern, reference_pattern_graph_id=reference_pattern_graph_id, reference_pattern_rankings=reference_pattern_rankings, variation_preset_rankings=variation_preset_rankings, recommendation_trust=recommendation_trust, persist=persist, run_id=run_id)

    def _write_recommendation_graph_edges(
        self,
        *,
        performance_graph_id: str | None,
        recommendation_input_graph_id: str | None,
        run_graph_id: str | None,
        item_graph_id: str | None,
        rendered_graph_id: str | None,
        reference_pattern_graph_id: str | None,
    ) -> None:
        return self.services.write_recommendation_graph_edges(performance_graph_id=performance_graph_id, recommendation_input_graph_id=recommendation_input_graph_id, run_graph_id=run_graph_id, item_graph_id=item_graph_id, rendered_graph_id=rendered_graph_id, reference_pattern_graph_id=reference_pattern_graph_id)

    def _write_audio_recommendation_graph_edges(
        self,
        *,
        recommendation_item_id: str,
        recommendation_graph_id: str | None,
        reference_pattern_graph_id: str | None,
        audio_recommendations: dict[str, Any],
        campaign_id: str | None = None,
    ) -> None:
        return self.services.write_audio_recommendation_graph_edges(recommendation_item_id=recommendation_item_id, recommendation_graph_id=recommendation_graph_id, reference_pattern_graph_id=reference_pattern_graph_id, audio_recommendations=audio_recommendations, campaign_id=campaign_id)

    def _stored_recommendation_item_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.stored_recommendation_item_payload(row)

    def _exceptions_for_recommendation(self, recommendation_item_id: str) -> list[dict[str, Any]]:
        return self.services.exceptions_for_recommendation(recommendation_item_id)

    def recommendation_item(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.services.recommendation_item(recommendation_item_id)

    def accept_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.accept_recommendation_item(recommendation_item_id, operator=operator, notes=notes, admin_override=admin_override, override_reason=override_reason)

    def reject_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        reason: str | None = None,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.reject_recommendation_item(recommendation_item_id, reason=reason, operator=operator, notes=notes, admin_override=admin_override, override_reason=override_reason)

    def link_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        source_asset_id: str | None = None,
        render_job_id: str | None = None,
        rendered_asset_id: str | None = None,
        post_id: str | None = None,
        performance_snapshot_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.link_recommendation_item(recommendation_item_id, source_asset_id=source_asset_id, render_job_id=render_job_id, rendered_asset_id=rendered_asset_id, post_id=post_id, performance_snapshot_id=performance_snapshot_id, evidence=evidence, admin_override=admin_override, override_reason=override_reason)

    def measure_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        performance_snapshot_id: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.measure_recommendation_item(recommendation_item_id, performance_snapshot_id=performance_snapshot_id, admin_override=admin_override, override_reason=override_reason)

    def execute_accepted_recommendation(
        self,
        recommendation_item_id: str,
        *,
        mode: str = DEFAULT_AUTONOMY_LEVEL,
        force: bool = False,
        dry_run_render: bool = False,
        run_audit: bool = True,
        contentforge_base_url: str | None = None,
    ) -> dict[str, Any]:
        return self.services.execute_accepted_recommendation(recommendation_item_id, mode=mode, force=force, dry_run_render=dry_run_render, run_audit=run_audit, contentforge_base_url=contentforge_base_url)

    def _compact_execution_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.services.compact_execution_result(result)

    def _create_trust_exceptions_for_recommendation(
        self,
        row: dict[str, Any],
        asset: dict[str, Any],
        *,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        return self.services.create_trust_exceptions_for_recommendation(row, asset, commit=commit)

    def _asset_has_final_audio_proof(self, asset: dict[str, Any]) -> bool:
        return self.services.asset_has_final_audio_proof(asset)

    def _recommendation_item_row(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.services.recommendation_item_row(recommendation_item_id)

    def _recommendation_item_campaign(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.recommendation_item_campaign(row)

    def _update_recommendation_lifecycle(
        self,
        recommendation_item_id: str,
        *,
        status: str,
        decision: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        baseline: dict[str, Any] | None = None,
        measurement_version: str | None = None,
        timestamp_column: str | None = None,
        event_type: str,
        message: str,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.services.update_recommendation_lifecycle(recommendation_item_id, status=status, decision=decision, outcome=outcome, baseline=baseline, measurement_version=measurement_version, timestamp_column=timestamp_column, event_type=event_type, message=message, admin_override=admin_override, override_reason=override_reason)

    def _validate_recommendation_transition(
        self,
        current_status: str,
        next_status: str,
        *,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> None:
        return self.services.validate_recommendation_transition(current_status, next_status, admin_override=admin_override, override_reason=override_reason)

    def _recommendation_baseline_payload(
        self,
        baseline_summary: dict[str, Any],
        *,
        baseline_score: int | None,
        threshold: int,
    ) -> dict[str, Any]:
        return self.services.recommendation_baseline_payload(baseline_summary, baseline_score=baseline_score, threshold=threshold)

    def _recommendation_performance_rows(self, row: dict[str, Any]) -> list[sqlite3.Row]:
        return self.services.recommendation_performance_rows(row)

    def _best_asset_history_score(self, asset: dict[str, Any]) -> int | None:
        return self.services.best_asset_history_score(asset)

    def _reference_pattern_score(self, pattern: dict[str, Any] | None) -> int:
        return self.services.reference_pattern_score(pattern)

    def _recommendation_account_score(self, asset: dict[str, Any], account: str | None) -> int:
        return self.services.recommendation_account_score(asset, account)

    def _recommendation_account_fit_evidence(
        self,
        campaign_id: str,
        asset: dict[str, Any],
        account: str | None,
    ) -> dict[str, Any]:
        return self.services.recommendation_account_fit_evidence(campaign_id, asset, account)

    def _account_memory_for(self, campaign_id: str, account_id: str | None) -> dict[str, Any] | None:
        return self.services.account_memory_for(campaign_id, account_id)

    def _operational_recommendation_score(self, asset: dict[str, Any]) -> int:
        return self.services.operational_recommendation_score(asset)

    def _recommendation_confidence(self, asset: dict[str, Any], pattern: dict[str, Any] | None) -> tuple[str, str]:
        return self.services.recommendation_confidence(asset, pattern)

    def _recommendation_data_quality(self, asset: dict[str, Any], pattern: dict[str, Any] | None) -> dict[str, Any]:
        return self.services.recommendation_data_quality(asset, pattern)

    def _recommendation_reasons(
        self,
        *,
        performance_score: int,
        reference_score: int,
        audit_score: int,
        account_score: int,
        novelty_score: int,
        operational_score: int,
        candidate: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
    ) -> list[str]:
        return self.services.recommendation_reasons(performance_score=performance_score, reference_score=reference_score, audit_score=audit_score, account_score=account_score, novelty_score=novelty_score, operational_score=operational_score, candidate=candidate, reference_pattern=reference_pattern)

    def _asset_target_account(self, asset: dict[str, Any]) -> str | None:
        return self.services.asset_target_account(asset)

    def _recommendation_reference_summary(self, pattern: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.services.recommendation_reference_summary(pattern)

    def _first_suggested_recipe(self, pattern: dict[str, Any] | None) -> str | None:
        return self.services.first_suggested_recipe(pattern)

    def _hook_guidance(self, pattern: dict[str, Any] | None, asset: dict[str, Any]) -> str:
        return self.services.hook_guidance(pattern, asset)

    def _caption_guidance(self, pattern: dict[str, Any] | None, asset: dict[str, Any]) -> str:
        return self.services.caption_guidance(pattern, asset)

    def campaign_readiness(self, campaign_slug: str, *, user_id: str | None = None) -> dict[str, Any]:
        return self.services.campaign_readiness(campaign_slug, user_id=user_id)

    def lifecycle_report(
        self,
        campaign_slug: str,
        *,
        user_id: str | None = None,
        threadsdash_posts: list[dict[str, Any]] | None = None,
        include_threadsdash: str = "auto",
        state: str | None = None,
        blocking_reason: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.lifecycle_report(
            campaign_slug,
            user_id=user_id,
            threadsdash_posts=threadsdash_posts,
            include_threadsdash=include_threadsdash,
            state=state,
            blocking_reason=blocking_reason,
            rendered_asset_id=rendered_asset_id,
        )

    def creator_os_lifecycle_dashboard(
        self,
        *,
        campaign: str,
        user_id: str | None = None,
        threadsdash_posts: list[dict[str, Any]] | None = None,
        include_threadsdash: str = "auto",
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.services.creator_os_lifecycle_dashboard(
            campaign=campaign,
            user_id=user_id,
            threadsdash_posts=threadsdash_posts,
            include_threadsdash=include_threadsdash,
            generated_at=generated_at,
        )

    def _creator_os_lifecycle_bucket(self, row: dict[str, Any]) -> str:
        return self.services.creator_os_lifecycle_bucket(row)

    def _lifecycle_snapshots_by_asset(self, campaign_id: str) -> dict[str, list[dict[str, Any]]]:
        return self.services.lifecycle_snapshots_by_asset(campaign_id)

    def _lifecycle_threadsdash_indexes(
        self,
        *,
        campaign_slug: str,
        user_id: str | None,
        include_threadsdash: str,
        threadsdash_posts: list[dict[str, Any]] | None,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
        return self.services.lifecycle_threadsdash_indexes(
            campaign_slug=campaign_slug,
            user_id=user_id,
            include_threadsdash=include_threadsdash,
            threadsdash_posts=threadsdash_posts,
        )

    def _lifecycle_row(
        self,
        *,
        campaign: dict[str, Any],
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        assignments: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        threadsdash_posts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.services.lifecycle_row(
            campaign=campaign,
            asset=asset,
            plan=plan,
            assignments=assignments,
            snapshots=snapshots,
            threadsdash_posts=threadsdash_posts,
        )

    def _derive_lifecycle_state(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        assignments: list[dict[str, Any]],
        readiness: dict[str, Any],
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
        mismatch: dict[str, Any],
        media_issue: dict[str, Any] | None,
    ) -> tuple[str, str | None, str]:
        return self.services.derive_lifecycle_state(
            asset=asset,
            plan=plan,
            assignments=assignments,
            readiness=readiness,
            post=post,
            snapshot=snapshot,
            mismatch=mismatch,
            media_issue=media_issue,
        )

    def _lifecycle_blocking_reason(self, blocking: list[Any]) -> str:
        return self.services.lifecycle_blocking_reason(blocking)

    def _lifecycle_media_validation_issue(self, *, asset: dict[str, Any], post: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.services.lifecycle_media_validation_issue(asset=asset, post=post)

    def _latest_lifecycle_post(self, posts: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self.services.latest_lifecycle_post(posts)

    def _lifecycle_snapshot_has_metrics(self, snapshot: dict[str, Any]) -> bool:
        return self.services.lifecycle_snapshot_has_metrics(snapshot)

    def _lifecycle_is_past_due(self, scheduled_for: Any) -> bool:
        return self.services.lifecycle_is_past_due(scheduled_for)

    def _lifecycle_past_due_resolved(self, post: dict[str, Any] | None) -> bool:
        return self.services.lifecycle_past_due_resolved(post)

    def _lifecycle_last_state_change(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
    ) -> str | None:
        return self.services.lifecycle_last_state_change(asset=asset, plan=plan, post=post, snapshot=snapshot)

    def _parse_lifecycle_time(self, value: Any) -> datetime | None:
        return self.services.parse_lifecycle_time(value)

    def _lifecycle_mismatch(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
        context_fingerprint: str | None,
    ) -> dict[str, Any]:
        return self.services.lifecycle_mismatch(
            asset=asset,
            plan=plan,
            post=post,
            snapshot=snapshot,
            context_fingerprint=context_fingerprint,
        )

    def _lifecycle_post_meta(self, post: dict[str, Any]) -> dict[str, Any]:
        return self.services.lifecycle_post_meta(post)

    def _lifecycle_fingerprint(self, value: Any) -> str:
        return self.services.lifecycle_fingerprint(value)

    def _canonical_lifecycle_context(self, value: Any) -> Any:
        return self.services.canonical_lifecycle_context(value)

    def _compact_lifecycle_post(self, post: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.services.compact_lifecycle_post(post)

    def _compact_lifecycle_snapshot(self, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.services.compact_lifecycle_snapshot(snapshot)

    def account_plan(self, campaign_slug: str, *, user_id: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.services.account_plan(campaign_slug, user_id=user_id, usage=usage)

    def ranking(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.ranking(campaign_slug)

    def _quality_score_for_ranking(self, asset: dict[str, Any]) -> int:
        return self.services.quality_score_for_ranking(asset)

    def _history_score(self, summary: dict[str, Any] | None) -> int:
        return self.services.history_score(summary)

    def _account_fit_score(self, asset: dict[str, Any]) -> int:
        return self.services.account_fit_score(asset)

    def _novelty_score(self, asset: dict[str, Any]) -> int:
        return self.services.novelty_score(asset)

    def _dashboard_rendered_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.dashboard_rendered_asset(asset)

    def _generated_asset_lineage(self, source_prompt: dict[str, Any], reference_pattern: dict[str, Any] | None) -> dict[str, Any]:
        return self.services.generated_asset_lineage(source_prompt, reference_pattern)

    def _audio_recommendations_for_asset(
        self,
        *,
        caption_generation: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
        recipe: str | None,
        account_tags: list[str],
    ) -> dict[str, Any]:
        return self.services.audio_recommendations_for_asset(
            caption_generation=caption_generation,
            reference_pattern=reference_pattern,
            recipe=recipe,
            account_tags=account_tags,
        )

    def performance_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.performance_summary(campaign_slug)

    def caption_outcome_report(self, campaign_slug: str) -> dict[str, Any]:
        return self.services.caption_outcome_report(campaign_slug)

    def _performance_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.services.performance_for_asset(asset)

    def _performance_snapshot_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.performance_snapshot_payload(row)

    def _account_memory_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.account_memory_payload(row)

    def _account_pattern_stats_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.account_pattern_stats_from_snapshots(
            campaign_id,
            account_id,
            snapshots,
            updated_at,
            account_baselines=account_baselines,
        )

    def _account_posting_windows_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.account_posting_windows_from_snapshots(
            campaign_id,
            account_id,
            snapshots,
            updated_at,
            account_baselines=account_baselines,
        )

    def _account_fatigue_from_pattern_stats(self, pattern_stats: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.account_fatigue_from_pattern_stats(pattern_stats)

    def _account_recommendation_outcomes(self, campaign_id: str, account_id: str, updated_at: str) -> dict[str, Any]:
        return self.services.account_recommendation_outcomes(campaign_id, account_id, updated_at)

    def _account_memory_confidence(self, sample_size: int, outcomes: dict[str, Any]) -> str:
        return self.services.account_memory_confidence(sample_size, outcomes)

    def _group_performance(self, snapshots: list[dict[str, Any]], key: str, *, account_baselines: dict[str, float] | None = None) -> dict[str, Any]:
        return self.services.group_performance(snapshots, key, account_baselines=account_baselines)

    def _aggregate_performance(self, snapshots: list[dict[str, Any]], *, account_baselines: dict[str, float] | None = None) -> dict[str, Any]:
        return self.services.aggregate_performance(snapshots, account_baselines=account_baselines)

    def _performance_metric_contract(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.performance_metric_contract(row)

    def _default_performance_metric_names(self, surface: str) -> list[str]:
        return self.services.default_performance_metric_names(surface)

    def _performance_leaderboards(self, snapshots: list[dict[str, Any]], *, account_baselines: dict[str, float] | None = None) -> dict[str, list[dict[str, Any]]]:
        return self.services.performance_leaderboards(snapshots, account_baselines=account_baselines)

    def _caption_outcome_manual_review(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        return self.services.caption_outcome_manual_review(snapshots)

    def _has_caption_outcome_context(self, snapshot: dict[str, Any]) -> bool:
        return self.services.has_caption_outcome_context(snapshot)

    def _caption_outcome_snapshot_with_placement(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self.services.caption_outcome_snapshot_with_placement(snapshot)

    def _caption_outcome_group(self, snapshots: list[dict[str, Any]], source_key: str, output_key: str) -> list[dict[str, Any]]:
        return self.services.caption_outcome_group(snapshots, source_key, output_key)

    def _caption_outcome_contexts_for_group(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.services.caption_outcome_contexts_for_group(snapshots)

    def _add_leaderboard_snapshot(
        self,
        items: dict[str, dict[str, Any]],
        key: str,
        snapshot: dict[str, Any],
        dimensions: dict[str, Any],
    ) -> None:
        return self.services.add_leaderboard_snapshot(items, key, snapshot, dimensions)

    def _rank_leaderboard_entries(
        self,
        items: dict[str, dict[str, Any]],
        *,
        limit: int = 20,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.services.rank_leaderboard_entries(items, limit=limit, account_baselines=account_baselines)

    def _performance_recommendation_label(self, summary: dict[str, Any]) -> str:
        return self.services.performance_recommendation_label(summary)

    def _performance_quality_score(self, summary: dict[str, Any]) -> int | None:
        return self.services.performance_quality_score(summary)

    def _performance_planning_score(self, summary: dict[str, Any]) -> int | None:
        return self.services.performance_planning_score(summary)

    def _performance_snapshot_dimensions(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.services.performance_snapshot_dimensions(row)

    def _performance_hook_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_hook_dimension(campaign_meta)

    def _performance_audio_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_audio_dimension(campaign_meta)

    def _performance_reference_format_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_reference_format_dimension(campaign_meta)

    def _performance_prompt_pattern_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_prompt_pattern_dimension(campaign_meta)

    def _performance_pattern_card_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_pattern_card_dimension(campaign_meta)

    def _performance_model_account_dimension(self, campaign_meta: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_model_account_dimension(campaign_meta, row)

    def _performance_caption_formula_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_caption_formula_dimension(campaign_meta)

    def _performance_variation_preset_dimension(self, campaign_meta: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.performance_variation_preset_dimension(campaign_meta, row)

    def _performance_score(self, *, source: dict[str, Any], caption: dict[str, Any], recipe: dict[str, Any]) -> int | None:
        return self.services.performance_score(source=source, caption=caption, recipe=recipe)

    def _audit_report_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload._audit_report_payload(self, row)

    def _local_export_readiness(self, asset: dict[str, Any], latest_audit: dict[str, Any] | None) -> dict[str, Any]:
        return self.services.local_export_readiness(asset, latest_audit)

    def explain_publishability(
        self,
        rendered_asset_id: str,
        *,
        distribution_plan_id: str | None = None,
    ) -> dict[str, Any]:
        return self.services.explain_publishability(
            rendered_asset_id,
            distribution_plan_id=distribution_plan_id,
        )

    def capture_publishability_rejection_evidence(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.services.capture_publishability_rejection_evidence(rendered_asset_id)

    def _capture_publishability_rejection_evidence_from_result(
        self,
        rendered_asset_id: str,
        result: dict[str, Any],
        *,
        commit: bool,
    ) -> dict[str, Any]:
        return self.services.capture_publishability_rejection_evidence_from_result(
            rendered_asset_id,
            result,
            commit=commit,
        )

    def _capture_discoverability_gate_rejection_evidence(
        self,
        *,
        gate_result: dict[str, Any],
        failed_stage: str,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        content_surface: str = "reel",
        commit: bool,
    ) -> dict[str, Any]:
        return self.services.capture_discoverability_gate_rejection_evidence(
            gate_result=gate_result,
            failed_stage=failed_stage,
            campaign_id=campaign_id,
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_asset_id,
            content_surface=content_surface,
            commit=commit,
        )

    def quarantine_asset(
        self,
        rendered_asset_id: str,
        *,
        reason: str,
        root_cause: str | None = None,
        blocking_reason: str | None = None,
        distribution_plan_id: str | None = None,
        threadsdash_post_id: str | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        asset = self.rendered_asset(rendered_asset_id)
        now = utc_now()
        quarantine_id = f"qasset_{hashlib.sha256(rendered_asset_id.encode('utf-8')).hexdigest()[:12]}"
        payload = sanitize_for_storage(metadata or {})
        self.conn.execute(
            """
            INSERT INTO quarantined_assets
            (id, campaign_id, rendered_asset_id, distribution_plan_id, threadsdash_post_id,
             reason, root_cause, blocking_reason, excluded_from_metrics, metadata_json,
             created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(rendered_asset_id) DO UPDATE SET
              distribution_plan_id = COALESCE(excluded.distribution_plan_id, quarantined_assets.distribution_plan_id),
              threadsdash_post_id = COALESCE(excluded.threadsdash_post_id, quarantined_assets.threadsdash_post_id),
              reason = excluded.reason,
              root_cause = excluded.root_cause,
              blocking_reason = excluded.blocking_reason,
              excluded_from_metrics = 1,
              metadata_json = excluded.metadata_json,
              created_by = excluded.created_by
            """,
            (
                quarantine_id,
                asset["campaign_id"],
                rendered_asset_id,
                distribution_plan_id,
                threadsdash_post_id,
                reason,
                root_cause,
                blocking_reason or reason,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now,
                created_by,
            ),
        )
        self.record_event(
            "asset_quarantined",
            campaign_id=asset["campaign_id"],
            rendered_asset_id=rendered_asset_id,
            status="failure",
            message=f"Asset quarantined: {reason}",
            metadata={
                "reason": reason,
                "rootCause": root_cause,
                "blockingReason": blocking_reason or reason,
                "distributionPlanId": distribution_plan_id,
                "threadsdashPostId": threadsdash_post_id,
            },
            commit=False,
        )
        if commit:
            self.conn.commit()
        return self._active_quarantine_for_asset(rendered_asset_id) or {}

    def record_proof_run(
        self,
        *,
        campaign_id: str | None,
        rendered_asset_id: str,
        distribution_plan_id: str | None = None,
        threadsdash_draft_id: str | None = None,
        threadsdash_post_id: str | None = None,
        status: str = "started",
        current_state: str = "creative_approved",
        blocking_reason: str | None = None,
        root_cause: str | None = None,
        metrics_eligible: bool = False,
        metadata: dict[str, Any] | None = None,
        proof_run_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.services.record_proof_run(
            campaign_id=campaign_id,
            rendered_asset_id=rendered_asset_id,
            distribution_plan_id=distribution_plan_id,
            threadsdash_draft_id=threadsdash_draft_id,
            threadsdash_post_id=threadsdash_post_id,
            status=status,
            current_state=current_state,
            blocking_reason=blocking_reason,
            root_cause=root_cause,
            metrics_eligible=metrics_eligible,
            metadata=metadata,
            proof_run_id=proof_run_id,
            commit=commit,
        )

    def _latest_audit_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (rendered_asset_id,),
        ).fetchone()
        return self._audit_report_payload(dict(row)) if row else None

    def _active_quarantine_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM quarantined_assets WHERE rendered_asset_id = ? LIMIT 1",
            (rendered_asset_id,),
        ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["metadata"] = json_load(payload.get("metadata_json"), {})
        return payload

    def _normalize_seconds(self, value: Any) -> float | None:
        return self.services.normalize_seconds(value)

    def _first_metadata_value(self, payload: dict[str, Any], *keys: str) -> Any:
        return self.services.first_metadata_value(payload, *keys)

    def _normalize_audio_segment(self, payload: Any) -> dict[str, Any] | None:
        return self.services.normalize_audio_segment(payload)

    def _audio_segment_for_asset(self, audio_intent: dict[str, Any]) -> dict[str, Any] | None:
        return self.services.audio_segment_for_asset(audio_intent)

    def _normalize_cover_frame(self, payload: Any) -> dict[str, Any] | None:
        return self.services.normalize_cover_frame(payload)

    def _cover_frame_for_asset(self, asset: dict[str, Any], caption_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.services.cover_frame_for_asset(asset, caption_context=caption_context)

    def _audio_selection_for_asset(self, asset: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        return self.services.audio_selection_for_asset(asset)

    def _audio_intent_is_attached(self, audio_intent: dict[str, Any], audio_id: str | None) -> bool:
        return self.services.audio_intent_is_attached(audio_intent, audio_id)

    def _audio_intent_claims_embedded_media(self, audio_intent: dict[str, Any]) -> bool:
        return self.services.audio_intent_claims_embedded_media(audio_intent)

    def _embedded_audio_verified(self, output_path: str) -> bool | None:
        return self.services.embedded_audio_verified(output_path)

    def _verification_id(self, prefix: str, *parts: Any) -> str:
        digest = hashlib.sha256(":".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"

    def _text_hash(self, value: str) -> str:
        normalized = " ".join((value or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def discoverability_safe_content_contract(self, *values: Any) -> dict[str, Any]:
        return self.services.discoverability_safe_content_contract(*values)

    def _reel_caption_account_safety_violations(self, *values: Any) -> list[dict[str, str]]:
        return list(self.discoverability_safe_content_contract(*values)["blockedTerms"])

    def _publishability_discoverability_fields(
        self,
        *,
        asset: dict[str, Any],
        caption_text: str,
        caption_context: dict[str, Any],
        post_caption: dict[str, Any],
    ) -> list[tuple[str, str]]:
        return self.services.publishability_discoverability_fields(
            asset=asset,
            caption_text=caption_text,
            caption_context=caption_context,
            post_caption=post_caption,
        )

    def _discoverability_evidence_for_fields(self, fields: list[tuple[str, str]]) -> list[dict[str, Any]]:
        return self.services.discoverability_evidence_for_fields(fields)

    def _instagram_post_caption_for_asset(
        self,
        asset: dict[str, Any],
        caption_context: dict[str, Any] | None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        caption_generation = asset.get("captionGeneration")
        if not isinstance(caption_generation, dict):
            caption_generation = json_load(asset.get("caption_generation_json"), {})
        if not isinstance(caption_generation, dict):
            caption_generation = {}
        source_records = [
            distribution_plan or {},
            caption_generation,
            caption_generation.get("instagramPostCaption") if isinstance(caption_generation.get("instagramPostCaption"), dict) else {},
            caption_generation.get("instagram_post_caption") if isinstance(caption_generation.get("instagram_post_caption"), dict) else {},
            caption_context or {},
            asset,
        ]
        post_caption = ""
        explicit_post_caption = False
        for record in source_records:
            if not isinstance(record, dict):
                continue
            for key in ("instagram_post_caption", "instagramPostCaption", "post_caption", "postCaption"):
                if key in record and isinstance(record.get(key), str):
                    post_caption = str(record.get(key) or "").strip()
                    explicit_post_caption = True
                    break
            if explicit_post_caption:
                break
        burned_caption = str(asset.get("caption") or (caption_context or {}).get("caption_text") or "").strip()
        caption_cta = next(
            (
                str(value).strip()
                for record in source_records
                if isinstance(record, dict)
                for value in (record.get("caption_cta"), record.get("captionCta"))
                if isinstance(value, str) and value.strip()
            ),
            "",
        )
        hashtags: list[str] = []
        for record in source_records:
            if not isinstance(record, dict):
                continue
            raw_tags = record.get("hashtags") or record.get("instagram_hashtags") or record.get("instagramHashtags")
            if not isinstance(raw_tags, list):
                continue
            for tag in raw_tags:
                if not isinstance(tag, str):
                    continue
                cleaned = re.sub(r"[^A-Za-z0-9_]", "", tag.strip().lstrip("#"))
                if cleaned and f"#{cleaned}" not in hashtags:
                    hashtags.append(f"#{cleaned}")
                if len(hashtags) >= 5:
                    break
            if len(hashtags) >= 5:
                break
        style = next(
            (
                str(value).strip()
                for record in source_records
                if isinstance(record, dict)
                for value in (record.get("post_caption_style"), record.get("postCaptionStyle"))
                if isinstance(value, str) and value.strip()
            ),
            "short_natural",
        )
        final_caption = post_caption
        if caption_cta and caption_cta.lower() not in final_caption.lower():
            final_caption = f"{final_caption}\n{caption_cta}".strip()
        missing_tags = [tag for tag in hashtags if tag.lower() not in final_caption.lower()]
        if missing_tags:
            final_caption = f"{final_caption}\n{' '.join(missing_tags)}".strip()
        return {
            "instagram_post_caption": final_caption,
            "instagram_post_caption_hash": self._text_hash(final_caption) if final_caption else None,
            "caption_cta": caption_cta or None,
            "hashtags": hashtags,
            "post_caption_style": style,
            "burned_caption_text": burned_caption,
            "burned_caption_hash": self._text_hash(burned_caption) if burned_caption else None,
        }

    def _instagram_post_caption_quality(self, post_caption: dict[str, Any]) -> dict[str, Any]:
        return self.services.instagram_post_caption_quality(post_caption)

    def caption_quality_repair_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.services.caption_quality_repair_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            limit=limit,
        )

    def _caption_quality_recovery_class(self, quality_reasons: list[str]) -> str:
        return self.services.caption_quality_recovery_class(quality_reasons)

    def _suggest_simple_instagram_post_caption(self, *, asset_id: str, current_caption: str, burned_caption: str) -> str:
        return self.services.suggest_simple_instagram_post_caption(
            asset_id=asset_id,
            current_caption=current_caption,
            burned_caption=burned_caption,
        )

    def _publishability_check(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None = None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.services.publishability_check(
            asset,
            latest_audit,
            distribution_plan=distribution_plan,
        )

    def _caption_lineage_sidecar(self, output_path: str) -> dict[str, Any]:
        if not output_path:
            return {}
        sidecar_path = Path(output_path + ".caption_lineage.json")
        if not sidecar_path.exists():
            return {}
        try:
            payload = json_load(sidecar_path.read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        return payload if isinstance(payload, dict) else {}
