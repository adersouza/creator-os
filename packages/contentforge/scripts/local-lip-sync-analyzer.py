#!/usr/bin/env python3
"""Deterministic Apple Vision face/lip-landmark motion measurement.

This script measures only the visual side of lip synchronization. It samples
decoded frames locally, asks macOS Vision for actual outer/inner lip landmarks,
and emits a content-bound landmark track. It never guesses a mouth rectangle.
The ContentForge Node adapter samples audio and owns the final alignment policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SAMPLE_RATE_HZ = 12.0
MIN_LANDMARK_SAMPLES = 30
MIN_LANDMARK_TRACK_COVERAGE = 0.60
MAX_MULTIPLE_FACE_RATIO = 0.10
MAX_UNSTABLE_TRACK_RATIO = 0.10
SWIFT_TIMEOUT_SECONDS = 120

# Kept inside the attested Python implementation so the analyzer registry hash
# covers the exact Vision request and coordinate conversion that produced the
# landmark evidence.
APPLE_VISION_SOURCE = r"""
import Foundation
import Vision
import AppKit

func jsonPrint(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [])
    print(String(data: data, encoding: .utf8)!)
}

guard CommandLine.arguments.count == 2 else {
    jsonPrint(["available": false, "reason": "landmark_manifest_missing"])
    exit(0)
}

