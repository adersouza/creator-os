"""Deterministic frame harvesting and provider-backed still editing."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

import imagehash
import requests
from PIL import Image, ImageFilter, ImageStat

DERIVED_STILL_SCHEMA = "campaign_factory.derived_still_source.v1"
PROMPT_BUILDER_VERSION = "derived_still_edit.v1"
EXPECTED_MODELS = {
    "gemini": "gemini-3-pro-image",
    "openai": "gpt-image-2",
}
PILOT_COLORWAYS = (
    "black",
    "white",
    "red",
    "royal blue",
    "emerald green",
    "soft pink",
)
LOCALITY_THRESHOLDS = {
    "colorway": {
        "identityScoreLossMax": 0.05,
        "faceBoxIouMin": 0.90,
        "poseLandmarkDriftMax": 0.03,
        "personSilhouetteIouMin": 0.94,
        "backgroundSsimMin": 0.97,
        "protectedFaceRegionSsimMin": 0.95,
        "garmentRegionChangeMin": 0.05,
    },
    "outfit_swap": {
        "identityScoreLossMax": 0.05,
        "faceBoxIouMin": 0.85,
        "poseLandmarkDriftMax": 0.06,
        "personSilhouetteIouMin": 0.88,
        "backgroundSsimMin": 0.94,
        "protectedFaceRegionSsimMin": 0.92,
        "garmentRegionChangeMin": 0.12,
    },
}


class ImageEditProvider(Protocol):
    provider: str
    model: str

    def preflight(self) -> dict[str, Any]: ...

    def quote(self, *, count: int, output_format: str) -> dict[str, Any]: ...

    def generate(
        self,
        *,
        source: Path,
        prompt: str,
        count: int,
        output_format: str,
    ) -> dict[str, Any]: ...


class _HttpImageEditProvider:
    provider = ""
    api_key_env = ""
    quote_env = ""

    def __init__(self, *, model: str | None = None, timeout_seconds: int = 180) -> None:
        self.model = model or EXPECTED_MODELS[self.provider]
        self.timeout_seconds = timeout_seconds

    def preflight(self) -> dict[str, Any]:
        if self.model != EXPECTED_MODELS[self.provider]:
            raise ValueError(
                f"{self.provider} model must be {EXPECTED_MODELS[self.provider]}"
            )
        if not os.environ.get(self.api_key_env):
            raise RuntimeError(f"{self.api_key_env}_missing")
        return {
            "provider": self.provider,
            "model": self.model,
            "authenticated": True,
        }

    def quote(self, *, count: int, output_format: str) -> dict[str, Any]:
        raw = os.environ.get(self.quote_env)
        try:
            amount = float(raw or "")
        except ValueError as exc:
            raise RuntimeError(f"{self.quote_env}_invalid") from exc
        if not math.isfinite(amount) or amount <= 0:
            raise RuntimeError(f"{self.quote_env}_missing")
        return {
            "provider": self.provider,
            "model": self.model,
            "amount": amount,
            "unit": "USD",
            "count": count,
            "format": output_format,
            "source": "operator_configured_exact_quote",
        }


class OpenAIImageEditProvider(_HttpImageEditProvider):
    provider = "openai"
    api_key_env = "OPENAI_API_KEY"
    quote_env = "OPENAI_IMAGE_EDIT_QUOTE_USD"

    def generate(
        self,
        *,
        source: Path,
        prompt: str,
        count: int,
        output_format: str,
    ) -> dict[str, Any]:
        self.preflight()
        with source.open("rb") as handle:
            response = requests.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
                files={"image": (source.name, handle, _mime(source))},
                data={
                    "model": self.model,
                    "prompt": prompt,
                    "n": str(1 if output_format == "grid_2x3" else count),
                    "size": "4096x4096" if output_format == "grid_2x3" else "1024x1536",
                    "response_format": "b64_json",
                },
                timeout=(15, self.timeout_seconds),
            )
        response.raise_for_status()
        body = response.json()
        images = [
            base64.b64decode(str(item["b64_json"]))
            for item in body.get("data") or []
            if isinstance(item, dict) and item.get("b64_json")
        ]
        return {
            "provider": self.provider,
            "model": self.model,
            "requestId": response.headers.get("x-request-id"),
            "images": images,
            "usage": body.get("usage"),
            "raw": {"created": body.get("created")},
        }


class GeminiImageEditProvider(_HttpImageEditProvider):
    provider = "gemini"
    api_key_env = "GEMINI_API_KEY"
    quote_env = "GEMINI_IMAGE_EDIT_QUOTE_USD"

    def generate(
        self,
        *,
        source: Path,
        prompt: str,
        count: int,
        output_format: str,
    ) -> dict[str, Any]:
        self.preflight()
        response = requests.post(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent"
            ),
            headers={
                "x-goog-api-key": os.environ[self.api_key_env],
                "Content-Type": "application/json",
            },
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    "mimeType": _mime(source),
                                    "data": base64.b64encode(
                                        source.read_bytes()
                                    ).decode(),
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
            timeout=(15, self.timeout_seconds),
        )
        response.raise_for_status()
        body = response.json()
        images: list[bytes] = []
        for candidate in body.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if isinstance(inline, dict) and inline.get("data"):
                    images.append(base64.b64decode(str(inline["data"])))
        return {
            "provider": self.provider,
            "model": self.model,
            "requestId": response.headers.get("x-request-id"),
            "images": images,
            "usage": body.get("usageMetadata"),
            "raw": {"modelVersion": body.get("modelVersion")},
        }


def provider_adapter(provider: str) -> ImageEditProvider:
    if provider == "openai":
        return OpenAIImageEditProvider()
    if provider == "gemini":
        return GeminiImageEditProvider()
    raise ValueError(f"unsupported still-edit provider: {provider}")


def build_edit_prompt(
    *,
    operation: str,
    output_format: str,
    count: int,
    colors: tuple[str, ...] = PILOT_COLORWAYS,
) -> str:
    if operation not in LOCALITY_THRESHOLDS:
        raise ValueError("operation must be colorway or outfit_swap")
    if output_format not in {"individual", "grid_2x3"}:
        raise ValueError("format must be individual or grid_2x3")
    variants = colors[:count]
    change = (
        "Change only the existing garment color, using these colors in order: "
        + ", ".join(variants)
        if operation == "colorway"
        else "Replace only the outfit, producing distinct tasteful outfits"
    )
    layout = (
        "Return one square 4K composite with exactly two rows and three columns. "
        "Every cell must be a complete 2:3 portrait with no gutters, labels, or text."
        if output_format == "grid_2x3"
        else f"Return exactly {count} separate 2:3 portrait images."
    )
    return (
        f"{change}. Preserve identity, body proportions, skin tone, pose, camera, "
        "lighting, background, hands, and framing exactly. Do not add text or UI. "
        f"{layout}"
    )


def split_grid_2x3(raw: bytes, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise ValueError("provider grid is not a readable image") from exc
    width, height = image.size
    if width != height or width < 3840:
        raise ValueError("grid_2x3 requires one square 4K composite")
    x_edges = (0, width // 3, (2 * width) // 3, width)
    y_edges = (0, height // 2, height)
    panels: list[Path] = []
    for row in range(2):
        for column in range(3):
            panel = image.crop(
                (
                    x_edges[column],
                    y_edges[row],
                    x_edges[column + 1],
                    y_edges[row + 1],
                )
            )
            if panel.width < 720 or panel.height < 1280:
                raise ValueError("grid panel dimensions are below 720x1280")
            ratio = panel.width / panel.height
            if not 0.64 <= ratio <= 0.69:
                raise ValueError("grid panel is not a recoverable 2:3 portrait")
            path = output_dir / f"panel_{row + 1}_{column + 1}.png"
            panel.save(path, format="PNG")
            panels.append(path)
    if len(panels) != 6:
        raise ValueError("six valid grid panels could not be recovered")
    return panels


def materialize_individual_outputs(
    images: list[bytes], output_dir: Path, *, count: int
) -> list[Path]:
    if len(images) < count:
        raise ValueError(
            f"provider returned {len(images)} individual images; expected {count}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, raw in enumerate(images[:count], start=1):
        try:
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:
            raise ValueError(f"provider image {index} is unreadable") from exc
        if image.width < 720 or image.height < 1280:
            raise ValueError(f"provider image {index} is below 720x1280")
        path = output_dir / f"variation_{index}.png"
        image.save(path, format="PNG")
        paths.append(path)
    return paths


def harvest_animation_frames(
    video: Path,
    output_dir: Path,
    *,
    count: int = 6,
    expected_sha256: str | None = None,
    evaluator: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= 6:
        raise ValueError("harvest count must be between 1 and 6")
    video = video.expanduser().resolve()
    if video.is_symlink() or not video.is_file():
        raise ValueError("animation source must be a regular file")
    digest = _sha256_file(video)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError("parent raw visual SHA mismatch")
    probe = _probe_video(video)
    if probe["width"] < 720 or probe["height"] < 1280:
        raise ValueError("animation dimensions are below 720x1280")
    output_dir.mkdir(parents=True, exist_ok=True)
    cuts = _scene_cuts(video, float(probe["durationSeconds"]))
    times = _candidate_times(float(probe["durationSeconds"]), cuts)
    candidates: list[dict[str, Any]] = []
    for index, stamp in enumerate(times):
        path = output_dir / f"candidate_{index + 1:03d}_{stamp:08.3f}.png"
        _extract_frame(video, path, stamp)
        evidence = (evaluator or evaluate_harvest_frame)(path)
        candidates.append(
            {
                "timeSec": stamp,
                "path": str(path),
                "sha256": _sha256_file(path),
                **evidence,
            }
        )
    selected: list[dict[str, Any]] = []
    selected_hashes: list[Any] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-float(item.get("score") or 0), float(item["timeSec"])),
    ):
        if candidate.get("eligible") is not True:
            continue
        if any(
            abs(float(candidate["timeSec"]) - float(item["timeSec"])) < 0.5
            for item in selected
        ):
            candidate.setdefault("rejections", []).append("temporal_sibling")
            continue
        perceptual = imagehash.phash(Image.open(candidate["path"]).convert("RGB"))
        if any(perceptual - prior < 6 for prior in selected_hashes):
            candidate.setdefault("rejections", []).append("perceptual_sibling")
            continue
        selected.append(candidate)
        selected_hashes.append(perceptual)
        if len(selected) == count:
            break
    contact_sheet = _contact_sheet(
        [Path(item["path"]) for item in selected],
        output_dir / "contact_sheet.jpg",
    )
    return {
        "schema": "reel_factory.animation_frame_harvest.v1",
        "source": {"path": str(video), "sha256": digest, "probe": probe},
        "sceneCutsSeconds": cuts,
        "candidateFrames": candidates,
        "selectedFrames": selected,
        "requestedCount": count,
        "acceptedCount": len(selected),
        "contactSheet": (
            {"path": str(contact_sheet), "sha256": _sha256_file(contact_sheet)}
            if contact_sheet
            else None
        ),
        "exhaustionReasons": sorted(
            {reason for item in candidates for reason in item.get("rejections") or []}
        )
        if len(selected) < count
        else [],
    }


def evaluate_harvest_frame(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    gray = image.convert("L")
    mean = float(ImageStat.Stat(gray).mean[0]) / 255.0
    black_fraction = sum(value < 12 for value in gray.resize((96, 96)).tobytes()) / (
        96 * 96
    )
    sharpness = min(
        1.0,
        float(ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]) / 24.0,
    )
    ocr = _ocr_text(path)
    face_count = _face_count(path)
    pose = _pose_signature(path)
    rejections: list[str] = []
    if mean < 0.04 or black_fraction > 0.92:
        rejections.append("black_frame")
    if sharpness < 0.12:
        rejections.append("blurred_frame")
    if ocr is None:
        rejections.append("ocr_evidence_unavailable")
    elif ocr:
        rejections.append("visible_text_or_ui")
    if face_count is None:
        rejections.append("face_evidence_unavailable")
    elif face_count != 1:
        rejections.append("multiple_or_missing_people")
    if pose is None:
        rejections.append("body_or_pose_evidence_unavailable")
    score = 0.55 * sharpness + 0.25 * min(1.0, mean * 2) + 0.20 * (1.0 if pose else 0.0)
    return {
        "eligible": not rejections,
        "score": round(score, 6),
        "rejections": rejections,
        "measurements": {
            "meanLuma": round(mean, 6),
            "blackFraction": round(black_fraction, 6),
            "sharpness": round(sharpness, 6),
            "ocrText": ocr,
            "faceCount": face_count,
            "poseSignature": pose,
        },
    }


def assess_edit_locality(
    source: Path,
    output: Path,
    *,
    operation: str,
    source_identity: Mapping[str, Any],
    output_identity: Mapping[str, Any],
    output_qc: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = LOCALITY_THRESHOLDS.get(operation)
    if thresholds is None:
        raise ValueError("operation must be colorway or outfit_swap")
    measurements = _locality_measurements(source, output)
    source_score = _number(source_identity.get("score"))
    output_score = _number(output_identity.get("score"))
    measurements["identityScoreLoss"] = (
        round(max(0.0, source_score - output_score), 6)
        if source_score is not None and output_score is not None
        else None
    )
    checks = {
        "identity": (
            source_identity.get("status") == "passed"
            and output_identity.get("status") == "passed"
            and _lte(measurements["identityScoreLoss"], 0.05)
        ),
        "anatomyExposure": _postable_qc(output_qc),
        "faceBoxIou": _gte(measurements.get("faceBoxIou"), thresholds["faceBoxIouMin"]),
        "poseLandmarkDrift": _lte(
            measurements.get("poseLandmarkDrift"),
            thresholds["poseLandmarkDriftMax"],
        ),
        "personSilhouetteIou": _gte(
            measurements.get("personSilhouetteIou"),
            thresholds["personSilhouetteIouMin"],
        ),
        "backgroundSsim": _gte(
            measurements.get("backgroundSsim"), thresholds["backgroundSsimMin"]
        ),
        "protectedFaceRegionSsim": _gte(
            measurements.get("protectedFaceRegionSsim"),
            thresholds["protectedFaceRegionSsimMin"],
        ),
        "garmentRegionChange": _gte(
            measurements.get("garmentRegionChange"),
            thresholds["garmentRegionChangeMin"],
        ),
    }
    return {
        "schema": "reel_factory.edit_locality_receipt.v1",
        "operation": operation,
        "source": {"path": str(source), "sha256": _sha256_file(source)},
        "output": {"path": str(output), "sha256": _sha256_file(output)},
        "thresholds": thresholds,
        "measurements": measurements,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
        "narrowComparisonReviewRequired": True,
        "comparisonReviewCriteria": [
            "requested clothing changed",
            "identity and body proportions stable",
            "skin tone, pose, camera, lighting, and background stable",
        ],
    }


def _locality_measurements(source: Path, output: Path) -> dict[str, float | None]:
    try:
        import cv2  # type: ignore
        import numpy as np
    except ImportError:
        return {
            key: None
            for key in (
                "faceBoxIou",
                "poseLandmarkDrift",
                "personSilhouetteIou",
                "backgroundSsim",
                "protectedFaceRegionSsim",
                "garmentRegionChange",
            )
        }
    before = cv2.imread(str(source))
    after = cv2.imread(str(output))
    if before is None or after is None:
        return {}
    height, width = before.shape[:2]
    after = cv2.resize(after, (width, height), interpolation=cv2.INTER_AREA)
    face_before = _face_box(source)
    face_after = _face_box(output, target_size=(width, height))
    pose_before = _pose_signature(source)
    pose_after = _pose_signature(output)
    mask_before = _person_mask(source, target_size=(width, height))
    mask_after = _person_mask(output, target_size=(width, height))
    face_iou = _box_iou(face_before, face_after)
    pose_drift = (
        sum(abs(a - b) for a, b in zip(pose_before, pose_after, strict=True))
        / len(pose_before)
        if pose_before and pose_after and len(pose_before) == len(pose_after)
        else None
    )
    silhouette_iou = (
        float(np.logical_and(mask_before, mask_after).sum())
        / max(1.0, float(np.logical_or(mask_before, mask_after).sum()))
        if mask_before is not None and mask_after is not None
        else None
    )
    background = (
        np.logical_not(np.logical_or(mask_before, mask_after))
        if mask_before is not None and mask_after is not None
        else None
    )
    face_mask = np.zeros((height, width), dtype=bool)
    if face_before and face_after:
        x0 = max(0, min(face_before[0], face_after[0]))
        y0 = max(0, min(face_before[1], face_after[1]))
        x1 = min(width, max(face_before[2], face_after[2]))
        y1 = min(height, max(face_before[3], face_after[3]))
        face_mask[y0:y1, x0:x1] = True
    garment_mask = np.zeros((height, width), dtype=bool)
    if mask_before is not None and face_before:
        y0 = min(height, face_before[3])
        y1 = min(height, y0 + int(height * 0.38))
        garment_mask[y0:y1] = mask_before[y0:y1]
    return {
        "faceBoxIou": _rounded(face_iou),
        "poseLandmarkDrift": _rounded(pose_drift),
        "personSilhouetteIou": _rounded(silhouette_iou),
        "backgroundSsim": _rounded(_masked_ssim(before, after, background)),
        "protectedFaceRegionSsim": _rounded(
            _masked_ssim(before, after, face_mask if face_mask.any() else None)
        ),
        "garmentRegionChange": _rounded(
            _masked_change(before, after, garment_mask if garment_mask.any() else None)
        ),
    }


def _probe_video(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    body = json.loads(result.stdout or "{}")
    stream: dict[str, Any] = next(
        (item for item in body.get("streams") or [] if isinstance(item, dict)),
        {},
    )
    duration_raw = stream.get("duration") or (body.get("format") or {}).get("duration")
    if duration_raw is None:
        raise ValueError("video duration is unavailable")
    duration = float(duration_raw)
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "durationSeconds": duration,
    }


def _scene_cuts(path: Path, duration: float) -> list[float]:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "select='gt(scene,0.35)',showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    import re

    cuts = {
        round(float(value), 3)
        for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)
        if 0 < float(value) < duration
    }
    return sorted(cuts)


def _candidate_times(duration: float, cuts: list[float]) -> list[float]:
    end = max(0.0, duration - 0.05)
    values = {duration * index / 12 for index in range(1, 12)}
    for cut in cuts:
        values.update((cut - 0.08, cut + 0.08))
    return sorted(
        {round(max(0.0, min(end, value)), 3) for value in values if 0 <= value <= end}
    )


def _extract_frame(video: Path, output: Path, stamp: float) -> None:
    result = subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{stamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or not output.is_file():
        raise RuntimeError(
            result.stderr.strip() or f"frame extraction failed at {stamp}"
        )


def _contact_sheet(paths: list[Path], output: Path) -> Path | None:
    if not paths:
        return None
    thumbs = []
    for path in paths:
        thumb = Image.open(path).convert("RGB")
        thumb.thumbnail((270, 480))
        thumbs.append(thumb)
    width = 270 * min(3, len(thumbs))
    rows = math.ceil(len(thumbs) / 3)
    sheet = Image.new("RGB", (width, 480 * rows), "black")
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % 3) * 270, (index // 3) * 480))
    sheet.save(output, quality=92)
    return output


def _ocr_text(path: Path) -> str | None:
    executable = shutil.which("tesseract")
    if not executable:
        return None
    result = subprocess.run(
        [executable, str(path), "stdout", "--psm", "11"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return " ".join(result.stdout.split()) if result.returncode == 0 else None


def _face_count(path: Path) -> int | None:
    from .ai_visual_qc import _face_count as count

    return count(path)


def _pose_signature(path: Path) -> tuple[float, ...] | None:
    from .placement import _pose_coverages_from_frame

    result = _pose_coverages_from_frame(path)
    if result is None:
        return None
    width, height = Image.open(path).size
    vertical, side = result
    return tuple(round(value / max(width, height), 6) for value in (*vertical, *side))


def _face_box(path: Path, target_size: tuple[int, int] | None = None):
    try:
        import cv2  # type: ignore

        from .placement import _YUNET_MODEL_PATH
    except ImportError:
        return None
    if not _YUNET_MODEL_PATH.is_file():
        return None
    image = cv2.imread(str(path))
    if image is None:
        return None
    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(_YUNET_MODEL_PATH), "", (width, height), 0.5, 0.3, 10
    )
    _, faces = detector.detect(image)
    if faces is None or len(faces) != 1:
        return None
    x, y, box_width, box_height = (float(value) for value in faces[0][:4])
    target_width, target_height = target_size or (width, height)
    return (
        int(x * target_width / width),
        int(y * target_height / height),
        int((x + box_width) * target_width / width),
        int((y + box_height) * target_height / height),
    )


def _person_mask(path: Path, target_size: tuple[int, int]):
    try:
        import cv2  # type: ignore

        from .placement import _seg_net
    except ImportError:
        return None
    net = _seg_net()
    image = cv2.imread(str(path))
    if net is None or image is None:
        return None
    blob = cv2.dnn.blobFromImage(
        image, 1 / 255.0, (192, 192), (127, 127, 127), swapRB=True
    )
    net.setInput(blob)
    mask = net.forward()[0].argmax(0).astype("uint8")
    return cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST).astype(bool)


def _box_iou(first, second) -> float | None:
    if first is None or second is None:
        return None
    x0, y0 = max(first[0], second[0]), max(first[1], second[1])
    x1, y1 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    area_a = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    area_b = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    return intersection / max(1, area_a + area_b - intersection)


def _masked_ssim(before, after, mask) -> float | None:
    if mask is None or not mask.any():
        return None
    import cv2  # type: ignore
    import numpy as np

    left = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)[mask].astype(np.float64)
    right = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)[mask].astype(np.float64)
    if left.size < 32:
        return None
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_left, mu_right = left.mean(), right.mean()
    var_left, var_right = left.var(), right.var()
    covariance = ((left - mu_left) * (right - mu_right)).mean()
    return float(
        ((2 * mu_left * mu_right + c1) * (2 * covariance + c2))
        / ((mu_left**2 + mu_right**2 + c1) * (var_left + var_right + c2))
    )


def _masked_change(before, after, mask) -> float | None:
    if mask is None or not mask.any():
        return None
    import numpy as np

    difference = np.abs(before.astype(np.float32) - after.astype(np.float32))
    return float(difference[mask].mean() / 255.0)


def _postable_qc(qc: Mapping[str, Any]) -> bool:
    anatomy = qc.get("anatomy")
    exposure = qc.get("exposure")
    return bool(
        qc.get("available") is True
        and isinstance(anatomy, Mapping)
        and anatomy.get("plausible") is True
        and anatomy.get("severity") != "severe"
        and isinstance(exposure, Mapping)
        and exposure.get("safe") is True
        and exposure.get("severity") != "severe"
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _gte(value: Any, minimum: float) -> bool:
    number = _number(value)
    return number is not None and number >= minimum


def _lte(value: Any, maximum: float) -> bool:
    number = _number(value)
    return number is not None and number <= maximum


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and math.isfinite(value) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mime(path: Path) -> str:
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
