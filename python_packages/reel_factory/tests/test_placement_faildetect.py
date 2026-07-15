"""Placement must FAIL LOUD when face detection is unavailable, not silently
dump captions on faces (the forehead bug)."""

import logging

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
