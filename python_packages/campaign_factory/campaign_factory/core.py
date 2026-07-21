from __future__ import annotations

import math
import re
import subprocess
import sys
import time  # noqa: F401 -- tests monkeypatch campaign_factory.core.time.sleep
import uuid
import zlib
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .config import Settings
from .db import connect, init_db
from .multi_blocker_unlock import MultiBlockerUnlockRepository
from .perceptual import compute_pdq_fingerprint, pdq_hamming_distance
from .persistence import json_load, utc_now
from .services import CampaignContext, CampaignDomainServices

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
RECOMMENDATION_EXECUTION_STATUSES = {
    "not_started",
    "running",
    "completed",
    "blocked",
    "failed",
}
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
CONTENTFORGE_VARIANT_PRESETS = {
    "caption_safe",
    "caption_safe_v2",
    "strong_safe",
    "subtle",
    "balanced",
}
CONTENTFORGE_VARIANT_PACK_SCHEMAS = {
    "contentforge.variant_pack.v1",
    "contentforge.variant_pack.v2",
}
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
STORY_NATIVE_PROOF_STYLES = {
    "amateur",
    "casual",
    "casual_selfie",
    "selfie",
    "mirror",
    "raw_phone",
}
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
            segment_length = int.from_bytes(data[index : index + 2], "big")
            if segment_length < 2:
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                if index + 7 <= len(data):
                    height = int.from_bytes(data[index + 3 : index + 5], "big")
                    width = int.from_bytes(data[index + 5 : index + 7], "big")
                    return _image_shape_payload(width, height)
                break
            index += segment_length
    if (
        len(data) >= 30
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
        and data[12:16] == b"VP8X"
    ):
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
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
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
    except zlib.error:
        return {"ok": False, "error": "png_decompress_failed"}
    rows: list[list[tuple[int, int, int]]] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        if cursor >= len(raw):
            return {"ok": False, "error": "png_truncated"}
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        if len(row) != stride:
            return {"ok": False, "error": "png_truncated"}
        recon = _png_unfilter_row(row, previous, filter_type, channels)
        previous = recon
        rows.append(
            [
                (recon[index], recon[index + 1], recon[index + 2])
                for index in range(0, len(recon), channels)
            ]
        )
    return {"ok": True, "width": width, "height": height, "pixels": rows}


def _png_unfilter_row(
    row: bytearray, previous: bytearray, filter_type: int, bpp: int
) -> bytearray:
    recon = bytearray(row)
    if filter_type == 0:
        return recon
    for index in range(len(recon)):
        left = recon[index - bpp] if index >= bpp else 0
        up = previous[index] if index < len(previous) else 0
        up_left = (
            previous[index - bpp] if index >= bpp and index - bpp < len(previous) else 0
        )
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
    except (OSError, subprocess.SubprocessError):
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
    aspect_ratio = (
        (effective_width / effective_height)
        if effective_width and effective_height
        else None
    )
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
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if not video_stream:
        return {"ok": False, "error": "no_video_stream"}
    audio_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )
    shape = probe_video_shape(path)
    fmt = parsed.get("format") if isinstance(parsed, dict) else {}
    duration = None
    try:
        duration = (
            float((fmt or {}).get("duration"))
            if (fmt or {}).get("duration") is not None
            else None
        )
    except (TypeError, ValueError):
        duration = None
    bitrate = None
    try:
        bitrate = (
            int((fmt or {}).get("bit_rate"))
            if (fmt or {}).get("bit_rate") is not None
            else None
        )
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
    return (
        normalized
        if normalized
        in {
            "regular_reel",
            "trial_reel",
            "story",
            "story_cta",
            "feed_single",
            "feed_carousel",
        }
        else "regular_reel"
    )


