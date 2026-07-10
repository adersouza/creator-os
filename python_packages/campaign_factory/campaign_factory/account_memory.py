from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)


class AccountMemoryRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
        json_load: Callable[[Any, Any], Any],
        sanitize_for_storage: Callable[[Any], Any],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        graph_id_for: Callable[..., str | None],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        account_reward_baselines: Callable[[list[dict[str, Any]]], dict[str, float]],
        aggregate_performance: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._json_load = json_load
        self._sanitize_for_storage = sanitize_for_storage
        self._campaign_by_slug = campaign_by_slug
        self._graph_id_for = graph_id_for
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._performance_snapshot_payload = performance_snapshot_payload
        self._account_reward_baselines = account_reward_baselines
        self._aggregate_performance = aggregate_performance
        self._performance_quality_score = performance_quality_score

    def rebuild_account_memory(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            rows = []
        else:
            rows = self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE campaign_id = ? AND "
                + learning_eligible_sql()
                + " ORDER BY snapshot_at DESC, created_at DESC",
                (campaign["id"], cutover_iso),
            ).fetchall()
        snapshots = [self._performance_snapshot_payload(dict(row)) for row in rows]
        by_account: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            account_id = (
                snapshot.get("instagramAccountId")
                or snapshot.get("accountId")
                or "unassigned"
            )
            by_account.setdefault(str(account_id), []).append(snapshot)
        accounts = sorted(by_account)
        account_baselines = self._account_reward_baselines(snapshots)
        now = self._utc_now()
        # This is a rebuild, not an incremental refresh. Remove memories and
        # derived pattern rows that no longer have learning-eligible evidence;
        # otherwise pre-cutover or fallback-only accounts would remain visible
        # after the shared predicate correctly excludes their source snapshots.
        self.conn.execute(
            "DELETE FROM account_pattern_stats WHERE campaign_id = ?",
            (campaign["id"],),
        )
        self.conn.execute(
            "DELETE FROM account_memory WHERE campaign_id = ?",
            (campaign["id"],),
        )
        for account_id in accounts:
            account_snapshots = by_account[account_id]
            aggregate = self._aggregate_performance(
                account_snapshots, account_baselines=account_baselines
            )
            performance_score = self._performance_quality_score(aggregate)
            pattern_stats = self.account_pattern_stats_from_snapshots(
                campaign["id"],
                account_id,
                account_snapshots,
                now,
                account_baselines=account_baselines,
            )
            posting_windows = self.account_posting_windows_from_snapshots(
                campaign["id"],
                account_id,
                account_snapshots,
                now,
                account_baselines=account_baselines,
            )
            fatigue = self.account_fatigue_from_pattern_stats(pattern_stats)
            outcomes = self.account_recommendation_outcomes(
                campaign["id"], account_id, now
            )
            confidence = self.account_memory_confidence(
                len(account_snapshots), outcomes
            )
            memory_key = f"{campaign['id']}:{account_id}"
            memory_id = (
                f"acctmem_{hashlib.sha256(memory_key.encode('utf-8')).hexdigest()[:12]}"
            )
            self.conn.execute(
                """
                INSERT INTO account_memory (
                  id, campaign_id, account_id, platform, sample_size, confidence, performance_score,
                  pattern_stats_json, posting_windows_json, fatigue_json, audience_notes_json,
                  recommendation_outcomes_json, updated_at
                )
                VALUES (?, ?, ?, 'instagram', ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                ON CONFLICT(campaign_id, account_id) DO UPDATE SET
                  sample_size = excluded.sample_size,
                  confidence = excluded.confidence,
                  performance_score = excluded.performance_score,
                  pattern_stats_json = excluded.pattern_stats_json,
                  posting_windows_json = excluded.posting_windows_json,
                  fatigue_json = excluded.fatigue_json,
                  recommendation_outcomes_json = excluded.recommendation_outcomes_json,
                  updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    campaign["id"],
                    account_id,
                    len(account_snapshots),
                    confidence,
                    performance_score,
                    json.dumps(
                        self._sanitize_for_storage(pattern_stats[:20]),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(posting_windows[:20]),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(fatigue),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(outcomes),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            memory_graph_id = self._ensure_graph_node(
                "account_memory",
                local_table="account_memory",
                local_id=memory_id,
                payload={
                    "campaign": campaign["slug"],
                    "accountId": account_id,
                    "sampleSize": len(account_snapshots),
                    "confidence": confidence,
                },
            )
            self._ensure_graph_edge(
                self._graph_id_for(
                    "campaigns",
                    campaign["id"],
                    entity_type="campaign",
                    payload={"slug": campaign["slug"]},
                ),
                memory_graph_id,
                "campaign_to_account_memory",
                evidence={"source": "rebuild_account_memory"},
            )
        self.conn.commit()
        return {
            "schema": "campaign_factory.account_memory_rebuild.v1",
            "campaign": campaign["slug"],
            "rebuiltAt": now,
            "accountCount": len(accounts),
            "snapshotCount": len(snapshots),
            "accounts": [
                self.account_memory_payload(dict(row))
                for row in self.conn.execute(
                    "SELECT * FROM account_memory WHERE campaign_id = ? ORDER BY account_id",
                    (campaign["id"],),
                ).fetchall()
            ],
        }

    def account_memory(
        self, campaign_slug: str, account: str | None = None
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        if account:
            rows = self.conn.execute(
                "SELECT * FROM account_memory WHERE campaign_id = ? AND account_id = ? ORDER BY updated_at DESC",
                (campaign["id"], account),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM account_memory WHERE campaign_id = ? ORDER BY account_id",
                (campaign["id"],),
            ).fetchall()
        memories = [self.account_memory_payload(dict(row)) for row in rows]
        return {
            "schema": "campaign_factory.account_memory.v1",
            "campaign": campaign["slug"],
            "account": account,
            "generatedAt": self._utc_now(),
            "accounts": memories,
            "warnings": [] if memories else ["account_memory_missing_or_not_rebuilt"],
        }

    def account_memory_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaignId": row["campaign_id"],
            "accountId": row["account_id"],
            "platform": row["platform"],
            "sampleSize": row["sample_size"],
            "confidence": row["confidence"],
            "performanceScore": row["performance_score"],
            "patternStats": self._json_load(row["pattern_stats_json"], []),
            "postingWindows": self._json_load(row["posting_windows_json"], []),
            "fatigue": self._json_load(row["fatigue_json"], {}),
            "audienceNotes": self._json_load(row["audience_notes_json"], {}),
            "recommendationOutcomes": self._json_load(
                row["recommendation_outcomes_json"], {}
            ),
            "updatedAt": row["updated_at"],
            "graphId": self._graph_id_for("account_memory", row["id"]),
        }

    def account_memory_for(
        self, campaign_id: str, account_id: str | None
    ) -> dict[str, Any] | None:
        if not account_id:
            return None
        row = self.conn.execute(
            "SELECT * FROM account_memory WHERE campaign_id = ? AND account_id = ?",
            (campaign_id, account_id),
        ).fetchone()
        return self.account_memory_payload(dict(row)) if row else None

    def account_pattern_stats_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for snapshot in snapshots:
            dimensions = snapshot.get("dimensions") or {}
            candidates: list[tuple[str, str, str | None]] = []
            if snapshot.get("recipe"):
                candidates.append(
                    ("recipe", str(snapshot["recipe"]), str(snapshot["recipe"]))
                )
            for key in (
                "hook",
                "audio",
                "referenceFormat",
                "promptPattern",
                "patternCard",
                "captionFormula",
                "modelAccount",
                "variationPreset",
            ):
                value = dimensions.get(key)
                if isinstance(value, dict) and value.get("key"):
                    candidates.append(
                        (
                            key,
                            str(value["key"]),
                            str(value.get("label") or value["key"]),
                        )
                    )
            for pattern_type, pattern_key, label in candidates:
                bucket = buckets.setdefault(
                    (pattern_type, pattern_key),
                    {
                        "patternType": pattern_type,
                        "patternKey": pattern_key,
                        "label": label,
                        "snapshots": [],
                    },
                )
                bucket["snapshots"].append(snapshot)
        stats = []
        for (pattern_type, pattern_key), bucket in buckets.items():
            aggregate = self._aggregate_performance(
                bucket["snapshots"], account_baselines=account_baselines
            )
            sample_size = int(aggregate.get("count") or 0)
            performance_score = self._performance_quality_score(aggregate)
            fatigue_score = min(
                100, round((sample_size / max(1, len(snapshots))) * 100)
            )
            stat = {
                "patternType": pattern_type,
                "patternKey": pattern_key,
                "label": bucket.get("label"),
                "sampleSize": sample_size,
                "performanceScore": performance_score,
                "fatigueScore": fatigue_score,
                "performance": aggregate,
            }
            stats.append(stat)
            stat_id = f"acctpat_{hashlib.sha256(f'{campaign_id}:{account_id}:{pattern_type}:{pattern_key}'.encode()).hexdigest()[:12]}"
            self.conn.execute(
                """
                INSERT INTO account_pattern_stats (
                  id, campaign_id, account_id, pattern_key, pattern_type, label,
                  sample_size, performance_score, fatigue_score, stats_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, account_id, pattern_type, pattern_key) DO UPDATE SET
                  label = excluded.label,
                  sample_size = excluded.sample_size,
                  performance_score = excluded.performance_score,
                  fatigue_score = excluded.fatigue_score,
                  stats_json = excluded.stats_json,
                  updated_at = excluded.updated_at
                """,
                (
                    stat_id,
                    campaign_id,
                    account_id,
                    pattern_key,
                    pattern_type,
                    bucket.get("label"),
                    sample_size,
                    performance_score,
                    fatigue_score,
                    json.dumps(
                        self._sanitize_for_storage(stat),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    updated_at,
                ),
            )
        stats.sort(
            key=lambda item: (
                item.get("performanceScore") or 0,
                item.get("sampleSize") or 0,
            ),
            reverse=True,
        )
        return stats

    def account_posting_windows_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            published_at = snapshot.get("publishedAt") or snapshot.get("snapshotAt")
            if not published_at:
                continue
            try:
                dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            buckets.setdefault((dt.weekday(), dt.hour), []).append(snapshot)
        windows = []
        for (weekday, hour), rows in buckets.items():
            aggregate = self._aggregate_performance(
                rows, account_baselines=account_baselines
            )
            score = self._performance_quality_score(aggregate)
            payload = {
                "weekday": weekday,
                "hour": hour,
                "sampleSize": len(rows),
                "performanceScore": score,
                "performance": aggregate,
            }
            windows.append(payload)
            window_id = f"acctwin_{hashlib.sha256(f'{campaign_id}:{account_id}:{weekday}:{hour}'.encode()).hexdigest()[:12]}"
            self.conn.execute(
                """
                INSERT INTO account_posting_windows (
                  id, campaign_id, account_id, weekday, hour, sample_size, performance_score, stats_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, account_id, weekday, hour) DO UPDATE SET
                  sample_size = excluded.sample_size,
                  performance_score = excluded.performance_score,
                  stats_json = excluded.stats_json,
                  updated_at = excluded.updated_at
                """,
                (
                    window_id,
                    campaign_id,
                    account_id,
                    weekday,
                    hour,
                    len(rows),
                    score,
                    json.dumps(
                        self._sanitize_for_storage(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    updated_at,
                ),
            )
        windows.sort(
            key=lambda item: (
                item.get("performanceScore") or 0,
                item.get("sampleSize") or 0,
            ),
            reverse=True,
        )
        return windows

    def account_fatigue_from_pattern_stats(
        self, pattern_stats: list[dict[str, Any]]
    ) -> dict[str, Any]:
        overused = [
            item
            for item in pattern_stats
            if int(item.get("sampleSize") or 0) >= 2
            and int(item.get("fatigueScore") or 0) >= 40
        ]
        max_score = max(
            [int(item.get("fatigueScore") or 0) for item in overused], default=0
        )
        if max_score >= 60:
            level = "high"
        elif max_score >= 40:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level,
            "score": max_score,
            "overusedPatterns": sorted(
                overused, key=lambda item: item.get("fatigueScore") or 0, reverse=True
            )[:10],
        }

    def account_recommendation_outcomes(
        self, campaign_id: str, account_id: str, updated_at: str
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT ri.*
            FROM recommendation_items ri
            JOIN recommendation_runs rr ON rr.id = ri.run_id
            WHERE rr.campaign_id = ?
              AND (ri.target_account = ? OR ri.target_account IS NULL)
              AND ri.status IN ('measured', 'proved', 'disproved')
            ORDER BY COALESCE(ri.measured_at, ri.created_at) DESC
            """,
            (campaign_id, account_id),
        ).fetchall()
        totals = {"measured": 0, "proved": 0, "disproved": 0}
        latest = []
        for row in rows:
            item = dict(row)
            status = item["status"]
            totals[status] = totals.get(status, 0) + 1
            outcome = self._json_load(item.get("outcome_json"), {})
            lift = None
            if (
                outcome.get("outcomeScore") is not None
                and outcome.get("baselineScore") is not None
            ):
                lift = int(outcome["outcomeScore"]) - int(outcome["baselineScore"])
            outcome_key = f"{campaign_id}:{account_id}:{item['id']}"
            outcome_id = f"acctout_{hashlib.sha256(outcome_key.encode('utf-8')).hexdigest()[:12]}"
            payload = {
                "recommendationItemId": item["id"],
                "status": status,
                "outcome": outcome,
                "baseline": self._json_load(item.get("baseline_json"), {}),
                "lift": lift,
            }
            self.conn.execute(
                """
                INSERT INTO account_recommendation_outcomes (
                  id, campaign_id, account_id, recommendation_item_id, status,
                  outcome_score, baseline_score, lift, payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, account_id, recommendation_item_id) DO UPDATE SET
                  status = excluded.status,
                  outcome_score = excluded.outcome_score,
                  baseline_score = excluded.baseline_score,
                  lift = excluded.lift,
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at
                """,
                (
                    outcome_id,
                    campaign_id,
                    account_id,
                    item["id"],
                    status,
                    outcome.get("outcomeScore"),
                    outcome.get("baselineScore"),
                    lift,
                    json.dumps(
                        self._sanitize_for_storage(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    updated_at,
                ),
            )
            latest.append(payload)
        measured_total = sum(totals.values())
        accuracy = (
            (totals["proved"] / (totals["proved"] + totals["disproved"]))
            if (totals["proved"] + totals["disproved"])
            else None
        )
        return {
            "counts": totals,
            "measuredTotal": measured_total,
            "proofAccuracy": accuracy,
            "latest": latest[:10],
        }

    def account_memory_confidence(
        self, sample_size: int, outcomes: dict[str, Any]
    ) -> str:
        measured = int(outcomes.get("measuredTotal") or 0)
        if sample_size >= 20 and measured >= 5:
            return "high"
        if sample_size >= 5 or measured >= 2:
            return "medium"
        return "low"
