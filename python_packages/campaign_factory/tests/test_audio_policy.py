from pathlib import Path

import pytest
from campaign_factory.audio_policy import (
    build_motion_audio_intent,
    validate_motion_audio_policy,
)


def test_silence_requires_explicit_policy_and_reason() -> None:
    assert (
        validate_motion_audio_policy(
            "native_trending_required",
            audio_path=None,
            generate_audio=False,
            preserve_audio=False,
            selected_reason=None,
        )
        == "native_trending_required"
    )
    with pytest.raises(ValueError, match="audio-selected-reason"):
        validate_motion_audio_policy(
            "silent_allowed",
            audio_path=None,
            generate_audio=False,
            preserve_audio=False,
            selected_reason=None,
        )


def test_native_policy_never_accepts_embedded_audio(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"voice")
    with pytest.raises(ValueError, match="forbids embedded audio"):
        validate_motion_audio_policy(
            "native_trending_required",
            audio_path=audio,
            generate_audio=False,
            preserve_audio=False,
            selected_reason=None,
        )


def test_embedded_original_intent_carries_fulfillment_proof() -> None:
    intent = build_motion_audio_intent(
        policy="original_embedded",
        audio={"mode": "preserved", "sidecarSha256": "a" * 64},
        output_sha256="b" * 64,
        selected_at="2026-07-24T12:00:00Z",
        track_name="Original source audio",
        source="source_video",
        start_offset_seconds=0,
        volume=1,
        selected_reason="Keep the creator's original recorded sound",
    )

    assert intent["policy"] == "original_embedded"
    assert intent["status"] == "attached"
    assert intent["operator_selection"]["start_offset_seconds"] == 0
    assert intent["operator_selection"]["volume"] == 1
    assert intent["fulfillment"] == {
        "status": "verified",
        "owner": "creator_os",
        "proof_required": True,
        "proof_type": "embedded_output_audio_stream",
        "audio_present": True,
        "output_sha256": "b" * 64,
        "audio_mode": "preserved",
        "sidecar_sha256": "a" * 64,
        "verified_at": "2026-07-24T12:00:00Z",
    }


def test_local_motion_rejects_unapplied_embedded_mix_settings() -> None:
    with pytest.raises(ValueError, match="start offsets are not applied"):
        build_motion_audio_intent(
            policy="creator_voice",
            audio={"mode": "source"},
            output_sha256="b" * 64,
            selected_at="2026-07-24T12:00:00Z",
            start_offset_seconds=1.25,
        )