def _normalize_schedule_mode(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "draft"
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized not in {"draft", "preview", "live"}:
        raise ValueError(
            f"unknown schedule mode {value!r}; expected draft, preview, or live"
        )
    return normalized


SECRET_KEY_PARTS = (
    "secret",
    "service_role",
    "serviceRole",
    "token",
    "apikey",
    "api_key",
    "password",
    "key",
)


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
        self.context = CampaignContext(self.conn, self.settings)

        def deferred(path: str):
            def call(*args: Any, **kwargs: Any) -> Any:
                target: Any = self.domains
                for name in path.split("."):
                    target = getattr(target, name)
                return target(*args, **kwargs)

            return call

        def load_source_lineage(source_lineage_path: Path | None) -> dict[str, Any]:
            if not source_lineage_path:
                return {}
            path = Path(source_lineage_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"source lineage not found: {path}")
            payload = json_load(path.read_text(encoding="utf-8"), {})
            if not isinstance(payload, dict):
                raise ValueError(f"source lineage must be a JSON object: {path}")
            deferred("finished_video.record_lineage_costs")(payload)
            return payload

        def audit_campaign(*args: Any, **kwargs: Any) -> dict[str, Any]:
            from .adapters.contentforge import audit_campaign as run_audit

            return run_audit(self, *args, **kwargs)

        def evaluate_export_readiness(*args: Any, **kwargs: Any) -> dict[str, Any]:
            from .adapters.threadsdash_draft_readiness import (
                evaluate_export_readiness as evaluate,
            )

            return evaluate(self, *args, **kwargs)

        def export_threadsdash(*args: Any, **kwargs: Any) -> dict[str, Any]:
            from .adapters.threadsdash_draft_delivery import (
                export_threadsdash as export,
            )

            return export(self, *args, **kwargs)

        self.domains = CampaignDomainServices(
            self.context,
            domain_constructor=lambda sandbox_settings: (
                CampaignFactory(sandbox_settings).domains
            ),
            audit_campaign=audit_campaign,
            evaluate_export_readiness=evaluate_export_readiness,
            export_threadsdash=export_threadsdash,
            new_id=new_id,
            new_graph_id=new_graph_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            probe_image_shape=probe_image_shape,
            probe_video_shape=lambda *args, **kwargs: probe_video_shape(
                *args, **kwargs
            ),
            probe_video_metadata=lambda *args, **kwargs: probe_video_metadata(
                *args, **kwargs
            ),
            read_png_rgb_pixels=read_png_rgb_pixels,
            ratio_label_from_shape=ratio_label_from_shape,
            dashboard_rendered_asset=lambda *args, **kwargs: deferred(
                "account_planning.dashboard_rendered_asset"
            )(*args, **kwargs),
            audio_recommendations_for_asset=lambda *args, **kwargs: deferred(
                "account_planning.audio_recommendations_for_asset"
            )(*args, **kwargs),
            generated_asset_lineage=lambda *args, **kwargs: deferred(
                "account_planning.generated_asset_lineage"
            )(*args, **kwargs),
            prepare_reel_inputs=deferred("reel_execution.prepare_reel_inputs"),
            reel_factory_python=reel_factory_python,
            make_batch=lambda *args, **kwargs: deferred("make_batch_repo.make_batch")(
                *args, **kwargs
            ),
            load_source_lineage=lambda *args, **kwargs: load_source_lineage(
                *args, **kwargs
            ),
            discoverability_generation_gate=deferred(
                "discoverability.discoverability_generation_gate"
            ),
            discoverability_pre_render_gate=deferred(
                "discoverability.discoverability_pre_render_gate"
            ),
            discoverability_safe_content_contract=deferred(
                "discoverability.discoverability_safe_content_contract"
            ),
            capture_discoverability_gate_rejection_evidence=lambda *args, **kwargs: (
                deferred(
                    "publishability.capture_discoverability_gate_rejection_evidence"
                )(*args, **kwargs)
            ),
            reference_hook_fallbacks=SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL,
            normalize_content_surface=normalize_content_surface,
            urlopen=lambda *args, **kwargs: urlopen(*args, **kwargs),
            concept_for_parent_asset=deferred(
                "variant_lineage.concept_for_parent_asset"
            ),
            explain_publishability=deferred("publishability.explain_publishability"),
            capture_publishability_rejection_evidence_from_result=lambda *args, **kwargs: (
                deferred(
                    "publishability.capture_publishability_rejection_evidence_from_result"
                )(*args, **kwargs)
            ),
            distribution_plan_payload=deferred(
                "distribution.distribution_plan_payload"
            ),
            verification_id=deferred("publishability.verification_id"),
            caption_lineage_sidecar=deferred("publishability.caption_lineage_sidecar"),
            active_quarantine_for_asset=deferred(
                "publishability.active_quarantine_for_asset"
            ),
            audio_segment_for_asset=deferred(
                "audio_operations.audio_segment_for_asset"
            ),
            cover_frame_for_asset=deferred("audio_operations.cover_frame_for_asset"),
            audio_intent_claims_embedded_media=deferred(
                "audio_operations.audio_intent_claims_embedded_media"
            ),
            embedded_audio_verified=deferred(
                "audio_operations.embedded_audio_verified"
            ),
            discoverability_evidence_for_fields=deferred(
                "discoverability.discoverability_evidence_for_fields"
            ),
            reference_hook_is_schedule_safe=deferred(
                "reference.reference_hook_is_schedule_safe"
            ),
            audio_intent_is_attached=deferred(
                "audio_operations.audio_intent_is_attached"
            ),
            requires_operator_visual_review_for_handoff=deferred(
                "surface_handoff.requires_operator_visual_review_for_handoff"
            ),
            ig_media_type_for_surface=deferred(
                "surface_handoff.ig_media_type_for_surface"
            ),
            surface_handoff_readiness_report=deferred(
                "surface_handoff.surface_handoff_readiness_report"
            ),
            recommend_audio=deferred("audio_recommendations.recommend_audio"),
            select_audio_for_recommendation=deferred(
                "audio_operations.select_audio_for_recommendation"
            ),
            surface_handoff_readiness_for_asset=deferred(
                "surface_handoff.surface_handoff_readiness_for_asset"
            ),
            audio_selection_for_asset=lambda *args, **kwargs: deferred(
                "audio_operations.audio_selection_for_asset"
            )(*args, **kwargs),
            surface_report_assets=deferred("surface_handoff.surface_report_assets"),
            build_surface_readiness=lambda *args, **kwargs: deferred(
                "surface_handoff.build_surface_readiness"
            )(*args, **kwargs),
            asset_matches_creator=deferred("surface_handoff.asset_matches_creator"),
            latest_audit_for_asset=deferred("publishability.latest_audit_for_asset"),
            content_trust_status_blockers=lambda *args, **kwargs: deferred(
                "surface_handoff.content_trust_status_blockers"
            )(*args, **kwargs),
            compute_pdq_fingerprint=lambda *args, **kwargs: compute_pdq_fingerprint(
                *args, **kwargs
            ),
            pdq_hamming_distance=lambda left, right: pdq_hamming_distance(left, right),
            surface_draft_proof=deferred("surface_handoff.surface_draft_proof"),
            asset_components=deferred("surface_handoff.asset_components"),
            instagram_post_caption_for_asset=deferred(
                "publishability.instagram_post_caption_for_asset"
            ),
            register_variant_asset=lambda *args, **kwargs: deferred(
                "variant_lineage.register_variant_asset"
            )(*args, **kwargs),
            suggest_simple_instagram_post_caption=lambda *args, **kwargs: deferred(
                "publishability.suggest_simple_instagram_post_caption"
            )(*args, **kwargs),
            text_hash=deferred("publishability.text_hash"),
            variant_lineage_for_asset=deferred(
                "variant_lineage.variant_lineage_for_asset"
            ),
            story_quality_gate_for_asset=deferred(
                "story_management.story_quality_gate_for_asset"
            ),
            story_style_value=deferred("story_management.story_style_value"),
            story_intent_value=deferred("story_management.story_intent_value"),
            ranking=lambda *args, **kwargs: deferred("account_planning.ranking")(
                *args, **kwargs
            ),
            dashboard=lambda *args, **kwargs: deferred("campaign_overview.dashboard")(
                *args, **kwargs
            ),
            creator_os_account_health_report=lambda *args, **kwargs: deferred(
                "account_health.creator_os_account_health_report"
            )(*args, **kwargs),
            creator_os_account_health_decision=lambda *args, **kwargs: deferred(
                "account_health.creator_os_account_health_decision"
            )(*args, **kwargs),
            creator_os_tier_posting_guidance=lambda *args, **kwargs: deferred(
                "account_health.creator_os_tier_posting_guidance"
            )(*args, **kwargs),
            creator_os_account_tier_summary=lambda *args, **kwargs: deferred(
                "account_health.creator_os_account_tier_summary"
            )(*args, **kwargs),
            creator_os_account_health_summary=lambda *args, **kwargs: deferred(
                "account_health.creator_os_account_health_summary"
            )(*args, **kwargs),
            creator_os_winner_recommendations=lambda *args, **kwargs: deferred(
                "creator_os_recommendations.creator_os_winner_recommendations"
            )(*args, **kwargs),
            creator_os_recommended_inventory=lambda *args, **kwargs: deferred(
                "creator_os_recommendations.creator_os_recommended_inventory"
            )(*args, **kwargs),
            recommendation_explainability=lambda *args, **kwargs: deferred(
                "creative_knowledge.recommendation_explainability"
            )(*args, **kwargs),
            build_creative_performance_analysis=lambda *args, **kwargs: deferred(
                "creative_knowledge.build_creative_performance_analysis"
            )(*args, **kwargs),
            build_creative_knowledge_base=lambda *args, **kwargs: deferred(
                "creative_knowledge.build_creative_knowledge_base"
            )(*args, **kwargs),
            creative_knowledge_rows=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_knowledge_rows"
            )(*args, **kwargs),
            creative_knowledge_result=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_knowledge_result"
            )(*args, **kwargs),
            creative_knowledge_score_weights=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_knowledge_score_weights"
            )(*args, **kwargs),
            creative_result_group=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_result_group"
            )(*args, **kwargs),
            creative_knowledge_results_for_report=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_knowledge_results_for_report"
            )(*args, **kwargs),
            creative_dimension_label=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_dimension_label"
            )(*args, **kwargs),
            learning_confidence_classification=lambda *args, **kwargs: deferred(
                "creative_knowledge.learning_confidence_classification"
            )(*args, **kwargs),
            creative_fatigue_signals=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_fatigue_signals"
            )(*args, **kwargs),
            creative_surface_rows=lambda *args, **kwargs: deferred(
                "creative_knowledge.creative_surface_rows"
            )(*args, **kwargs),
            recommendation_quality_bucket=lambda *args, **kwargs: deferred(
                "creative_knowledge.recommendation_quality_bucket"
            )(*args, **kwargs),
            creator_os_daily_plan=deferred("daily_plan.creator_os_daily_plan"),
            creator_os_execution_readiness=lambda *args, **kwargs: deferred(
                "execution_readiness.creator_os_execution_readiness"
            )(*args, **kwargs),
            inventory_slo_report=deferred("inventory_planning.inventory_slo_report"),
            exception_queue_priority_report=deferred(
                "exceptions.exception_queue_priority_report"
            ),
            parent_factory_autopilot_plan=deferred(
                "parent_factory_planning.parent_factory_autopilot_plan"
            ),
            inventory_autopilot_plan=deferred(
                "inventory_planning.inventory_autopilot_plan"
            ),
            inventory_stage_counts=deferred(
                "inventory_planning.inventory_stage_counts"
            ),
            inventory_production_requirements=deferred(
                "inventory_planning.inventory_production_requirements"
            ),
            exception_queue_report=deferred("exceptions.exception_queue_report"),
            reel_factory_parent_metrics=deferred(
                "reel_factory_reports.reel_factory_parent_metrics"
            ),
            parent_factory_production_scorecard=deferred(
                "parent_factory_trials.parent_factory_production_scorecard"
            ),
            build_surface_inventory=lambda *args, **kwargs: deferred(
                "surface_inventory.build_surface_inventory"
            )(*args, **kwargs),
            surface_readiness_scorecard=deferred(
                "readiness_report.surface_readiness_scorecard"
            ),
            certification_asset_for_surface=deferred(
                "carousel_integrity.certification_asset_for_surface"
            ),
            latest_proof_run_for_asset=deferred(
                "carousel_integrity.latest_proof_run_for_asset"
            ),
            latest_surface_metric_for_asset=deferred(
                "carousel_integrity.latest_surface_metric_for_asset"
            ),
            empty_surface_certification_audit=deferred(
                "carousel_integrity.empty_surface_certification_audit"
            ),
            surface_certification_audit=deferred(
                "carousel_integrity.surface_certification_audit"
            ),
            audio_selection_payload=deferred(
                "audio_operations.audio_selection_payload"
            ),
            audio_workflow_summary=deferred("audio_operations.audio_workflow_summary"),
            events_for_asset=deferred("events.events_for_asset"),
            story_mix_plan=deferred("story_management.story_mix_plan"),
            story_calendar_plan=deferred("story_management.story_calendar_plan"),
            json_load=json_load,
            parent_factory_yield_waterfall=deferred(
                "parent_factory_reports.parent_factory_yield_waterfall"
            ),
            exception_next_action=deferred("exceptions.exception_next_action"),
            story_source_blockers=deferred("story_management.story_source_blockers"),
            normalize_story_enum=deferred("story_management.normalize_story_enum"),
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
            recommendation_proof_summary=deferred(
                "recommendation_accuracy_repo.recommendation_proof_summary"
            ),
            multi_blocker_inventory_unlock_report=lambda *args, **kwargs: deferred(
                "multi_blocker_unlock.multi_blocker_inventory_unlock_report"
            )(*args, **kwargs),
            multi_blocker_repair_minutes=MultiBlockerUnlockRepository.MULTI_BLOCKER_REPAIR_MINUTES,
            account_trust_states=ACCOUNT_TRUST_STATES,
            recommendation_eligibility_states=RECOMMENDATION_ELIGIBILITY_STATES,
            warming_stages=WARMING_STAGES,
            content_surfaces=CONTENT_SURFACES,
            creative_risk_block_threshold=CREATIVE_RISK_BLOCK_THRESHOLD,
            creative_risk_caution_threshold=CREATIVE_RISK_CAUTION_THRESHOLD,
        )
        self.settings.campaigns_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.domains.close()
