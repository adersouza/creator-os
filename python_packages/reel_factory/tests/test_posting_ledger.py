import json
import tempfile
import unittest
from pathlib import Path

from audio_intent import write_audio_intent
from campaign_store import connect as connect_campaign_store
from manifest import Manifest
from posting_ledger import (
    assign_approved_reels,
    create_posting_plan,
    export_schedule_package,
    ledger_conflicts,
    review_queue,
    transition_slot,
)

STACEY_SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
STACEY1_SOUL_ID = "5828d958-91dd-4d6d-8909-934503f47644"
LARISSA_SOUL_ID = "44326567-b12c-410c-95b7-31891bb0629b"


class PostingLedgerTests(unittest.TestCase):
    def test_pilot_plan_creates_105_slots_and_enforces_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            accounts = [f"stacey_{idx}" for idx in range(5)]

            result = create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=accounts,
                start_date="2026-06-03",
                days=7,
            )
            self.assertEqual(result["created"], 105)
            self.assertEqual(result["slot_count"], 105)

            second = create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=accounts,
                start_date="2026-06-03",
                days=7,
            )
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["existing"], 105)

    def test_assignment_blocks_same_content_even_when_filename_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=["stacey_a"],
                start_date="2026-06-03",
                days=1,
            )
            video_a = root / "a.mp4"
            video_b = root / "renamed" / "b.mp4"
            video_b.parent.mkdir()
            video_a.write_bytes(b"same rendered reel bytes")
            video_b.write_bytes(b"same rendered reel bytes")
            lineage_a = video_a.with_suffix(
                video_a.suffix + ".generated_asset_lineage.json"
            )
            lineage_b = video_b.with_suffix(
                video_b.suffix + ".generated_asset_lineage.json"
            )
            lineage = {
                "source": {"sourceReferenceId": "ref_a", "soulName": "Stacey"},
                "generation": {"klingJobId": "kling_1"},
            }
            lineage_a.write_text(json.dumps(lineage), encoding="utf-8")
            lineage_b.write_text(json.dumps(lineage), encoding="utf-8")

            approved = {
                "schema": "reel_factory.approved_export.v1",
                "items": [
                    {
                        "output_path": str(video_a),
                        "hook_text": "caption a",
                        "campaign": {
                            "campaign_id": "camp_stacey",
                            "asset_generation_id": "asset_a",
                        },
                        "generated_asset_lineage": lineage,
                    },
                    {
                        "output_path": str(video_b),
                        "hook_text": "caption b",
                        "campaign": {
                            "campaign_id": "camp_stacey",
                            "asset_generation_id": "asset_b",
                        },
                        "generated_asset_lineage": lineage,
                    },
                ],
            }
            approved_path = root / "approved.json"
            approved_path.write_text(json.dumps(approved), encoding="utf-8")

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )
            self.assertEqual(assigned["assigned"], 1)
            self.assertEqual(len(assigned["conflicts"]), 1)
            self.assertIn(
                "duplicate_content_fingerprint_for_account",
                assigned["conflicts"][0]["reasons"],
            )
            self.assertIn(
                "duplicate_content_fingerprint_for_campaign",
                assigned["conflicts"][0]["reasons"],
            )

    def test_assignment_blocks_cross_account_source_family_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=["stacey_a", "stacey_b"],
                start_date="2026-06-03",
                days=1,
            )
            video_a = root / "a.mp4"
            video_b = root / "b.mp4"
            video_a.write_bytes(b"rendered reel a")
            video_b.write_bytes(b"rendered reel b")
            lineage_a = {
                "source": {
                    "sourceReferenceId": "ref_same",
                    "sourceFamilyId": "family_same",
                    "soulName": "Stacey",
                },
                "generation": {"klingJobId": "kling_1"},
            }
            lineage_b = {
                "source": {
                    "sourceReferenceId": "ref_same",
                    "sourceFamilyId": "family_same",
                    "soulName": "Stacey",
                },
                "generation": {"klingJobId": "kling_2"},
            }
            video_a.with_suffix(
                video_a.suffix + ".generated_asset_lineage.json"
            ).write_text(json.dumps(lineage_a), encoding="utf-8")
            video_b.with_suffix(
                video_b.suffix + ".generated_asset_lineage.json"
            ).write_text(json.dumps(lineage_b), encoding="utf-8")
            approved = {
                "schema": "reel_factory.approved_export.v1",
                "items": [
                    {
                        "output_path": str(video_a),
                        "hook_text": "caption a",
                        "generated_asset_lineage": lineage_a,
                    },
                    {
                        "output_path": str(video_b),
                        "hook_text": "caption b",
                        "generated_asset_lineage": lineage_b,
                    },
                ],
            }
            approved_path = root / "approved.json"
            approved_path.write_text(json.dumps(approved), encoding="utf-8")

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 1)
            reasons = [
                reason
                for conflict in assigned["conflicts"]
                for reason in conflict["reasons"]
            ]
            self.assertIn("cross_account_source_or_perceptual_reuse", reasons)

    def test_state_transitions_lineage_audio_gate_and_schedule_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            plan = create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=["stacey_a"],
                start_date="2026-06-03",
                days=1,
            )
            slot_id = plan["slots"][0]["posting_slot_id"]

            with self.assertRaisesRegex(ValueError, "lineage"):
                transition_slot(root, slot_id, "ready_for_review")

            video = root / "out.mp4"
            video.write_bytes(b"ready reel")
            lineage_path = video.with_suffix(
                video.suffix + ".generated_asset_lineage.json"
            )
            lineage_path.write_text(
                json.dumps(
                    {"source": {"sourceReferenceId": "ref_a", "soulName": "Stacey"}}
                ),
                encoding="utf-8",
            )
            approved = {
                "items": [
                    {
                        "output_path": str(video),
                        "hook_text": "caption",
                        "campaign": {
                            "campaign_id": "camp_stacey",
                            "asset_generation_id": "asset_a",
                        },
                        "generated_asset_lineage": {
                            "source": {
                                "sourceReferenceId": "ref_a",
                                "soulName": "Stacey",
                            }
                        },
                    }
                ]
            }
            approved_path = root / "approved.json"
            approved_path.write_text(json.dumps(approved), encoding="utf-8")
            assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )
            transition_slot(root, slot_id, "approved", actor="tester")

            blocked = export_schedule_package(
                root,
                campaign_id="camp_stacey",
                date_from="2026-06-03",
                date_to="2026-06-03",
                dry_run=True,
            )
            self.assertEqual(blocked["count"], 0)

            write_audio_intent(video, mode="native_trending_audio", platform="ig")
            still_blocked = export_schedule_package(
                root,
                campaign_id="camp_stacey",
                date_from="2026-06-03",
                date_to="2026-06-03",
                dry_run=True,
            )
            self.assertEqual(still_blocked["count"], 0)

            audio_path = video.with_suffix(video.suffix + ".audio_intent.json")
            audio_payload = json.loads(audio_path.read_text(encoding="utf-8"))
            audio_payload["status"] = "selected"
            audio_payload["audio_selection"] = {
                "track_id": "native_track_1",
                "title": "manual trend",
            }
            audio_path.write_text(json.dumps(audio_payload), encoding="utf-8")
            ready = export_schedule_package(
                root,
                campaign_id="camp_stacey",
                date_from="2026-06-03",
                date_to="2026-06-03",
                dry_run=True,
            )
            self.assertEqual(ready["count"], 1)
            self.assertIn("content_fingerprint", ready["items"][0])

            queue = review_queue(root, campaign_id="camp_stacey")
            self.assertEqual(queue["count"], 1)
            conflicts = ledger_conflicts(root, campaign_id="camp_stacey")
            self.assertEqual(conflicts["count"], 0)

            transition_slot(root, slot_id, "scheduled", actor="tester")
            transition_slot(
                root, slot_id, "posted", actor="tester", posted_at="2026-06-03T10:00:00"
            )
            transition_slot(
                root,
                slot_id,
                "metrics_imported",
                actor="tester",
                metrics={
                    "views": 1000,
                    "likes": 100,
                    "comments": 10,
                    "shares": 5,
                    "saves": 6,
                    "retention": 0.42,
                },
            )
            events = (
                Manifest(root / "manifest.json")
                .conn.execute(
                    "SELECT COUNT(*) AS c FROM posting_slot_events WHERE posting_slot_id=?",
                    (slot_id,),
                )
                .fetchone()["c"]
            )
            self.assertGreaterEqual(events, 4)

    def test_assignment_accepts_two_soul_stacey_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=[
                    {
                        "handle": "stacey_a",
                        "accepted_soul_ids": [STACEY_SOUL_ID, STACEY1_SOUL_ID],
                    }
                ],
                start_date="2026-06-03",
                days=1,
            )
            video_a = root / "stacey.mp4"
            video_b = root / "stacey1.mp4"
            video_a.write_bytes(b"stacey soul")
            video_b.write_bytes(b"stacey1 soul")
            lineage_a = {"source": {"soulId": STACEY_SOUL_ID, "soulName": "Stacey"}}
            lineage_b = {"source": {"soulId": STACEY1_SOUL_ID, "soulName": "Stacey1"}}
            approved_path = root / "approved.json"
            approved_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "output_path": str(video_a),
                                "generated_asset_lineage": lineage_a,
                            },
                            {
                                "output_path": str(video_b),
                                "generated_asset_lineage": lineage_b,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 2)
            self.assertEqual(assigned["conflicts"], [])

    def test_identity_mismatch_does_not_consume_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            plan = create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=[
                    {
                        "handle": "stacey_a",
                        "accepted_soul_ids": [STACEY_SOUL_ID, STACEY1_SOUL_ID],
                    }
                ],
                start_date="2026-06-03",
                days=1,
            )
            wrong = root / "wrong.mp4"
            correct = root / "correct.mp4"
            wrong.write_bytes(b"larissa in stacey slot")
            correct.write_bytes(b"stacey in stacey slot")
            approved_path = root / "approved.json"
            approved_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "output_path": str(wrong),
                                "generated_asset_lineage": {
                                    "source": {
                                        "soulId": LARISSA_SOUL_ID,
                                        "soulName": "Larissa",
                                    }
                                },
                            },
                            {
                                "output_path": str(correct),
                                "generated_asset_lineage": {
                                    "source": {
                                        "soulId": STACEY_SOUL_ID,
                                        "soulName": "Stacey",
                                    }
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 1)
            self.assertEqual(
                assigned["assignments"][0]["posting_slot_id"],
                plan["slots"][0]["posting_slot_id"],
            )
            self.assertEqual(
                assigned["conflicts"][0]["reasons"],
                ["creator_identity_mismatch_for_slot"],
            )

    def test_name_only_identity_matches_case_insensitively_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=["stacey_a"],
                start_date="2026-06-03",
                days=1,
            )
            match = root / "match.mp4"
            mismatch = root / "mismatch.mp4"
            match.write_bytes(b"name match")
            mismatch.write_bytes(b"name mismatch")
            approved_path = root / "approved.json"
            approved_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "output_path": str(match),
                                "creator": "sTaCeY",
                                "generated_asset_lineage": {
                                    "source": {"sourceReferenceId": "ref_match"}
                                },
                            },
                            {
                                "output_path": str(mismatch),
                                "creator": "Larissa",
                                "generated_asset_lineage": {
                                    "source": {"sourceReferenceId": "ref_mismatch"}
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 1)
            reasons = [
                reason
                for conflict in assigned["conflicts"]
                for reason in conflict["reasons"]
            ]
            self.assertIn("creator_identity_mismatch_for_slot", reasons)

    def test_assignment_rejects_item_without_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id="camp_stacey",
                accounts=["stacey_a"],
                start_date="2026-06-03",
                days=1,
            )
            video = root / "no_identity.mp4"
            video.write_bytes(b"no identity")
            approved_path = root / "approved.json"
            approved_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "output_path": str(video),
                                "generated_asset_lineage": {
                                    "source": {"sourceReferenceId": "ref_no_identity"}
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            assigned = assign_approved_reels(
                root, campaign_id="camp_stacey", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 0)
            self.assertEqual(
                assigned["conflicts"][0]["reasons"],
                ["creator_identity_unverifiable_for_slot"],
            )

    def test_campaign_store_reseed_corrects_stacey_soul_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect_campaign_store(root)
            conn.execute(
                "UPDATE creators SET soul_id=? WHERE name='Stacey'",
                (STACEY1_SOUL_ID,),
            )
            conn.commit()
            conn.close()

            conn = connect_campaign_store(root)
            row = conn.execute(
                "SELECT soul_id FROM creators WHERE name='Stacey'"
            ).fetchone()

            self.assertEqual(row["soul_id"], STACEY_SOUL_ID)

    def test_empty_slots_do_not_crash_identity_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            video = root / "orphan.mp4"
            video.write_bytes(b"orphan")
            approved_path = root / "approved.json"
            approved_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "output_path": str(video),
                                "generated_asset_lineage": {
                                    "source": {
                                        "soulId": STACEY_SOUL_ID,
                                        "soulName": "Stacey",
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            assigned = assign_approved_reels(
                root, campaign_id="camp_empty", approved_export=approved_path
            )

            self.assertEqual(assigned["assigned"], 0)
            self.assertEqual(
                assigned["conflicts"][0]["reasons"], ["no_available_planned_slot"]
            )


if __name__ == "__main__":
    unittest.main()
