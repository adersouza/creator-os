"""SQLite-backed local command queue for reel_factory workers."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from sqlite_utils import connect_sqlite

QUEUE_STATES = {"queued", "claimed", "running", "succeeded", "failed", "interrupted"}


class RenderQueue:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.db_path = self.root / "render_queue.sqlite"
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


class RedisRenderQueue:
    """Optional Redis-backed queue using the same command-job shape.

    This intentionally avoids making Redis/RQ a hard dependency. Install
    ``redis`` and set ``REDIS_URL`` to use it.
    """

    def __init__(self, root: Path, url: str | None = None):
        try:
            import redis  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Redis queue backend requires `python3 -m pip install redis`"
            ) from e
        self.root = Path(root).resolve()
        self.url = url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.redis = redis.Redis.from_url(self.url, decode_responses=True)
        self.prefix = f"reel_factory:{hash(str(self.root))}:"
        self.redis.ping()

    def _key(self, suffix: str) -> str:
        return self.prefix + suffix

    def enqueue(
        self, *, job_key: str, command: list[str], cwd: Path, max_attempts: int = 2
    ) -> str:
        existing = self.redis.get(self._key(f"job_key:{job_key}"))
        if existing:
            return str(existing)
        job_id = f"q_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        data = {
            "job_id": job_id,
            "job_key": job_key,
            "command_json": json.dumps(command),
            "cwd": str(cwd),
            "status": "queued",
            "attempts": "0",
            "max_attempts": str(max_attempts),
            "created_at": str(now),
        }
        pipe = self.redis.pipeline()
        pipe.hset(self._key(f"job:{job_id}"), mapping=data)
        pipe.set(self._key(f"job_key:{job_key}"), job_id)
        pipe.lpush(self._key("queued"), job_id)
        pipe.sadd(self._key("jobs"), job_id)
        pipe.execute()
        return job_id

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        job_id = self.redis.rpop(self._key("queued"))
        if not job_id:
            return None
        now = int(time.time())
        key = self._key(f"job:{job_id}")
        self.redis.hset(
            key,
            mapping={
                "status": "claimed",
                "worker_id": worker_id,
                "claimed_at": str(now),
                "heartbeat_at": str(now),
            },
        )
        return self._row_to_job(self.redis.hgetall(key))

    def mark_running(self, job_id: str, worker_id: str) -> None:
        key = self._key(f"job:{job_id}")
        attempts = int(self.redis.hget(key, "attempts") or 0) + 1
        now = int(time.time())
        self.redis.hset(
            key,
            mapping={
                "status": "running",
                "worker_id": worker_id,
                "attempts": str(attempts),
                "started_at": str(now),
                "heartbeat_at": str(now),
            },
        )

    def heartbeat(self, job_id: str, worker_id: str) -> None:
        self.redis.hset(
            self._key(f"job:{job_id}"), "heartbeat_at", str(int(time.time()))
        )

    def finish(
        self, job_id: str, status: str, *, error_text: str | None = None
    ) -> None:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError("finish status must be succeeded, failed, or interrupted")
        self.redis.hset(
            self._key(f"job:{job_id}"),
            mapping={
                "status": status,
                "ended_at": str(int(time.time())),
                "error_text": error_text[-2000:] if error_text else "",
            },
        )

    def recover_stale(self, stale_after_sec: int = 300) -> int:
        cutoff = int(time.time()) - stale_after_sec
        count = 0
        for job_id in self.redis.smembers(self._key("jobs")):
            key = self._key(f"job:{job_id}")
            row = self.redis.hgetall(key)
            if row.get("status") not in {"claimed", "running"}:
                continue
            heartbeat = int(
                row.get("heartbeat_at")
                or row.get("claimed_at")
                or row.get("started_at")
                or 0
            )
            if heartbeat >= cutoff:
                continue
            if int(row.get("attempts") or 0) < int(row.get("max_attempts") or 2):
                self.redis.hset(key, mapping={"status": "queued", "worker_id": ""})
                self.redis.lpush(self._key("queued"), job_id)
            else:
                self.finish(job_id, "interrupted", error_text="worker heartbeat stale")
            count += 1
        return count

    def status(self) -> dict[str, Any]:
        counts = {state: 0 for state in sorted(QUEUE_STATES)}
        recent = []
        for job_id in self.redis.smembers(self._key("jobs")):
            job = self._row_to_job(self.redis.hgetall(self._key(f"job:{job_id}")))
            counts[job.get("status", "queued")] = (
                counts.get(job.get("status", "queued"), 0) + 1
            )
            recent.append(job)
        recent.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
        return {
            "counts": counts,
            "recent": recent[:20],
            "backend": "redis",
            "url": self.url,
        }

    def _row_to_job(self, row: dict[str, str]) -> dict[str, Any]:
        data: dict[str, Any] = dict(row)
        data["command"] = json.loads(data.pop("command_json", "[]"))
        for key in (
            "attempts",
            "max_attempts",
            "created_at",
            "claimed_at",
            "started_at",
            "ended_at",
            "heartbeat_at",
        ):
            if key in data and data[key] not in ("", None):
                data[key] = int(data[key])
        return data


def get_queue(root: Path, backend: str = "sqlite"):
    if backend == "sqlite":
        return RenderQueue(root)
    if backend in {"redis", "rq"}:
        return RedisRenderQueue(root)
    raise ValueError("queue backend must be sqlite, redis, or rq")
