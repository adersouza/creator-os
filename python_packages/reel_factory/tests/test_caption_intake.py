import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caption_bank import CaptionBankStore, caption_hash, load_or_build_caption_bank_store
from caption_intake import plan_placement, promote, scan_local


class CaptionIntakeTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "01_captions").mkdir()
        (root / "01_captions" / "clip_001.json").write_text(
            json.dumps({"hooks": ["be honest\nam i your type"]}),
            encoding="utf-8",
        )
        CaptionBankStore.build(root).write(root)
        return root

    def test_scan_local_dedupes_existing_captions(self):
        root = self._root()
        source = root / "tmp" / "lineage.json"
        source.parent.mkdir()
        source.write_text(
            json.dumps(
                {
                    "rawCaptionText": "be honest\nam i your type",
                    "captionOutcomeContext": {"caption_text": "would you date me or run away?"},
                }
            ),
            encoding="utf-8",
        )

        report = scan_local(root, include_seed=False)
        texts = {row["text"] for row in report["candidates"]}

        self.assertIn("would you date me or run away?", texts)
        self.assertNotIn("be honest\nam i your type", texts)

    def test_candidate_intake_does_not_affect_caption_mix(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [{"text": "brand new candidate", "caption_hash": caption_hash("brand new candidate")}],
                }
            ),
            encoding="utf-8",
        )

        store = load_or_build_caption_bank_store(root)
        selected = store.resolve_mix("Stacey", limit=None)

        self.assertNotIn("brand new candidate", {item["text"] for item in selected})

    def test_promote_rejects_unsafe_approved_caption(self):
        root = self._root()
        approved = root / "approved.json"
        approved.write_text(json.dumps(["link in bio", "safe little question?"]), encoding="utf-8")

        report = promote(root, approved)
        store = CaptionBankStore.from_root(root)
        texts = {item["text"] for item in store.all_items()}

        self.assertEqual(report["promoted"], 1)
        self.assertIn("safe little question?", texts)
        self.assertNotIn("link in bio", texts)
        self.assertEqual(report["rejected"][0]["blockedTerms"], ["link"])

    def test_promote_rebuilds_banks_with_approved_caption(self):
        root = self._root()
        approved = root / "approved.txt"
        approved.write_text("would you say hi first?", encoding="utf-8")

        report = promote(root, approved)
        store = CaptionBankStore.from_root(root)
        promoted = next(item for item in store.all_items() if item["text"] == "would you say hi first?")

        self.assertEqual(report["promoted"], 1)
        self.assertEqual(Path(report["sidecar"]).name[:16], "approved_intake_")
        self.assertIn("comment_bait", promoted["banks"])

    def test_plan_placement_adds_timed_hooks_without_explicit_bands(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [
                        {
                            "caption_hash": caption_hash("wife material\nor heartbreak material?"),
                            "text": "wife material\nor heartbreak material?",
                            "banks": ["shared_girl_next_door", "boyfriend_bait"],
                            "status": "candidate",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = plan_placement(root)
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        row = payload["candidates"][0]
        segments = row["hookVariants"]["timed"]["segments"]

        self.assertEqual(report["timedEligible"], 1)
        self.assertEqual(row["placementIntent"]["staticBand"], "lower_center")
        self.assertEqual(row["placementIntent"]["timedPlacementMode"], "segment")
        self.assertFalse(any("band" in segment for segment in segments))
        self.assertTrue(Path(report["reviewFile"]).exists())


if __name__ == "__main__":
    unittest.main()
