"""Fail-closed audio policy checks shared by draft and readiness adapters."""

from __future__ import annotations

from typing import Any


def audio_intent_allows_live(intent: Any) -> bool:
    if not isinstance(intent, dict):
        return True
    policy = str(intent.get("policy") or "").strip().lower()
    if not intent.get("required", False):
        return policy == "silent_allowed"
    status = str(intent.get("status") or "").strip().lower()
    if status in {"skipped", "not_required"}:
        return policy == "silent_allowed"
    if policy in {
        "embedded_trending_required",
        "original_embedded",
        "creator_voice",
        "royalty_free",
    }:
        fulfillment = intent.get("fulfillment")
        base_complete = bool(
            status in {"attached", "verified"}
            and isinstance(fulfillment, dict)
            and fulfillment.get("audio_present") is True
            and str(fulfillment.get("output_sha256") or "").strip()
            and str(fulfillment.get("proof_type") or "").strip()
        )
        if not base_complete or policy != "embedded_trending_required":
            return base_complete
        assert isinstance(fulfillment, dict)
        verification = fulfillment.get("verification_receipt")
        lineage = intent.get("lineage")
        return bool(
            fulfillment.get("evidence_class") == "EXACT_BYTE_VERIFIED"
            and str(fulfillment.get("acquired_audio_sha256") or "").strip()
            and str(fulfillment.get("embedded_audio_fingerprint") or "").strip()
            and isinstance(verification, dict)
            and verification.get("status") == "verified"
            and verification.get("audioPresent") is True
            and str(verification.get("audioCodec") or "").strip().lower() == "aac"
            and isinstance(lineage, dict)
            and _valid_sha256(lineage.get("embeddingReceiptSha256"))
            and _valid_sha256(lineage.get("processedSegmentSha256"))
            and lineage.get("acquiredAudioSha256")
            == fulfillment.get("acquired_audio_sha256")
            and lineage.get("finalMediaSha256") == fulfillment.get("output_sha256")
            and lineage.get("finalAudioFingerprint")
            == fulfillment.get("embedded_audio_fingerprint")
            and isinstance(lineage.get("segmentStartSeconds"), (int, float))
            and isinstance(lineage.get("segmentEndSeconds"), (int, float))
            and lineage["segmentEndSeconds"] > lineage["segmentStartSeconds"]
        )
    if policy != "native_trending_required":
        return False
    if status not in {"attached", "verified"}:
        return False
    selection = intent.get("operator_selection")
    if not isinstance(selection, dict):
        return False
    has_native_locator = any(
        isinstance(selection.get(key), str) and selection.get(key).strip()
        for key in (
            "platform_audio_id",
            "platform_url",
            "native_audio_id",
            "native_audio_url",
            "audio_id",
        )
    )
    has_selected_at = isinstance(selection.get("selected_at"), str) and bool(
        selection.get("selected_at").strip()
    )
    final_key = "verified_at" if status == "verified" else "attached_at"
    has_final_timestamp = isinstance(selection.get(final_key), str) and bool(
        selection.get(final_key).strip()
    )
    return bool(has_native_locator and has_selected_at and has_final_timestamp)


def _valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )
