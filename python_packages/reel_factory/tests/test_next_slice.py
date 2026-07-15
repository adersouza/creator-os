import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reel_factory.hook_tools import find_near_duplicates, normalize_hook_text
from reel_factory.placement_scorer import PlacementSummary, score_lanes
from reel_factory.reel_pipeline import (
    CaptionSegmentPlan,
    Recipe,
    compute_job_key,
    resolve_segment_bands,
)


def _fixture_lineage_identity(lineage, *_args, **_kwargs):
    return {
        **lineage,
        "contentFingerprint": "a" * 64,
        "perceptualFingerprint": "phash64:0000000000000000",
        "perceptualClusterId": "phash64:0000000000000000",
        "perceptualAlgorithm": "frame_sampled_phash_v1",
        "sourceFamilyId": "fixture-family",
    }


class NextSliceTests(unittest.TestCase):
    def test_placement_scorer_chooses_lowest_lane(self):
        summary = score_lanes(
            stddev_samples=[(40.0, 10.0, 20.0)],
            face_samples=[(0.0, 0.0, 100.0)],
            motion_samples=[(5.0, 5.0, 5.0)],
            center_penalty=8.0,
        )
        self.assertEqual(summary.lane, "center")
        self.assertLess(summary.scores["center"], summary.scores["top"])

    def test_fuzzy_duplicate_detection_catches_near_dupes(self):
        hooks = [
            "when he says he misses you",
            "when he say he misses u",
            "completely different hook",
        ]
        dupes = find_near_duplicates(hooks, threshold=88)
        self.assertEqual(dupes[0]["first"], 0)
        self.assertEqual(dupes[0]["duplicate"], 1)
        self.assertEqual(normalize_hook_text(hooks[0]), "when he says he misses you")

    def test_segment_mode_keeps_single_segment_on_source_band(self):
        async def fake_probe(*args, **kwargs):
            return PlacementSummary("right", {"side_right": 1.0}, 3, "right")

        with tempfile.TemporaryDirectory() as tmp:
            plan = CaptionSegmentPlan(Path(tmp) / "a.png", 0.0, None, "hello", "bottom")
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=[plan],
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=5.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual(resolved[0].band, "bottom")

    def test_segment_mode_keeps_stacey_timed_captions_lower_center(self):
        async def fake_probe(*args, **kwargs):
            raise AssertionError(
                "lower-center timed captions should not re-probe into top/bottom lanes"
            )

        with tempfile.TemporaryDirectory() as tmp:
            plans = [
                CaptionSegmentPlan(
                    Path(tmp) / "a.png", 0.0, 2.0, "first", "lower_center"
                ),
                CaptionSegmentPlan(
                    Path(tmp) / "b.png", 2.0, 4.0, "second", "lower_center_alt"
                ),
                CaptionSegmentPlan(
                    Path(tmp) / "c.png", 4.0, None, "third", "lower_center"
                ),
            ]
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=plans,
                    source_band="lower_center",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=6.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual(
                [s.band for s in resolved],
                ["lower_center", "lower_center_alt", "lower_center"],
            )

    def test_segment_mode_uses_segment_probe_when_score_is_clear(self):
        calls = [
            PlacementSummary(
                "right", {"side_right": 10.0, "side_left": 100.0}, 3, "right"
            ),
            PlacementSummary(
                "left", {"side_left": 20.0, "side_right": 100.0}, 3, "left"
            ),
        ]

        async def fake_probe(*args, **kwargs):
            return calls.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            plans = [
                CaptionSegmentPlan(Path(tmp) / "a.png", 0.0, 2.0, "first", "bottom"),
                CaptionSegmentPlan(Path(tmp) / "b.png", 2.0, 4.0, "second", "bottom"),
            ]
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=plans,
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=5.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual([s.band for s in resolved], ["right", "left"])

    def test_segment_mode_prevents_short_left_right_flip(self):
        calls = [
            PlacementSummary(
                "right", {"side_right": 10.0, "side_left": 100.0}, 3, "right"
            ),
            PlacementSummary(
                "left", {"side_left": 1.0, "side_right": 100.0}, 3, "left"
            ),
        ]

        async def fake_probe(*args, **kwargs):
            return calls.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            plans = [
                CaptionSegmentPlan(Path(tmp) / "a.png", 0.0, 1.0, "first", "bottom"),
                CaptionSegmentPlan(Path(tmp) / "b.png", 1.0, 2.0, "second", "bottom"),
            ]
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=plans,
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=5.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual([s.band for s in resolved], ["right", "right"])

    def test_segment_mode_moves_repeated_lane_for_retention_when_safe(self):
        calls = [
            PlacementSummary(
                "top", {"top": 10.0, "bottom": 18.0, "center": 25.0}, 3, "top"
            ),
            PlacementSummary(
                "top", {"top": 10.0, "bottom": 18.0, "center": 25.0}, 3, "top"
            ),
            PlacementSummary(
                "top", {"top": 10.0, "bottom": 18.0, "center": 25.0}, 3, "top"
            ),
        ]

        async def fake_probe(*args, **kwargs):
            return calls.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            plans = [
                CaptionSegmentPlan(Path(tmp) / "a.png", 0.0, 2.0, "first", "bottom"),
                CaptionSegmentPlan(Path(tmp) / "b.png", 2.0, 4.0, "second", "bottom"),
                CaptionSegmentPlan(Path(tmp) / "c.png", 4.0, 6.0, "third", "bottom"),
            ]
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=plans,
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=7.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual([s.band for s in resolved], ["top", "bottom", "top"])

    def test_segment_mode_keeps_repeated_lane_when_alternates_are_bad(self):
        calls = [
            PlacementSummary(
                "top", {"top": 10.0, "bottom": 70.0, "center": 80.0}, 3, "top"
            ),
            PlacementSummary(
                "top", {"top": 10.0, "bottom": 70.0, "center": 80.0}, 3, "top"
            ),
        ]

        async def fake_probe(*args, **kwargs):
            return calls.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            plans = [
                CaptionSegmentPlan(Path(tmp) / "a.png", 0.0, 2.0, "first", "bottom"),
                CaptionSegmentPlan(Path(tmp) / "b.png", 2.0, 4.0, "second", "bottom"),
            ]
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=plans,
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=5.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual([s.band for s in resolved], ["top", "top"])

    def test_long_side_caption_falls_back_to_lane(self):
        async def fake_probe(*args, **kwargs):
            return PlacementSummary(
                "right",
                {"top": 10.0, "bottom": 30.0, "side_right": 1.0, "side_left": 100.0},
                3,
                "right",
            )

        with tempfile.TemporaryDirectory() as tmp:
            long_text = (
                "this is a very long caption that should wrap into a tall side caption"
            )
            plan = CaptionSegmentPlan(
                Path(tmp) / "a.png", 0.0, 2.0, long_text, "bottom"
            )
            resolved = __import__("asyncio").run(
                resolve_segment_bands(
                    Path("clip.mp4"),
                    segments=[
                        plan,
                        CaptionSegmentPlan(
                            Path(tmp) / "b.png", 2.0, 4.0, "short", "bottom"
                        ),
                    ],
                    source_band="bottom",
                    placement_mode="segment",
                    placement_signals="basic",
                    recipe=Recipe("v01_original"),
                    duration=5.0,
                    probe_func=fake_probe,
                )
            )
            self.assertEqual(resolved[0].band, "top")

    def test_segment_mode_changes_job_key_but_source_default_does_not(self):
        recipe = Recipe("v01_original")
        default_key = compute_job_key("hash", "caption", recipe)
        explicit_source_key = compute_job_key(
            "hash", "caption", recipe, placement_mode="source"
        )
        segment_key = compute_job_key(
            "hash", "caption", recipe, placement_mode="segment"
        )
        self.assertEqual(default_key, explicit_source_key)
        self.assertNotEqual(default_key, segment_key)


if __name__ == "__main__":
    unittest.main()