do {
    let manifestData = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    guard let manifest = try JSONSerialization.jsonObject(with: manifestData) as? [[String: Any]] else {
        jsonPrint(["available": false, "reason": "landmark_manifest_invalid"])
        exit(0)
    }
    var frames: [[String: Any]] = []
    for item in manifest {
        guard let identifier = item["identifier"] as? Int,
              let imagePath = item["path"] as? String,
              let image = NSImage(contentsOfFile: imagePath),
              let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            frames.append(["identifier": item["identifier"] ?? -1, "available": false, "reason": "frame_decode_failed"])
            continue
        }
        let request = VNDetectFaceLandmarksRequest()
        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
            let observations = request.results ?? []
            var faces: [[String: Any]] = []
            for observation in observations {
                guard let landmarks = observation.landmarks,
                      let outer = landmarks.outerLips,
                      let inner = landmarks.innerLips else { continue }
                let rect = observation.boundingBox
                func points(_ region: VNFaceLandmarkRegion2D) -> [[String: Double]] {
                    return region.normalizedPoints.map { point in
                        ["x": Double(point.x), "y": Double(point.y)]
                    }
                }
                faces.append([
                    "confidence": Double(observation.confidence),
                    "box": [
                        "x": Int(round(rect.minX * CGFloat(cgImage.width))),
                        "y": Int(round((1.0 - rect.maxY) * CGFloat(cgImage.height))),
                        "w": Int(round(rect.width * CGFloat(cgImage.width))),
                        "h": Int(round(rect.height * CGFloat(cgImage.height)))
                    ],
                    "frame": ["width": cgImage.width, "height": cgImage.height],
                    "outerLips": points(outer),
                    "innerLips": points(inner)
                ])
            }
            frames.append(["identifier": identifier, "available": true, "faces": faces])
        } catch {
            frames.append(["identifier": identifier, "available": false, "reason": "vision_request_failed", "error": error.localizedDescription])
        }
    }
    jsonPrint([
        "available": true,
        "provider": "apple_vision",
        "request": "VNDetectFaceLandmarksRequest",
        "frames": frames
    ])
} catch {
    jsonPrint(["available": false, "reason": "landmark_runtime_failed", "error": error.localizedDescription])
}
"""


def _result(**payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _fail(reason: str, **details: Any) -> int:
    _result(available=False, reason=reason, **details)
    return 0


def _face_area(face: dict[str, Any]) -> int:
    box = face.get("box") or {}
    return max(0, int(box.get("w") or 0)) * max(0, int(box.get("h") or 0))


def _point_span(points: list[dict[str, Any]], axis: str) -> float:
    values = [
        float(point[axis]) for point in points if math.isfinite(float(point[axis]))
    ]
    return max(values) - min(values) if len(values) >= 2 else 0.0


def _mouth_opening_ratio(face: dict[str, Any]) -> float | None:
    outer = face.get("outerLips")
    inner = face.get("innerLips")
    if not isinstance(outer, list) or not isinstance(inner, list):
        return None
    if len(outer) < 6 or len(inner) < 6:
        return None
    width = _point_span(outer, "x")
    if width <= 1e-6:
        return None
    inner_height = _point_span(inner, "y")
    outer_height = _point_span(outer, "y")
    # Inner-lip aperture is the primary articulation signal. The small outer-lip
    # term keeps closed-lip consonant movement observable without using pixels.
    return max(0.0, min(1.0, (inner_height + (0.15 * outer_height)) / width))


def _box_iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    ax1, ay1 = float(first["x"]), float(first["y"])
    ax2, ay2 = ax1 + float(first["w"]), ay1 + float(first["h"])
    bx1, by1 = float(second["x"]), float(second["y"])
    bx2, by2 = bx1 + float(second["w"]), by1 + float(second["h"])
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    union = (
        (float(first["w"]) * float(first["h"]))
        + (float(second["w"]) * float(second["h"]))
        - intersection
    )
    return intersection / union if union > 0 else 0.0


def _landmark_fingerprint(frames: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        frames, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _toolchain_identity(swift: str, environment: dict[str, str]) -> dict[str, Any]:
    try:
        swift_path = Path(swift).resolve(strict=True)
        swift_version = subprocess.run(
            [str(swift_path), "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
            env=environment,
        )
        macos_version = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
            env=environment,
        )
        macos_build = subprocess.run(
            ["/usr/bin/sw_vers", "-buildVersion"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "reason": "apple_vision_toolchain_identity_unavailable",
            "error": type(exc).__name__,
        }
    if any(
        completed.returncode != 0
        for completed in (swift_version, macos_version, macos_build)
    ):
        return {
            "available": False,
            "reason": "apple_vision_toolchain_identity_unavailable",
        }
    core = {
        "schema": "contentforge.apple_vision_toolchain.v1",
        "macosProductVersion": macos_version.stdout.strip(),
        "macosBuildVersion": macos_build.stdout.strip(),
        "machineArchitecture": platform.machine(),
        "swiftExecutable": str(swift_path),
        "swiftExecutableSha256": _sha256_file(swift_path),
        "swiftVersion": " ".join(swift_version.stdout.split()),
        "visionRequest": "VNDetectFaceLandmarksRequest",
        "embeddedSwiftSourceSha256": hashlib.sha256(
            APPLE_VISION_SOURCE.encode("utf-8")
        ).hexdigest(),
    }
    encoded = json.dumps(
        core, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return {
        "available": True,
        **core,
        "toolchainFingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def _run_apple_vision(manifest: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"available": False, "reason": "apple_vision_requires_macos"}
    swift = shutil.which("swift")
    if not swift:
        return {"available": False, "reason": "apple_vision_runtime_unavailable"}
    script_path = root / "face-landmarks.swift"
    manifest_path = root / "frames.json"
    script_path.write_text(APPLE_VISION_SOURCE, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}
    }
    toolchain = _toolchain_identity(swift, environment)
    if toolchain.get("available") is not True:
        return toolchain
    try:
        completed = subprocess.run(
            [swift, str(script_path), str(manifest_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=SWIFT_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "reason": "apple_vision_runtime_failed",
            "error": type(exc).__name__,
        }
    try:
        decoded = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "available": False,
            "reason": "apple_vision_output_invalid",
            "exitCode": completed.returncode,
        }
    if completed.returncode != 0 or decoded.get("available") is not True:
        return {
            "available": False,
            "reason": str(decoded.get("reason") or "apple_vision_runtime_failed"),
            "error": str(decoded.get("error") or completed.stderr or "")[:500],
        }
    decoded["toolchainEvidence"] = toolchain
    return decoded


def main() -> int:
    if len(sys.argv) != 2:
        return _fail("media_path_missing")
    media_path = Path(sys.argv[1]).expanduser().resolve()
    if not media_path.is_file():
        return _fail("media_file_missing")
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-specific
        return _fail("local_video_runtime_unavailable", error=type(exc).__name__)

    capture = cv2.VideoCapture(str(media_path))
    if not capture.isOpened():
        return _fail("video_decode_failed")
    frames_per_second = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    if not math.isfinite(frames_per_second) or frames_per_second <= 0:
        capture.release()
        return _fail("video_frame_rate_invalid")
    stride = max(1, math.ceil(frames_per_second / SAMPLE_RATE_HZ))
    effective_rate = frames_per_second / stride
    sampled = 0
    manifest: list[dict[str, Any]] = []
    frame_metadata: dict[int, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="contentforge-lip-landmarks-") as temp:
        root = Path(temp)
        frame_index = -1
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                frame_index += 1
                if frame_index % stride:
                    continue
                identifier = sampled
                sampled += 1
                timestamp = frame_index / frames_per_second
                image_path = root / f"frame-{identifier:05d}.png"
                if not cv2.imwrite(str(image_path), frame):
                    continue
                manifest.append({"identifier": identifier, "path": str(image_path)})
                frame_metadata[identifier] = {
                    "timeSeconds": round(timestamp, 6),
                    "width": int(frame.shape[1]),
                    "height": int(frame.shape[0]),
                }
        finally:
            capture.release()

        if sampled < MIN_LANDMARK_SAMPLES:
            return _fail(
                "insufficient_video_samples",
                sampling={
                    "requestedFramesPerSecond": SAMPLE_RATE_HZ,
                    "effectiveFramesPerSecond": round(effective_rate, 6),
                    "sampledFrames": sampled,
                },
            )
        vision = _run_apple_vision(manifest, root)

    if vision.get("available") is not True:
        return _fail(
            str(vision.get("reason") or "mouth_landmark_evidence_unavailable"),
            landmarkEvidence={
                "available": False,
                "provider": "apple_vision",
                "reason": str(vision.get("reason") or "measurement_unavailable"),
            },
        )

    landmark_frames: list[dict[str, Any]] = []
    face_track_boxes: list[dict[str, Any]] = []
    multiple = 0
    unstable = 0
    prior_box: dict[str, Any] | None = None
    for frame_result in vision.get("frames") or []:
        identifier = int(frame_result.get("identifier", -1))
        metadata = frame_metadata.get(identifier)
        if not metadata or frame_result.get("available") is not True:
            prior_box = None
            continue
        faces = frame_result.get("faces") or []
        if len(faces) > 1:
            multiple += 1
        faces = [face for face in faces if _mouth_opening_ratio(face) is not None]
        if not faces:
            prior_box = None
            continue
        face = max(faces, key=_face_area)
        box = face["box"]
        if prior_box is not None and _box_iou(prior_box, box) < 0.10:
            unstable += 1
        prior_box = box
        opening = _mouth_opening_ratio(face)
        exact = {
            "timeSeconds": metadata["timeSeconds"],
            "mouthOpeningRatio": round(float(opening), 8),
            "articulationMotion": round(float(opening), 8),
            "outerLips": face["outerLips"],
            "innerLips": face["innerLips"],
            "faceConfidence": round(float(face.get("confidence") or 0), 8),
        }
        landmark_frames.append(exact)
        face_track_boxes.append(
            {
                "timeSeconds": metadata["timeSeconds"],
                "box": box,
                "frame": {
                    "width": metadata["width"],
                    "height": metadata["height"],
                },
            }
        )

    detected = len(landmark_frames)
    coverage = detected / sampled if sampled else 0.0
    multiple_ratio = multiple / detected if detected else 0.0
    unstable_ratio = unstable / max(1, detected - 1)
    toolchain = vision.get("toolchainEvidence") or {}
    toolchain_fingerprint = str(toolchain.get("toolchainFingerprint") or "")
    if toolchain.get("available") is not True or len(toolchain_fingerprint) != 64:
        return _fail(
            "apple_vision_toolchain_identity_unavailable",
            toolchainEvidence=toolchain,
        )
    common = {
        "runtime": {
            "python": sys.version.split()[0],
            "opencv": str(cv2.__version__),
            "landmarkProvider": "apple_vision",
            "landmarkRequest": "VNDetectFaceLandmarksRequest",
            "toolchainFingerprint": toolchain_fingerprint,
        },
        "toolchainEvidence": toolchain,
        "sampling": {
            "requestedFramesPerSecond": SAMPLE_RATE_HZ,
            "effectiveFramesPerSecond": round(effective_rate, 6),
            "sampledFrames": sampled,
            "landmarkFrames": detected,
            "faceFrames": detected,
            "faceTrackCoverage": round(coverage, 8),
            "multipleFaceFrames": multiple,
            "multipleFaceRatio": round(multiple_ratio, 8),
            "unstableTrackTransitions": unstable,
            "unstableTrackRatio": round(unstable_ratio, 8),
        },
        "landmarkEvidence": {
            "available": True,
            "provider": "apple_vision",
            "request": "VNDetectFaceLandmarksRequest",
            "coordinateSpace": "face_normalized",
            "frameCount": detected,
            "fingerprint": _landmark_fingerprint(landmark_frames),
            "toolchainFingerprint": toolchain_fingerprint,
        },
        "faceTrackBoxes": face_track_boxes,
        "landmarkFrames": landmark_frames,
    }
    if detected < MIN_LANDMARK_SAMPLES:
        return _fail("insufficient_mouth_landmark_track", **common)
    if coverage < MIN_LANDMARK_TRACK_COVERAGE:
        return _fail("mouth_landmark_track_incomplete", **common)
    if multiple_ratio > MAX_MULTIPLE_FACE_RATIO:
        return _fail("multiple_face_track_ambiguous", **common)
    if unstable_ratio > MAX_UNSTABLE_TRACK_RATIO:
        return _fail("face_track_identity_unstable", **common)
    _result(
        available=True,
        **common,
        mouthMotionEnvelope=[
            {
                "timeSeconds": frame["timeSeconds"],
                "mouthOpeningRatio": frame["mouthOpeningRatio"],
                "articulationMotion": frame["articulationMotion"],
            }
            for frame in landmark_frames
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
