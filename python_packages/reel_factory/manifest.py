"""SQLite manifest store with JSON export for reel_factory."""
from __future__ import annotations

import hashlib
import json
import logging
import shlex
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from metrics_store import ensure_metrics_schema
from campaign_store import ensure_campaign_schema
from intelligence_store import ensure_intelligence_schema

log = logging.getLogger("reel")


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Manifest:
    SCHEMA_VERSION = 8

    def __init__(self, json_path: Path):
        self.json_path = json_path
        self.db_path = json_path.with_suffix(".sqlite")
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._init_db()
        if self._is_empty() and json_path.exists():
            self._import_json(json_path)

    def _init_db(self) -> None:
        self.conn.executescript("""
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_video_hash TEXT NOT NULL,
            source_duration_sec REAL NOT NULL,
            ingested_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS variations (
            job_key TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            recipe TEXT NOT NULL,
            recipe_params_json TEXT NOT NULL,
            caption_text TEXT NOT NULL,
            caption_hash TEXT NOT NULL,
            output_path TEXT NOT NULL,
            output_hash TEXT NOT NULL,
            output_size_bytes INTEGER NOT NULL,
            duration_sec REAL NOT NULL,
            audio TEXT NOT NULL,
            encoded_at INTEGER NOT NULL,
            encoder TEXT NOT NULL,
            status TEXT NOT NULL,
            review_state TEXT NOT NULL DEFAULT 'draft',
            render_time_sec REAL,
            error_message TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        );
        CREATE TABLE IF NOT EXISTS render_attempts (
            attempt_id TEXT PRIMARY KEY,
            job_key TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            temp_path TEXT NOT NULL,
            final_path TEXT NOT NULL,
            ffmpeg_cmd TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_variations_video_id ON variations(video_id);
        CREATE INDEX IF NOT EXISTS idx_variations_recipe ON variations(recipe);
        CREATE INDEX IF NOT EXISTS idx_variations_caption_hash ON variations(caption_hash);
        CREATE INDEX IF NOT EXISTS idx_variations_active_failures
            ON variations(encoded_at, recipe)
            WHERE status = 'failed';
        CREATE INDEX IF NOT EXISTS idx_render_attempts_job_key
            ON render_attempts(job_key, attempt_no);
        CREATE TABLE IF NOT EXISTS analysis_cache (
            cache_key TEXT PRIMARY KEY,
            source_hash TEXT NOT NULL,
            analyzer TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_cache_source
            ON analysis_cache(source_hash, analyzer);
        """)
        ensure_metrics_schema(self.conn)
        ensure_campaign_schema(self.conn)
        ensure_intelligence_schema(self.conn)
        cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(variations)").fetchall()
        }
        if "error_message" not in cols:
            self.conn.execute("ALTER TABLE variations ADD COLUMN error_message TEXT")
        if "review_state" not in cols:
            self.conn.execute("ALTER TABLE variations ADD COLUMN review_state TEXT NOT NULL DEFAULT 'draft'")
        self.conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (self.SCHEMA_VERSION, int(time.time())),
        )
        self.conn.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
        self.conn.commit()

    def _is_empty(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()
        return int(row["n"]) == 0

    def _import_json(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"could not import existing manifest.json: {e}")
            return
        for video_id, vid in data.get("videos", {}).items():
            self.upsert_video(
                video_id,
                Path(vid.get("source_path", "")),
                vid.get("source_video_hash", ""),
                float(vid.get("source_duration_sec", 0.0)),
                ingested_at=int(vid.get("ingested_at", int(time.time()))),
            )
            for var in vid.get("variations", []):
                self._insert_variation_row(
                    video_id=video_id,
                    job_key=var.get("job_key", ""),
                    recipe=var.get("recipe", ""),
                    recipe_params=var.get("recipe_params", {}),
                    caption_text=var.get("caption_text", ""),
                    caption_hash=var.get("caption_hash", ""),
                    output_path=var.get("output_path", ""),
                    output_hash=var.get("output_hash", ""),
                    output_size_bytes=int(var.get("output_size_bytes", 0)),
                    duration_sec=float(var.get("duration_sec", 0.0)),
                    audio=var.get("audio", "stripped"),
                    encoded_at=int(var.get("encoded_at", int(time.time()))),
                    encoder=var.get("encoder", "h264_videotoolbox"),
                    status=var.get("status", "ok"),
                    review_state=var.get("review_state", "draft"),
                    render_time_sec=var.get("render_time_sec"),
                    error_message=var.get("error_message"),
                )
        self.conn.commit()
        log.info(f"imported existing manifest.json into {self.db_path.name}")

    def has_job(self, key: str) -> bool:
        row = self.conn.execute(
            "SELECT output_path FROM variations WHERE job_key = ? AND status = 'ok'",
            (key,),
        ).fetchone()
        if row and Path(row["output_path"]).exists():
            return True
        return False

    def materialize_cached_job(self, video_id: str, key: str) -> bool:
        """Attach an existing content-addressed render to another clip entry.

        Job keys intentionally ignore clip IDs so duplicate source/caption/recipe
        combinations can reuse an existing render. Downstream tools still need a
        variation row under the current ``video_id``; this creates a deterministic
        alias row that points at the cached output without re-encoding.
        """
        alias_key = f"{key}:video:{sha256_str(video_id)[:12]}"
        existing = self.conn.execute(
            """
            SELECT output_path FROM variations
            WHERE video_id = ?
              AND status = 'ok'
              AND (job_key = ? OR job_key = ?)
            """,
            (video_id, key, alias_key),
        ).fetchone()
        if existing and Path(existing["output_path"]).exists():
            return True

        cached = self.conn.execute(
            "SELECT * FROM variations WHERE job_key = ? AND status = 'ok'",
            (key,),
        ).fetchone()
        if not cached or not Path(cached["output_path"]).exists():
            return False
        if cached["video_id"] == video_id:
            return True

        try:
            recipe_params = json.loads(cached["recipe_params_json"])
        except Exception:
            recipe_params = {}
        lineage = recipe_params.setdefault("_lineage", {})
        if isinstance(lineage, dict):
            lineage.setdefault("cachedFromJobKey", key)
            lineage.setdefault("cachedFromVideoId", cached["video_id"])
            lineage["renderJobKey"] = alias_key

        self._insert_variation_row(
            video_id=video_id,
            job_key=alias_key,
            recipe=cached["recipe"],
            recipe_params=recipe_params,
            caption_text=cached["caption_text"],
            caption_hash=cached["caption_hash"],
            output_path=cached["output_path"],
            output_hash=cached["output_hash"],
            output_size_bytes=int(cached["output_size_bytes"]),
            duration_sec=float(cached["duration_sec"]),
            audio=cached["audio"],
            encoded_at=int(time.time()),
            encoder=cached["encoder"],
            status=cached["status"],
            review_state="draft",
            render_time_sec=0.0,
        )
        return True

    def upsert_video(self, video_id: str, source_path: Path, src_hash: str,
                     duration: float, ingested_at: int | None = None):
        existing = self.conn.execute(
            "SELECT ingested_at FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO videos (
                video_id, source_path, source_video_hash, source_duration_sec, ingested_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                source_path = excluded.source_path,
                source_video_hash = excluded.source_video_hash,
                source_duration_sec = excluded.source_duration_sec
            """,
            (
                video_id,
                str(source_path),
                src_hash,
                round(duration, 3),
                ingested_at or (int(existing["ingested_at"]) if existing else int(time.time())),
            ),
        )

    def _insert_variation_row(self, *, video_id: str, job_key: str, recipe: str,
                              recipe_params: dict, caption_text: str,
                              caption_hash: str, output_path: str,
                              output_hash: str, output_size_bytes: int,
                              duration_sec: float, audio: str, encoded_at: int,
                              encoder: str, status: str,
                              review_state: str = "draft",
                              render_time_sec: float | None = None,
                              error_message: str | None = None) -> None:
        if not job_key:
            return
        self.conn.execute(
            """
            INSERT OR REPLACE INTO variations (
                job_key, video_id, recipe, recipe_params_json, caption_text,
                caption_hash, output_path, output_hash, output_size_bytes,
                duration_sec, audio, encoded_at, encoder, status, review_state,
                render_time_sec, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_key,
                video_id,
                recipe,
                json.dumps(recipe_params, sort_keys=True, ensure_ascii=False),
                caption_text,
                caption_hash,
                output_path,
                output_hash,
                output_size_bytes,
                round(duration_sec, 3),
                audio,
                encoded_at,
                encoder,
                status,
                review_state,
                render_time_sec,
                error_message,
            ),
        )

    def add_variation(self, video_id: str, recipe: Recipe, caption: str,
                      out_path: Path, key: str, duration: float,
                      render_time_sec: float | None = None,
                      lineage: dict[str, Any] | None = None,
                      encoder: str = "h264_videotoolbox",
                      target_ratio: str = "9:16"):
        cap_h = sha256_str(caption)
        out_h = sha256_file(out_path)
        size = out_path.stat().st_size
        recipe_params = asdict(recipe)
        recipe_params["_target_ratio"] = target_ratio
        if lineage:
            recipe_params["_lineage"] = lineage
        self._insert_variation_row(
            video_id=video_id,
            job_key=key,
            recipe=recipe.name,
            recipe_params=recipe_params,
            caption_text=caption,
            caption_hash=cap_h,
            output_path=str(out_path),
            output_hash=out_h,
            output_size_bytes=size,
            duration_sec=duration,
            audio="stripped",
            encoded_at=int(time.time()),
            encoder=encoder,
            status="ok",
            render_time_sec=render_time_sec,
        )

    def add_failure(self, video_id: str, recipe: Recipe, caption: str,
                    out_path: Path, key: str, duration: float,
                    error_message: str, render_time_sec: float | None = None,
                    encoder: str = "h264_videotoolbox",
                    target_ratio: str = "9:16"):
        cap_h = sha256_str(caption)
        recipe_params = asdict(recipe)
        recipe_params["_target_ratio"] = target_ratio
        self._insert_variation_row(
            video_id=video_id,
            job_key=key,
            recipe=recipe.name,
            recipe_params=recipe_params,
            caption_text=caption,
            caption_hash=cap_h,
            output_path=str(out_path),
            output_hash="",
            output_size_bytes=0,
            duration_sec=duration,
            audio="stripped",
            encoded_at=int(time.time()),
            encoder=encoder,
            status="failed",
            render_time_sec=render_time_sec,
            error_message=error_message[-2000:],
        )

    def set_review_state(self, filename: str, review_state: str) -> bool:
        if review_state not in {"draft", "approved", "rejected"}:
            raise ValueError("review_state must be draft, approved, or rejected")
        cur = self.conn.execute(
            "UPDATE variations SET review_state = ? WHERE output_path LIKE ?",
            (review_state, f"%/{filename}"),
        )
        return cur.rowcount > 0

    def add_attempt(self, *, key: str, attempt_no: int, status: str,
                    temp_path: Path, final_path: Path, ffmpeg_cmd: list[str],
                    started_at: int, ended_at: int | None = None,
                    error_message: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO render_attempts (
                attempt_id, job_key, attempt_no, status, temp_path, final_path,
                ffmpeg_cmd, started_at, ended_at, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{key}:{attempt_no}",
                key,
                attempt_no,
                status,
                str(temp_path),
                str(final_path),
                " ".join(shlex.quote(c) for c in ffmpeg_cmd),
                started_at,
                ended_at,
                error_message[-2000:] if error_message else None,
            ),
        )

    def get_analysis(self, source_hash: str, analyzer: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload_json FROM analysis_cache WHERE source_hash = ? AND analyzer = ?",
            (source_hash, analyzer),
        ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["payload_json"])
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def set_analysis(self, source_hash: str, analyzer: str, payload: dict) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO analysis_cache (
                cache_key, source_hash, analyzer, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                sha256_str(f"{source_hash}|{analyzer}"),
                source_hash,
                analyzer,
                json.dumps(payload, sort_keys=True, ensure_ascii=False),
                int(time.time()),
            ),
        )

    def to_json_data(self) -> dict:
        data = {"schema_version": self.SCHEMA_VERSION, "videos": {}, "updated_at": int(time.time())}
        videos = self.conn.execute("SELECT * FROM videos ORDER BY video_id").fetchall()
        for vid in videos:
            variations = []
            rows = self.conn.execute(
                "SELECT * FROM variations WHERE video_id = ? ORDER BY encoded_at, job_key",
                (vid["video_id"],),
            ).fetchall()
            for row in rows:
                variations.append({
                    "job_key": row["job_key"],
                    "recipe": row["recipe"],
                    "recipe_params": json.loads(row["recipe_params_json"]),
                    "caption_text": row["caption_text"],
                    "caption_hash": row["caption_hash"],
                    "output_path": row["output_path"],
                    "output_hash": row["output_hash"],
                    "output_size_bytes": row["output_size_bytes"],
                    "duration_sec": row["duration_sec"],
                    "audio": row["audio"],
                    "encoded_at": row["encoded_at"],
                    "encoder": row["encoder"],
                    "status": row["status"],
                    "review_state": row["review_state"],
                    "render_time_sec": row["render_time_sec"],
                    "error_message": row["error_message"],
                })
            data["videos"][vid["video_id"]] = {
                "source_path": vid["source_path"],
                "source_video_hash": vid["source_video_hash"],
                "source_duration_sec": vid["source_duration_sec"],
                "ingested_at": vid["ingested_at"],
                "variations": variations,
            }
        return data

    def save(self):
        self.conn.commit()
        tmp = self.json_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.to_json_data(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.json_path)
