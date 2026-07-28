"""Bounded, deterministic reference-Reel analysis and Seedance prompt evidence."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import atomic_write_text

from .audio_policy import build_motion_audio_intent
from .audio_radar import (
    AudioCache,
    AudioLocator,
    bind_embedding_receipt,
    embed_selected_audio,
    select_segment,
)
from .reference_video_remix_stage import detect_reference_video_scenes

ANALYSIS_SCHEMA: Final = "campaign_factory.recreate_reel_analysis.v1"
PROMPT_SCHEMA: Final = "campaign_factory.recreate_reel_prompt.v1"
REVIEW_SCHEMA: Final = "campaign_factory.recreate_reel_review.v1"
SUPPORTED_SUFFIXES: Final = frozenset({".mp4", ".mov", ".m4v", ".webm"})
RECREATE_REEL_STAGE: Final[dict[str, Any]] = {
    "modelId": "higgsfield_seedance2_recreate_reel",
    "providerModel": "seedance_2_0",
    "recipeId": "higgsfield_recreate_reel",
    "durationSeconds": None,
    "resolution": "720p",
    "mode": "std",
    "sound": "off",
    "generatedAudio": False,
    "task": "reference_to_video",
}
RECREATION_REVIEW_FIELDS: Final = (
    "creatorIdentity",
    "facialConsistency",
    "bodyConsistency",
    "handsAnatomy",
    "clothingStability",
    "backgroundStability",
    "broadActionFidelity",
    "cameraFramingFidelity",
    "pacingFidelity",
    "choreographyFidelity",
    "socialNativeAppearance",
    "attractiveness",
    "obviousAiArtifacts",
    "audioSynchronization",
)


def fulfill_reference_audio(
    factory: Any,
    *,
    job: Mapping[str, Any],
    generation_result: dict[str, Any],
    selected_at: str | None,
    motion_stage_result: Callable[[dict[str, Any]], dict[str, Any]],
    probe_video: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Embed exact authorized reference audio as a verified AAC derivative."""

    reference = Path(str(job.get("referenceVideoPath") or "")).expanduser()
    if reference.is_symlink():
        raise RuntimeError("reference audio source must not be a symlink")
    reference = reference.resolve()
    expected_sha = str(job.get("referenceVideoSha256") or "")
    if not reference.is_file() or _sha256_file(reference) != expected_sha:
        raise RuntimeError("reference audio source SHA mismatch")
    analysis = job.get("referenceVideo")
    if not isinstance(analysis, dict) or not (analysis.get("media") or {}).get(
        "audioPresent"
    ):
        raise RuntimeError("REFERENCE_AUDIO_REQUIRED needs embedded reference audio")
    stage = motion_stage_result(generation_result)
    registered = stage.get("registeredAsset")
    if not isinstance(registered, dict):
        raise RuntimeError("production generated asset registration missing")
    rendered_asset_id = str(registered.get("id") or "")
    video_path = Path(str(registered.get("output_path") or "")).expanduser().resolve()
    if not rendered_asset_id or not video_path.is_file():
        raise RuntimeError("production generated asset binding is unsafe")
    completed_at = selected_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquired = AudioCache(video_path.parent / ".audio-cache").acquire(
        AudioLocator(
            provider="operator_reference",
            platform=str(analysis.get("sourcePlatform") or "private_reference"),
            track_id=expected_sha,
            kind="local_file",
            value=str(reference),
        ),
        retrieved_at=completed_at,
    )
    segment = select_segment(
        acquired,
        reel_duration_seconds=float(probe_video(video_path)["durationSeconds"]),
        preferred_offsets=(0.0,),
    )
    final_path = video_path.with_name(
        f"{video_path.stem}__reference_audio{video_path.suffix}"
    )
    receipt = embed_selected_audio(
        video_path=video_path,
        acquired=acquired,
        segment=segment,
        output_path=final_path,
        policy="original_embedded",
    )
    receipt["selection"] = {
        "canonicalTrackId": f"reference_audio:{expected_sha}",
        "sourceVideoSha256": expected_sha,
        "referenceVideoId": analysis.get("referenceVideoId"),
        "selectedReason": ["REFERENCE_AUDIO_REQUIRED"],
    }
    receipt["audioIntent"] = build_motion_audio_intent(
        policy="original_embedded",
        audio={
            "mode": "preserved",
            "sidecarSha256": segment.decoded_audio_fingerprint,
        },
        output_sha256=receipt["finalVideo"]["sha256"],
        selected_at=completed_at,
        track_id=f"reference_audio:{expected_sha}",
        track_name="Authorized reference Reel audio",
        source="operator_authorized_reference",
        selected_reason="REFERENCE_AUDIO_REQUIRED",
    )
    receipt_path = final_path.with_suffix(".audio_embedding.json")
    atomic_write_text(
        receipt_path,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    binding = bind_embedding_receipt(
        factory.conn,
        rendered_asset_id=rendered_asset_id,
        embedding_receipt=receipt,
        bound_at=completed_at,
    )
    refreshed = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    stage["registeredAsset"] = dict(refreshed) if refreshed else registered
    return {
        "policy": "original_embedded",
        "requestedPolicy": "REFERENCE_AUDIO_REQUIRED",
        "status": "verified",
        "receiptPath": str(receipt_path),
        "receipt": receipt,
        "binding": binding,
        "finalVideoSha256": binding["finalVideoSha256"],
        "outputPath": binding["outputPath"],
    }


def analyze_reference_reel(
    path: Path,
    *,
    source_platform: str | None = None,
    operator_authorized: bool,
    declared_talking: bool = False,
) -> dict[str, Any]:
    """Inspect one private reference without registering or copying it."""

    reference = _safe_reference(path)
    probe = _ffprobe(reference)
    video_streams = [
        row
        for row in probe.get("streams", [])
        if isinstance(row, dict) and row.get("codec_type") == "video"
    ]
    audio_streams = [
        row
        for row in probe.get("streams", [])
        if isinstance(row, dict) and row.get("codec_type") == "audio"
    ]
    if len(video_streams) != 1:
        raise ValueError("recreate_reel reference must contain one video stream")
    video = video_streams[0]
    duration = _duration(probe, video)
    if not 4 <= duration <= 15:
        raise ValueError("recreate_reel reference duration must be 4 to 15 seconds")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0 or abs((width / height) - (9 / 16)) > 0.03:
        raise ValueError("recreate_reel reference must be portrait 9:16")
    fps = _frame_rate(video)
    scenes = detect_reference_video_scenes(reference)
    cut_timestamps = [
        float(scene["startSeconds"])
        for scene in scenes["scenes"][1:]
        if float(scene["startSeconds"]) > 0
    ]
    first_hash = _sample_frame_sha(reference, 0.0)
    last_hash = _sample_frame_sha(reference, max(0.0, duration - 0.05))
    motion = _coarse_motion_energy(reference, duration)
    reference_sha = _sha256_file(reference)
    core = {
        "schema": ANALYSIS_SCHEMA,
        "referenceVideoId": f"reference_video_{reference_sha[:20]}",
        "sourcePlatform": _clean(source_platform),
        "originalLocalFile": {
            "path": str(reference),
            "sha256": reference_sha,
            "bytes": reference.stat().st_size,
        },
        "operatorAuthorization": {
            "authorized": bool(operator_authorized),
            "intendedUse": "recreate_reel",
        },
        "media": {
            "durationSeconds": duration,
            "width": width,
            "height": height,
            "frameRate": fps,
            "videoCodec": str(video.get("codec_name") or ""),
            "audioPresent": bool(audio_streams),
            "audioCodec": (
                str(audio_streams[0].get("codec_name") or "") if audio_streams else None
            ),
        },
        "structure": {
            "shotCount": int(scenes["shotCount"]),
            "cutTimestampsSeconds": cut_timestamps,
            "firstFrameSha256": first_hash,
            "lastFrameSha256": last_hash,
            "framingProgression": "requires_operator_visual_review",
            "cameraDistance": "requires_operator_visual_review",
            "cameraMotion": "requires_operator_visual_review",
            "subjectActions": "requires_operator_visual_review",
            "poseSequence": "requires_operator_visual_review",
            "environment": "requires_operator_visual_review",
            "wardrobeConcept": "requires_operator_visual_review",
            "facialPerformanceStyle": "requires_operator_visual_review",
            "originalTextOverlays": "not_transcribed",
            "coarseMotionEnergy": motion,
            "motionIntensity": _motion_label(motion),
        },
        "audio": {
            "identity": (
                {
                    "kind": "embedded_reference_audio",
                    "sourceVideoSha256": reference_sha,
                    "streamIndex": int(audio_streams[0].get("index") or 0),
                }
                if audio_streams
                else None
            ),
            "likelySynchronizationImportance": (
                "operator_confirmation_required" if audio_streams else "low"
            ),
        },
        "routing": {
            "declaredTalking": bool(declared_talking),
            "status": "blocked_unqualified_creator_voice"
            if declared_talking
            else "experimental_seedance_recreation",
            "precisionChoreographySupported": False,
        },
        "analysisLimits": {
            "boundedFrameSamples": 12,
            "semanticFieldsInvented": False,
            "signedSourceUrlRetained": False,
            "providerCalls": 0,
        },
    }
    return {**core, "analysisFingerprint": _fingerprint(core)}


def build_recreation_prompt(analysis: dict[str, Any]) -> dict[str, Any]:
    validate_reference_analysis(analysis)
    structure = analysis["structure"]
    prompt = (
        "Closely follow the supplied reference video's broad performance sequence, "
        "shot progression, pacing, social energy, and camera/framing progression. "
        "Use the supplied approved creator image as the same person throughout. "
        "Recreate the performance with stable facial identity, natural anatomy, "
        "consistent clothing and a casual social-native vertical-video appearance. "
        f"The reference has {structure['shotCount']} shot(s), "
        f"{structure['motionIntensity']} motion intensity, and cut timestamps "
        f"{structure['cutTimestampsSeconds']}. "
        "Do not reproduce source text overlays. Do not add titles, interface chrome, "
        "generated music, ambient audio, or new dialogue. Preserve structure, "
        "performance, and camera progression; choreography similarity is advisory "
        "and must not be described as identical."
    )
    core = {
        "schema": PROMPT_SCHEMA,
        "referenceVideoId": analysis["referenceVideoId"],
        "referenceVideoSha256": analysis["originalLocalFile"]["sha256"],
        "desiredFidelity": ["STRUCTURE", "PERFORMANCE", "CAMERA"],
        "exactChoreographyRequired": False,
        "text": " ".join(prompt.split()),
        "generatedAudio": False,
    }
    return {**core, "promptFingerprint": _fingerprint(core)}


def build_recreation_review(
    *,
    final_sha256: str,
    reference_analysis: dict[str, Any],
    ratings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Retain independent fidelity fields; blanks remain unknown."""

    validate_reference_analysis(reference_analysis)
    values = {
        key: str(value).strip()
        for key, value in (ratings or {}).items()
        if key in RECREATION_REVIEW_FIELDS and str(value).strip()
    }
    return {
        "schema": REVIEW_SCHEMA,
        "finalSha256": _sha(final_sha256, "final_sha256"),
        "referenceVideoSha256": reference_analysis["originalLocalFile"]["sha256"],
        "ratings": values,
        "wouldPost": None,
        "operatorReviewRequired": True,
        "advisoryMeasures": {
            "durationRatio": None,
            "frameRateDifference": None,
            "shotCountDifference": None,
            "cutTimingDifference": None,
            "coarseMotionEnergySimilarity": None,
            "framingProgressionSimilarity": None,
        },
    }


def rank_character_references(
    sources: list[dict[str, Any]], analysis: dict[str, Any]
) -> list[dict[str, Any]]:
    """Rank only already-approved candidates using recorded framing facts."""

    validate_reference_analysis(analysis)
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for source in sources:
        compatibility = source.get("compatibility")
        compatibility = compatibility if isinstance(compatibility, dict) else {}
        facts = compatibility.get("observedFacts")
        facts = facts if isinstance(facts, dict) else {}
        ratio = facts.get("aspectRatio")
        ratio_score = (
            max(0.0, 1.0 - abs(float(ratio) - (9 / 16)) * 4)
            if isinstance(ratio, (int, float))
            else 0.0
        )
        body = str(facts.get("bodyVisibility") or "").lower()
        body_score = {
            "full": 0.25,
            "full_body": 0.25,
            "mid": 0.18,
            "mid_body": 0.18,
            "chest_up": 0.12,
            "close_up": 0.08,
        }.get(body, 0.0)
        score = round(ratio_score + body_score, 6)
        source["recreationCharacterCompatibility"] = {
            "schema": "campaign_factory.recreate_character_compatibility.v1",
            "referenceVideoId": analysis["referenceVideoId"],
            "score": score,
            "signals": {
                "portraitAspectRatio": ratio,
                "recordedBodyVisibility": facts.get("bodyVisibility"),
                "openingFraming": "requires_operator_visual_review",
            },
            "permissionGranted": False,
            "approvedSourceRequired": True,
        }
        ranked.append((score, str(source.get("id") or ""), source))
    return [row[2] for row in sorted(ranked, key=lambda row: (-row[0], row[1]))]


def validate_reference_analysis(value: dict[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != "analysisFingerprint"}
    if core.get("schema") != ANALYSIS_SCHEMA or value.get(
        "analysisFingerprint"
    ) != _fingerprint(core):
        raise ValueError("recreate_reel_reference_analysis_invalid")
    return value


def _safe_reference(path: Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise ValueError("reference video must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"reference video not found: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported reference video type: {resolved.suffix}")
    return resolved


def _ffprobe(path: Path) -> dict[str, Any]:
    command = [
        shutil.which("ffprobe") or "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=60
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ffprobe failed")[-1000:])
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ffprobe returned a non-object")
    return payload


def _duration(probe: dict[str, Any], video: dict[str, Any]) -> float:
    value = video.get("duration") or (probe.get("format") or {}).get("duration")
    if value is None:
        raise ValueError("reference duration is unavailable")
    try:
        duration = round(float(value), 6)
    except (TypeError, ValueError) as exc:
        raise ValueError("reference duration is unavailable") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("reference duration is invalid")
    return duration


def _frame_rate(stream: dict[str, Any]) -> float:
    raw = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = raw.split("/", 1)
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("reference frame rate is invalid") from exc
    return round(value, 6)


def _sample_frame_sha(path: Path, offset: float) -> str:
    completed = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{offset:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
        timeout=90,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError("reference frame sampling failed")
    return hashlib.sha256(completed.stdout).hexdigest()


def _coarse_motion_energy(path: Path, duration: float) -> float:
    samples = 12
    width, height = 64, 112
    fps = max(0.1, (samples - 1) / duration)
    completed = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-vf",
            f"fps={fps:.8f},scale={width}:{height},format=gray",
            "-frames:v",
            str(samples),
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
        timeout=90,
    )
    frame_bytes = width * height
    raw = completed.stdout
    if completed.returncode != 0 or len(raw) < frame_bytes * 2:
        return 0.0
    frames = [
        raw[index : index + frame_bytes]
        for index in range(0, len(raw) - frame_bytes + 1, frame_bytes)
    ][:samples]
    differences = []
    for previous, current in zip(frames, frames[1:], strict=False):
        differences.append(
            sum(
                abs(left - right) for left, right in zip(previous, current, strict=True)
            )
            / (frame_bytes * 255)
        )
    return round(sum(differences) / len(differences), 6) if differences else 0.0


def _motion_label(value: float) -> str:
    if value < 0.025:
        return "low"
    if value < 0.075:
        return "moderate"
    return "high"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _clean(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _sha(value: str, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{label} must be a SHA-256")
    return text
