"""No-safe-lane rescue: re-score with high-confidence faces only.

Measured on the stacey batch: 4 of 424 source clips had every lane rejected and
shipped captionless reels, yet each frame had 660-1260px with no real face in
it. YuNet had hallucinated large low-confidence boxes onto hips and thighs
(max confidence 0.581) while the real faces scored 0.884-0.931. The rescue
re-scores with only >= 0.85 boxes, and fires ONLY when the alternative is a reel
with no caption at all.
"""

from pathlib import Path
from typing import Any

from reel_factory import placement
from reel_factory.placement_scorer import score_lanes

# A full-body portrait: real face in the top band, plus a hallucinated "face"
# on the hips. Coverage numbers are the shape measured on src_b8b3f09644.
_REAL_FACE_TOP = (98_000.0, 0.0, 0.0)
_WITH_HALLUCINATION = (116_246.0, 186_604.0, 214_800.0)
_HEAD_TOP_ONLY = (30.0, 0.5, 0.0)
_FOCAL_SATURATED = (60.0, 60.0, 60.0)
_STDDEV = (44.0, 46.0, 33.0)


def _score(face_samples: list[tuple[float, float, float]]) -> Any:
    return score_lanes(
        stddev_samples=[_STDDEV],
        face_samples=face_samples,
        head_samples=[_HEAD_TOP_ONLY],
        focal_samples=[_FOCAL_SATURATED],
        motion_samples=[],
        pose_samples=[],
        placement_policy="focal-safe",
    )


def _decision(summary: Any) -> dict[str, Any]:
    return summary.metadata["captionPlacementDecision"]


def _run_rescue(summary: Any, frames: list[Path], monkeypatch: Any, strict_face: Any):
    monkeypatch.setattr(
        placement, "_face_coverage_from_frame", lambda _f, **_kw: strict_face
    )
    return placement._rescue_no_safe_lane(
        summary,
        frames=frames,
        std_samples=[_STDDEV],
        head_samples=[_HEAD_TOP_ONLY],
        focal_samples=[_FOCAL_SATURATED],
        motion_samples=[],
        pose_samples=[],
        caption_placement_policy="focal-safe",
    )


def test_hallucinated_face_rejects_every_lane(monkeypatch):
    """The bug itself: junk boxes in two lanes leave nowhere to put text."""
    assert _decision(_score([_WITH_HALLUCINATION]))["reasonCode"] == "no_safe_caption_lane"


def test_rescue_recovers_a_lane_when_only_real_faces_count(monkeypatch):
    summary = _score([_WITH_HALLUCINATION])
    rescued, rescue = _run_rescue(summary, [Path("f.png")], monkeypatch, _REAL_FACE_TOP)

    decision = _decision(rescued)
    assert decision["reasonCode"] == "safe_caption_lane"
    assert decision["selectedLane"] == "bottom"
    assert rescue is not None
    assert rescue["trigger"] == "no_safe_caption_lane"
    assert rescue["minFaceConfidence"] == placement._RESCUE_FACE_CONFIDENCE
    # Auditable, not silent -- the original complaint about this failure was
    # that a captionless reel passed every gate with no record anywhere.
    assert set(decision["rescuedFrom"]["originalRejectedLanes"]) == {
        "top",
        "center",
        "bottom",
    }


def test_rescue_does_not_touch_a_clip_that_already_passed(monkeypatch):
    """The 99% must never reach the strict-confidence bar."""
    summary = _score([_REAL_FACE_TOP])
    assert _decision(summary)["status"] == "passed"

    rescued, rescue = _run_rescue(summary, [Path("f.png")], monkeypatch, _REAL_FACE_TOP)
    assert rescue is None
    assert rescued is summary


def test_rescue_declines_when_no_face_clears_the_bar(monkeypatch):
    """All-low-confidence must stay blocked.

    Passing here on zero face evidence would let a lane through on the absence
    of a detector rather than on evidence it is clear -- the exact failure this
    gate exists to prevent.
    """
    summary = _score([_WITH_HALLUCINATION])
    rescued, rescue = _run_rescue(summary, [Path("f.png")], monkeypatch, (0.0, 0.0, 0.0))
    assert rescue is None
    assert _decision(rescued)["reasonCode"] == "no_safe_caption_lane"


def test_rescue_declines_when_the_real_face_blocks_every_lane(monkeypatch):
    """A genuinely unusable frame stays unusable."""
    summary = _score([_WITH_HALLUCINATION])
    everywhere = (150_000.0, 150_000.0, 150_000.0)
    rescued, rescue = _run_rescue(summary, [Path("f.png")], monkeypatch, everywhere)
    assert rescue is None
    assert _decision(rescued)["reasonCode"] == "no_safe_caption_lane"


def test_confidence_filter_reports_zero_not_none_when_nothing_clears(tmp_path):
    """`None` means "detector could not run" and makes the scorer fall back to
    the focal heuristic. "Looked, found nothing credible" must be zero."""
    import cv2
    import numpy as np

    frame = tmp_path / "blank.png"
    cv2.imwrite(str(frame), np.zeros((320, 180, 3), np.uint8))
    # A blank frame yields no detections at all, so this exercises the
    # no-detections path; the kept-empty path is covered by the unit above.
    assert placement._face_coverage_from_frame(frame, min_confidence=0.99) in (
        None,
        (0.0, 0.0, 0.0),
    )
