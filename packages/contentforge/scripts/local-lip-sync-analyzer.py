#!/usr/bin/env python3
"""Deterministic local face-track and mouth-motion measurement.

This script deliberately measures only the visual side of lip synchronization.
The ContentForge Node adapter extracts the audio envelope itself, aligns the two
time series, and owns the final policy verdict. No network or model provider is
used here.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

SAMPLE_RATE_HZ = 12.0
MIN_FACE_SAMPLES = 8
MIN_FACE_TRACK_COVERAGE = 0.60
MAX_MULTIPLE_FACE_RATIO = 0.10
ROI_WIDTH = 48
ROI_HEIGHT = 24


def _result(**payload: Any) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _fail(reason: str, **details: Any) -> int:
    _result(available=False, reason=reason, **details)
    return 0


def _largest_face(faces: Any) -> tuple[int, int, int, int]:
    return max(
        (tuple(int(value) for value in face) for face in faces),
        key=lambda row: row[2] * row[3],
    )


def _roi(
    gray: Any, face: tuple[int, int, int, int], *, mouth: bool, cv2: Any
) -> Any | None:
    x, y, width, height = face
    left = max(0, x + round(width * 0.18))
    right = min(gray.shape[1], x + round(width * 0.82))
    if mouth:
        top = max(0, y + round(height * 0.55))
        bottom = min(gray.shape[0], y + round(height * 0.92))
    else:
        top = max(0, y + round(height * 0.16))
        bottom = min(gray.shape[0], y + round(height * 0.48))
    if right - left < 8 or bottom - top < 6:
        return None
    return cv2.resize(
        gray[top:bottom, left:right],
        (ROI_WIDTH, ROI_HEIGHT),
        interpolation=cv2.INTER_AREA,
    )


def main() -> int:
    if len(sys.argv) != 2:
        return _fail("media_path_missing")
    media_path = Path(sys.argv[1]).expanduser().resolve()
    if not media_path.is_file():
        return _fail("media_file_missing")
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-specific
        return _fail("local_face_runtime_unavailable", error=type(exc).__name__)

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return _fail("local_face_detector_unavailable")
    capture = cv2.VideoCapture(str(media_path))
    if not capture.isOpened():
        return _fail("video_decode_failed")
    frames_per_second = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    if not math.isfinite(frames_per_second) or frames_per_second <= 0:
        capture.release()
        return _fail("video_frame_rate_invalid")
    stride = max(1, round(frames_per_second / SAMPLE_RATE_HZ))
    effective_rate = frames_per_second / stride
    sampled = 0
    detected = 0
    multiple = 0
    frame_index = -1
    previous_mouth = None
    previous_upper = None
    previous_time = None
    envelope: list[dict[str, float]] = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % stride:
                continue
            sampled += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(48, 48),
                flags=cv2.CASCADE_SCALE_IMAGE,
            )
            if len(faces) == 0:
                previous_mouth = None
                previous_upper = None
                previous_time = None
                continue
            detected += 1
            if len(faces) > 1:
                multiple += 1
            face = _largest_face(faces)
            mouth = _roi(gray, face, mouth=True, cv2=cv2)
            upper = _roi(gray, face, mouth=False, cv2=cv2)
            if mouth is None or upper is None:
                previous_mouth = None
                previous_upper = None
                previous_time = None
                continue
            timestamp = frame_index / frames_per_second
            if (
                previous_mouth is not None
                and previous_upper is not None
                and previous_time is not None
            ):
                gap = timestamp - previous_time
                if gap <= (2.1 / effective_rate):
                    mouth_delta = (
                        float(np.mean(cv2.absdiff(previous_mouth, mouth))) / 255.0
                    )
                    upper_delta = (
                        float(np.mean(cv2.absdiff(previous_upper, upper))) / 255.0
                    )
                    articulation = max(0.0, mouth_delta - (0.75 * upper_delta))
                    envelope.append(
                        {
                            "timeSeconds": round((timestamp + previous_time) / 2.0, 6),
                            "mouthDelta": round(mouth_delta, 8),
                            "upperFaceDelta": round(upper_delta, 8),
                            "articulationMotion": round(articulation, 8),
                        }
                    )
            previous_mouth = mouth
            previous_upper = upper
            previous_time = timestamp
    finally:
        capture.release()

    coverage = detected / sampled if sampled else 0.0
    multiple_ratio = multiple / detected if detected else 0.0
    common = {
        "runtime": {
            "python": sys.version.split()[0],
            "opencv": str(cv2.__version__),
            "detector": str(cascade_path),
        },
        "sampling": {
            "requestedFramesPerSecond": SAMPLE_RATE_HZ,
            "effectiveFramesPerSecond": round(effective_rate, 6),
            "sampledFrames": sampled,
            "faceFrames": detected,
            "faceTrackCoverage": round(coverage, 8),
            "multipleFaceFrames": multiple,
            "multipleFaceRatio": round(multiple_ratio, 8),
        },
    }
    if sampled < MIN_FACE_SAMPLES:
        return _fail("insufficient_video_samples", **common)
    if detected < MIN_FACE_SAMPLES:
        return _fail("insufficient_face_track", **common)
    if coverage < MIN_FACE_TRACK_COVERAGE:
        return _fail("face_track_incomplete", **common)
    if multiple_ratio > MAX_MULTIPLE_FACE_RATIO:
        return _fail("multiple_face_track_ambiguous", **common)
    if len(envelope) < MIN_FACE_SAMPLES - 1:
        return _fail("insufficient_mouth_motion_samples", **common)
    _result(
        available=True,
        **common,
        mouthMotionEnvelope=envelope,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
