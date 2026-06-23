import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from approval_board import HARD_REJECT_REASONS, build_approval_board


class ApprovalBoardTests(unittest.TestCase):
    def test_builds_board_and_pending_decision_files(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        manifest = root / "approved_manifest.json"
        source = root / "source.png"
        clean = root / "clean.mp4"
        normal = root / "normal.mp4"
        timed = root / "timed.mp4"
        for path in (source, clean, normal, timed):
            path.write_bytes(b"placeholder")
        manifest.write_text(
            json.dumps(
                {
                    "schema": "creator_os.approved_reel_batch.v1",
                    "count": 1,
                    "items": [
                        {
                            "id": 1,
                            "source_board_id": 7,
                            "stem": "ref07_stacey_faithful",
                            "image": str(source),
                            "clean": str(clean),
                            "normal": str(normal),
                            "timed": str(timed),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = build_approval_board(manifest, title="Test Board")
        decisions = json.loads(Path(result["decisionJsonPath"]).read_text(encoding="utf-8"))
        html = Path(result["boardPath"]).read_text(encoding="utf-8")

        self.assertEqual(result["count"], 1)
        self.assertEqual(decisions["items"][0]["status"], "pending")
        self.assertIsNone(decisions["items"][0]["selected_lane"])
        self.assertEqual(set(decisions["items"][0]["lanes"]), {"clean", "normal", "timed"})
        self.assertIn("caption_bad_placement", decisions["hardRejectReasons"])
        self.assertIn(HARD_REJECT_REASONS[0], html)
        self.assertIn("Manual lane: no burned text", html)
        self.assertIn("Timed Overlay", html)

        with Path(result["decisionCsvPath"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["stem"], "ref07_stacey_faithful")
        self.assertEqual(rows[0]["selected_lane"], "")
        self.assertEqual(rows[0]["timed"], str(timed))


if __name__ == "__main__":
    unittest.main()
