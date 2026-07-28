"""Deterministic FFmpeg embedding and post-render audio verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .acquisition import AcquiredAudio, probe_media
from .segment import SegmentSelection, decoded_audio_fingerprint


class AudioEmbeddingError(RuntimeError):
    """FFmpeg output failed audio, duration, geometry, or lineage verification."""


@dataclass(frozen=True)
class EmbeddingSettings:
    """Bounded deterministic mix controls."""

    volume: float = 0.82
    target_lufs: float = -14.0
    true_peak_db: float = -1.5
    loudness_range: float = 11.0
    fade_in_seconds: float = 0.15
    fade_out_seconds: float = 0.15
    speech_music_volume: float = 0.24
    sample_rate: int = 48_000
    aac_bitrate: str = "192k"
    mix_ambient: bool = False


def embed_selected_audio(
    *,
    video_path: Path,
    acquired: AcquiredAudio,
    segment: SegmentSelection,
    output_path: Path,
    settings: EmbeddingSettings = EmbeddingSettings(),
    policy: str = "embedded_trending_required",
    speaking: bool = False,
) -> dict[str, Any]:
    """Create an audio-complete MP4 derivative and return bound proof."""

    if policy not in {"embedded_trending_required", "original_embedded"}:
        raise AudioEmbeddingError("embedding stage received an unsupported policy")
    if not 0 <= settings.volume <= 1 or not 0 <= settings.speech_music_volume <= 1:
        raise AudioEmbeddingError("audio volume must be between zero and one")
    source_video = video_path.expanduser()
    if source_video.is_symlink():
        raise AudioEmbeddingError("source video must not be a symlink")
    source_video = source_video.resolve()
    if not source_video.is_file():
        raise AudioEmbeddingError("source video is missing")
    raw_output = output_path.expanduser()
    if raw_output.is_symlink():
        raise AudioEmbeddingError("output video must not be a symlink")
    output = raw_output.resolve()
    if output == source_video:
        raise AudioEmbeddingError("output video must differ from source video")
    source_probe = probe_media(source_video)
    source_duration = _duration(source_probe)
    if abs(source_duration - segment.duration_seconds) > 0.12:
        raise AudioEmbeddingError("selected segment duration does not match Reel")
    geometry = _geometry(source_probe)
    has_source_audio = any(
        isinstance(stream, dict) and stream.get("codec_type") == "audio"
        for stream in source_probe.get("streams", [])
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.partial-{os.getpid()}.mp4")
    partial.unlink(missing_ok=True)
    fade_in = min(settings.fade_in_seconds, source_duration / 4)
    fade_out = min(settings.fade_out_seconds, source_duration / 4)
    fade_out_start = max(0.0, source_duration - fade_out)
    music_filters = (
        f"atrim=start=0:duration={source_duration:.6f},"
        "asetpts=PTS-STARTPTS,"
        f"aresample={settings.sample_rate},"
        f"loudnorm=I={settings.target_lufs}:TP={settings.true_peak_db}:"
        f"LRA={settings.loudness_range},"
        f"volume={settings.speech_music_volume if speaking else settings.volume:.6f},"
        f"afade=t=in:st=0:d={fade_in:.6f},"
        f"afade=t=out:st={fade_out_start:.6f}:d={fade_out:.6f}"
    )
    if speaking and has_source_audio:
        filter_complex = (
            f"[1:a:0]{music_filters}[music];"
            f"[0:a:0]atrim=start=0:duration={source_duration:.6f},"
            f"asetpts=PTS-STARTPTS,aresample={settings.sample_rate}[speech];"
            "[speech][music]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.95[aout]"
        )
        audio_policy_action = "duck_music_under_speech"
    else:
        filter_complex = f"[1:a:0]{music_filters}[aout]"
        audio_policy_action = (
            "replace_existing_audio"
            if has_source_audio
            else "add_audio_to_silent_video"
        )
    command = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-hide_banner",
        "-y",
        "-nostdin",
        "-i",
        str(source_video),
        "-ss",
        f"{segment.start_offset_seconds:.6f}",
        "-i",
        str(acquired.cache_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        settings.aac_bitrate,
        "-ar",
        str(settings.sample_rate),
        "-t",
        f"{source_duration:.6f}",
        "-movflags",
        "+faststart",
        str(partial),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        partial.unlink(missing_ok=True)
        raise AudioEmbeddingError(
            (result.stderr or "ffmpeg audio embedding failed")[-3000:].strip()
        )
    try:
        verification = _verify_output(
            partial,
            source_duration=source_duration,
            source_geometry=geometry,
        )
        final_sha = _sha256_file(partial)
        audio_fingerprint = decoded_audio_fingerprint(partial)
        os.replace(partial, output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    command_fingerprint = hashlib.sha256(
        json.dumps(
            _redacted_command(command),
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "creator_os.audio_embedding_receipt.v1",
        "policy": policy,
        "originalVideo": {
            "path": str(source_video),
            "sha256": _sha256_file(source_video),
            "durationSeconds": source_duration,
            "geometry": geometry,
            "audioPresent": has_source_audio,
        },
        "selectedTrack": {
            "provider": acquired.provider,
            "platform": acquired.platform,
            "trackId": acquired.track_id,
            "acquiredAudioSha256": acquired.byte_sha256,
            "acquisitionReceipt": acquired.receipt(),
        },
        "selectedSegment": segment.receipt(),
        "mixSettings": {
            **asdict(settings),
            "speaking": speaking,
            "policyAction": audio_policy_action,
        },
        "ffmpeg": {
            "commandFingerprint": command_fingerprint,
            "videoCodecAction": "copy",
            "audioCodec": "aac",
        },
        "finalVideo": {
            "path": str(output),
            "sha256": final_sha,
            "audioFingerprint": audio_fingerprint,
        },
        "verification": verification,
    }


def _verify_output(
    path: Path,
    *,
    source_duration: float,
    source_geometry: dict[str, int],
) -> dict[str, Any]:
    probe = probe_media(path)
    duration = _duration(probe)
    geometry = _geometry(probe)
    audio_streams = [
        stream
        for stream in probe.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if len(audio_streams) != 1:
        raise AudioEmbeddingError("final MP4 must contain exactly one audio stream")
    stream = audio_streams[0]
    if stream.get("codec_name") != "aac":
        raise AudioEmbeddingError("final MP4 audio codec is not AAC")
    if geometry != source_geometry:
        raise AudioEmbeddingError("final MP4 geometry changed")
    if abs(duration - source_duration) > 0.12:
        raise AudioEmbeddingError("final MP4 duration changed")
    return {
        "status": "verified",
        "proofType": "embedded_output_audio_stream",
        "audioPresent": True,
        "audioStreamCount": 1,
        "audioCodec": "aac",
        "sampleRate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "durationSeconds": duration,
        "sourceDurationSeconds": source_duration,
        "durationDeltaSeconds": round(duration - source_duration, 6),
        "geometry": geometry,
    }


def _duration(probe: dict[str, Any]) -> float:
    try:
        return round(float((probe.get("format") or {}).get("duration") or 0), 6)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AudioEmbeddingError("media duration is missing") from exc


def _geometry(probe: dict[str, Any]) -> dict[str, int]:
    for stream in probe.get("streams", []):
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            return {
                "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0),
            }
    raise AudioEmbeddingError("media has no video stream")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    for value in command:
        if value.startswith(("http://", "https://")):
            redacted.append("<provider-url>")
        else:
            redacted.append(value)
    return redacted
