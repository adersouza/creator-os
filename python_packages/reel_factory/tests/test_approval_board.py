import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from approval_board import HARD_REJECT_REASONS, build_approval_board, promote_approval_decisions


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
                            "normal": {
                                "path": str(normal),
                                "captionPlacementDecision": {
                                    "status": "passed",
                                    "selectedLane": "lower_center",
                                    "reason": "Stacey preset render band",
                                },
                            },
                            "timed": {
                                "path": str(timed),
                                "captionPlacementDecision": {
                                    "status": "passed",
                                    "selectedLane": "lower_center,lower_center_alt",
                                    "reason": "Timed Stacey preset render bands",
                                },
                            },
                            "contentForgeStatus": "warn",
                            "contentForgeWarnings": ["caption_low_contrast", "watchability_static_opening"],
                            "contentForgeBlockingCodes": [],
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
        self.assertEqual(decisions["items"][0]["selected_lanes"], [])
        self.assertEqual(set(decisions["items"][0]["lanes"]), {"clean", "normal", "timed"})
        self.assertEqual(decisions["items"][0]["review_status"], "review")
        self.assertEqual(decisions["items"][0]["contentforge"]["warningCodes"], ["caption_low_contrast", "watchability_static_opening"])
        self.assertEqual(decisions["items"][0]["placement"]["lanes"]["normal"]["finalBand"], "lower_center")
        self.assertIn("caption_bad_placement", decisions["hardRejectReasons"])
        self.assertIn(HARD_REJECT_REASONS[0], html)
        self.assertIn("Manual lane: no burned text", html)
        self.assertIn("Timed Overlay", html)
        self.assertIn("caption_low_contrast", html)
        self.assertIn("watchability_static_opening", html)
        self.assertIn("scored unknown", html)
        self.assertIn("rendered lower_center", html)
        self.assertIn('data-filter="caption"', html)
        self.assertIn('data-review-status="review"', html)
        self.assertIn("select any lanes", html)
        self.assertIn("approval_decisions.reviewed.json", html)
        self.assertIn('data-lane="normal"', html)
        self.assertIn('data-grade="A"', html)
        self.assertIn('data-rating-field="post_potential"', html)
        self.assertIn('original.manifestPath + ":" + original.createdAt', html)

        with Path(result["decisionCsvPath"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["stem"], "ref07_stacey_faithful")
        self.assertEqual(rows[0]["selected_lane"], "")
        self.assertEqual(rows[0]["selected_lanes"], "")
        self.assertEqual(rows[0]["timed"], str(timed))

    def test_promotes_approved_selected_lanes_to_one_folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        clean_source = root / "clean.mp4"
        timed_source = root / "timed.mp4"
        clean_source.write_bytes(b"clean")
        timed_source.write_bytes(b"timed")
        decisions = root / "approval_decisions.json"
        decisions.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.approval_decisions.v1",
                    "items": [
                        {
                            "id": 2,
                            "stem": "ref02_stacey",
                            "source_board_id": 4,
                            "status": "approved",
                            "selected_lane": "normal",
                            "selected_lanes": ["clean", "timed"],
                            "grade": "A",
                            "ratings": {"model_match": 5, "post_potential": 4},
                            "notes": "good",
                            "image": str(root / "source.png"),
                            "lanes": {
                                "clean": {"path": str(clean_source), "decision": "pending", "notes": ""},
                                "timed": {"path": str(timed_source), "decision": "pending", "notes": ""},
                            },
                        },
                        {
                            "id": 3,
                            "stem": "ref03_stacey",
                            "status": "rejected",
                            "selected_lane": "timed",
                            "lanes": {"timed": {"path": str(root / "timed.mp4")}},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = promote_approval_decisions(decisions)
        manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))

        self.assertEqual(result["count"], 2)
        self.assertEqual([item["selectedLane"] for item in manifest["items"]], ["clean", "timed"])
        self.assertEqual(manifest["items"][0]["selectedLanes"], ["clean", "timed"])
        self.assertEqual(manifest["items"][0]["grade"], "A")
        self.assertEqual(manifest["items"][0]["ratings"]["post_potential"], 4)
        self.assertEqual(manifest["items"][0]["notes"], "good")
        self.assertEqual(manifest["items"][0]["sourceSha256"], hashlib.sha256(b"clean").hexdigest())
        self.assertEqual(manifest["items"][0]["outputSha256"], hashlib.sha256(b"clean").hexdigest())
        self.assertEqual(manifest["items"][0]["contentForgeStatus"], None)
        copied = [Path(item["outputPath"]).read_bytes() for item in manifest["items"]]
        self.assertEqual(copied, [b"clean", b"timed"])

    def test_builds_board_from_contentforge_audit_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        normal = root / "normal.mp4"
        normal.write_bytes(b"normal")
        audit = root / "review.contentforge_audit.json"
        audit.write_text(
            json.dumps(
                {
                    "schema": "campaign_factory.review_batch_contentforge_audit.v1",
                    "fileResults": [
                        {
                            "outputPath": str(normal),
                            "status": "review",
                            "warningCodes": ["watchability_static_opening"],
                            "blockingCodes": [],
                            "topWarnings": [{"code": "watchability_static_opening", "message": "Static opening"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest = root / "review_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema": "creator_os.approved_reel_batch.v1",
                    "contentForgeAuditPath": str(audit),
                    "items": [
                        {
                            "id": 1,
                            "stem": "with_audit_path",
                            "normal": {"path": str(normal)},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = build_approval_board(manifest, title="Audit Path Board")
        decisions = json.loads(Path(result["decisionJsonPath"]).read_text(encoding="utf-8"))

        self.assertEqual(decisions["items"][0]["review_status"], "review")
        self.assertEqual(decisions["items"][0]["contentforge"]["warningCodes"], ["watchability_static_opening"])


if __name__ == "__main__":
    unittest.main()
