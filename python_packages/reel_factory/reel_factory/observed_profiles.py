"""Deterministic, pre-audio visual derivatives for supervised experiments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
PROFILE_VERSION = 1
MAX_ATTEMPTS = 40
ENCODER_SETTINGS = {
    "videoCodec": "libx264",
    "crf": 18,
    "preset": "medium",
    "pixelFormat": "yuv420p",
    "imageJpegQuality": 95,
}
CONTENTFORGE_QC_POLICY_FILES = (
    "lib/similarity.js",
    "lib/campaign-factory-audit-config.js",
    "lib/campaign-originality-audit.js",
    "lib/video-analysis-gate.js",
    "lib/virality-gate.js",
    "lib/trusted-media-analysis.js",
    "lib/analyzer-registry.js",
    "analyzer-authority.v2.json",
    "analyzer-validation/production-authority-v2.json",
)

QcCallback = Callable[[Path, Path, list[Path]], dict[str, Any]]
EquivalenceQcCallback = Callable[[Path, Path], bool | dict[str, Any]]


@dataclass(frozen=True)
class ProfileDefinition:
    profile_id: str
    observed_source: str
    supports_images: bool
    supports_videos: bool
    envelope: dict[str, Any]

    @property
    def definition_sha256(self) -> str:
        return _canonical_sha256(
            {
                "id": self.profile_id,
                "version": PROFILE_VERSION,
                "observedSource": self.observed_source,
                "supportsImages": self.supports_images,
                "supportsVideos": self.supports_videos,
                "envelope": self.envelope,
            }
        )


PROFILES = {
    "mirror_crop_tone": ProfileDefinition(
        profile_id="mirror_crop_tone",
        observed_source="ofm",
        supports_images=True,
        supports_videos=True,
        envelope={
            "horizontalCropTotal": [0.02, 0.06],
            "verticalCropTotal": [0.0, 0.03],
            "zoom": [1.01, 1.05],
            "brightness": [-0.015, 0.015],
            "contrast": [0.99, 1.04],
            "saturation": [0.98, 1.04],
            "horizontalMirror": True,
        },
    ),
    "tilt_crop_dark": ProfileDefinition(
        profile_id="tilt_crop_dark",
        observed_source="spoofzy",
        supports_images=True,
        supports_videos=True,
        envelope={
            "rotationDegreesMagnitude": [0.15, 0.45],
            "cropTotal": [0.02, 0.05],
            "zoom": [1.02, 1.06],
            "brightness": [-0.04, -0.015],
            "contrast": [0.98, 1.03],
            "saturation": [0.97, 1.02],
        },
    ),
    "light_editorial": ProfileDefinition(
        profile_id="light_editorial",
        observed_source="creator_os",
        supports_images=True,
        supports_videos=True,
        envelope={
            "cropTotal": [0.005, 0.025],
            "positionShift": [-0.01, 0.01],
            "brightness": [-0.01, 0.01],
            "contrast": [0.99, 1.02],
            "saturation": [0.99, 1.02],
        },
    ),
    "opening_trim": ProfileDefinition(
        profile_id="opening_trim",
        observed_source="ofm",
        supports_images=False,
        supports_videos=True,
        envelope={"openingFrames": [2, 4]},
    ),
}


def normalize_profile_id(value: str) -> str:
    profile, separator, version = str(value or "").strip().partition("@")
    if profile not in PROFILES:
        raise ValueError(f"unsupported observed profile: {value}")
    if separator and version != str(PROFILE_VERSION):
        raise ValueError(f"unsupported observed profile version: {value}")
    return profile


def default_attempt_limit(target_accepted_count: int) -> int:
    if target_accepted_count < 1:
        raise ValueError("count must be positive")
    return min(MAX_ATTEMPTS, max(4, 4 * target_accepted_count))


def render_observed_profile(
    *,
    source_path: Path,
    output_dir: Path,
    parent_asset_id: str,
    expected_source_sha256: str,
    profile: str,
    target_accepted_count: int,
    caption_state: str,
    audio_state: str,
    passive_content: bool,
    synchronized_content: bool,
    visible_text: bool,
    attempt_limit: int | None = None,
    qc_callback: QcCallback | None = None,
    qc_policy_sha256: str | None = None,
    audio_embedder_sha256: str | None = None,
) -> dict[str, Any]:
    """Render up to N accepted derivatives; rejected attempts never consume N."""

    source = source_path.expanduser().resolve()
    output_root = output_dir.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(
            f"observed profile source is not a regular file: {source}"
        )
    source_sha = _sha256_file(source)
    expected_sha = str(expected_source_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("expected_source_sha256 must be a lowercase SHA-256")
    if source_sha != expected_sha:
        raise ValueError("observed profile source SHA-256 mismatch")
    profile_id = normalize_profile_id(profile)
    definition = PROFILES[profile_id]
    count = int(target_accepted_count)
    limit = (
        default_attempt_limit(count) if attempt_limit is None else int(attempt_limit)
    )
    if limit < 1 or limit > MAX_ATTEMPTS:
        raise ValueError(f"attempt_limit must be between 1 and {MAX_ATTEMPTS}")
    media = probe_media_identity(source)
    eligibility = profile_eligibility(
        definition,
        media_type=media["mediaType"],
        caption_state=caption_state,
        audio_state=audio_state,
        passive_content=passive_content,
        synchronized_content=synchronized_content,
        visible_text=visible_text,
    )
    if int(media["width"]) < 64 or int(media["height"]) < 64:
        eligibility["blockers"].append("unsupported_dimensions")
        eligibility["eligible"] = False
    toolchain = toolchain_receipt(
        qc_policy_sha256=qc_policy_sha256,
        audio_embedder_sha256=audio_embedder_sha256,
    )
    receipt: dict[str, Any] = {
        "schema": "creator_os.visual_derivative_receipt.v1",
        "parentAssetId": str(parent_asset_id),
        "source": media,
        "profile": {
            "id": profile_id,
            "version": PROFILE_VERSION,
            "observedSource": definition.observed_source,
            "definitionSha256": definition.definition_sha256,
        },
        "eligibility": eligibility,
        "targetAcceptedCount": count,
        "actualAcceptedCount": 0,
        "attemptLimit": limit,
        "attempts": [],
        "accepted": [],
        "exhaustionReasons": [],
        "toolchain": toolchain,
        "createdAt": _utc_now(),
    }
    if not eligibility["eligible"]:
        receipt["exhaustionReasons"] = list(eligibility["blockers"])
        return receipt

    output_root.mkdir(parents=True, exist_ok=True)
    accepted_paths: list[Path] = []
    accepted_shas: set[str] = set()
    retry_for_slot = 0
    for candidate_index in range(1, limit + 1):
        if len(accepted_paths) >= count:
            break
        retry_for_slot += 1
        seed = hashlib.sha256(
            (
                f"{source_sha}:{profile_id}@{PROFILE_VERSION}:"
                f"{candidate_index}:{retry_for_slot}"
            ).encode()
        ).hexdigest()
        sampled = sample_profile_parameters(definition, seed=seed, media=media)
        extension = _output_extension(source, media["mediaType"])
        output = output_root / (
            f"{_safe_name(parent_asset_id)}_{profile_id}_"
            f"candidate_{candidate_index:02d}{extension}"
        )
        command = build_ffmpeg_command(
            source=source,
            output=output,
            media=media,
            profile_id=profile_id,
            sampled=sampled,
        )
        attempt = {
            "candidateIndex": candidate_index,
            "attempt": retry_for_slot,
            "seed": seed,
            "sampledParameters": sampled,
            "status": "render_failed",
            "reasons": [],
        }
        try:
            _run(command, timeout=300)
            if media["mediaType"] == "image":
                _strip_image_metadata(output)
            output_media = probe_media_identity(output)
            integrity_reasons = _output_integrity_reasons(
                source=media,
                output=output_media,
                profile_id=profile_id,
                sampled=sampled,
            )
            output_sha = output_media["sha256"]
            if output_sha == source_sha:
                integrity_reasons.append("output_matches_source")
            if output_sha in accepted_shas:
                integrity_reasons.append("duplicate_accepted_output")
            qc = (
                qc_callback(source, output, list(accepted_paths))
                if qc_callback
                else {
                    "status": "passed" if not integrity_reasons else "failed",
                    "blockingCodes": list(integrity_reasons),
                }
            )
            blocking_codes = list(
                dict.fromkeys(
                    [
                        *integrity_reasons,
                        *[
                            str(code)
                            for code in (qc.get("blockingCodes") or [])
                            if str(code).strip()
                        ],
                    ]
                )
            )
            if qc.get("status") != "passed":
                blocking_codes.append("contentforge_qc_failed")
            blocking_codes = list(dict.fromkeys(blocking_codes))
            if blocking_codes:
                attempt["status"] = "rejected"
                attempt["reasons"] = blocking_codes
                output.unlink(missing_ok=True)
            else:
                accepted_index = len(accepted_paths) + 1
                attempt["status"] = "accepted"
                receipt["accepted"].append(
                    {
                        "candidateIndex": candidate_index,
                        "acceptedIndex": accepted_index,
                        "attempt": retry_for_slot,
                        "sampledParameters": sampled,
                        "ffmpegArgs": command,
                        "metadataPolicy": "strip_inherited",
                        "output": output_media,
                        "qc": {
                            **qc,
                            "status": "passed",
                            "blockingCodes": [],
                        },
                    }
                )
                accepted_paths.append(output)
                accepted_shas.add(output_sha)
                retry_for_slot = 0
        except Exception as exc:
            output.unlink(missing_ok=True)
            attempt["status"] = "render_failed"
            attempt["reasons"] = [f"render_failed:{type(exc).__name__}:{exc}"]
        receipt["attempts"].append(attempt)

    receipt["actualAcceptedCount"] = len(accepted_paths)
    if len(accepted_paths) < count:
        receipt["exhaustionReasons"] = _exhaustion_reasons(receipt["attempts"])
    _atomic_write_json(
        output_root
        / f"{_safe_name(parent_asset_id)}_{profile_id}.visual_derivative_receipt.json",
        receipt,
    )
    return receipt


def profile_eligibility(
    definition: ProfileDefinition,
    *,
    media_type: str,
    caption_state: str,
    audio_state: str,
    passive_content: bool,
    synchronized_content: bool,
    visible_text: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    if media_type == "image" and not definition.supports_images:
        blockers.append("profile_does_not_support_images")
    if media_type == "video" and not definition.supports_videos:
        blockers.append("profile_does_not_support_videos")
    if caption_state != "uncaptioned_verified":
        blockers.append("uncaptioned_source_evidence_missing")
    if audio_state not in {"none", "pre_final"}:
        blockers.append("pre_final_audio_state_required")
    if not passive_content:
        blockers.append("passive_content_required")
    if synchronized_content:
        blockers.append("synchronized_content_ineligible")
    if definition.profile_id == "mirror_crop_tone" and visible_text:
        blockers.append("mirror_visible_text_ineligible")
    return {
        "eligible": not blockers,
        "mediaType": media_type,
        "captionState": caption_state
        if caption_state in {"uncaptioned_verified", "captioned", "unknown"}
        else "unknown",
        "audioState": audio_state
        if audio_state in {"none", "pre_final", "final_bound", "unknown"}
        else "unknown",
        "passiveContent": bool(passive_content),
        "synchronizedContent": bool(synchronized_content),
        "visibleText": bool(visible_text),
        "blockers": blockers,
    }


def sample_profile_parameters(
    definition: ProfileDefinition, *, seed: str, media: dict[str, Any]
) -> dict[str, Any]:
    rng = random.Random(int(seed[:16], 16))
    envelope = definition.envelope

    def value(name: str, digits: int = 6) -> float:
        lower, upper = envelope[name]
        return round(rng.uniform(float(lower), float(upper)), digits)

    if definition.profile_id == "mirror_crop_tone":
        return {
            "horizontalMirror": True,
            "horizontalCropTotal": value("horizontalCropTotal"),
            "verticalCropTotal": value("verticalCropTotal"),
            "zoom": value("zoom"),
            "horizontalBias": round(rng.uniform(-0.3, 0.3), 6),
            "verticalBias": round(rng.uniform(-0.3, 0.3), 6),
            "brightness": value("brightness"),
            "contrast": value("contrast"),
            "saturation": value("saturation"),
        }
    if definition.profile_id == "tilt_crop_dark":
        magnitude = value("rotationDegreesMagnitude")
        return {
            "rotationDegrees": magnitude if rng.random() >= 0.5 else -magnitude,
            "cropTotal": value("cropTotal"),
            "zoom": value("zoom"),
            "horizontalBias": round(rng.uniform(-0.2, 0.2), 6),
            "verticalBias": round(rng.uniform(-0.2, 0.2), 6),
            "brightness": value("brightness"),
            "contrast": value("contrast"),
            "saturation": value("saturation"),
        }
    if definition.profile_id == "light_editorial":
        return {
            "cropTotal": value("cropTotal"),
            "positionShiftX": value("positionShift"),
            "positionShiftY": value("positionShift"),
            "brightness": value("brightness"),
            "contrast": value("contrast"),
            "saturation": value("saturation"),
        }
    if definition.profile_id == "opening_trim":
        lower, upper = envelope["openingFrames"]
        return {
            "openingFrames": rng.randint(int(lower), int(upper)),
            "fps": media.get("fps"),
        }
    raise ValueError(f"unsupported observed profile: {definition.profile_id}")


def build_ffmpeg_command(
    *,
    source: Path,
    output: Path,
    media: dict[str, Any],
    profile_id: str,
    sampled: dict[str, Any],
) -> list[str]:
    width = int(media["width"])
    height = int(media["height"])
    filters = _video_filters(
        width=width,
        height=height,
        profile_id=profile_id,
        sampled=sampled,
    )
    command = [FFMPEG, "-hide_banner", "-y", "-nostdin", "-i", str(source)]
    if filters:
        command.extend(["-vf", ",".join(filters)])
    command.extend(["-map_metadata", "-1", "-map_chapters", "-1"])
    if media["mediaType"] == "image":
        command.extend(["-frames:v", "1"])
        if output.suffix.lower() in {".jpg", ".jpeg"}:
            command.extend(["-q:v", "2"])
        else:
            command.extend(["-compression_level", "4"])
    else:
        command.extend(
            [
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                str(ENCODER_SETTINGS["crf"]),
                "-preset",
                str(ENCODER_SETTINGS["preset"]),
                "-pix_fmt",
                str(ENCODER_SETTINGS["pixelFormat"]),
                "-movflags",
                "+faststart",
            ]
        )
    command.append(str(output))
    return command


def _video_filters(
    *, width: int, height: int, profile_id: str, sampled: dict[str, Any]
) -> list[str]:
    if profile_id == "opening_trim":
        return [
            f"trim=start_frame={int(sampled['openingFrames'])}",
            "setpts=PTS-STARTPTS",
        ]
    filters: list[str] = []
    if sampled.get("horizontalMirror"):
        filters.append("hflip")
    if "rotationDegrees" in sampled:
        radians = float(sampled["rotationDegrees"]) * math.pi / 180.0
        filters.append(f"rotate={radians:.10f}:ow=iw:oh=ih:fillcolor=black")
    horizontal_crop = float(
        sampled.get("horizontalCropTotal", sampled.get("cropTotal", 0.0))
    )
    vertical_crop = float(
        sampled.get("verticalCropTotal", sampled.get("cropTotal", 0.0))
    )
    zoom = max(1.0, float(sampled.get("zoom", 1.0)))
    horizontal_crop = 1.0 - ((1.0 - horizontal_crop) / zoom)
    vertical_crop = 1.0 - ((1.0 - vertical_crop) / zoom)
    if horizontal_crop or vertical_crop:
        crop_width = _even_dimension(width * (1.0 - horizontal_crop))
        crop_height = _even_dimension(height * (1.0 - vertical_crop))
        spare_x = max(0, width - crop_width)
        spare_y = max(0, height - crop_height)
        x_bias = float(
            sampled.get("horizontalBias", sampled.get("positionShiftX", 0.0))
        )
        y_bias = float(sampled.get("verticalBias", sampled.get("positionShiftY", 0.0)))
        x = max(0, min(spare_x, round((spare_x / 2) + (x_bias * width))))
        y = max(0, min(spare_y, round((spare_y / 2) + (y_bias * height))))
        filters.extend(
            [
                f"crop={crop_width}:{crop_height}:{x}:{y}",
                f"scale={width}:{height}:flags=lanczos",
            ]
        )
    filters.append(
        "eq="
        f"brightness={float(sampled.get('brightness', 0.0)):.6f}:"
        f"contrast={float(sampled.get('contrast', 1.0)):.6f}:"
        f"saturation={float(sampled.get('saturation', 1.0)):.6f}"
    )
    return filters


def probe_media_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    suffix = resolved.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        with Image.open(resolved) as image:
            width, height = image.size
        return {
            "path": str(resolved),
            "sha256": _sha256_file(resolved),
            "mediaType": "image",
            "byteSize": resolved.stat().st_size,
            "width": width,
            "height": height,
            "fps": None,
            "durationSeconds": None,
            "audioPresent": None,
        }
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError(f"unsupported observed profile media type: {suffix}")
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(resolved),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "ffprobe failed").strip())
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise ValueError("observed profile source has no video stream")
    fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    duration = _number((payload.get("format") or {}).get("duration"))
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "mediaType": "video",
        "byteSize": resolved.stat().st_size,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "durationSeconds": duration,
        "audioPresent": any(item.get("codec_type") == "audio" for item in streams),
    }


def toolchain_receipt(
    *,
    qc_policy_sha256: str | None = None,
    audio_embedder_sha256: str | None = None,
) -> dict[str, str]:
    renderer_path = Path(__file__).resolve()
    ffmpeg_version = _command_output([FFMPEG, "-version"]).splitlines()[0]
    ffmpeg_build_sha = hashlib.sha256(
        _command_output([FFMPEG, "-version"]).encode("utf-8")
    ).hexdigest()
    audio_embedder = renderer_path.with_name("audio_mux.py")
    values = {
        "repositorySha": _repository_sha(renderer_path),
        "rendererImplementationSha256": _sha256_file(renderer_path),
        "ffmpegVersion": ffmpeg_version,
        "ffmpegBuildSha256": ffmpeg_build_sha,
        "encoderSettingsSha256": _canonical_sha256(ENCODER_SETTINGS),
        "audioEmbedderSha256": (
            str(audio_embedder_sha256)
            if re.fullmatch(r"[0-9a-f]{64}", str(audio_embedder_sha256 or ""))
            else _sha256_file(audio_embedder)
        ),
        "qcPolicySha256": _resolved_qc_policy_sha256(qc_policy_sha256),
    }
    values["fingerprint"] = _canonical_sha256(values)
    return values


def renderer_runtime_receipt(
    *,
    qc_policy_sha256: str | None = None,
    audio_embedder_sha256: str | None = None,
) -> dict[str, Any]:
    """Fingerprint the exact renderer, codecs, fonts, and host instance."""

    renderer_path = Path(__file__).resolve()
    ffmpeg_path = Path(shutil.which(FFMPEG) or FFMPEG).expanduser().resolve()
    ffprobe_path = Path(shutil.which(FFPROBE) or FFPROBE).expanduser().resolve()
    if not ffmpeg_path.is_file() or not ffprobe_path.is_file():
        raise RuntimeError("renderer runtime executables are unavailable")

    def executable(path: Path, *, capabilities: list[list[str]]) -> dict[str, str]:
        version_output = _command_output([str(path), "-version"])
        capability_material = "\n".join(
            _command_output([str(path), *arguments]) for arguments in capabilities
        )
        return {
            "path": str(path),
            "sha256": _sha256_file(path),
            "version": version_output.splitlines()[0],
            "capabilitiesSha256": hashlib.sha256(
                capability_material.encode("utf-8")
            ).hexdigest(),
        }

    ffmpeg = executable(
        ffmpeg_path,
        capabilities=[
            ["-hide_banner", "-encoders"],
            ["-hide_banner", "-decoders"],
            ["-hide_banner", "-filters"],
        ],
    )
    ffprobe = executable(ffprobe_path, capabilities=[["-buildconf"]])
    font_root = renderer_path.with_name("fonts").resolve()
    fonts = [
        {
            "ref": f"fonts/{path.name}",
            "sha256": _sha256_file(path),
        }
        for path in sorted(font_root.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.suffix.lower() in {".ttf", ".otf", ".woff2"}
    ]
    if not fonts:
        raise RuntimeError("renderer font inventory is unavailable")
    host = {
        "system": platform.system() or "unknown",
        "release": platform.release() or "unknown",
        "machine": platform.machine() or "unknown",
        "python": platform.python_version(),
        "hostInstanceSha256": hashlib.sha256(
            (platform.node() or "unknown-host").encode("utf-8")
        ).hexdigest(),
    }
    codec_policy = {
        "videoCodec": str(ENCODER_SETTINGS["videoCodec"]),
        "pixelFormat": str(ENCODER_SETTINGS["pixelFormat"]),
        "imageJpegQuality": int(ENCODER_SETTINGS["imageJpegQuality"]),
        "identityAudioPolicy": "copy_if_present",
    }
    audio_embedder = renderer_path.with_name("audio_mux.py")
    values: dict[str, Any] = {
        "repositorySha": _repository_sha(renderer_path),
        "rendererImplementationSha256": _sha256_file(renderer_path),
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "fonts": fonts,
        "fontsFingerprint": _canonical_sha256(fonts),
        "host": host,
        "hostFingerprint": _canonical_sha256(host),
        "codecPolicy": codec_policy,
        "codecPolicyFingerprint": _canonical_sha256(codec_policy),
        "encoderSettingsSha256": _canonical_sha256(ENCODER_SETTINGS),
        "audioEmbedderSha256": (
            str(audio_embedder_sha256)
            if re.fullmatch(r"[0-9a-f]{64}", str(audio_embedder_sha256 or ""))
            else _sha256_file(audio_embedder)
        ),
        "qcPolicySha256": _resolved_qc_policy_sha256(qc_policy_sha256),
    }
    values["fingerprint"] = _canonical_sha256(values)
    return values


def qualify_renderer_equivalence(
    *,
    source_path: Path,
    output_path: Path,
    receipt_path: Path,
    minimum_ssim: float = 0.995,
    qc_policy_sha256: str | None = None,
    audio_embedder_sha256: str | None = None,
    qc_regression_callback: EquivalenceQcCallback | None = None,
) -> dict[str, Any]:
    """Render an identity artifact and bind qualification to the toolchain."""

    source = source_path.expanduser().resolve()
    output = output_path.expanduser().resolve()
    source_media = probe_media_identity(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        FFMPEG,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
    ]
    if source_media["mediaType"] == "image":
        command.extend(["-frames:v", "1"])
        command.extend(
            ["-q:v", "2"]
            if output.suffix.lower() in {".jpg", ".jpeg"}
            else ["-compression_level", "4"]
        )
    else:
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-crf",
                str(ENCODER_SETTINGS["crf"]),
                "-preset",
                str(ENCODER_SETTINGS["preset"]),
                "-pix_fmt",
                str(ENCODER_SETTINGS["pixelFormat"]),
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
            ]
        )
    command.append(str(output))
    _run(command, timeout=300)
    if source_media["mediaType"] == "image":
        _strip_image_metadata(output)
    output_media = probe_media_identity(output)
    ssim = _measure_ssim(source, output)
    fps = float(source_media.get("fps") or 1.0)
    source_duration = float(source_media.get("durationSeconds") or 0.0)
    output_duration = float(output_media.get("durationSeconds") or 0.0)
    checks = {
        "dimensionsEqual": (
            source_media["width"],
            source_media["height"],
        )
        == (output_media["width"], output_media["height"]),
        "frameRateEqual": source_media.get("fps") == output_media.get("fps"),
        "durationWithinOneFrame": source_media["mediaType"] == "image"
        or abs(source_duration - output_duration) <= (1.0 / max(fps, 1.0)),
        "audioPolicyEqual": source_media.get("audioPresent")
        == output_media.get("audioPresent"),
    }
    resolved_qc_policy_sha256 = _resolved_qc_policy_sha256(qc_policy_sha256)
    raw_qc_evidence = (
        qc_regression_callback(source, output) if qc_regression_callback else None
    )
    if isinstance(raw_qc_evidence, dict):
        qc_regression = bool(raw_qc_evidence.get("regressed"))
        qc_evidence = {
            "evaluated": True,
            "policySha256": resolved_qc_policy_sha256,
            "baselineReport": raw_qc_evidence.get("baselineReport"),
            "identityReport": raw_qc_evidence.get("identityReport"),
            "newBlockingCodes": sorted(
                {
                    str(code)
                    for code in raw_qc_evidence.get("newBlockingCodes", [])
                    if str(code)
                }
            ),
        }
    else:
        qc_regression = bool(raw_qc_evidence)
        qc_evidence = {
            "evaluated": False,
            "policySha256": resolved_qc_policy_sha256,
            "baselineReport": None,
            "identityReport": None,
            "newBlockingCodes": [],
        }
    qualified = (
        all(checks.values())
        and ssim >= minimum_ssim
        and not qc_regression
        and qc_evidence["evaluated"]
    )
    toolchain = renderer_runtime_receipt(
        qc_policy_sha256=resolved_qc_policy_sha256,
        audio_embedder_sha256=audio_embedder_sha256,
    )
    source_identity = _portable_media_identity(source_media)
    output_identity = _portable_media_identity(output_media)
    duration_delta = abs(source_duration - output_duration)
    duration_delta_frames = (
        0.0 if source_media["mediaType"] == "image" else duration_delta * max(fps, 1.0)
    )
    fixture_id = (
        "control_"
        + _canonical_sha256(
            {
                "sourceSha256": source_media["sha256"],
                "mediaClass": _media_class(source_media),
            }
        )[:24]
    )
    core: dict[str, Any] = {
        "schema": "creator_os.renderer_equivalence_receipt.v2",
        "qualificationId": "renderer_qualification_"
        + _canonical_sha256(
            {
                "fixtureId": fixture_id,
                "toolchainFingerprint": toolchain["fingerprint"],
            }
        )[:24],
        "mediaClass": _media_class(source_media),
        "toolchain": toolchain,
        "fixture": {
            "fixtureId": fixture_id,
            "kind": "exact_control_bytes",
            "inputSha256": source_media["sha256"],
            "deterministicInput": True,
        },
        "equivalencePolicy": {
            "policyId": "reel_factory.renderer_equivalence",
            "policyVersion": "2.0.0",
            "qualificationScope": "exact_toolchain_and_host",
            "crossMachineByteReproducibility": "not_claimed",
            "byteIdentityRequired": False,
            "minimumSsim": minimum_ssim,
            "maximumDurationDeltaFrames": 1,
            "requiredStreamChecks": [
                "dimensions",
                "frame_rate",
                "duration",
                "audio_policy",
            ],
        },
        "source": source_identity,
        "identityOutput": output_identity,
        "checks": checks,
        "measurements": {
            "ssim": round(ssim, 6),
            "byteIdentical": source_media["sha256"] == output_media["sha256"],
            "durationDeltaSeconds": round(duration_delta, 9),
            "durationDeltaFrames": round(duration_delta_frames, 9),
        },
        "qcEvidence": qc_evidence,
        "qcRegression": bool(qc_regression),
        "status": "qualified" if qualified else "failed",
        "qualifiedAt": _utc_now(),
    }
    receipt = {**core, "receiptFingerprint": _canonical_sha256(core)}
    _atomic_write_json(receipt_path.expanduser().resolve(), receipt)
    return receipt


def _portable_media_identity(media: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": media["sha256"],
        "mediaType": media["mediaType"],
        "byteSize": int(media["byteSize"]),
        "width": int(media["width"]),
        "height": int(media["height"]),
        "fps": media.get("fps"),
        "durationSeconds": media.get("durationSeconds"),
        "audioPresent": media.get("audioPresent"),
    }


def _measure_ssim(source: Path, output: Path) -> float:
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-i",
            str(source),
            "-i",
            str(output),
            "-lavfi",
            "ssim",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    match = re.search(r"All:([0-9.]+)", result.stderr or "")
    if result.returncode != 0 or match is None:
        raise RuntimeError("renderer equivalence SSIM measurement failed")
    return float(match.group(1))


def _output_integrity_reasons(
    *,
    source: dict[str, Any],
    output: dict[str, Any],
    profile_id: str,
    sampled: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if (source["width"], source["height"]) != (output["width"], output["height"]):
        reasons.append("output_dimensions_changed")
    if source["mediaType"] != output["mediaType"]:
        reasons.append("output_media_type_changed")
    if output["mediaType"] == "video":
        if (
            not output.get("fps")
            or abs(float(source.get("fps") or 0) - float(output.get("fps") or 0)) > 0.01
        ):
            reasons.append("output_frame_rate_changed")
        if output.get("audioPresent"):
            reasons.append("pre_audio_output_contains_audio")
        source_duration = float(source.get("durationSeconds") or 0)
        output_duration = float(output.get("durationSeconds") or 0)
        expected = source_duration
        if profile_id == "opening_trim":
            expected -= int(sampled["openingFrames"]) / float(source.get("fps") or 1)
        tolerance = max(0.12, 2 / float(source.get("fps") or 1))
        if output_duration <= 0 or abs(output_duration - expected) > tolerance:
            reasons.append("output_duration_mismatch")
    return reasons


def _output_extension(source: Path, media_type: str) -> str:
    if media_type == "video":
        return ".mp4"
    return ".png" if source.suffix.lower() == ".png" else ".jpg"


def _exhaustion_reasons(attempts: list[dict[str, Any]]) -> list[str]:
    reasons = [
        str(reason)
        for attempt in attempts
        for reason in attempt.get("reasons") or []
        if str(reason).strip()
    ]
    return list(dict.fromkeys(reasons)) or ["attempt_limit_exhausted"]


def _media_class(media: dict[str, Any]) -> str:
    if media["mediaType"] == "image":
        return f"image:{media['width']}x{media['height']}"
    return (
        f"video:{media['width']}x{media['height']}:"
        f"{float(media.get('fps') or 0):.3f}:"
        f"{'audio' if media.get('audioPresent') else 'silent'}"
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("_") or "asset"


def _even_dimension(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def _run(command: list[str], *, timeout: int) -> None:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(detail[-2000:])


def _strip_image_metadata(path: Path) -> None:
    with Image.open(path) as image:
        pixels = (
            image.convert("RGB")
            if path.suffix.lower() in {".jpg", ".jpeg"}
            else image.copy()
        )
    temporary = path.with_name(f"{path.stem}.metadata-scrub{path.suffix}")
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        pixels.save(temporary, format="JPEG", quality=95, optimize=False)
    else:
        pixels.save(temporary, format="PNG", compress_level=4)
    temporary.replace(path)


def _command_output(command: list[str]) -> str:
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "command failed").strip())
    return result.stdout or result.stderr


def _repository_sha(path: Path) -> str:
    configured = os.environ.get("CREATOR_OS_SOURCE_SHA", "").strip()
    if configured:
        return configured
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else _sha256_file(path)[:12]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contentforge_qc_policy_sha256(contentforge_root: Path | None = None) -> str:
    root = (
        contentforge_root.expanduser().resolve()
        if contentforge_root is not None
        else Path(__file__).resolve().parents[3] / "packages" / "contentforge"
    )
    materials = []
    for relative in CONTENTFORGE_QC_POLICY_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"ContentForge QC policy material is missing: {path}")
        materials.append({"path": relative, "sha256": _sha256_file(path)})
    return _canonical_sha256(materials)


def _resolved_qc_policy_sha256(value: str | None) -> str:
    if value is None:
        return contentforge_qc_policy_sha256()
    resolved = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", resolved):
        raise ValueError("qc_policy_sha256 must be a lowercase SHA-256")
    return resolved


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_rate(value: Any) -> float:
    text = str(value or "")
    if not text or text == "0/0":
        return 0.0
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / max(float(denominator), 1.0)
    return float(text)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
