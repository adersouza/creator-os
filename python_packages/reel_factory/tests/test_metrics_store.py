import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from campaign_store import ensure_campaign_schema
from manifest import Manifest
from metrics_store import (
    _variation_for_filename,
    connect_metrics_db,
    ensure_metrics_schema,
    import_metrics_csv,
    import_outcomes_csv,
    metrics_leaderboard,
    metrics_summary,
    refresh_outcomes_from_performance_sync,
    retract_bridge_outcome,
    soul_metrics_report,
    upsert_bridge_outcome,
)
from reel_pipeline import Recipe
from winner_dna import upsert_reel_feature

STACEY_SOUL = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
STACEY1_SOUL = "5828d958-91dd-4d6d-8909-934503f47644"


class MetricsStoreSoulAttributionTests(unittest.TestCase):
    def test_bridge_monotonic_guard_and_publish_metrics_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "shared.mp4"
            output.write_bytes(b"video")
            conn = connect_metrics_db(root / "manifest.sqlite")
            ensure_metrics_schema(conn)
            base = {
                "id": "snap_new",
                "campaign_id": "campaign_1",
                "rendered_output_path": str(output),
                "rendered_filename": output.name,
                "post_id": "post_1",
                "platform": "instagram",
                "instagram_account_id": "ig_1",
                "published_at": "2026-01-02T00:00:00+00:00",
                "snapshot_at": "2026-01-03T00:00:00+00:00",
                "views": 500,
                "likes": 50,
                "comments": 5,
                "shares": 4,
                "saves": 3,
            }
            newest = upsert_bridge_outcome(root, conn, base)
            older = upsert_bridge_outcome(
                root,
                conn,
                {
                    **base,
                    "id": "snap_old",
                    "snapshot_at": "2026-01-02T12:00:00+00:00",
                    "views": 10,
                },
            )

            self.assertEqual(newest["status"], "written")
            self.assertEqual(older["status"], "superseded")
            self.assertEqual(
                conn.execute("SELECT views FROM reel_outcomes").fetchone()[0], 500
            )
            self.assertEqual(
                conn.execute("SELECT views FROM publish_metrics").fetchone()[0], 500
            )

            second = upsert_bridge_outcome(
                root,
                conn,
                {
                    **base,
                    "id": "snap_second",
                    "post_id": "post_2",
                    "instagram_account_id": "ig_2",
                    "published_at": "2026-01-04T00:00:00+00:00",
                    "snapshot_at": "2026-01-05T00:00:00+00:00",
                    "views": 900,
                },
            )
            metric = conn.execute("SELECT * FROM publish_metrics").fetchone()
            self.assertEqual(metric["source_outcome_id"], second["outcomeId"])
            self.assertEqual(metric["views"], 900)

            retract_bridge_outcome(
                conn,
                outcome_id=second["outcomeId"],
                filename=second["filename"],
            )
            restored = conn.execute("SELECT * FROM publish_metrics").fetchone()
            self.assertEqual(restored["source_outcome_id"], newest["outcomeId"])
            self.assertEqual(restored["views"], 500)
            conn.close()

    def test_metrics_connection_uses_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "manifest.sqlite"
            conn = connect_metrics_db(db_path)

            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

            self.assertEqual(journal_mode, "wal")
            self.assertEqual(busy_timeout, 30000)

    def test_campaign_output_metrics_filename_lookup_uses_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_metrics_db(Path(tmp) / "manifest.sqlite")
            ensure_campaign_schema(conn)
            ensure_metrics_schema(conn)

            plan = "\n".join(
                row[3]
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM campaign_outputs WHERE metrics_filename=?",
                    ("posted.mp4",),
                ).fetchall()
            )

            self.assertIn("idx_campaign_outputs_metrics_filename", plan)

    def test_legacy_variations_filename_column_migrates_and_uses_exact_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_metrics_db(Path(tmp) / "manifest.sqlite")
            conn.execute(
                """
                CREATE TABLE variations (
                    job_key TEXT PRIMARY KEY,
                    output_path TEXT NOT NULL,
                    caption_text TEXT NOT NULL,
                    recipe TEXT NOT NULL,
                    review_state TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO variations VALUES (?, ?, ?, ?, ?)",
                (
                    "job_1",
                    "/tmp/rendered/clip_exact.mp4",
                    "hook",
                    "v01_original",
                    "approved",
                ),
            )

            ensure_metrics_schema(conn)

            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(variations)").fetchall()
            }
            plan = "\n".join(
                row[3]
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM variations WHERE filename=?",
                    ("clip_exact.mp4",),
                ).fetchall()
            )
            row = _variation_for_filename(conn, "clip_exact.mp4")

            self.assertIn("filename", columns)
            self.assertIn("idx_variations_filename", plan)
            self.assertEqual(row["job_key"], "job_1")

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

    def test_import_metrics_writes_stable_campaign_output_key_for_renamed_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)
            manifest = Manifest(root / "manifest.json")
            now = 1
            manifest.conn.execute(
                """
                INSERT INTO campaign_outputs (
                    campaign_output_id, output_path, job_key, caption_text, recipe,
                    review_state, metrics_filename, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "co_renamed_metric",
                    str(out),
                    "job_renamed_metric",
                    "hook",
                    "v01_original",
                    "approved",
                    "posted_metric_name.mp4",
                    now,
                    now,
                ),
            )
            manifest.conn.commit()

            import_metrics_csv(root, self._metrics_csv(root, "posted_metric_name.mp4"))
            row = (
                sqlite3.connect(root / "manifest.sqlite")
                .execute(
                    """
                    SELECT campaign_output_id, job_key
                    FROM publish_metrics
                    WHERE filename=?
                    """,
                    ("posted_metric_name.mp4",),
                )
                .fetchone()
            )

            self.assertEqual(row[0], "co_renamed_metric")
            self.assertEqual(row[1], "job_renamed_metric")

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

    def test_outcomes_import_reimports_dateless_accountless_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)
            csv_path = root / "outcomes.csv"
            csv_path.write_text(
                "filename,platform,views,likes,comments,shares,saves\n"
                f"{out.name},instagram_reels,100,10,2,3,5\n",
                encoding="utf-8",
            )

            import_outcomes_csv(root, csv_path)
            csv_path.write_text(
                "filename,platform,views,likes,comments,shares,saves\n"
                f"{out.name},instagram_reels,250,20,4,5,6\n",
                encoding="utf-8",
            )
            import_outcomes_csv(root, csv_path)

            conn = sqlite3.connect(root / "manifest.sqlite")
            row = conn.execute(
                """
                SELECT COUNT(*), MAX(views), account, posted_at
                FROM reel_outcomes
                WHERE filename=?
                """,
                (out.name,),
            ).fetchone()

            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], 250)
            self.assertEqual(row[2], "")
            self.assertEqual(row[3], "")

    def test_gui_metrics_read_from_reel_outcomes_not_legacy_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._variation(root)
            csv_path = root / "outcomes.csv"
            csv_path.write_text(
                "filename,platform,account,posted_at,views,likes,comments,shares,saves\n"
                f"{out.name},instagram_reels,acct,2026-07-01,123,10,2,3,5\n",
                encoding="utf-8",
            )
            import_outcomes_csv(root, csv_path)
            conn = sqlite3.connect(root / "manifest.sqlite")
            conn.execute("DELETE FROM publish_metrics WHERE filename=?", (out.name,))
            conn.commit()

            summary = metrics_summary(root)
            leaderboard = metrics_leaderboard(root)

            self.assertEqual(summary[0]["avg_views"], 123.0)
            self.assertEqual(leaderboard["recipes"][0]["avg_views"], 123.0)

    def test_metrics_schema_coalesces_legacy_null_outcome_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = sqlite3.connect(root / "manifest.sqlite")
            conn.row_factory = sqlite3.Row
            ensure_metrics_schema(conn)
            conn.execute(
                """
                INSERT INTO reel_outcomes (
                    outcome_id, filename, platform, account, posted_at, imported_at
                ) VALUES (?, ?, ?, NULL, NULL, ?)
                """,
                ("outcome_legacy", "legacy.mp4", "instagram_reels", 1),
            )
            conn.commit()

            ensure_metrics_schema(conn)
            row = conn.execute(
                "SELECT account, posted_at FROM reel_outcomes WHERE outcome_id=?",
                ("outcome_legacy",),
            ).fetchone()

            self.assertEqual(row["account"], "")
            self.assertEqual(row["posted_at"], "")

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

    def test_refresh_outcomes_bridges_synced_performance_and_winner_dna(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "reel_factory"
            root.mkdir()
            out = self._variation(root, source_stem="e2e_lacebody")
            self._caption_lineage(out, "e2e_lacebody")
            self._source_lineage(root, "e2e_lacebody", STACEY_SOUL)
            upsert_reel_feature(
                root,
                out,
                features={
                    "scene": "bedroom",
                    "camera": "tripod",
                    "pose": "standing",
                    "motion": "hair_flip",
                    "outfit": "black_dress",
                    "creator": "stacey",
                    "grid_source": 0,
                    "caption_style": "short_direct",
                    "hook_type": "curiosity",
                    "body_style": "hourglass",
                },
            )
            campaign_db = Path(tmp) / "campaign_factory.sqlite"
            source = sqlite3.connect(campaign_db)
            source.executescript("""
                CREATE TABLE performance_snapshots (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT,
                    rendered_asset_id TEXT,
                    post_id TEXT,
                    platform TEXT,
                    account_id TEXT,
                    instagram_account_id TEXT,
                    permalink TEXT,
                    published_at TEXT,
                    snapshot_at TEXT,
                    views INTEGER,
                    likes INTEGER,
                    comments INTEGER,
                    shares INTEGER,
                    saves INTEGER,
                    watch_time_seconds REAL,
                    metrics_eligible INTEGER,
                    created_at TEXT
                );
                CREATE TABLE rendered_assets (
                    id TEXT PRIMARY KEY,
                    output_path TEXT,
                    filename TEXT,
                    caption TEXT,
                    recipe TEXT,
                    review_state TEXT
                );
            """)
            source.execute(
                "INSERT INTO rendered_assets VALUES (?, ?, ?, ?, ?, ?)",
                ("asset_1", str(out), out.name, "hook", "v01_original", "approved"),
            )
            source.execute(
                """
                INSERT INTO performance_snapshots (
                    id, campaign_id, rendered_asset_id, post_id, platform, account_id,
                    instagram_account_id, permalink, published_at, snapshot_at, views,
                    likes, comments, shares, saves, watch_time_seconds,
                    metrics_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "perf_old",
                    "may",
                    "asset_1",
                    "post_1",
                    "instagram",
                    "acct",
                    "@stacey",
                    "https://example.test/p/1",
                    "2026-07-01",
                    "2026-07-01T00:00:00Z",
                    10,
                    1,
                    0,
                    0,
                    0,
                    1.0,
                    1,
                    "2026-07-01T00:00:00Z",
                ),
            )
            source.execute(
                """
                INSERT INTO performance_snapshots (
                    id, campaign_id, rendered_asset_id, post_id, platform, account_id,
                    instagram_account_id, permalink, published_at, snapshot_at, views,
                    likes, comments, shares, saves, watch_time_seconds,
                    metrics_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "perf_new",
                    "may",
                    "asset_1",
                    "post_1",
                    "instagram",
                    "acct",
                    "@stacey",
                    "https://example.test/p/1",
                    "2026-07-01",
                    "2026-07-02T00:00:00Z",
                    100,
                    12,
                    3,
                    4,
                    5,
                    2.5,
                    1,
                    "2026-07-02T00:00:00Z",
                ),
            )
            source.commit()
            source.close()

            result = refresh_outcomes_from_performance_sync(
                root, campaign_factory_db=campaign_db, campaign="may"
            )
            conn = sqlite3.connect(root / "manifest.sqlite")
            conn.row_factory = sqlite3.Row
            outcome = conn.execute(
                "SELECT * FROM reel_outcomes WHERE filename=?", (out.name,)
            ).fetchone()
            legacy = conn.execute(
                "SELECT * FROM publish_metrics WHERE filename=?", (out.name,)
            ).fetchone()
            dna = conn.execute(
                "SELECT * FROM winner_dna WHERE feature_key='scene'"
            ).fetchone()

            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["skipped"], [])
            self.assertEqual(result["captionWeights"]["updated"], 1)
            self.assertEqual(outcome["views"], 100)
            self.assertEqual(outcome["soul_id"], STACEY_SOUL)
            self.assertEqual(legacy["likes"], 12)
            self.assertEqual(legacy["soul_id"], STACEY_SOUL)
            self.assertEqual(dna["feature_value"], "bedroom")


if __name__ == "__main__":
    unittest.main()
