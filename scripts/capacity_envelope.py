#!/usr/bin/env python3
"""Measure Creator OS capacity against isolated, exact-size local fixtures.

This command never reads or writes canonical Creator OS runtime state.  Every
run creates a new directory below an operator-selected workspace, initializes
the real Campaign Factory and Reel Factory SQLite schemas there, generates real
fixture bytes, and writes one atomic evidence receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "packages/creator_os_core",
    ROOT / "packages/pipeline_contracts",
    ROOT / "python_packages/campaign_factory",
    ROOT / "python_packages/reel_factory",
):
    sys.path.insert(0, str(package_root))
sys.path.insert(0, str(ROOT / "scripts"))

from backup_runtime_state import backup_runtime_state, restore_runtime_state
from campaign_factory.config import Settings
from campaign_factory.contentforge_cli import run_contentforge
from campaign_factory.core import CampaignFactory
from creator_os_core.fileops import atomic_write_json
from creator_os_core.media_probe import probe_video_stream
from creator_os_core.sqlite import connect_sqlite
from reel_factory.local_generation_queue import hardware_identity
from reel_factory.render_queue import RenderQueue

SCHEMA = "creator_os.capacity_envelope.v1"
POLICY_VERSION = "capacity-envelope-policy.v1"
FIXTURE_VERSION = "capacity-envelope-fixture.v1"
FIXED_TIME = "2026-07-30T12:00:00Z"
ASSET_BYTES = 256
FILE_SHARD_SIZE = 1_000


@dataclass(frozen=True)
class CapacityTier:
    name: str
    creators: int
    assets: int
    asset_files: int
    claim_eligible: bool


CAPACITY_TIERS: dict[str, CapacityTier] = {
    "smoke": CapacityTier(
        name="smoke",
        creators=2,
        assets=128,
        asset_files=128,
        claim_eligible=False,
    ),
    "10-creators-10k-assets": CapacityTier(
        name="10-creators-10k-assets",
        creators=10,
        assets=10_000,
        asset_files=10_000,
        claim_eligible=True,
    ),
    "100-creators-100k-assets": CapacityTier(
        name="100-creators-100k-assets",
        creators=100,
        assets=100_000,
        asset_files=100_000,
        claim_eligible=True,
    ),
    "1000-creators-1m-assets": CapacityTier(
        name="1000-creators-1m-assets",
        creators=1_000,
        assets=1_000_000,
        asset_files=1_000_000,
        claim_eligible=True,
    ),
}

MANDATORY_LANES = (
    "database_fixture",
    "query_latency_index_use",
    "sqlite_contention",
    "filesystem_traversal",
    "sha_probe",
    "ffmpeg_throughput",
    "contentforge_throughput",
    "render_queue_throughput",
    "provider_queue_admission",
    "report_latency",
    "backup_restore",
    "failure_recovery",
)

# These are conservative release gates, not measured claims. A tier must meet
# all of them on the exact fixture before it may become a supported envelope.
THRESHOLDS: dict[str, float] = {
    "queryP95MsMax": 250.0,
    "sqliteWriteP95MsMax": 500.0,
    "sqliteBusyErrorsMax": 0.0,
    "filesystemFilesPerSecondMin": 1_000.0,
    "shaMiBPerSecondMin": 20.0,
    "ffmpegMediaToWallRatioMin": 0.20,
    "contentforgeItemsPerSecondMin": 0.01,
    "renderQueueOpsPerSecondMin": 20.0,
    "providerAdmissionOpsPerSecondMin": 20.0,
    "reportLatencyMsMax": 2_000.0,
    "backupSecondsMax": 1_800.0,
    "restoreSecondsMax": 1_800.0,
}


class LaneSkipped(RuntimeError):
    """A measurement could not execute and therefore cannot support a claim."""


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(float(ordered[index]), 4)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if value <= 0:
        return 0
    return value if platform.system() == "Darwin" else value * 1024


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_workspace(workspace: Path) -> Path:
    resolved = workspace.expanduser().resolve()
    protected = (
        ROOT.resolve(),
        (ROOT / "python_packages/campaign_factory").resolve(),
        (ROOT / "python_packages/reel_factory").resolve(),
    )
    if any(
        resolved == candidate
        or _path_is_within(resolved, candidate)
        or _path_is_within(candidate, resolved)
        for candidate in protected
    ):
        raise ValueError("capacity_workspace_overlaps_repository_or_runtime")
    if resolved.is_symlink():
        raise ValueError("capacity_workspace_must_not_be_symlink")
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise ValueError("capacity_workspace_must_be_directory")
    return resolved


def _repo_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "unknown"


def _tool_evidence(name: str) -> dict[str, Any]:
    executable = shutil.which(name)
    if not executable:
        return {"available": False, "name": name}
    path = Path(executable).resolve()
    version = subprocess.run(
        [str(path), "-version" if name in {"ffmpeg", "ffprobe"} else "--version"],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    first_line = (version.stdout or version.stderr).splitlines()
    return {
        "available": version.returncode == 0,
        "name": name,
        "path": str(path),
        "sha256": _sha256_file(path),
        "version": first_line[0][:500] if first_line else "unknown",
    }


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _measure_lane(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    rss_before = _rss_bytes()
    try:
        evidence = operation()
        status = "passed"
        error = None
    except LaneSkipped as exc:
        evidence = {}
        status = "skipped"
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - evidence boundary must stay truthful
        evidence = {}
        status = "failed"
        error = f"{type(exc).__name__}:{exc}"
    elapsed = time.perf_counter() - started
    return {
        "name": name,
        "status": status,
        "durationSeconds": round(elapsed, 6),
        "peakRssBytes": max(rss_before, _rss_bytes()),
        "error": error,
        "evidence": evidence,
    }


def _settings(run_root: Path) -> Settings:
    reel_root = run_root / "reel_factory"
    (reel_root / "00_source_videos").mkdir(parents=True, exist_ok=True)
    (reel_root / "01_captions").mkdir(parents=True, exist_ok=True)
    return Settings(
        root=run_root / "campaign_factory",
        db_path=run_root / "state/campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=ROOT / "packages/contentforge",
        reference_factory_root=run_root / "reference_factory",
        reference_reels_root=run_root / "reference_factory",
        threadsdash_root=run_root / "threadsdashboard-unavailable",
        campaigns_dir=run_root / "campaigns",
        creative_approvals_dir=run_root / "creative_approvals",
    )


def _fixture_bytes(index: int) -> bytes:
    header = json.dumps(
        {"assetIndex": index, "fixture": FIXTURE_VERSION},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(header) > ASSET_BYTES:
        raise RuntimeError("capacity_fixture_payload_exceeds_size")
    return header + b" " * (ASSET_BYTES - len(header))


def _populate_fixture(
    factory: CampaignFactory, run_root: Path, tier: CapacityTier
) -> dict[str, Any]:
    conn = factory.conn
    assets_root = run_root / "assets"
    assets_root.mkdir(parents=True, exist_ok=False)
    model_ids: list[str] = []
    campaign_ids: list[str] = []
    for index in range(tier.creators):
        creator_slug = f"capacity_creator_{index:04d}"
        campaign = factory.domains.models.upsert_campaign(
            f"capacity_campaign_{index:04d}",
            creator_slug,
            name=f"Capacity Campaign {index:04d}",
        )
        model = factory.conn.execute(
            "SELECT id FROM models WHERE slug = ?", (creator_slug,)
        ).fetchone()
        if model is None:
            raise RuntimeError("capacity_fixture_model_missing")
        model_ids.append(str(model["id"]))
        campaign_ids.append(str(campaign["id"]))
    accounts = [
        (
            f"account_capacity_{index:04d}",
            f"capacity_{index:04d}",
            f"capacity_external_{index:04d}",
            model_ids[index],
            FIXED_TIME,
            FIXED_TIME,
        )
        for index in range(tier.creators)
    ]
    conn.executemany(
        """
        INSERT INTO accounts
        (id, handle, external_id, model_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        accounts,
    )
    conn.commit()

    batch: list[tuple[Any, ...]] = []
    total_bytes = 0
    for index in range(tier.assets):
        shard = assets_root / f"{index // FILE_SHARD_SIZE:06d}"
        shard.mkdir(exist_ok=True)
        path = shard / f"asset_{index:09d}.bin"
        payload = _fixture_bytes(index)
        path.write_bytes(payload)
        total_bytes += len(payload)
        creator_index = index % tier.creators
        batch.append(
            (
                f"source_capacity_{index:09d}",
                campaign_ids[creator_index],
                model_ids[creator_index],
                hashlib.sha256(payload).hexdigest(),
                str(path),
                str(path),
                path.name,
                "image",
                "feed_single",
                "instagram",
                "{}",
                "[]",
                "approved",
                FIXED_TIME,
                FIXED_TIME,
            )
        )
        if len(batch) >= 1_000:
            conn.executemany(
                """
                INSERT INTO source_assets
                (id, campaign_id, model_id, content_hash, original_path,
                 stored_path, filename, media_type, content_surface, platform,
                 source_prompt, account_ids_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            conn.commit()
            batch.clear()
    if batch:
        conn.executemany(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path,
             stored_path, filename, media_type, content_surface, platform,
             source_prompt, account_ids_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        conn.commit()

    counts = {
        "creators": int(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0]),
        "campaigns": int(conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]),
        "accounts": int(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]),
        "assets": int(conn.execute("SELECT COUNT(*) FROM source_assets").fetchone()[0]),
        "assetFiles": sum(1 for path in assets_root.rglob("*") if path.is_file()),
        "assetBytes": total_bytes,
    }
    exact = (
        counts["creators"] == tier.creators
        and counts["assets"] == tier.assets
        and counts["assetFiles"] == tier.asset_files
    )
    if not exact:
        raise RuntimeError(f"capacity_fixture_count_mismatch:{counts}")
    return {
        "counts": counts,
        "exact": True,
        "assetsRoot": str(assets_root),
        "modelIds": model_ids,
        "campaignIds": campaign_ids,
    }


def _query_lane(
    factory: CampaignFactory, tier: CapacityTier, fixture: dict[str, Any]
) -> dict[str, Any]:
    campaign_id = str(fixture["campaignIds"][0])
    model_id = str(fixture["modelIds"][0])
    queries = {
        "campaign_assets": (
            """
            SELECT id, content_hash FROM source_assets
            WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 100
            """,
            (campaign_id,),
        ),
        "exact_asset_hash": (
            """
            SELECT id FROM source_assets
            WHERE campaign_id = ? AND content_hash = ?
            """,
            (
                campaign_id,
                hashlib.sha256(_fixture_bytes(0)).hexdigest(),
            ),
        ),
        "creator_accounts": (
            "SELECT id FROM accounts WHERE model_id = ? ORDER BY created_at DESC",
            (model_id,),
        ),
        "asset_count": ("SELECT COUNT(*) FROM source_assets", ()),
    }
    results: dict[str, Any] = {}
    all_latencies: list[float] = []
    for name, (sql, params) in queries.items():
        plan = [
            str(row["detail"])
            for row in factory.conn.execute(
                f"EXPLAIN QUERY PLAN {sql}", params
            ).fetchall()
        ]
        timings: list[float] = []
        for _ in range(9):
            started = time.perf_counter()
            factory.conn.execute(sql, params).fetchall()
            timings.append((time.perf_counter() - started) * 1_000)
        all_latencies.extend(timings)
        results[name] = {
            "p50Ms": _percentile(timings, 0.50),
            "p95Ms": _percentile(timings, 0.95),
            "p99Ms": _percentile(timings, 0.99),
            "queryPlan": plan,
        }
    return {
        "queries": results,
        "overallP95Ms": _percentile(all_latencies, 0.95),
        "assetCount": tier.assets,
    }


def _contention_lane(db_path: Path) -> dict[str, Any]:
    with connect_sqlite(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capacity_write_probe (
              worker_id INTEGER NOT NULL,
              ordinal INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(worker_id, ordinal)
            )
            """
        )
        conn.commit()

    def writer(worker_id: int) -> dict[str, Any]:
        timings: list[float] = []
        errors: list[str] = []
        connection = connect_sqlite(db_path)
        try:
            for ordinal in range(12):
                started = time.perf_counter()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        INSERT INTO capacity_write_probe
                        (worker_id, ordinal, created_at) VALUES (?, ?, ?)
                        """,
                        (worker_id, ordinal, FIXED_TIME),
                    )
                    connection.commit()
                    timings.append((time.perf_counter() - started) * 1_000)
                except sqlite3.Error as exc:
                    connection.rollback()
                    errors.append(type(exc).__name__)
        finally:
            connection.close()
        return {"timings": timings, "errors": errors}

    with ThreadPoolExecutor(max_workers=4) as pool:
        worker_results = list(pool.map(writer, range(4)))
    timings = [value for result in worker_results for value in result["timings"]]
    errors = [value for result in worker_results for value in result["errors"]]
    with connect_sqlite(db_path) as conn:
        rows = int(
            conn.execute("SELECT COUNT(*) FROM capacity_write_probe").fetchone()[0]
        )
    return {
        "workers": 4,
        "attemptedWrites": 48,
        "committedWrites": rows,
        "busyErrors": len(errors),
        "errorClasses": sorted(set(errors)),
        "writeP50Ms": _percentile(timings, 0.50),
        "writeP95Ms": _percentile(timings, 0.95),
        "writeP99Ms": _percentile(timings, 0.99),
    }


def _filesystem_lane(assets_root: Path, expected_files: int) -> dict[str, Any]:
    started = time.perf_counter()
    files = 0
    total_bytes = 0
    for path in assets_root.rglob("*"):
        if path.is_file():
            files += 1
            total_bytes += path.stat().st_size
    elapsed = max(time.perf_counter() - started, 1e-9)
    if files != expected_files:
        raise RuntimeError(f"filesystem_fixture_count_mismatch:{files}")
    return {
        "files": files,
        "bytes": total_bytes,
        "seconds": round(elapsed, 6),
        "filesPerSecond": round(files / elapsed, 3),
    }


def _run_command(command: list[str], *, timeout: int = 120) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown failure")[-2_000:]
        raise RuntimeError(f"capacity_command_failed:{command[0]}:{detail.strip()}")
    return time.perf_counter() - started


def _generate_media(run_root: Path) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise LaneSkipped("ffmpeg_or_ffprobe_unavailable")
    media_root = run_root / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    sha_sample = media_root / "sha-sample.bin"
    sample_block = hashlib.sha256(FIXTURE_VERSION.encode()).digest() * 32
    with sha_sample.open("wb") as handle:
        for _ in range(8 * 1_024):
            handle.write(sample_block)
    source = media_root / "source.mp4"
    source_seconds = 1.0
    generation_seconds = _run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x38598b:s=320x568:r=24:d=1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(source),
        ]
    )
    renders: list[dict[str, Any]] = []
    for index in range(2):
        output = media_root / f"render_{index}.mp4"
        elapsed = _run_command(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vf",
                f"eq=brightness={0.005 * (index + 1):.3f}",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(output),
            ]
        )
        renders.append(
            {
                "path": str(output),
                "seconds": round(elapsed, 6),
                "sha256": _sha256_file(output),
                "probe": probe_video_stream(output),
            }
        )
    total_render_seconds = sum(float(row["seconds"]) for row in renders)
    return {
        "source": str(source),
        "shaSample": str(sha_sample),
        "sourceSha256": _sha256_file(source),
        "sourceProbe": probe_video_stream(source),
        "sourceGenerationSeconds": round(generation_seconds, 6),
        "renders": renders,
        "renderCount": len(renders),
        "mediaSeconds": source_seconds * len(renders),
        "wallSeconds": round(total_render_seconds, 6),
        "mediaToWallRatio": round(
            (source_seconds * len(renders)) / max(total_render_seconds, 1e-9), 4
        ),
    }


def _sha_probe_lane(media: dict[str, Any]) -> dict[str, Any]:
    media_path = Path(str(media["source"]))
    path = Path(str(media["shaSample"]))
    size = path.stat().st_size
    started = time.perf_counter()
    digest = _sha256_file(path)
    elapsed = max(time.perf_counter() - started, 1e-9)
    probe = probe_video_stream(media_path)
    return {
        "path": str(path),
        "probedMediaPath": str(media_path),
        "bytes": size,
        "sha256": digest,
        "probe": probe,
        "seconds": round(elapsed, 6),
        "mibPerSecond": round((size / (1024**2)) / elapsed, 4),
    }


def _contentforge_lane(media: dict[str, Any]) -> dict[str, Any]:
    source = Path(str(media["source"]))
    contentforge_root = ROOT / "packages/contentforge"
    if not (contentforge_root / "node_modules/ajv").is_dir():
        raise LaneSkipped("contentforge_dependencies_unavailable")
    started = time.perf_counter()
    try:
        response = run_contentforge(
            contentforge_root,
            "analyze-media",
            {
                "mediaPath": str(source),
                "mediaSha256": str(media["sourceSha256"]),
                "producedAt": FIXED_TIME,
                "overlaysExist": False,
            },
            timeout=240,
        )
    except RuntimeError as exc:
        if "analyzer executable qualification is blocked" in str(exc):
            raise LaneSkipped("contentforge_analyzer_authority_unqualified") from exc
        raise
    elapsed = max(time.perf_counter() - started, 1e-9)
    return {
        "items": 1,
        "seconds": round(elapsed, 6),
        "itemsPerSecond": round(1 / elapsed, 6),
        "responseSchema": response.get("schema"),
        "responseStatus": response.get("status")
        or response.get("overallVerdict")
        or "completed",
        "responseFingerprint": _fingerprint(response),
    }


def _render_queue_lane(run_root: Path) -> dict[str, Any]:
    queue = RenderQueue(run_root / "render_queue")
    count = 32
    started = time.perf_counter()
    for index in range(count):
        queue.enqueue(
            job_key=f"capacity-job-{index:04d}",
            command=["capacity-noop", str(index)],
            cwd=run_root,
            max_attempts=2,
        )
    claimed = 0
    for index in range(count):
        job = queue.claim(f"capacity-worker-{index % 4}")
        if job is None:
            break
        worker = f"capacity-worker-{index % 4}"
        queue.mark_running(str(job["job_id"]), worker)
        queue.finish(str(job["job_id"]), "succeeded", worker_id=worker)
        claimed += 1
    elapsed = max(time.perf_counter() - started, 1e-9)
    status = queue.status()
    queue.conn.close()
    return {
        "enqueued": count,
        "completed": claimed,
        "seconds": round(elapsed, 6),
        "operationsPerSecond": round((count + claimed * 3) / elapsed, 3),
        "statusCounts": status["counts"],
    }


def _provider_admission_lane(
    factory: CampaignFactory, tier: CapacityTier, fixture: dict[str, Any]
) -> dict[str, Any]:
    count = min(32, tier.assets)
    run_id = "orun_capacity_provider"
    started = time.perf_counter()
    factory.conn.execute("BEGIN IMMEDIATE")
    factory.conn.execute(
        """
        INSERT INTO daily_orchestrator_runs
        (id, run_key, status, algorithm_version, policy_fingerprint,
         requested_items, selected_items, limits_json, stop_reason,
         next_run_reason, created_at, updated_at)
        VALUES (?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "capacity-provider-admission",
            "capacity-probe.v1",
            _fingerprint({"tier": tier.name}),
            count,
            count,
            json.dumps({"provider": count}, sort_keys=True),
            "requested_capacity_filled",
            "none",
            FIXED_TIME,
            FIXED_TIME,
        ),
    )
    rows = []
    for index in range(count):
        creator_index = index % tier.creators
        rows.append(
            (
                f"oitem_capacity_{index:04d}",
                run_id,
                index,
                str(fixture["modelIds"][creator_index]),
                str(fixture["campaignIds"][creator_index]),
                f"source_capacity_{index:09d}",
                "calm_animation",
                "passive_selfie",
                "selected",
                0,
                3,
                "{}",
                _fingerprint({"ordinal": index, "tier": tier.name}),
                FIXED_TIME,
                FIXED_TIME,
            )
        )
    factory.conn.executemany(
        """
        INSERT INTO daily_orchestrator_items
        (id, run_id, ordinal, creator_id, campaign_id, source_asset_id,
         mode, intent, state, attempt_count, max_attempts,
         selection_reason_json, decision_fingerprint, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    factory.conn.commit()
    elapsed = max(time.perf_counter() - started, 1e-9)
    admitted = int(
        factory.conn.execute(
            "SELECT COUNT(*) FROM daily_orchestrator_items WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    return {
        "attempted": count,
        "admitted": admitted,
        "seconds": round(elapsed, 6),
        "operationsPerSecond": round(admitted / elapsed, 3),
        "externalProviderCalls": 0,
    }


def _report_lane(factory: CampaignFactory) -> dict[str, Any]:
    timings: list[float] = []
    result: dict[str, Any] = {}
    for _ in range(5):
        started = time.perf_counter()
        result = factory.domains.live_scale.actual_account_operational_counts()
        timings.append((time.perf_counter() - started) * 1_000)
    return {
        "report": "actual_account_operational_counts",
        "p50Ms": _percentile(timings, 0.50),
        "p95Ms": _percentile(timings, 0.95),
        "p99Ms": _percentile(timings, 0.99),
        "result": result,
    }


def _backup_restore_lane(
    run_root: Path, db_path: Path, assets_root: Path
) -> dict[str, Any]:
    created = datetime.now(UTC)
    backup_started = time.perf_counter()
    backup = backup_runtime_state(
        run_root,
        run_root / "backups",
        timestamp="capacity",
        created_at=created,
        database_sources=(
            ("campaign_factory", db_path, Path("campaign_factory.sqlite")),
        ),
        directory_sources=(("assets", assets_root, Path("assets")),),
        required_databases=("campaign_factory",),
        required_directories=("assets",),
        config_evidence={},
        rpo_seconds=3_600,
        rto_seconds=1_800,
    )
    backup_seconds = time.perf_counter() - backup_started
    restore = restore_runtime_state(
        Path(str(backup["backupDir"])),
        run_root / "restore",
        operator="capacity-envelope",
        authorized=True,
        path_rebindings={
            "campaign_factory": "state/campaign_factory.sqlite",
            "assets": "artifacts/assets",
        },
        allow_stale=True,
        now=created,
    )
    return {
        "backupStatus": backup["status"],
        "backupManifestFingerprint": backup["manifestFingerprint"],
        "backupSeconds": round(backup_seconds, 6),
        "restoreSeconds": round(float(restore["rtoSeconds"]), 6),
        "restoreIntegrity": all(
            row.get("rowCounts") is not None for row in restore["databases"]
        ),
        "restoredAssetFiles": next(
            (
                int(row["fileCount"])
                for row in restore["directories"]
                if row["name"] == "assets"
            ),
            0,
        ),
    }


def _failure_recovery_lane(run_root: Path) -> dict[str, Any]:
    queue = RenderQueue(run_root / "failure_recovery_queue")
    job_id = queue.enqueue(
        job_key="capacity-stale-job",
        command=["capacity-noop"],
        cwd=run_root,
        max_attempts=1,
    )
    job = queue.claim("capacity-stale-worker")
    if job is None or str(job["job_id"]) != job_id:
        raise RuntimeError("capacity_stale_job_claim_failed")
    queue.mark_running(job_id, "capacity-stale-worker")
    queue.conn.execute(
        "UPDATE queue_jobs SET heartbeat_at = 1 WHERE job_id = ?", (job_id,)
    )
    queue.conn.commit()
    recovered = queue.recover_stale(stale_after_sec=1)
    status = queue.status()["counts"]
    queue.conn.close()
    replay = RenderQueue(run_root / "failure_recovery_queue")
    second_recovery = replay.recover_stale(stale_after_sec=1)
    replay.conn.close()
    return {
        "recovered": recovered,
        "interrupted": int(status["interrupted"]),
        "idempotentSecondRecovery": second_recovery == 0,
    }


def _threshold_evaluation(
    lanes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    values = {
        "queryP95MsMax": lanes["query_latency_index_use"]["evidence"].get(
            "overallP95Ms"
        ),
        "sqliteWriteP95MsMax": lanes["sqlite_contention"]["evidence"].get("writeP95Ms"),
        "sqliteBusyErrorsMax": lanes["sqlite_contention"]["evidence"].get("busyErrors"),
        "filesystemFilesPerSecondMin": lanes["filesystem_traversal"]["evidence"].get(
            "filesPerSecond"
        ),
        "shaMiBPerSecondMin": lanes["sha_probe"]["evidence"].get("mibPerSecond"),
        "ffmpegMediaToWallRatioMin": lanes["ffmpeg_throughput"]["evidence"].get(
            "mediaToWallRatio"
        ),
        "contentforgeItemsPerSecondMin": lanes["contentforge_throughput"][
            "evidence"
        ].get("itemsPerSecond"),
        "renderQueueOpsPerSecondMin": lanes["render_queue_throughput"]["evidence"].get(
            "operationsPerSecond"
        ),
        "providerAdmissionOpsPerSecondMin": lanes["provider_queue_admission"][
            "evidence"
        ].get("operationsPerSecond"),
        "reportLatencyMsMax": lanes["report_latency"]["evidence"].get("p95Ms"),
        "backupSecondsMax": lanes["backup_restore"]["evidence"].get("backupSeconds"),
        "restoreSecondsMax": lanes["backup_restore"]["evidence"].get("restoreSeconds"),
    }
    results: dict[str, Any] = {}
    passed = True
    for key, limit in THRESHOLDS.items():
        value = values.get(key)
        comparison = "minimum" if key.endswith("Min") else "maximum"
        item_passed = value is not None and (
            float(value) >= limit if comparison == "minimum" else float(value) <= limit
        )
        results[key] = {
            "comparison": comparison,
            "limit": limit,
            "observed": value,
            "passed": item_passed,
        }
        passed = passed and item_passed
    return {"passed": passed, "checks": results}


def capacity_claim_is_valid(receipt: dict[str, Any]) -> bool:
    """Return true only for an exact, complete, non-inferred tier measurement."""

    if receipt.get("schema") != SCHEMA:
        return False
    claimed_fingerprint = str(receipt.get("receiptFingerprint") or "")
    if claimed_fingerprint != _fingerprint(
        {key: value for key, value in receipt.items() if key != "receiptFingerprint"}
    ):
        return False
    tier = receipt.get("tier") if isinstance(receipt.get("tier"), dict) else {}
    actual = (
        receipt.get("fixture", {}).get("actualCounts")
        if isinstance(receipt.get("fixture"), dict)
        else {}
    )
    support = (
        receipt.get("supportClaim")
        if isinstance(receipt.get("supportClaim"), dict)
        else {}
    )
    lanes = receipt.get("lanes") if isinstance(receipt.get("lanes"), dict) else {}
    if (
        not tier.get("claimEligible")
        or not support.get("supported")
        or support.get("inferred")
        or not receipt.get("fixture", {}).get("exact")
        or actual.get("creators") != tier.get("creators")
        or actual.get("assets") != tier.get("assets")
        or actual.get("assetFiles") != tier.get("assetFiles")
        or not receipt.get("thresholdEvaluation", {}).get("passed")
    ):
        return False
    return all(
        isinstance(lanes.get(name), dict) and lanes[name].get("status") == "passed"
        for name in MANDATORY_LANES
    )


def run_capacity_benchmark(
    *, tier_name: str, workspace: Path, receipt_path: Path | None = None
) -> dict[str, Any]:
    if tier_name not in CAPACITY_TIERS:
        raise ValueError(f"unknown_capacity_tier:{tier_name}")
    if receipt_path is not None and _path_is_within(
        receipt_path.expanduser().resolve(), ROOT
    ):
        raise ValueError("capacity_receipt_must_not_be_written_inside_repository")
    tier = CAPACITY_TIERS[tier_name]
    workspace_root = _validate_workspace(workspace)
    definition = {
        **asdict(tier),
        "fixtureVersion": FIXTURE_VERSION,
        "policyVersion": POLICY_VERSION,
        "mandatoryLanes": list(MANDATORY_LANES),
        "thresholds": THRESHOLDS,
    }
    definition_fingerprint = _fingerprint(definition)
    run_root = workspace_root / (f"capacity-{tier.name}-{definition_fingerprint[:12]}")
    if run_root.exists():
        raise FileExistsError(f"capacity_run_already_exists:{run_root}")
    run_root.mkdir(mode=0o700)

    toolchain = {
        name: _tool_evidence(name) for name in ("python3", "node", "ffmpeg", "ffprobe")
    }
    fixture_fingerprint = _fingerprint(
        {
            "definitionFingerprint": definition_fingerprint,
            "repoSha": _repo_sha(),
            "toolchain": {
                key: {
                    "available": value["available"],
                    "sha256": value.get("sha256"),
                    "version": value.get("version"),
                }
                for key, value in toolchain.items()
            },
        }
    )
    settings = _settings(run_root)
    factory: CampaignFactory | None = None
    lanes: dict[str, dict[str, Any]] = {}
    media: dict[str, Any] = {}
    fixture: dict[str, Any] = {}
    try:
        factory = CampaignFactory(settings)
        lanes["database_fixture"] = _measure_lane(
            "database_fixture",
            lambda: _populate_fixture(factory, run_root, tier),
        )
        fixture = dict(lanes["database_fixture"]["evidence"])
        if fixture:
            lanes["database_fixture"]["evidence"] = {
                "counts": fixture.get("counts"),
                "exact": fixture.get("exact"),
                "assetsRoot": fixture.get("assetsRoot"),
            }
        if lanes["database_fixture"]["status"] != "passed":
            raise RuntimeError("capacity_database_fixture_failed")
        lanes["query_latency_index_use"] = _measure_lane(
            "query_latency_index_use", lambda: _query_lane(factory, tier, fixture)
        )
        lanes["sqlite_contention"] = _measure_lane(
            "sqlite_contention", lambda: _contention_lane(settings.db_path)
        )
        lanes["filesystem_traversal"] = _measure_lane(
            "filesystem_traversal",
            lambda: _filesystem_lane(
                Path(str(fixture["assetsRoot"])), tier.asset_files
            ),
        )
        media_lane = _measure_lane(
            "ffmpeg_throughput", lambda: _generate_media(run_root)
        )
        lanes["ffmpeg_throughput"] = media_lane
        media = dict(media_lane["evidence"])
        lanes["sha_probe"] = _measure_lane(
            "sha_probe",
            lambda: (
                _sha_probe_lane(media)
                if media
                else (_ for _ in ()).throw(
                    LaneSkipped("ffmpeg_media_fixture_unavailable")
                )
            ),
        )
        lanes["contentforge_throughput"] = _measure_lane(
            "contentforge_throughput",
            lambda: (
                _contentforge_lane(media)
                if media
                else (_ for _ in ()).throw(
                    LaneSkipped("ffmpeg_media_fixture_unavailable")
                )
            ),
        )
        lanes["render_queue_throughput"] = _measure_lane(
            "render_queue_throughput", lambda: _render_queue_lane(run_root)
        )
        lanes["provider_queue_admission"] = _measure_lane(
            "provider_queue_admission",
            lambda: _provider_admission_lane(factory, tier, fixture),
        )
        lanes["report_latency"] = _measure_lane(
            "report_latency", lambda: _report_lane(factory)
        )
        factory.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        factory.conn.commit()
        lanes["backup_restore"] = _measure_lane(
            "backup_restore",
            lambda: _backup_restore_lane(
                run_root, settings.db_path, Path(str(fixture["assetsRoot"]))
            ),
        )
        lanes["failure_recovery"] = _measure_lane(
            "failure_recovery", lambda: _failure_recovery_lane(run_root)
        )
    except Exception as exc:  # preserve a truthful receipt for partial execution
        for name in MANDATORY_LANES:
            lanes.setdefault(
                name,
                {
                    "name": name,
                    "status": "skipped",
                    "durationSeconds": 0.0,
                    "peakRssBytes": _rss_bytes(),
                    "error": f"dependency_failed:{type(exc).__name__}:{exc}",
                    "evidence": {},
                },
            )
    finally:
        if factory is not None:
            factory.close()

    fixture_counts = fixture.get("counts") if isinstance(fixture, dict) else {}
    fixture_exact = bool(fixture.get("exact"))
    thresholds = _threshold_evaluation(lanes)
    mandatory_passed = all(
        lanes.get(name, {}).get("status") == "passed" for name in MANDATORY_LANES
    )
    supported = bool(
        tier.claim_eligible
        and fixture_exact
        and mandatory_passed
        and thresholds["passed"]
    )
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "policyVersion": POLICY_VERSION,
        "repository": {"root": str(ROOT), "sha": _repo_sha()},
        "tier": {
            "name": tier.name,
            "creators": tier.creators,
            "assets": tier.assets,
            "assetFiles": tier.asset_files,
            "claimEligible": tier.claim_eligible,
            "definitionFingerprint": definition_fingerprint,
        },
        "fixture": {
            "version": FIXTURE_VERSION,
            "fingerprint": fixture_fingerprint,
            "exact": fixture_exact,
            "actualCounts": fixture_counts,
            "runRoot": str(run_root),
        },
        "hardware": hardware_identity(),
        "toolchain": toolchain,
        "lanes": lanes,
        "thresholdEvaluation": thresholds,
        "resourceSummary": {
            "peakRssBytes": _rss_bytes(),
            "runBytes": sum(
                path.stat().st_size for path in run_root.rglob("*") if path.is_file()
            ),
            "freeBytesAfter": int(shutil.disk_usage(run_root).free),
        },
        "supportClaim": {
            "supported": supported,
            "largestSupportedTier": tier.name if supported else None,
            "inferred": False,
            "reason": (
                "exact_tier_all_mandatory_lanes_and_thresholds_passed"
                if supported
                else (
                    "smoke_profile_is_never_claim_eligible"
                    if tier.name == "smoke"
                    else "exact_tier_incomplete_or_threshold_failed"
                )
            ),
        },
        "externalEffects": {
            "paidProviderCalls": 0,
            "productionPathsTouched": False,
            "publishingEffects": 0,
        },
    }
    receipt["receiptFingerprint"] = _fingerprint(receipt)
    if capacity_claim_is_valid(receipt) != supported:
        receipt["supportClaim"]["supported"] = False
        receipt["supportClaim"]["largestSupportedTier"] = None
        receipt["supportClaim"]["reason"] = "claim_self_validation_failed"
        receipt["receiptFingerprint"] = _fingerprint(
            {
                key: value
                for key, value in receipt.items()
                if key != "receiptFingerprint"
            }
        )
    destination = (
        receipt_path.expanduser().resolve()
        if receipt_path is not None
        else run_root / "capacity-receipt.json"
    )
    atomic_write_json(destination, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=tuple(CAPACITY_TIERS), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = run_capacity_benchmark(
        tier_name=args.tier,
        workspace=args.workspace,
        receipt_path=args.receipt,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["supportClaim"]["supported"] or args.tier == "smoke" else 1


if __name__ == "__main__":
    raise SystemExit(main())
