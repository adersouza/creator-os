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
        return bool(
            str(fulfillment.get("acquired_audio_sha256") or "").strip()
            and str(fulfillment.get("embedded_audio_fingerprint") or "").strip()
            and isinstance(verification, dict)
            and verification.get("status") == "verified"
            and verification.get("audioPresent") is True
            and str(verification.get("audioCodec") or "").strip().lower() == "aac"
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
