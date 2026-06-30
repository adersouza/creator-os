import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from export_approved import export_approved
from hook_tools import find_near_duplicates, normalize_hook_text
from metrics_store import import_metrics_csv, metrics_summary
from placement_scorer import PlacementSummary, score_lanes
from reel_pipeline import (
    CaptionSegmentPlan,
    Manifest,
    Recipe,
    compute_job_key,
    resolve_segment_bands,
)


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

    def test_review_state_persists_to_manifest_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", src, "src-hash", 2.5)
            manifest.add_variation("clip_001", recipe, "caption", out, key, 2.5)
            self.assertTrue(manifest.set_review_state(out.name, "approved"))
            manifest.save()
            row = manifest.to_json_data()["videos"]["clip_001"]["variations"][0]
            self.assertEqual(row["review_state"], "approved")

    def test_review_decision_history_undo_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", src, "src-hash", 2.5)
            manifest.add_variation("clip_001", recipe, "caption", out, key, 2.5)

            self.assertTrue(
                manifest.record_review_decision(
                    out.name,
                    "maybe",
                    reviewer="ader",
                    reason="needs second look",
                    deck_id="deck_1",
                    reference_hash="reference_hash_1",
                    soul_id="stacey",
                    aspect_ratio="3:4",
                    visual_qc_status="passed",
                    identity_verification_status="passed",
                )
            )
            self.assertTrue(
                manifest.record_review_decision(
                    out.name, "approved", reviewer="ader", deck_id="deck_1"
                )
            )
            history_count = manifest.conn.execute(
                "SELECT COUNT(*) AS n FROM review_decision_history"
            ).fetchone()["n"]
            self.assertEqual(history_count, 2)
            self.assertTrue(manifest.undo_review_decision(out.name, reviewer="ader"))
            row = manifest.conn.execute(
                "SELECT decision FROM review_decisions WHERE filename = ?", (out.name,)
            ).fetchone()
            self.assertEqual(row["decision"], "maybe")

            review_root = root / "review_views"
            counts = manifest.regenerate_review_folders(review_root, deck_id="deck_1")
            self.assertEqual(counts["maybe"], 1)
            self.assertTrue((review_root / "maybe" / out.name).exists())
            self.assertTrue(
                manifest.review_integrity_check(
                    deck_id="deck_1", folder_root=review_root
                )["ok"]
            )

            out.write_bytes(b"tampered")
            integrity = manifest.review_integrity_check(
                deck_id="deck_1", folder_root=review_root
            )
            self.assertFalse(integrity["ok"])
            self.assertIn(
                "hash_mismatch", {issue["type"] for issue in integrity["issues"]}
            )

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

    def test_metrics_import_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", src, "src-hash", 2.5)
            manifest.add_variation("clip_001", recipe, "caption", out, key, 2.5)
            manifest.save()

            metrics = root / "metrics.csv"
            with metrics.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["filename", "views", "likes", "platform"]
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "filename": out.name,
                        "views": "1000",
                        "likes": "50",
                        "platform": "ig",
                    }
                )
                writer.writerow(
                    {
                        "filename": "unknown.mp4",
                        "views": "5",
                        "likes": "1",
                        "platform": "ig",
                    }
                )

            result = import_metrics_csv(root, metrics)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["ignored"], ["unknown.mp4"])
            summary = metrics_summary(root)
            self.assertEqual(summary[0]["avg_views"], 1000.0)
            self.assertEqual(summary[0]["avg_likes"], 50.0)

    def test_export_approved_outputs_json_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe, target_ratio="4:5")
            manifest.upsert_video("clip_001", src, "src-hash", 2.5)
            manifest.add_variation(
                "clip_001", recipe, "caption", out, key, 2.5, target_ratio="4:5"
            )
            manifest.set_review_state(out.name, "approved")
            manifest.save()

            result = export_approved(
                root, account="acct", platform="ig", date="2026-05-13"
            )

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["items"][0]["target_ratio"], "4:5")
            self.assertEqual(
                result["items"][0]["audio_workflow"]["warning"], "missing_audio_intent"
            )
            self.assertTrue(Path(result["path"]).exists())

    def test_export_approved_preserves_audio_intent_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            out.with_suffix(out.suffix + ".audio_intent.json").write_text(
                '{"schema":"pipeline.audio_intent.v1","required":true,"status":"recommended"}',
                encoding="utf-8",
            )
            out.with_suffix(out.suffix + ".generated_asset_lineage.json").write_text(
                '{"schema":"campaign_factory.generated_asset_lineage.v1","source":{"patternCardId":"pattern_1"},"generation":{"tool":"higgsfield_kling_manual"},"review":{"humanReviewRequired":true}}',
                encoding="utf-8",
            )
            (root / "_readiness.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.readiness.v1",
                        "platform": "instagram_reels",
                        "records": [
                            {
                                "filename": out.name,
                                "status": "warn",
                                "score": 90,
                                "warnings": ["missing_audio_intent"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", src, "src-hash", 2.5)
            manifest.add_variation("clip_001", recipe, "caption", out, key, 2.5)
            manifest.set_review_state(out.name, "approved")
            manifest.save()

            result = export_approved(
                root, account="acct", platform="ig", date="2026-05-13"
            )

            self.assertEqual(
                result["items"][0]["audio_intent"]["status"], "recommended"
            )
            self.assertEqual(
                result["items"][0]["generated_asset_lineage"]["source"][
                    "patternCardId"
                ],
                "pattern_1",
            )
            self.assertEqual(result["items"][0]["platform_readiness"]["status"], "warn")
            self.assertTrue(
                result["items"][0]["audio_workflow"]["local_muxing_is_preview_only"]
            )
            self.assertNotIn("warning", result["items"][0]["audio_workflow"])


if __name__ == "__main__":
    unittest.main()
