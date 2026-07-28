#!/usr/bin/env python3
"""Deterministic Apple Vision body/hand landmark continuity evidence.

This analyzer is deliberately evidence-only. It measures track coverage and
landmark continuity; it does not claim identity or anatomy approval.
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
from statistics import median
from typing import Any

SAMPLE_RATE_HZ = 8.0
MIN_BODY_TRACK_COVERAGE = 0.60
SWIFT_TIMEOUT_SECONDS = 120

APPLE_VISION_SOURCE = r"""
import Foundation
import Vision
import AppKit

func jsonPrint(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [])
    print(String(data: data, encoding: .utf8)!)
}

func points(_ observation: VNRecognizedPointsObservation) -> [String: [String: Double]] {
    guard let recognized = try? observation.recognizedPoints(forGroupKey: .all) else { return [:] }
    var result: [String: [String: Double]] = [:]
    for (name, point) in recognized {
        result[name.rawValue] = [
            "x": Double(point.location.x),
            "y": Double(point.location.y),
            "confidence": Double(point.confidence)
        ]
    }
    return result
}

guard CommandLine.arguments.count == 2 else {
    jsonPrint(["available": false, "reason": "landmark_manifest_missing"])
    exit(0)
}

do {
    let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    guard let manifest = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
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
        let bodyRequest = VNDetectHumanBodyPoseRequest()
        let handRequest = VNDetectHumanHandPoseRequest()
        handRequest.maximumHandCount = 2
        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([bodyRequest, handRequest])
            let bodies = (bodyRequest.results ?? []).map { ["points": points($0)] }
            let hands = (handRequest.results ?? []).map { ["points": points($0)] }
            frames.append([
                "identifier": identifier,
                "available": true,
                "bodies": bodies,
                "hands": hands
            ])
        } catch {
            frames.append([
                "identifier": identifier,
                "available": false,
                "reason": "vision_request_failed",
                "error": error.localizedDescription
            ])
        }
    }
    jsonPrint([
        "available": true,
        "provider": "apple_vision",
        "requests": ["VNDetectHumanBodyPoseRequest", "VNDetectHumanHandPoseRequest"],
        "frames": frames
    ])
} catch {
    jsonPrint(["available": false, "reason": "landmark_runtime_failed", "error": error.localizedDescription])
}
"""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result(**payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _fail(reason: str, **details: Any) -> int:
    _result(available=False, reason=reason, **details)
    return 0


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
        product = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
            env=environment,
        )
        build = subprocess.run(
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
    if any(item.returncode != 0 for item in (swift_version, product, build)):
        return {
            "available": False,
            "reason": "apple_vision_toolchain_identity_unavailable",
        }
    core = {
        "available": True,
        "schema": "contentforge.apple_vision_toolchain.v1",
        "macosProductVersion": product.stdout.strip(),
        "macosBuildVersion": build.stdout.strip(),
        "machineArchitecture": platform.machine(),
        "swiftExecutable": str(swift_path),
        "swiftExecutableSha256": _sha256_file(swift_path),
        "swiftVersion": " ".join(swift_version.stdout.split()),
        "visionRequests": [
            "VNDetectHumanBodyPoseRequest",
            "VNDetectHumanHandPoseRequest",
        ],
        "embeddedSwiftSourceSha256": hashlib.sha256(
            APPLE_VISION_SOURCE.encode()
        ).hexdigest(),
    }
    return {
        **core,
        "toolchainFingerprint": _fingerprint(core),
    }


def _run_apple_vision(manifest: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"available": False, "reason": "apple_vision_requires_macos"}
    swift = shutil.which("swift")
    if not swift:
        return {"available": False, "reason": "apple_vision_runtime_unavailable"}
    script = root / "pose-landmarks.swift"
    manifest_path = root / "frames.json"
    script.write_text(APPLE_VISION_SOURCE, encoding="utf-8")
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
            [swift, str(script), str(manifest_path)],
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


def _qualified_points(track: dict[str, Any]) -> dict[str, dict[str, float]]:
    raw = track.get("points")
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): point
        for name, point in raw.items()
        if isinstance(point, dict)
        and float(point.get("confidence") or 0) >= 0.35
        and all(math.isfinite(float(point.get(axis) or 0)) for axis in ("x", "y"))
    }


def _track_score(track: dict[str, Any]) -> tuple[int, float]:
    points = _qualified_points(track)
    return len(points), sum(float(point["confidence"]) for point in points.values())


def _normalized_transition(
    first: dict[str, dict[str, float]],
    second: dict[str, dict[str, float]],
) -> float | None:
    common = sorted(set(first) & set(second))
    if len(common) < 3:
        return None
    xs = [float(first[name]["x"]) for name in first]
    ys = [float(first[name]["y"]) for name in first]
    scale = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if scale <= 1e-6:
        return None
    distances = [
        math.hypot(
            float(second[name]["x"]) - float(first[name]["x"]),
            float(second[name]["y"]) - float(first[name]["y"]),
        )
        / scale
        for name in common
    ]
    return median(distances)


def _continuity(track_frames: list[dict[str, Any]]) -> dict[str, Any]:
    transitions: list[float] = []
    for first, second in zip(track_frames, track_frames[1:], strict=False):
        value = _normalized_transition(first["points"], second["points"])
        if value is not None:
            transitions.append(value)
    return {
        "measuredTransitions": len(transitions),
        "medianNormalizedJointMotion": (
            round(median(transitions), 8) if transitions else None
        ),
        "p95NormalizedJointMotion": (
            round(
                sorted(transitions)[
                    min(len(transitions) - 1, int(len(transitions) * 0.95))
                ],
                8,
            )
            if transitions
            else None
        ),
        "largeJumpTransitions": sum(value > 0.35 for value in transitions),
        "largeJumpRatio": (
            round(sum(value > 0.35 for value in transitions) / len(transitions), 8)
            if transitions
            else None
        ),
    }


def main() -> int:
    if len(sys.argv) != 2:
        return _fail("media_path_missing")
    media_path = Path(sys.argv[1]).expanduser().resolve()
    if not media_path.is_file():
        return _fail("media_file_missing")
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        return _fail("local_video_runtime_unavailable", error=type(exc).__name__)

    capture = cv2.VideoCapture(str(media_path))
    if not capture.isOpened():
        return _fail("video_decode_failed")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        return _fail("video_frame_rate_invalid")
    stride = max(1, math.ceil(fps / SAMPLE_RATE_HZ))
    manifest: list[dict[str, Any]] = []
    metadata: dict[int, dict[str, Any]] = {}
    frame_hashes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="contentforge-pose-landmarks-") as temp:
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
                identifier = len(manifest)
                image_path = root / f"frame-{identifier:05d}.png"
                if not cv2.imwrite(str(image_path), frame):
                    continue
                timestamp = round(frame_index / fps, 6)
                manifest.append({"identifier": identifier, "path": str(image_path)})
                metadata[identifier] = {"timeSeconds": timestamp}
                frame_hashes.append(
                    {
                        "timeSeconds": timestamp,
                        "sha256": _sha256_file(image_path),
                    }
                )
        finally:
            capture.release()
        if len(manifest) < 2:
            return _fail("insufficient_video_samples")
        vision = _run_apple_vision(manifest, root)

    if vision.get("available") is not True:
        return _fail(
            str(vision.get("reason") or "pose_continuity_unavailable"),
            toolchainEvidence=vision.get("toolchainEvidence"),
        )

    body_frames: list[dict[str, Any]] = []
    hand_frames: list[dict[str, Any]] = []
    multi_person_frames = 0
    for frame in vision.get("frames") or []:
        identifier = int(frame.get("identifier", -1))
        if identifier not in metadata or frame.get("available") is not True:
            continue
        bodies = list(frame.get("bodies") or [])
        if len(bodies) > 1:
            multi_person_frames += 1
        if bodies:
            body = max(bodies, key=_track_score)
            points = _qualified_points(body)
            if len(points) >= 4:
                body_frames.append(
                    {
                        "timeSeconds": metadata[identifier]["timeSeconds"],
                        "points": points,
                    }
                )
        hands = sorted(
            (hand for hand in frame.get("hands") or [] if _qualified_points(hand)),
            key=_track_score,
            reverse=True,
        )
        if hands:
            hand_frames.append(
                {
                    "timeSeconds": metadata[identifier]["timeSeconds"],
                    "points": _qualified_points(hands[0]),
                    "detectedHands": len(hands),
                }
            )

    sampled = len(manifest)
    body_coverage = len(body_frames) / sampled
    hand_coverage = len(hand_frames) / sampled
    toolchain = vision.get("toolchainEvidence") or {}
    if toolchain.get("available") is not True:
        return _fail(
            "apple_vision_toolchain_identity_unavailable",
            toolchainEvidence=toolchain,
        )
    common = {
        "passed": True,
        "evidenceScope": "technical_landmark_continuity_only",
        "identityApproval": False,
        "anatomyApproval": False,
        "mediaSha256": _sha256_file(media_path),
        "sampling": {
            "requestedFramesPerSecond": SAMPLE_RATE_HZ,
            "effectiveFramesPerSecond": round(fps / stride, 6),
            "sampledFrames": sampled,
            "frameSetFingerprint": _fingerprint(frame_hashes),
        },
        "body": {
            "status": "measured",
            "trackedFrames": len(body_frames),
            "trackCoverage": round(body_coverage, 8),
            "multiplePersonFrames": multi_person_frames,
            "continuity": _continuity(body_frames),
        },
        "hands": {
            "status": "measured" if hand_frames else "not_applicable",
            "reason": None if hand_frames else "hands_not_detected",
            "trackedFrames": len(hand_frames),
            "trackCoverage": round(hand_coverage, 8),
            "continuity": _continuity(hand_frames),
        },
        "landmarkEvidence": {
            "provider": "apple_vision",
            "requests": vision.get("requests"),
            "bodyFrameCount": len(body_frames),
            "handFrameCount": len(hand_frames),
            "fingerprint": _fingerprint(
                {"bodyFrames": body_frames, "handFrames": hand_frames}
            ),
            "toolchainFingerprint": toolchain["toolchainFingerprint"],
        },
        "toolchainEvidence": toolchain,
    }
    if body_coverage < MIN_BODY_TRACK_COVERAGE:
        return _fail("body_landmark_track_incomplete", **common)
    _result(available=True, **common)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
