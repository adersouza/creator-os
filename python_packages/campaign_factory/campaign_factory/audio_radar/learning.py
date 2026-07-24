"""Audio performance-learning fact construction."""

from __future__ import annotations

from typing import Any


def build_audio_performance_fact(
    *,
    embedding_receipt: dict[str, Any],
    creator: str,
    account: str,
    visual_intent: dict[str, Any],
    publication_id: str | None,
    metrics_1h: dict[str, Any] | None = None,
    metrics_24h: dict[str, Any] | None = None,
    metrics_72h: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind trend, mix, creative context, publication, and metric windows."""

    selection = embedding_receipt.get("selection")
    selection = selection if isinstance(selection, dict) else {}
    segment = embedding_receipt.get("selectedSegment")
    segment = segment if isinstance(segment, dict) else {}
    settings = embedding_receipt.get("mixSettings")
    settings = settings if isinstance(settings, dict) else {}
    final_video = embedding_receipt.get("finalVideo")
    final_video = final_video if isinstance(final_video, dict) else {}
    selected_track = embedding_receipt.get("selectedTrack")
    selected_track = selected_track if isinstance(selected_track, dict) else {}
    return {
        "schema": "campaign_factory.audio_performance_fact.v1",
        "audioPolicy": embedding_receipt.get("policy"),
        "canonicalTrackId": selection.get("canonicalTrackId"),
        "canonicalTitle": selection.get("canonicalTitle"),
        "canonicalArtists": selection.get("canonicalArtists") or [],
        "platformSoundIds": selection.get("platformSoundIds") or [],
        "provider": selected_track.get("provider"),
        "trendRank": selection.get("trendRank"),
        "trendVelocity": selection.get("trendVelocity"),
        "segment": {
            "startOffsetSeconds": segment.get("start_offset_seconds"),
            "durationSeconds": segment.get("duration_seconds"),
            "score": segment.get("segment_score"),
        },
        "mixVolume": settings.get("volume"),
        "creator": creator,
        "account": account,
        "visualIntent": visual_intent,
        "publicationId": publication_id,
        "finalVideoSha256": final_video.get("sha256"),
        "audioFingerprint": final_video.get("audioFingerprint"),
        "metrics": {
            "1h": metrics_1h,
            "24h": metrics_24h,
            "72h": metrics_72h,
        },
    }
