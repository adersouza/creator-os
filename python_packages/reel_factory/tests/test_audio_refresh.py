import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reel_factory.audio_provider import (
    local_winners_path,
    trending_cml_path,
    watch_list_path,
)
from reel_factory.audio_refresh import (
    refresh_cml_from_export,
    refresh_from_review,
    refresh_latest_cml_export,
)


class AudioRefreshTests(unittest.TestCase):
    def test_refresh_from_review_writes_current_pool_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.json"
            candidates = []
            for idx in range(1, 27):
                candidates.append(
                    {
                        "review_index": idx,
                        "track_id": f"track_{idx}",
                        "track_name": f"Track {idx}",
                        "source": "tiktok_cml"
                        if idx < 24
                        else "local_archive_audio_id",
                        "tags": ["pop"] if idx < 24 else ["local_winner"],
                    }
                )
            review.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")

            result = refresh_from_review(root, review)

            self.assertEqual(result["cml"], 6)
            self.assertEqual(result["local_winners"], 3)
            self.assertEqual(result["watch_list"], 9)
            self.assertEqual(
                len(json.loads(trending_cml_path(root).read_text())["tracks"]), 6
            )
            self.assertEqual(
                len(json.loads(local_winners_path(root).read_text())["tracks"]), 3
            )
            self.assertEqual(
                len(json.loads(watch_list_path(root).read_text())["tracks"]), 9
            )

    def test_refresh_cml_from_export_filters_to_allowed_style_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "official_cml.json"
            export.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "a",
                                "track_name": "Runway",
                                "trend_rank": 2,
                                "tags": ["fashion"],
                            },
                            {
                                "track_id": "b",
                                "track_name": "Dirge",
                                "trend_rank": 1,
                                "tags": ["sorrow"],
                            },
                            {
                                "track_id": "c",
                                "track_name": "Chill Fit",
                                "trend_rank": 3,
                                "tags": ["chill"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = refresh_cml_from_export(root, export)

            tracks = json.loads(trending_cml_path(root).read_text())["tracks"]
            self.assertEqual(result["cml"], 2)
            self.assertEqual([track["track_id"] for track in tracks], ["a", "c"])

    def test_refresh_latest_cml_export_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            export = inbox / "weekly.json"
            export.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "a",
                                "track_name": "Runway",
                                "trend_rank": 1,
                                "tags": ["fashion"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            first = refresh_latest_cml_export(root, drop_dir=inbox)
            second = refresh_latest_cml_export(root, drop_dir=inbox)

            self.assertEqual(first["status"], "imported")
            self.assertEqual(second["status"], "already_imported")
            self.assertEqual(
                len(json.loads(trending_cml_path(root).read_text())["tracks"]), 1
            )


if __name__ == "__main__":
    unittest.main()
