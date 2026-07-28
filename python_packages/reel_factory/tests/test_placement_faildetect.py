"""Placement must FAIL LOUD when face detection is unavailable, not silently
dump captions on faces (the forehead bug)."""

import logging
import sys
from types import SimpleNamespace

import reel_factory.placement as placement


def test_face_detection_available_true_when_deps_present(monkeypatch, tmp_path):
    model = tmp_path / "face_detection_yunet_2023mar.onnx"
    model.write_bytes(b"present")
    monkeypatch.setattr(placement, "_YUNET_MODEL_PATH", model)
    ok, reason = placement.face_detection_available()
    assert ok, f"expected face detection available in test env, got: {reason}"
    assert reason == ""


def test_reports_missing_model(monkeypatch, tmp_path):
    monkeypatch.setattr(placement, "_YUNET_MODEL_PATH", tmp_path / "nope.onnx")
    ok, reason = placement.face_detection_available()
    assert not ok
    assert "missing" in reason.lower()


def test_warns_once_when_blind(monkeypatch, caplog):
    monkeypatch.setattr(placement, "_YUNET_MODEL_PATH", tmp_path_missing())
    monkeypatch.setattr(placement, "_FACE_BLIND_WARNED", False)
    with caplog.at_level(logging.WARNING):
        placement._warn_if_blind()
        placement._warn_if_blind()  # second call must not re-warn
    degraded = [r for r in caplog.records if "PLACEMENT DEGRADED" in r.getMessage()]
    assert len(degraded) == 1


def tmp_path_missing():
    from pathlib import Path

    return Path("/nonexistent/face_model.onnx")


def test_pose_tasks_provenance_rejects_missing_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        placement, "_MEDIAPIPE_POSE_MODEL_PATH", tmp_path / "missing.task"
    )
    provenance = placement._pose_tasks_provenance()
    assert provenance["available"] is False
    assert provenance["reason"] == "mediapipe_pose_model_missing"


def test_pose_tasks_provenance_rejects_wrong_model_hash(monkeypatch, tmp_path):
    model = tmp_path / "pose.task"
    model.write_bytes(b"wrong")
    monkeypatch.setattr(placement, "_MEDIAPIPE_POSE_MODEL_PATH", model)
    provenance = placement._pose_tasks_provenance()
    assert provenance["available"] is False
    assert provenance["reason"] == "mediapipe_pose_model_sha256_mismatch"


def test_pose_tasks_inference_is_reused_for_vertical_and_side_coverage(
    monkeypatch, tmp_path
):
    import cv2
    import numpy as np

    frame = tmp_path / "frame.png"
    assert cv2.imwrite(str(frame), np.zeros((300, 200, 3), dtype=np.uint8))
    landmarks = [
        SimpleNamespace(x=0.5, y=0.5, visibility=0.0, presence=0.0) for _ in range(33)
    ]
    for index, x, y in (
        (11, 0.2, 0.2),
        (12, 0.8, 0.2),
        (23, 0.3, 0.8),
        (24, 0.7, 0.8),
    ):
        landmarks[index] = SimpleNamespace(x=x, y=y, visibility=0.9, presence=0.9)

    class Landmarker:
        calls = 0

        def detect(self, _image):
            self.calls += 1
            return SimpleNamespace(pose_landmarks=[landmarks])

    landmarker = Landmarker()
    fake_mp = SimpleNamespace(
        Image=lambda **_kwargs: object(),
        ImageFormat=SimpleNamespace(SRGB="SRGB"),
    )
    monkeypatch.setattr(placement, "_pose_landmarker", lambda: landmarker)
    monkeypatch.setitem(sys.modules, "mediapipe", fake_mp)

    vertical, side = placement._pose_coverages_from_frame(frame) or (None, None)

    assert landmarker.calls == 1
    assert vertical is not None and len(vertical) == 3
    assert side is not None and len(side) == 2
