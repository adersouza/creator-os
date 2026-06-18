import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from readiness_check import evaluate_output, run_readiness
from virality_qc import evaluate_virality_report


class ViralityQcTests(unittest.TestCase):
    def test_evaluate_virality_report_passes_high_supplied_higgsfield_report(self):
        result = evaluate_virality_report(
            {
                "report_id": "vf_1",
                "provider": "higgsfield",
                "model": "virality_predictor",
                "viralityScore": 87,
                "hookScore": 72,
                "retentionRisk": 22,
            },
            required=True,
        )

        self.assertEqual(result["schema"], "reel_factory.virality_qc.v1")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["score"], 87)
        self.assertEqual(result["reportId"], "vf_1")
        self.assertEqual(result["warnings"], [])

    def test_evaluate_virality_report_blocks_low_score_when_required(self):
        result = evaluate_virality_report(
            {
                "score": 0.42,
                "prediction": {"hookScore": 0.7, "retentionRisk": 0.2},
            },
            required=True,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("virality_score_low", result["warnings"])
        self.assertEqual(result["score"], 42)

    def test_readiness_blocks_missing_virality_only_when_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "02_processed" / "clip_001" / "clip_001_h00_v01_original_light_deadbeef.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"fake")

            default_row = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=output,
                platform="instagram_reels",
                dimensions=(1080, 1920),
            )
            required_row = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=output,
                platform="instagram_reels",
                dimensions=(1080, 1920),
                require_virality=True,
            )

            self.assertNotIn("virality_report_missing", default_row["warnings"])
            self.assertEqual(required_row["status"], "not_ready")
            self.assertIn("virality_report_missing", required_row["warnings"])
            self.assertEqual(required_row["viralityQc"]["status"], "failed")

    def test_run_readiness_reads_output_virality_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "02_processed" / "clip_001" / "clip_001_h00_v01_original_light_deadbeef.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"fake")
            output.with_suffix(output.suffix + ".virality_report.json").write_text(
                json.dumps({"provider": "higgsfield", "score": 91, "hookScore": 75, "retentionRisk": 20}),
                encoding="utf-8",
            )

            result = run_readiness(root, clip="clip_001", require_virality=True)

            self.assertEqual(result["summary"]["not_ready"], 0)
            self.assertEqual(result["records"][0]["viralityQc"]["status"], "passed")
            self.assertEqual(result["records"][0]["viralityQc"]["score"], 91)


if __name__ == "__main__":
    unittest.main()
