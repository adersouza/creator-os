"""Explicit audio-policy construction for Creator OS generation assets."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

AUDIO_POLICIES = (
    "embedded_trending_required",
    "native_trending_required",
    "original_embedded",
    "creator_voice",
    "royalty_free",
    "silent_allowed",
)

EMBEDDED_AUDIO_POLICIES = {
    "original_embedded",
    "creator_voice",
    "royalty_free",
}
_AUDIO_ALIASES = {
    "embedded_trending": "embedded_trending_required",
    "reference_audio_required": "original_embedded",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def resolve_production_audio_policy_alias(value: str) -> str:
    resolved = _AUDIO_ALIASES.get(value, value)
    if resolved not in AUDIO_POLICIES:
        raise ValueError(f"unsupported production audio policy: {value}")
    return resolved


def audio_preview_evidence(item: dict[str, Any]) -> dict[str, str]:
    raw_value = item.get("raw")
    raw: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    nested_value = item.get("previewEvidence")
    nested: dict[str, Any] = nested_value if isinstance(nested_value, dict) else {}
    raw_nested_value = raw.get("previewEvidence")
    raw_nested: dict[str, Any] = (
        raw_nested_value if isinstance(raw_nested_value, dict) else {}
    )
    path = str(
        item.get("localPreviewPath")
        or item.get("local_preview_path")
        or nested.get("path")
        or raw_nested.get("path")
        or ""
    ).strip()
    sha256 = (
        str(
            item.get("previewSha256")
            or item.get("preview_sha256")
            or nested.get("sha256")
            or raw.get("previewSha256")
            or raw.get("preview_sha256")
            or raw_nested.get("sha256")
            or ""
        )
        .strip()
        .lower()
    )
    evidence: dict[str, str] = {}
    if path:
        evidence["path"] = path
    if sha256:
        evidence["sha256"] = sha256
        evidence["sha256Format"] = (
            "valid" if _SHA256_RE.fullmatch(sha256) else "invalid"
        )
    return evidence


def is_native_audio_url(url: str, platform: str) -> bool:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.lower().rstrip("/")
    platform_norm = "_".join(
        str(platform or "").strip().lower().replace("-", "_").split()
    )
    if platform_norm == "instagram":
        return (host == "instagram.com" or host.endswith(".instagram.com")) and (
            "/reels/audio/" in f"{path}/" or path.startswith("/audio/")
        )
    if platform_norm == "tiktok":
        return (
            host == "tiktok.com" or host.endswith(".tiktok.com")
        ) and path.startswith("/music/")
    return bool(url)


def is_reel_page_url(url: str, platform: str) -> bool:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.lower().rstrip("/")
    platform_norm = "_".join(
        str(platform or "").strip().lower().replace("-", "_").split()
    )
    if platform_norm == "instagram":
        return (host == "instagram.com" or host.endswith(".instagram.com")) and bool(
            re.match(r"^/(?:reel|reels|p|tv)/[^/]+$", path)
        )
    if platform_norm == "tiktok":
        return (
            host == "tiktok.com" or host.endswith(".tiktok.com")
        ) and "/video/" in path
    return False


def validate_production_intent_audio_policy(intent: str, policy: str) -> None:
    if intent == "recreate_reel":
        if policy not in {
            "embedded_trending_required",
            "original_embedded",
            "silent_allowed",
        }:
            raise ValueError(
                "recreate_reel audio must be embedded_trending_required, "
                "REFERENCE_AUDIO_REQUIRED, or silent_allowed"
            )
    elif policy != "embedded_trending_required":
        raise ValueError(
            "non-talking production intents require embedded_trending_required"
        )


def resolve_motion_audio_policy(
    policy: str | None,
    *,
    audio_mode: str,
) -> str:
    """Resolve legacy direct-call fixtures without making silence the default."""
    value = str(policy or "").strip()
    if not value:
        value = {
            "preserved": "original_embedded",
            "source": "creator_voice",
            "generated": "royalty_free",
        }.get(audio_mode, "embedded_trending_required")
    if value not in AUDIO_POLICIES:
        raise ValueError(f"unsupported audio policy: {value}")
    return value


def validate_motion_audio_policy(
    policy: str | None,
    *,
    audio_path: Path | None,
    generate_audio: bool,
    preserve_audio: bool,
    selected_reason: str | None,
) -> str:
    """Fail closed when requested media inputs contradict the declared policy."""
    requested_mode = (
        "preserved"
        if preserve_audio
        else "source"
        if audio_path is not None
        else "generated"
        if generate_audio
        else "none"
    )
    resolved = resolve_motion_audio_policy(policy, audio_mode=requested_mode)
    reason = str(selected_reason or "").strip()

    if resolved == "native_trending_required" and requested_mode != "none":
        raise ValueError(
            "native_trending_required forbids embedded audio inputs; choose an "
            "embedded audio policy explicitly"
        )
    if resolved == "embedded_trending_required" and requested_mode != "none":
        raise ValueError(
            "embedded_trending_required uses the post-render Audio Radar stage; "
            "model-conditioning audio inputs are forbidden"
        )
    if resolved == "original_embedded" and requested_mode != "preserved":
        raise ValueError("original_embedded requires --preserve-audio")
    if resolved == "creator_voice" and requested_mode != "source":
        raise ValueError("creator_voice requires an explicit --audio source")
    if resolved == "royalty_free" and requested_mode not in {"source", "generated"}:
        raise ValueError("royalty_free requires --audio or --generate-audio")
    if resolved == "silent_allowed":
        if requested_mode != "none":
            raise ValueError("silent_allowed forbids audio generation and audio inputs")
        if not reason:
            raise ValueError("silent_allowed requires --audio-selected-reason")
    if resolved == "royalty_free" and not reason:
        raise ValueError("royalty_free requires --audio-selected-reason")
    return resolved


def build_motion_audio_intent(
    *,
    policy: str | None,
    audio: dict[str, Any],
    output_sha256: str,
    selected_at: str,
    track_id: str | None = None,
    track_name: str | None = None,
    source: str | None = None,
    start_offset_seconds: float | None = None,
    volume: float | None = None,
    selected_reason: str | None = None,
) -> dict[str, Any]:
    """Build the exact handoff record stored with a generated motion asset."""
    audio_mode = str(audio.get("mode") or "none")
    resolved = resolve_motion_audio_policy(policy, audio_mode=audio_mode)
    embedded = resolved in EMBEDDED_AUDIO_POLICIES and audio_mode in {
        "source",
        "generated",
        "preserved",
    }
    expected_modes = {
        "original_embedded": {"preserved"},
        "creator_voice": {"source"},
        "royalty_free": {"source", "generated"},
    }
    pending_reference_audio = resolved == "original_embedded" and audio_mode == "none"
    if (
        resolved in EMBEDDED_AUDIO_POLICIES
        and not pending_reference_audio
        and audio_mode not in expected_modes[resolved]
    ):
        raise ValueError(
            f"{resolved} does not match worker audio mode {audio_mode or 'none'}"
        )
    if resolved == "native_trending_required" and audio_mode != "none":
        raise ValueError("native_trending_required cannot claim embedded output audio")
    if resolved == "embedded_trending_required" and audio_mode != "none":
        raise ValueError(
            "embedded_trending_required requires a separate verified post-render output"
        )
    if resolved == "silent_allowed" and audio_mode != "none":
        raise ValueError("silent_allowed cannot claim embedded output audio")
    if start_offset_seconds is not None and start_offset_seconds < 0:
        raise ValueError("audio start offset must be non-negative")
    if volume is not None and not 0 <= volume <= 1:
        raise ValueError("audio volume must be between 0 and 1")
    if embedded and start_offset_seconds not in {None, 0, 0.0}:
        raise ValueError(
            "embedded audio start offsets are not applied by the local motion worker"
        )
    if embedded and volume not in {None, 1, 1.0}:
        raise ValueError(
            "embedded audio volume changes are not applied by the local motion worker"
        )

    default_reason = {
        "embedded_trending_required": (
            "Audio Radar must acquire, select, embed, and verify a compatible trend"
        ),
        "native_trending_required": (
            "Native Instagram audio must be resolved and verified by ThreadsDashboard"
        ),
        "original_embedded": "Preserve the original source-video audio",
        "creator_voice": "Use the supplied creator voice track",
        "royalty_free": "Use the approved royalty-free audio source",
        "silent_allowed": "Operator explicitly approved silent publication",
    }[resolved]
    selection: dict[str, Any] = {
        "track_id": _clean(track_id),
        "audio_id": _clean(track_id),
        "audio_title": _clean(track_name),
        "track_name": _clean(track_name),
        "source": _clean(source)
        or (
            "instagram_native"
            if resolved == "native_trending_required"
            else "audio_radar_pending"
            if resolved == "embedded_trending_required"
            else f"embedded_{resolved}"
        ),
        "selection_source": "creator_os_generation",
        "start_offset_seconds": start_offset_seconds,
        "volume": volume,
        "selected_reason": _clean(selected_reason) or default_reason,
        "selected_at": selected_at,
        "attached_at": selected_at if embedded else None,
    }
    selection = {key: value for key, value in selection.items() if value is not None}
    if start_offset_seconds is not None:
        selection["audio_segment"] = {"start_seconds": start_offset_seconds}

    status = (
        "attached"
        if embedded
        else "blocked"
        if pending_reference_audio
        else "not_required"
        if resolved == "silent_allowed"
        else "blocked"
        if resolved == "embedded_trending_required"
        else "needs_operator_selection"
    )
    fulfillment = {
        "status": (
            "verified"
            if embedded
            else "pending"
            if pending_reference_audio
            else "explicitly_allowed"
            if resolved == "silent_allowed"
            else "pending"
        ),
        "owner": (
            "threads_dashboard"
            if resolved == "native_trending_required"
            else "creator_os"
        ),
        "proof_required": resolved != "silent_allowed",
        "proof_type": (
            "embedded_output_audio_stream"
            if embedded
            or pending_reference_audio
            or resolved == "embedded_trending_required"
            else "explicit_silent_policy"
            if resolved == "silent_allowed"
            else "instagram_native_audio_receipt"
        ),
        "audio_present": embedded,
        "output_sha256": output_sha256,
        "audio_mode": audio_mode,
        "sidecar_sha256": _clean(audio.get("sidecarSha256")),
        "verified_at": selected_at if embedded else None,
    }
    fulfillment = {
        key: value for key, value in fulfillment.items() if value is not None
    }
    return {
        "schema": "pipeline.audio_intent.v1",
        "policy": resolved,
        "mode": {
            "embedded_trending_required": "embedded_trending_audio",
            "native_trending_required": "native_platform_audio",
            "original_embedded": "embedded_original_audio",
            "creator_voice": "embedded_creator_voice",
            "royalty_free": "embedded_royalty_free_audio",
            "silent_allowed": "silence",
        }[resolved],
        "required": resolved != "silent_allowed",
        "status": status,
        "platform": "instagram",
        "surface": "reels",
        "recommendations": [],
        "operator_selection": selection,
        "fulfillment": fulfillment,
        "gates": {
            "allow_draft_export": True,
            "allow_preview_schedule": True,
            "allow_live_schedule": embedded or resolved == "silent_allowed",
            "allow_publish": False,
        },
    }


def build_embedded_trending_audio_intent(
    embedding_receipt: dict[str, Any],
    *,
    selected_at: str,
) -> dict[str, Any]:
    """Convert verified Audio Radar output into the exact publish handoff."""

    if (
        embedding_receipt.get("schema") != "creator_os.audio_embedding_receipt.v1"
        or embedding_receipt.get("policy") != "embedded_trending_required"
    ):
        raise ValueError("invalid embedded trending receipt")
    verification = embedding_receipt.get("verification")
    final_video = embedding_receipt.get("finalVideo")
    selected_track = embedding_receipt.get("selectedTrack")
    segment = embedding_receipt.get("selectedSegment")
    selection = embedding_receipt.get("selection")
    mix = embedding_receipt.get("mixSettings")
    if not all(
        isinstance(value, dict)
        for value in (
            verification,
            final_video,
            selected_track,
            segment,
            selection,
            mix,
        )
    ):
        raise ValueError("embedded trending receipt is incomplete")
    assert isinstance(verification, dict)
    assert isinstance(final_video, dict)
    assert isinstance(selected_track, dict)
    assert isinstance(segment, dict)
    assert isinstance(selection, dict)
    assert isinstance(mix, dict)
    output_sha = _sha256_value(final_video.get("sha256"), "final video")
    audio_fingerprint = _sha256_value(
        final_video.get("audioFingerprint"),
        "embedded audio",
    )
    acquired_sha = _sha256_value(
        selected_track.get("acquiredAudioSha256"),
        "acquired audio",
    )
    processed_segment_sha = _sha256_value(
        segment.get("processed_segment_sha256"),
        "processed segment",
    )
    segment_start = _nonnegative_float(
        segment.get("start_offset_seconds"),
        "segment start",
    )
    segment_end = _positive_float(segment.get("end_seconds"), "segment end")
    segment_duration = _positive_float(
        segment.get("duration_seconds"),
        "segment duration",
    )
    if segment_end <= segment_start or not math.isclose(
        segment_end - segment_start,
        segment_duration,
        abs_tol=0.01,
    ):
        raise ValueError("embedded trending segment bounds are inconsistent")
    if (
        verification.get("status") != "verified"
        or verification.get("audioPresent") is not True
        or verification.get("audioCodec") != "aac"
    ):
        raise ValueError("embedded trending output audio is not verified")
    canonical_track_id = _clean(selection.get("canonicalTrackId"))
    raw_platform_sound_ids = selection.get("platformSoundIds")
    if not canonical_track_id or not isinstance(raw_platform_sound_ids, list):
        raise ValueError("embedded trending track identity is incomplete")
    platform_sound_ids = []
    for value in raw_platform_sound_ids:
        if not isinstance(value, dict):
            raise ValueError("embedded trending platform sound identity is invalid")
        platform = _clean(value.get("platform"))
        sound_id = _clean(value.get("sound_id")) or _clean(value.get("soundId"))
        if not platform or not sound_id:
            raise ValueError("embedded trending platform sound identity is incomplete")
        platform_sound_ids.append(
            {
                key: item
                for key, item in {
                    "platform": platform,
                    "sound_id": sound_id,
                    "region": _clean(value.get("region")),
                }.items()
                if item is not None
            }
        )
    canonical_artists = selection.get("canonicalArtists")
    rights = _audio_rights(selection)
    artist_name = (
        ", ".join(str(value) for value in canonical_artists)
        if isinstance(canonical_artists, list)
        else None
    )
    track_id = _clean(selected_track.get("trackId")) or canonical_track_id
    operator_selection = {
        "track_id": track_id,
        "audio_id": track_id,
        "audio_title": _clean(selection.get("canonicalTitle")),
        "track_name": _clean(selection.get("canonicalTitle")),
        "artist_name": artist_name,
        "canonical_track_id": canonical_track_id,
        "provider": _clean(selected_track.get("provider")),
        "source": "embedded_trending_audio_radar",
        "selection_source": "creator_os_audio_radar",
        "platform_sound_ids": platform_sound_ids,
        "start_offset_seconds": segment.get("start_offset_seconds"),
        "segment_duration_seconds": segment.get("duration_seconds"),
        "segment_score": segment.get("segment_score"),
        "beat_evidence": segment.get("beat_evidence"),
        "hook_evidence": segment.get("hook_evidence"),
        "volume": mix.get("volume"),
        "selected_reason": segment.get("selection_reason"),
        "acquired_audio_sha256": acquired_sha,
        "embedded_audio_fingerprint": audio_fingerprint,
        "selected_at": selected_at,
        "attached_at": selected_at,
        "verified_at": selected_at,
        "proof_type": "embedded_output_audio_stream",
    }
    operator_selection = {
        key: value for key, value in operator_selection.items() if value is not None
    }
    rights_allowed = _audio_rights_allow_live(rights)
    return {
        "schema": "pipeline.audio_intent.v1",
        "policy": "embedded_trending_required",
        "mode": "embedded_trending_audio",
        "required": True,
        "status": "verified",
        "platform": "instagram",
        "surface": "reels",
        "recommendations": [],
        "operator_selection": operator_selection,
        "fulfillment": {
            "status": "verified",
            "owner": "creator_os",
            "proof_required": True,
            "proof_type": "embedded_output_audio_stream",
            "evidence_class": "EXACT_BYTE_VERIFIED",
            "audio_present": True,
            "output_sha256": output_sha,
            "acquired_audio_sha256": acquired_sha,
            "embedded_audio_fingerprint": audio_fingerprint,
            "verification_receipt": verification,
            "verified_at": selected_at,
        },
        "lineage": {
            "embeddingReceiptSha256": embedding_receipt_sha256(embedding_receipt),
            "processedSegmentSha256": processed_segment_sha,
            "segmentStartSeconds": segment_start,
            "segmentEndSeconds": segment_end,
            "acquiredAudioSha256": acquired_sha,
            "finalMediaSha256": output_sha,
            "finalAudioFingerprint": audio_fingerprint,
        },
        "rights": rights,
        "performance_learning": {
            "canonical_track_id": canonical_track_id,
            "platform_sound_ids": platform_sound_ids,
            "provider": selected_track.get("provider"),
            "trend_rank": selection.get("trendRank"),
            "trend_velocity": selection.get("trendVelocity"),
            "metrics": {"1h": None, "24h": None, "72h": None},
        },
        "gates": {
            "allow_draft_export": True,
            "allow_preview_schedule": True,
            "allow_live_schedule": rights_allowed,
            "allow_publish": rights_allowed,
        },
    }


def embedding_receipt_sha256(embedding_receipt: dict[str, Any]) -> str:
    """Hash the immutable embedding receipt core, excluding its audio-intent view."""

    core = {
        key: value for key, value in embedding_receipt.items() if key != "audioIntent"
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audio_rights(selection: dict[str, Any]) -> dict[str, Any]:
    labels = selection.get("advisoryLabels")
    source = labels if isinstance(labels, dict) else {}
    return {
        "required": source.get("usageRightsRequired") is True,
        "usageRightsStatus": _clean(source.get("usageRightsStatus"))
        or "rights_unknown",
        "rightsSource": _clean(source.get("rightsSource")),
        "territory": _clean(source.get("territory")),
        "accountScope": _clean(source.get("accountScope")),
        "commercialUseAllowed": (
            source.get("commercialUseAllowed")
            if isinstance(source.get("commercialUseAllowed"), bool)
            else None
        ),
        "expiresAt": _clean(source.get("expiresAt")),
        "evidenceReceipt": source.get("evidenceReceipt"),
    }


def _audio_rights_allow_live(rights: dict[str, Any]) -> bool:
    if rights.get("required") is not True:
        return True
    if rights.get("usageRightsStatus") not in {
        "platform_native_authorized",
        "operator_supplied_authorized",
        "licensed",
    }:
        return False
    if rights.get("commercialUseAllowed") is not True:
        return False
    if not all(
        rights.get(key)
        for key in ("rightsSource", "territory", "accountScope", "evidenceReceipt")
    ):
        return False
    expires_at = rights.get("expiresAt")
    if not expires_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) > datetime.now(UTC)


def _sha256_value(value: object, label: str) -> str:
    cleaned = _clean(value)
    if (
        cleaned is None
        or len(cleaned) != 64
        or any(char not in "0123456789abcdef" for char in cleaned)
    ):
        raise ValueError(f"{label} SHA-256 is invalid")
    return cleaned


def _nonnegative_float(value: object, label: str) -> float:
    result = _finite_float(value, label)
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _positive_float(value: object, label: str) -> float:
    result = _finite_float(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _finite_float(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} is invalid")
    return result


def _clean(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
