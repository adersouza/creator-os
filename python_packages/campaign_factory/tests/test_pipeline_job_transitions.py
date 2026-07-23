from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from campaign_test_support import make_factory


def _race(tmp_path: Path, job_id: str, actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        factory = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            try:
                return ("ok", action(factory, job_id)["status"])
            except RuntimeError as exc:
                return ("conflict", str(exc))
        finally:
            factory.close()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_start_is_compare_and_swap_under_concurrent_workers(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
    finally:
        factory.close()

    results = _race(
        tmp_path,
        job["id"],
        [lambda cf, job_id: cf.domains.events.start_pipeline_job(job_id)] * 2,
    )
    assert [result[0] for result in results].count("ok") == 1
    assert [result[0] for result in results].count("conflict") == 1

    reloaded = make_factory(tmp_path)
    try:
        row = reloaded.domains.events.pipeline_job(job["id"])
        assert row["status"] == "running"
        assert row["attemptCount"] == 1
    finally:
        reloaded.close()


def test_terminal_transition_is_immutable_under_finish_fail_race(
    tmp_path: Path,
) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
        factory.domains.events.start_pipeline_job(job["id"])
    finally:
        factory.close()

    results = _race(
        tmp_path,
        job["id"],
        [
            lambda cf, job_id: cf.domains.events.finish_pipeline_job(
                job_id, {"winner": "finish"}
            ),
            lambda cf, job_id: cf.domains.events.fail_pipeline_job(
                job_id, "failure winner", {"winner": "fail"}
            ),
        ],
    )
    assert [result[0] for result in results].count("ok") == 1
    assert [result[0] for result in results].count("conflict") == 1

    reloaded = make_factory(tmp_path)
    try:
        row = reloaded.domains.events.pipeline_job(job["id"])
        terminal = row["status"]
        assert terminal in {"succeeded", "failed"}
        with pytest.raises(RuntimeError, match="pipeline_job_transition_conflict"):
            reloaded.domains.events.finish_pipeline_job(job["id"], {"late": True})
        with pytest.raises(RuntimeError, match="pipeline_job_transition_conflict"):
            reloaded.domains.events.fail_pipeline_job(job["id"], "late")
        assert reloaded.domains.events.pipeline_job(job["id"])["status"] == terminal
        with pytest.raises(
            sqlite3.IntegrityError, match="terminal pipeline jobs are immutable"
        ):
            reloaded.conn.execute(
                "UPDATE pipeline_jobs SET error = 'direct mutation' WHERE id = ?",
                (job["id"],),
            )
    finally:
        reloaded.close()


def test_reclaim_rowcount_does_not_claim_a_concurrent_start(tmp_path: Path) -> None:
    factory = make_factory(tmp_path)
    try:
        job = factory.domains.events.create_pipeline_job("render", None)
        factory.conn.execute(
            "UPDATE pipeline_jobs SET updated_at = datetime('now', '-5 hours'), "
            "created_at = datetime('now', '-5 hours') WHERE id = ?",
            (job["id"],),
        )
        factory.conn.commit()
    finally:
        factory.close()

    barrier = Barrier(2)

    def start():
        local = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            try:
                local.domains.events.start_pipeline_job(job["id"])
                return "started"
            except RuntimeError:
                return "conflict"
        finally:
            local.close()

    def reclaim():
        local = make_factory(tmp_path)
        try:
            barrier.wait(timeout=5)
            return local.domains.events.reclaim_stale_pipeline_jobs(2.0)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future = pool.submit(start)
        reclaim_future = pool.submit(reclaim)
        start_result = start_future.result()
        reclaim_result = reclaim_future.result()

    reloaded = make_factory(tmp_path)
    try:
        status = reloaded.domains.events.pipeline_job(job["id"])["status"]
        assert (start_result, status, reclaim_result["reclaimedCount"]) in {
            ("started", "running", 0),
            ("conflict", "failed", 1),
        }
    finally:
        reloaded.close()
