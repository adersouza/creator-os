import json
import tempfile
import unittest
from pathlib import Path

from benchmark_harness import create_benchmark_plan, record_benchmark_result


class BenchmarkHarnessTests(unittest.TestCase):
    def test_create_benchmark_plan_requires_shared_motion_and_writes_two_conditions(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "refs" / "reel_001.mp4"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"mp4")
            prompts = root / "prompts"
            prompts.mkdir()
            neutral = prompts / "reel_001_neutral.json"
            enhanced = prompts / "reel_001_enhanced.json"
            neutral.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid with fitted black dress and centered framing",
                        "klingMotionPrompt": "slow push in, subtle hip sway, steady handheld pacing",
                    }
                ),
                encoding="utf-8",
            )
            enhanced.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid with fitted black dress, deeper cleavage, fuller breasts, rounder ass, wider hips, tighter waist, centered framing",
                        "klingMotionPrompt": "slow push in, subtle hip sway, steady handheld pacing",
                    }
                ),
                encoding="utf-8",
            )

            result = create_benchmark_plan(
                root,
                [
                    {
                        "reel_id": "reel_001",
                        "reference_path": str(reference),
                        "neutral_prompt_json": str(neutral),
                        "enhanced_prompt_json": str(enhanced),
                    }
                ],
            )

            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["path"]).exists())
            plan = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                plan["schema"], "reel_factory.visual_direction_benchmark.v1"
            )
            self.assertEqual(plan["conditions"], ["neutral", "enhanced"])
            self.assertEqual(
                plan["reels"][0]["sharedKlingMotionPrompt"],
                "slow push in, subtle hip sway, steady handheld pacing",
            )
            self.assertEqual(set(plan["reels"][0]["variants"]), {"neutral", "enhanced"})
            self.assertEqual(
                plan["reels"][0]["variants"]["neutral"]["gridStem"],
                "reel_001_neutral_grid",
            )
            self.assertEqual(
                plan["reels"][0]["variants"]["enhanced"]["gridStem"],
                "reel_001_enhanced_grid",
            )
            self.assertEqual(
                len(plan["reels"][0]["variants"]["neutral"]["panelAnimationStems"]), 6
            )
            self.assertEqual(
                len(plan["reels"][0]["variants"]["enhanced"]["panelAnimationStems"]), 6
            )

    def test_create_benchmark_plan_rejects_different_motion_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "ref.mp4"
            reference.write_bytes(b"mp4")
            neutral = root / "neutral.json"
            enhanced = root / "enhanced.json"
            neutral.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid with fitted black dress",
                        "klingMotionPrompt": "slow push in",
                    }
                ),
                encoding="utf-8",
            )
            enhanced.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid with fitted black dress and stronger curves",
                        "klingMotionPrompt": "fast zoom",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "same klingMotionPrompt"):
                create_benchmark_plan(
                    root,
                    [
                        {
                            "reel_id": "reel_001",
                            "reference_path": str(reference),
                            "neutral_prompt_json": str(neutral),
                            "enhanced_prompt_json": str(enhanced),
                        }
                    ],
                )

    def test_record_benchmark_result_appends_operator_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = record_benchmark_result(
                root,
                benchmark_id="visual_direction_v1",
                reel_id="reel_001",
                winner="enhanced",
                reason="better outfit fit, stronger curves, cleaner framing",
                selected_panels={"neutral": 2, "enhanced": 5},
                scores={"neutral": 3, "enhanced": 5},
            )

            self.assertTrue(result["ok"])
            path = Path(result["path"])
            self.assertTrue(path.exists())
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["winner"], "enhanced")
            self.assertEqual(rows[0]["selectedPanels"]["enhanced"], 5)
            self.assertEqual(rows[0]["scores"]["neutral"], 3)


if __name__ == "__main__":
    unittest.main()
