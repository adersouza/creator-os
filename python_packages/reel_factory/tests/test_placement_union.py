"""Whole-clip subject union: hard blockers (face/pose) use max across frames so a
static caption never lands where the subject appears on ANY frame."""

from placement_scorer import _max3, _mean3, score_lanes


def test_max3_is_worst_case_per_lane():
    samples = [(0.0, 0.0, 9.0), (8.0, 0.0, 0.0)]  # face top on f2, bottom on f1
    assert _max3(samples) == (8.0, 0.0, 9.0)
    assert _mean3(samples) == (4.0, 0.0, 4.5)  # mean would hide the peaks


def test_face_union_blocks_lane_seen_on_any_frame():
    # face never in center; appears TOP on one frame, BOTTOM on another.
    face = [(10.0, 0.0, 0.0), (0.0, 0.0, 10.0)]
    s = score_lanes(stddev_samples=[(1.0, 1.0, 1.0)], face_samples=face)
    lane = s.lane
    # center is the only lane the face never enters -> must win.
    assert lane == "center", (lane, s.metadata)


def test_no_regression_when_static_single_frame():
    # single frame: max == mean, behavior identical to before.
    face = [(0.0, 0.0, 6.0)]  # face bottom -> caption should avoid bottom
    s = score_lanes(stddev_samples=[(1.0, 1.0, 1.0)], face_samples=face)
    assert s.lane in ("top", "center")
