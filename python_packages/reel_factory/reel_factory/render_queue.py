"""SQLite-backed local command queue for reel_factory workers."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from reel_factory.sqlite_utils import connect_sqlite
from reel_factory.state_paths import render_queue_db_path

QUEUE_STATES = {"queued", "claimed", "running", "succeeded", "failed", "interrupted"}


class RenderQueue:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.db_path = render_queue_db_path(self.root)
        self.conn = connect_sqlite(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS queue_jobs (
            job_id TEXT PRIMARY KEY,
            job_key TEXT NOT NULL UNIQUE,
            command_json TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            worker_id TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 2,
            created_at INTEGER NOT NULL,
            claimed_at INTEGER,
            started_at INTEGER,
            ended_at INTEGER,
            heartbeat_at INTEGER,
            error_text TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_jobs(status, created_at);
        """)
        self.conn.commit()

    def enqueue(
        self, *, job_key: str, command: list[str], cwd: Path, max_attempts: int = 2
    ) -> str:
        job_id = f"q_{uuid.uuid4().hex[:16]}"
        self.conn.execute(
            """
            INSERT OR IGNORE INTO queue_jobs (
                job_id, job_key, command_json, cwd, status, max_attempts, created_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                job_id,
                job_key,
                json.dumps(command),
                str(cwd),
                max_attempts,
                int(time.time()),
            ),
        )
        row = self.conn.execute(
            "SELECT job_id FROM queue_jobs WHERE job_key = ?", (job_key,)
        ).fetchone()
        self.conn.commit()
        return str(row["job_id"])

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        now = int(time.time())
        row = self.conn.execute(
            "SELECT * FROM queue_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        cur = self.conn.execute(
            """
            UPDATE queue_jobs
            SET status = 'claimed', worker_id = ?, claimed_at = ?, heartbeat_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (worker_id, now, now, row["job_id"]),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        row = self.conn.execute(
            "SELECT * FROM queue_jobs WHERE job_id = ?", (row["job_id"],)
        ).fetchone()
        return self._row_to_job(row)

    def mark_running(self, job_id: str, worker_id: str) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE queue_jobs
            SET status = 'running', started_at = COALESCE(started_at, ?),
                heartbeat_at = ?, attempts = attempts + 1
            WHERE job_id = ? AND worker_id = ?
            """,
            (now, now, job_id, worker_id),
        )
        self.conn.commit()

    def heartbeat(self, job_id: str, worker_id: str) -> None:
        self.conn.execute(
            "UPDATE queue_jobs SET heartbeat_at = ? WHERE job_id = ? AND worker_id = ?",
            (int(time.time()), job_id, worker_id),
        )
        self.conn.commit()

    def finish(
        self, job_id: str, status: str, *, error_text: str | None = None
    ) -> None:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError("finish status must be succeeded, failed, or interrupted")
        self.conn.execute(
            """
            UPDATE queue_jobs
            SET status = ?, ended_at = ?, error_text = ?
            WHERE job_id = ?
            """,
            (
                status,
                int(time.time()),
                error_text[-2000:] if error_text else None,
                job_id,
            ),
        )
        self.conn.commit()

    def recover_stale(self, stale_after_sec: int = 300) -> int:
        cutoff = int(time.time()) - stale_after_sec
        rows = self.conn.execute(
            """
            SELECT * FROM queue_jobs
            WHERE status IN ('claimed', 'running') AND COALESCE(heartbeat_at, claimed_at, started_at, 0) < ?
            """,
            (cutoff,),
        ).fetchall()
        count = 0
        for row in rows:
            if int(row["attempts"]) < int(row["max_attempts"]):
                self.conn.execute(
                    "UPDATE queue_jobs SET status = 'queued', worker_id = NULL WHERE job_id = ?",
                    (row["job_id"],),
                )
            else:
                self.conn.execute(
                    "UPDATE queue_jobs SET status = 'interrupted', ended_at = ?, error_text = ? WHERE job_id = ?",
                    (int(time.time()), "worker heartbeat stale", row["job_id"]),
                )
            count += 1
        self.conn.commit()
        return count

    def status(self) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM queue_jobs GROUP BY status"
        ).fetchall()
        counts = {state: 0 for state in sorted(QUEUE_STATES)}
        counts.update({row["status"]: row["n"] for row in rows})
        recent = [
            self._row_to_job(row)
            for row in self.conn.execute(
                "SELECT * FROM queue_jobs ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        ]
        return {"counts": counts, "recent": recent, "db": str(self.db_path)}

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["command"] = json.loads(data.pop("command_json"))
        return data


def get_queue(root: Path) -> RenderQueue:
    """Return the single supported local queue implementation."""

    return RenderQueue(root)
