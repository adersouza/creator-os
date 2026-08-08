"""A forced band must be checked against what the caption actually covers.

`apply_creator_style_preset` forces `lower_center` for the Stacey/Larissa
format and `reel_pipeline` then rewrote every recipe's band with it, discarding
the placement result computed moments earlier.

The obvious fix -- defer whenever the enclosing LANE was rejected -- is wrong.
Lane vetoes are computed on thirds: `center` spans 33.3%-66.7% of frame height
while a lower_center caption occupies 51%-66%, so a face at 33-51% rejects the
lane without touching the text. Measured on the 424-clip run, the lane rule
downgrades 252 clips; the caption-window rule downgrades 8, and all 8 were
confirmed by eye to have the chin entering the caption band.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reel_factory.reel_pipeline_support import (  # noqa: E402
    _FORCED_BAND_FACE_OVERLAP,
    resolve_forced_caption_band,
)


class _Summary:
    def __init__(self, overlaps=None, rejected=()):
        self.metadata = {
            "captionPlacementDecision": {"rejectedLanes": list(rejected)},
        }
        if overlaps is not None:
            self.metadata["subBandFaceOverlap"] = overlaps


CLEAR = {"top": 0.0, "center": 0.0, "lower_center": 0.0, "bottom": 0.0}


class ForcedBandResolutionTests(unittest.TestCase):
    def test_a_clear_caption_window_keeps_the_forced_band(self):
        band, downgrade = resolve_forced_caption_band(
            "lower_center", _Summary(CLEAR), "bottom"
        )
        self.assertEqual(band, "lower_center")
        self.assertIsNone(downgrade)

    def test_a_rejected_lane_alone_does_not_downgrade(self):
        # The 252-vs-8 case: center lane vetoed, caption window still clear.
        band, downgrade = resolve_forced_caption_band(
            "lower_center", _Summary(CLEAR, rejected=["center", "top"]), "bottom"
        )
        self.assertEqual(band, "lower_center")
        self.assertIsNone(downgrade)

    def test_a_face_under_the_caption_downgrades(self):
        overlaps = {**CLEAR, "lower_center": 0.44}
        band, downgrade = resolve_forced_caption_band(
            "lower_center", _Summary(overlaps), "bottom"
        )
        self.assertNotEqual(band, "lower_center")
        self.assertIsNotNone(downgrade)
        self.assertEqual(downgrade["forcedBand"], "lower_center")
        self.assertEqual(downgrade["faceOverlap"], 0.44)

    def test_the_fallback_band_is_itself_verified(self):
        # bottom is also covered, so it must not be chosen as the escape hatch.
        overlaps = {"top": 0.0, "center": 0.9, "lower_center": 0.5, "bottom": 0.8}
        band, downgrade = resolve_forced_caption_band(
            "lower_center", _Summary(overlaps), "bottom"
        )
        self.assertEqual(band, "top")
        self.assertEqual(downgrade["clearAlternatives"], ["top"])

    def test_no_signal_leaves_the_forced_band_alone(self):
        # Detector unavailable: downgrading on no evidence would silently move
        # every caption off the house-style band.
        band, downgrade = resolve_forced_caption_band(
            "lower_center", _Summary(None, rejected=["center"]), "bottom"
        )
        self.assertEqual(band, "lower_center")
        self.assertIsNone(downgrade)

    def test_auto_band_is_untouched(self):
        for value in ("auto", None):
            band, downgrade = resolve_forced_caption_band(value, _Summary(CLEAR), "top")
            self.assertEqual(band, value)
            self.assertIsNone(downgrade)

    def test_threshold_is_a_boundary_not_a_cliff(self):
        just_under = {**CLEAR, "lower_center": _FORCED_BAND_FACE_OVERLAP - 0.001}
        just_over = {**CLEAR, "lower_center": _FORCED_BAND_FACE_OVERLAP}
        self.assertIsNone(
            resolve_forced_caption_band("lower_center", _Summary(just_under), "bottom")[
                1
            ]
        )
        self.assertIsNotNone(
            resolve_forced_caption_band("lower_center", _Summary(just_over), "bottom")[
                1
            ]
        )


if __name__ == "__main__":
    unittest.main()
