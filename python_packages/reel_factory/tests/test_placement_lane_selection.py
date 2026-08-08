"""A passed placement must never select a lane it also rejected.

`lane = min(LANES, ...)` ran BEFORE `rejected_lanes` was computed, so the
cheapest lane won even when the vetoes had disqualified it. Real QC row
src_55f2caedfb passed with selectedLane="top" while rejectedLanes was
["top", "center"] -- top scored 140.3 against bottom's 144.4 and won a
comparison the veto should have removed it from.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reel_factory.placement_scorer import LANES, score_lanes  # noqa: E402


def _decision(**kw):
    summary = score_lanes(stddev_samples=[(1.0, 1.0, 1.0)], **kw)
    return summary, summary.metadata["captionPlacementDecision"]


class LaneSelectionTests(unittest.TestCase):
    # Reproduces the real defect. Face coverage is MAX-NORMALIZED, so the top
    # lane's 0.6 against center's 1.0 becomes a relative 108 -- over the 70 veto
    # threshold, yet still the cheapest lane of the three (top 108, center 188,
    # bottom 120). That combination is what let the old code select a lane it
    # had just rejected. A plain "face only in the top lane" fixture does NOT
    # reproduce it: there the vetoed lane is also the most expensive, so the old
    # min() happened to agree with the veto and the test passed on broken code.
    VETOED_CHEAPEST = dict(
        stddev_samples=[(0.0, 0.0, 0.0)],
        focal_samples=[(0.0, 0.0, 0.2)],
        face_samples=[(0.6, 1.0, 0.0)],
    )

    def test_selected_lane_is_never_a_rejected_lane(self):
        summary = score_lanes(**self.VETOED_CHEAPEST)
        decision = summary.metadata["captionPlacementDecision"]
        self.assertEqual(decision["status"], "passed")
        self.assertNotIn(decision["selectedLane"], decision["rejectedLanes"])

    def test_a_vetoed_cheapest_lane_hands_off_to_the_next_survivor(self):
        summary = score_lanes(**self.VETOED_CHEAPEST)
        decision = summary.metadata["captionPlacementDecision"]
        scores = decision["scores"]
        # The lane the OLD rule would have taken, to pin why this fixture matters.
        cheapest = min(LANES, key=lambda k: (scores[k], 0 if k != "center" else 1))
        self.assertIn(cheapest, decision["rejectedLanes"])
        self.assertEqual(decision["selectedLane"], "bottom")

    def test_every_lane_rejected_still_fails_closed(self):
        # Face everywhere -> nothing survives -> no caption, not a coin flip.
        _, decision = _decision(
            face_samples=[(1.0, 1.0, 1.0)], head_samples=[(1.0, 1.0, 1.0)]
        )
        self.assertEqual(set(decision["rejectedLanes"]), set(LANES))
        self.assertEqual(decision["decisionClass"], "failed_no_safe_lane")
        self.assertIsNone(decision["selectedLane"])
        self.assertEqual(decision["renderPolicy"], "clean_without_overlay")

    def test_a_clean_frame_still_selects_the_cheapest_lane(self):
        # No vetoes -> behaviour must be identical to before the reorder.
        # Detector samples must be PRESENT (empty ones would trip
        # insufficient_evidence) but carry no coverage, so nothing is vetoed.
        summary, decision = _decision(focal_samples=[(0.0, 0.0, 0.0)])
        self.assertEqual(decision["rejectedLanes"], [])
        expected = min(
            LANES,
            key=lambda k: (summary.scores[k], 0 if k != "center" else 1),
        )
        self.assertEqual(decision["selectedLane"], expected)


if __name__ == "__main__":
    unittest.main()
