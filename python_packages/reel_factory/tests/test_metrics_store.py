import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from manifest import Manifest
from metrics_store import (
    ensure_metrics_schema,
    import_metrics_csv,
    import_outcomes_csv,
    soul_metrics_report,
)
from reel_pipeline import Recipe

STACEY_SOUL = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
STACEY1_SOUL = "5828d958-91dd-4d6d-8909-934503f47644"


class MetricsStoreSoulAttributionTests(unittest.TestCase):
    def _variation(
        self,
        root: Path,
        *,
        source_stem: str = "e2e_lacebody",
        filename: str | None = None,
    ) -> Path:
        filename = filename or f"{source_stem}_h171_v01_original_light_deadbeef.mp4"
        manifest = Manifest(root / "manifest.json")
        src = root / "00_source_videos" / f"{source_stem}.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"src")
        out = root / "02_processed" / source_stem / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"video")
        manifest.upsert_video(source_stem, src, "hash", 2.0)
        manifest.add_variation(
            source_stem,
            Recipe("v01_original"),
            "hook",
            out,
            f"job_{filename}",
            2.0,
        )
        manifest.conn.commit()
        return out

    def _caption_lineage(self, out: Path, source_stem: str) -> None:
        out.with_suffix(out.suffix + ".caption_lineage.json").write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_lineage.v1",
                    "captionOutcomeContext": {"source_clip": source_stem},
                }
            ),
            encoding="utf-8",
        )

    def _source_lineage(
        self,
        root: Path,
        source_stem: str,
        soul_id: str,
        *,
        suffix: str = "generated_asset_lineage",
    ) -> None:
        path = root / "00_source_videos" / f"{source_stem}.{suffix}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"source": {"soulId": soul_id}}),
            encoding="utf-8",
        )

    def _metrics_csv(self, root: Path, filename: str, *, views: int = 100) -> Path:
        path = root / "metrics.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "filename",
                    "platform",
                    "account",
                    "uploaded_at",
                    "views",
                    "likes",
                    "comments",
                    "shares",
                    "saves",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "filename": filename,
                    "platform": "ig",
                    "account": "stacey",
                    "uploaded_at": "2026-07-01",
                    "views": views,
                    "likes": 10,
                    "comments": 2,
                    "shares": 3,
                    "saves": 5,
                }
            )
        return path

    def test_import_resolves_soul_id_from_caption_lineage_to_generated_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)
            self._caption_lineage(out, "e2e_lacebody")
            self._source_lineage(root, "e2e_lacebody", STACEY_SOUL)

            import_metrics_csv(root, self._metrics_csv(root, out.name))
            row = (
                sqlite3.connect(root / "manifest.sqlite")
                .execute(
                    "SELECT soul_id FROM publish_metrics WHERE filename=?", (out.name,)
                )
                .fetchone()
            )

            self.assertEqual(row[0], STACEY_SOUL)

    def test_import_resolves_direct_reference_source_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root, source_stem="e2e_ref")
            self._caption_lineage(out, "e2e_ref")
            self._source_lineage(
                root, "e2e_ref", STACEY1_SOUL, suffix="direct_reference_lineage"
            )

            import_metrics_csv(root, self._metrics_csv(root, out.name))
            row = (
                sqlite3.connect(root / "manifest.sqlite")
                .execute(
                    "SELECT soul_id FROM publish_metrics WHERE filename=?", (out.name,)
                )
                .fetchone()
            )

            self.assertEqual(row[0], STACEY1_SOUL)

    def test_missing_caption_lineage_uses_rendered_stem_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root, source_stem="e2e_lacebody")
            self._source_lineage(root, "e2e_lacebody", STACEY_SOUL)

            import_metrics_csv(root, self._metrics_csv(root, out.name))
            row = (
                sqlite3.connect(root / "manifest.sqlite")
                .execute(
                    "SELECT soul_id FROM publish_metrics WHERE filename=?", (out.name,)
                )
                .fetchone()
            )

            self.assertEqual(row[0], STACEY_SOUL)

    def test_unresolvable_soul_id_imports_as_unattributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)

            import_metrics_csv(root, self._metrics_csv(root, out.name))
            conn = sqlite3.connect(root / "manifest.sqlite")
            row = conn.execute(
                "SELECT soul_id FROM publish_metrics WHERE filename=?", (out.name,)
            ).fetchone()
            report = soul_metrics_report(root)

            self.assertIsNone(row[0])
            self.assertEqual(report["unattributed_count"], 1)
            self.assertEqual(report["rows"][0]["soul_id"], "unattributed")

    def test_outcomes_import_writes_soul_id_to_both_metrics_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)
            self._caption_lineage(out, "e2e_lacebody")
            self._source_lineage(root, "e2e_lacebody", STACEY_SOUL)
            csv_path = root / "outcomes.csv"
            csv_path.write_text(
                "filename,platform,account,posted_at,views,likes,comments,shares,saves\n"
                f"{out.name},instagram_reels,stacey,2026-07-01,100,10,2,3,5\n",
                encoding="utf-8",
            )

            import_outcomes_csv(root, csv_path)
            conn = sqlite3.connect(root / "manifest.sqlite")
            outcome = conn.execute(
                "SELECT soul_id FROM reel_outcomes WHERE filename=?", (out.name,)
            ).fetchone()
            legacy = conn.execute(
                "SELECT soul_id FROM publish_metrics WHERE filename=?", (out.name,)
            ).fetchone()

            self.assertEqual(outcome[0], STACEY_SOUL)
            self.assertEqual(legacy[0], STACEY_SOUL)

    def test_soul_metrics_report_aggregates_souls_and_unattributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = sqlite3.connect(root / "manifest.sqlite")
            conn.row_factory = sqlite3.Row
            ensure_metrics_schema(conn)
            conn.executemany(
                """
                INSERT INTO publish_metrics (
                    filename, account, views, likes, comments, shares, saves,
                    soul_id, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                [
                    ("a.mp4", "stacey", 100, 10, 2, 3, 5, STACEY_SOUL),
                    ("b.mp4", "stacey", 300, 30, 4, 5, 1, STACEY_SOUL),
                    ("c.mp4", "stacey", 50, 5, 1, 1, 1, STACEY1_SOUL),
                    ("d.mp4", "stacey", 10, 1, 0, 0, 0, None),
                ],
            )
            conn.commit()

            report = soul_metrics_report(root)
            rows = {row["soul_id"]: row for row in report["rows"]}

            self.assertEqual(rows[STACEY_SOUL]["post_count"], 2)
            self.assertEqual(rows[STACEY_SOUL]["mean_views"], 200.0)
            self.assertEqual(rows[STACEY_SOUL]["total_engagements"], 60)
            self.assertEqual(rows[STACEY_SOUL]["engagement_rate"], 0.15)
            self.assertEqual(rows[STACEY1_SOUL]["post_count"], 1)
            self.assertEqual(rows["unattributed"]["post_count"], 1)
            self.assertEqual(report["unattributed_count"], 1)


if __name__ == "__main__":
    unittest.main()
