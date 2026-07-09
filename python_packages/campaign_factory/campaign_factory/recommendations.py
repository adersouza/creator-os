from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)
from pipeline_contracts import validate_recommendation_next_batch

from .persistence import json_load

RECOMMENDATION_ITEM_STATUSES = {
    "proposed",
    "accepted",
    "rejected",
    "executed",
    "posted",
    "measured",
    "proved",
    "disproved",
}
RECOMMENDATION_STATUS_TRANSITIONS = {
    "proposed": {"accepted", "rejected"},
    "accepted": {"executed", "posted", "rejected"},
    "rejected": set(),
    "executed": {"posted", "measured", "proved", "disproved"},
    "posted": {"measured", "proved", "disproved"},
    "measured": {"proved", "disproved"},
    "proved": set(),
    "disproved": set(),
}
RECOMMENDATION_MEASUREMENT_VERSION = "recommendation_measurement.v1"
RECOMMENDATION_MEASUREMENT_THRESHOLD = 5
AUTONOMY_LEVELS = {"level_1", "level_2", "level_3"}
DEFAULT_AUTONOMY_LEVEL = "level_2"


class RecommendationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        graph_id_for: Callable[..., str | None],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        ensure_graph_edge_strict: Callable[..., str | None],
        record_event: Callable[..., dict[str, Any]],
        performance_summary: Callable[[str], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        active_reference_pattern_for_campaign: Callable[[str], dict[str, Any] | None],
        reference_pattern_payload: Callable[[dict[str, Any]], dict[str, Any]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        account_reward_baselines: Callable[[list[dict[str, Any]]], dict[str, float]],
        aggregate_performance: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
        performance_planning_score: Callable[[dict[str, Any]], int | None],
        rendered_asset: Callable[[str], dict[str, Any]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        assignments_for_asset: Callable[[str], list[dict[str, Any]]],
        account_memory_for: Callable[[str, str | None], dict[str, Any] | None],
        recommend_audio: Callable[..., dict[str, Any]],
        autonomy_level: Callable[[], str],
        create_exception: Callable[..., dict[str, Any]],
        exception_payload: Callable[[dict[str, Any]], dict[str, Any]],
        create_pipeline_job: Callable[..., dict[str, Any]],
        start_pipeline_job: Callable[[str], dict[str, Any]],
        finish_pipeline_job: Callable[..., dict[str, Any]],
        fail_pipeline_job: Callable[..., dict[str, Any]],
        prepare_reel_from_reference: Callable[..., dict[str, Any]],
        run_reel_factory: Callable[..., dict[str, Any]],
        sync_reel_outputs: Callable[..., dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self.campaign_by_slug = campaign_by_slug
        self.graph_id_for = graph_id_for
        self.ensure_graph_node = ensure_graph_node
        self.ensure_graph_edge = ensure_graph_edge
        self.ensure_graph_edge_strict = ensure_graph_edge_strict
        self.record_event = record_event
        self.performance_summary = performance_summary
        self.ranking = ranking
        self.active_reference_pattern_for_campaign = (
            active_reference_pattern_for_campaign
        )
        self._reference_pattern_payload = reference_pattern_payload
        self._performance_snapshot_payload = performance_snapshot_payload
        self._account_reward_baselines = account_reward_baselines
        self._aggregate_performance = aggregate_performance
        self._performance_quality_score = performance_quality_score
        self._performance_planning_score = performance_planning_score
        self.rendered_asset = rendered_asset
        self._dashboard_rendered_asset = dashboard_rendered_asset
        self.assignments_for_asset = assignments_for_asset
        self._account_memory_for = account_memory_for
        self.recommend_audio = recommend_audio
        self.autonomy_level = autonomy_level
        self.create_exception = create_exception
        self._exception_payload = exception_payload
        self.create_pipeline_job = create_pipeline_job
        self.start_pipeline_job = start_pipeline_job
        self.finish_pipeline_job = finish_pipeline_job
        self.fail_pipeline_job = fail_pipeline_job
        self.prepare_reel_from_reference = prepare_reel_from_reference
        self.run_reel_factory = run_reel_factory
        self.sync_reel_outputs = sync_reel_outputs

    def recommend_next_batch(
        self,
        campaign_slug: str,
        *,
        count: int = 20,
        account: str | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        campaign = self.campaign_by_slug(campaign_slug)
        campaign_graph_id = self.graph_id_for(
            "campaigns",
            campaign["id"],
            entity_type="campaign",
            payload={"slug": campaign["slug"], "platform": campaign["platform"]},
        )
        performance = self.performance_summary(campaign["slug"])
        ranking = self.ranking(campaign["slug"])
        reference_pattern_rankings = self.ranked_reference_patterns_for_campaign(
            campaign["id"]
        )
        reference_pattern = (
            reference_pattern_rankings[0]["pattern"]
            if reference_pattern_rankings
            else self.active_reference_pattern_for_campaign(campaign["id"])
            or self.top_reference_pattern()
        )
        variation_preset_rankings = self.ranked_variation_presets_for_campaign(
            campaign["id"], account=account
        )
        recommendation_trust = self.latest_recommendation_trust_context(
            campaign["id"], account=account
        )
        reference_pattern_id = (
            reference_pattern.get("id") if reference_pattern else None
        )
        reference_pattern_graph_id = (
            self.graph_id_for(
                "reference_patterns",
                reference_pattern_id,
                entity_type="reference_pattern",
                payload=reference_pattern,
            )
            if reference_pattern_id
            else None
        )
        candidates = self.account_ranked_candidates(
            ranking.get("assets") or [],
            account=account,
        )
        input_snapshot = {
            "schema": "campaign_factory.recommendations.input_snapshot.v1",
            "campaignId": campaign["id"],
            "campaign": campaign["slug"],
            "account": account,
            "count": max(1, int(count)),
            "scoringVersion": "recommendation_score.v1",
            "performanceSnapshotCount": performance.get("snapshotCount") or 0,
            "candidateRenderedAssetIds": [
                item.get("renderedAssetId") for item in candidates
            ],
            "referencePatternId": reference_pattern_id,
            "referencePatternRankings": self.compact_recommendation_rankings(
                reference_pattern_rankings
            ),
            "variationPresetRankings": self.compact_recommendation_rankings(
                variation_preset_rankings
            ),
            "recommendationTrust": recommendation_trust,
        }
        input_hash = hashlib.sha256(
            json.dumps(input_snapshot, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        run_id = f"recrun_{input_hash}"
        run_graph_id = None
        now = self._utc_now()
        if persist:
            row = self.conn.execute(
                "SELECT id FROM recommendation_runs WHERE campaign_id = ? AND scope = 'next_batch' AND input_hash = ?",
                (campaign["id"], input_hash),
            ).fetchone()
            run_id = row["id"] if row else run_id
            self.conn.execute(
                """
                INSERT INTO recommendation_runs (
                  id, campaign_id, scope, scoring_version, input_hash,
                  input_snapshot_json, created_at, updated_at
                )
                VALUES (?, ?, 'next_batch', 'recommendation_score.v1', ?, ?, ?, ?)
                ON CONFLICT(campaign_id, scope, input_hash) DO UPDATE SET
                  scoring_version = excluded.scoring_version,
                  input_snapshot_json = excluded.input_snapshot_json,
                  updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    campaign["id"],
                    input_hash,
                    json.dumps(
                        self._sanitize_for_storage(input_snapshot),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
            run_graph_id = self.ensure_graph_node(
                "recommendation_run",
                local_table="recommendation_runs",
                local_id=run_id,
                payload={
                    "campaign": campaign["slug"],
                    "inputHash": input_hash,
                    "scope": "next_batch",
                },
            )
            if campaign_graph_id:
                self.ensure_graph_edge(
                    campaign_graph_id,
                    run_graph_id,
                    "campaign_to_recommendation_run",
                    evidence={"source": "campaign_factory.recommend_next_batch"},
                )

        items = []
        warnings = []
        for rank, candidate in enumerate(candidates[: max(1, int(count))], start=1):
            asset = self.rendered_asset(candidate["renderedAssetId"])
            enriched = self._dashboard_rendered_asset(asset)
            item = self.recommendation_item_payload(
                campaign=campaign,
                campaign_graph_id=campaign_graph_id,
                run_graph_id=run_graph_id,
                rank=rank,
                account=account,
                candidate=candidate,
                asset=enriched,
                reference_pattern=reference_pattern,
                reference_pattern_graph_id=reference_pattern_graph_id,
                reference_pattern_rankings=reference_pattern_rankings,
                variation_preset_rankings=variation_preset_rankings,
                recommendation_trust=recommendation_trust,
                persist=persist,
                run_id=run_id,
            )
            items.append(item)
        if not items:
            warnings.append("no_rendered_assets_available")
            fallback = self.reference_only_recommendation_item(
                campaign=campaign,
                campaign_graph_id=campaign_graph_id,
                run_graph_id=run_graph_id,
                account=account,
                reference_pattern=reference_pattern,
                reference_pattern_graph_id=reference_pattern_graph_id,
                reference_pattern_rankings=reference_pattern_rankings,
                variation_preset_rankings=variation_preset_rankings,
                recommendation_trust=recommendation_trust,
                persist=persist,
                run_id=run_id,
            )
            if fallback:
                items.append(fallback)
        if persist:
            self.record_event(
                "recommendation_run_created",
                campaign_id=campaign["id"],
                status="success" if items else "warning",
                message=f"Recommended next batch for {campaign['slug']}",
                metadata={
                    "runId": run_id,
                    "itemCount": len(items),
                    "inputHash": input_hash,
                    "warnings": warnings,
                },
                commit=False,
            )
            self.conn.commit()
        plan = {
            "schema": "campaign_factory.recommendations.next_batch.v1",
            "campaign": campaign["slug"],
            "campaignGraphId": campaign_graph_id,
            "runId": run_id if persist else None,
            "runGraphId": run_graph_id,
            "persisted": bool(persist),
            "scoringVersion": "recommendation_score.v1",
            "generatedAt": now,
            "count": len(items),
            "requestedCount": max(1, int(count)),
            "account": account,
            "inputHash": input_hash,
            "warnings": warnings,
            "items": items,
        }
        validate_recommendation_next_batch(plan)
        return plan

    def account_ranked_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        account: str | None,
    ) -> list[dict[str, Any]]:
        if not account:
            return candidates
        return sorted(
            candidates,
            key=lambda candidate: (
                self.recommendation_account_score(
                    self.rendered_asset(candidate["renderedAssetId"]),
                    account,
                ),
                int(candidate.get("score") or 0),
            ),
            reverse=True,
        )

    def recommendation_runs(
        self, campaign_slug: str, *, limit: int = 10
    ) -> dict[str, Any]:
        campaign = self.campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            """
            SELECT * FROM recommendation_runs
            WHERE campaign_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (campaign["id"], max(1, min(int(limit), 100))),
        ).fetchall()
        runs = []
        for row in rows:
            items = self.conn.execute(
                "SELECT * FROM recommendation_items WHERE run_id = ? ORDER BY rank",
                (row["id"],),
            ).fetchall()
            runs.append(
                {
                    "id": row["id"],
                    "scope": row["scope"],
                    "scoringVersion": row["scoring_version"],
                    "inputHash": row["input_hash"],
                    "inputSnapshot": json_load(row["input_snapshot_json"], {}),
                    "runGraphId": self.graph_id_for("recommendation_runs", row["id"]),
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                    "items": [
                        self.stored_recommendation_item_payload(dict(item))
                        for item in items
                    ],
                }
            )
        return {
            "schema": "campaign_factory.recommendation_runs.v1",
            "campaign": campaign["slug"],
            "runs": runs,
        }

    def top_reference_pattern(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM reference_patterns ORDER BY COALESCE(rank, 999999), label LIMIT 1"
        ).fetchone()
        return self._reference_pattern_payload(dict(row)) if row else None

    def ranked_reference_patterns_for_campaign(
        self, campaign_id: str
    ) -> list[dict[str, Any]]:
        pattern_rows = self.conn.execute(
            "SELECT * FROM reference_patterns ORDER BY COALESCE(rank, 999999), label"
        ).fetchall()
        patterns = [self._reference_pattern_payload(dict(row)) for row in pattern_rows]
        if not patterns:
            return []
        pattern_by_key: dict[str, dict[str, Any]] = {}
        for pattern in patterns:
            keys = {
                pattern.get("id"),
                pattern.get("clusterKey"),
                pattern.get("label"),
                self._slugify(str(pattern.get("label") or "")),
            }
            for key in keys:
                if key:
                    pattern_by_key[str(key)] = pattern
                    pattern_by_key[self._slugify(str(key))] = pattern
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            rows = []
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM performance_snapshots
                WHERE campaign_id = ? AND {learning_eligible_sql()}
                ORDER BY snapshot_at DESC, created_at DESC
                """,
                (campaign_id, cutover_iso),
            ).fetchall()
        all_snapshots = [self._performance_snapshot_payload(dict(row)) for row in rows]
        account_baselines = self._account_reward_baselines(all_snapshots)
        buckets: dict[str, dict[str, Any]] = {}
        for snapshot in all_snapshots:
            dimensions = snapshot.get("dimensions") or {}
            candidate_keys: set[str] = set()
            for dimension_key in ("promptPattern", "patternCard", "hook"):
                dimension = dimensions.get(dimension_key)
                if not isinstance(dimension, dict):
                    continue
                for key_name in ("key", "label", "clusterKey", "patternCardId"):
                    value = dimension.get(key_name)
                    if value:
                        candidate_keys.add(str(value))
                        candidate_keys.add(self._slugify(str(value)))
            matched_patterns = {
                pattern_by_key[key]["id"]: pattern_by_key[key]
                for key in candidate_keys
                if key in pattern_by_key
            }
            for pattern_id, pattern in matched_patterns.items():
                bucket = buckets.setdefault(
                    pattern_id, {"pattern": pattern, "snapshots": {}}
                )
                bucket["snapshots"][snapshot["id"]] = snapshot
        rankings = []
        for bucket in buckets.values():
            snapshots = list(bucket["snapshots"].values())
            performance = self._aggregate_performance(
                snapshots, account_baselines=account_baselines
            )
            rankings.append(
                {
                    "pattern": bucket["pattern"],
                    "patternId": bucket["pattern"].get("id"),
                    "clusterKey": bucket["pattern"].get("clusterKey"),
                    "label": bucket["pattern"].get("label"),
                    "sampleSize": int(performance.get("count") or 0),
                    "performanceScore": self._performance_quality_score(performance),
                    "planningScore": self._performance_planning_score(performance),
                    "bandit": (performance.get("learning") or {}).get("bandit"),
                    "performance": performance,
                }
            )
        return sorted(
            rankings,
            key=lambda item: (
                -(
                    item["planningScore"]
                    if item.get("planningScore") is not None
                    else -1
                ),
                -(
                    item["performanceScore"]
                    if item.get("performanceScore") is not None
                    else -1
                ),
                -int(item.get("sampleSize") or 0),
                int((item.get("pattern") or {}).get("rank") or 999999),
                str(item.get("label") or ""),
            ),
        )

    def ranked_variation_presets_for_campaign(
        self, campaign_id: str, *, account: str | None = None
    ) -> list[dict[str, Any]]:
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            rows = []
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM performance_snapshots
                WHERE campaign_id = ? AND {learning_eligible_sql()}
                ORDER BY snapshot_at DESC, created_at DESC
                """,
                (campaign_id, cutover_iso),
            ).fetchall()
        all_snapshots = [self._performance_snapshot_payload(dict(row)) for row in rows]
        account_baselines = self._account_reward_baselines(all_snapshots)
        buckets: dict[str, list[dict[str, Any]]] = {}
        for snapshot in all_snapshots:
            if account and account not in {
                snapshot.get("instagramAccountId"),
                snapshot.get("accountId"),
            }:
                continue
            preset = (snapshot.get("dimensions") or {}).get("variationPreset")
            if not isinstance(preset, dict) or not preset.get("key"):
                continue
            buckets.setdefault(str(preset["key"]), []).append(snapshot)
        rankings = []
        for preset_name, snapshots in buckets.items():
            performance = self._aggregate_performance(
                snapshots, account_baselines=account_baselines
            )
            latest = snapshots[0]
            preset = (latest.get("dimensions") or {}).get("variationPreset") or {}
            rankings.append(
                {
                    "presetName": preset_name,
                    "label": preset.get("label") or preset_name,
                    "sampleSize": int(performance.get("count") or 0),
                    "performanceScore": self._performance_quality_score(performance),
                    "planningScore": self._performance_planning_score(performance),
                    "bandit": (performance.get("learning") or {}).get("bandit"),
                    "performance": performance,
                }
            )
        return sorted(
            rankings,
            key=lambda item: (
                -(
                    item["planningScore"]
                    if item.get("planningScore") is not None
                    else -1
                ),
                -(
                    item["performanceScore"]
                    if item.get("performanceScore") is not None
                    else -1
                ),
                -int(item.get("sampleSize") or 0),
                str(item.get("presetName") or ""),
            ),
        )

    def compact_recommendation_rankings(
        self, rankings: list[dict[str, Any]], *, limit: int = 5
    ) -> list[dict[str, Any]]:
        compact = []
        for item in rankings[:limit]:
            row = {
                key: item.get(key)
                for key in (
                    "patternId",
                    "clusterKey",
                    "presetName",
                    "label",
                    "sampleSize",
                    "performanceScore",
                    "planningScore",
                    "bandit",
                )
                if item.get(key) is not None
            }
            learning = (item.get("performance") or {}).get("learning") or {}
            if learning:
                row["learning"] = learning
            compact.append(row)
        return compact

    def recommendation_reference_pattern_evidence(
        self,
        rankings: list[dict[str, Any]],
        selected_pattern: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "selectedPatternId": (selected_pattern or {}).get("id"),
            "selectedClusterKey": (selected_pattern or {}).get("clusterKey"),
            "selectionSource": "performance_snapshots"
            if rankings
            else "active_or_static_fallback",
            "rankings": self.compact_recommendation_rankings(rankings),
        }

    def recommendation_variation_preset_evidence(
        self,
        rankings: list[dict[str, Any]],
        selected_preset: str | None,
    ) -> dict[str, Any]:
        return {
            "selectedPresetName": selected_preset,
            "selectionSource": "performance_snapshots"
            if rankings
            else "default_fallback",
            "rankings": self.compact_recommendation_rankings(rankings),
        }

    def latest_recommendation_trust_context(
        self, campaign_id: str, *, account: str | None
    ) -> dict[str, Any]:
        account_key = account or ""
        row = self.conn.execute(
            """
            SELECT * FROM recommendation_accuracy_reports
            WHERE campaign_id = ?
              AND account_key IN (?, '')
            ORDER BY CASE WHEN account_key = ? THEN 0 ELSE 1 END, updated_at DESC
            LIMIT 1
            """,
            (campaign_id, account_key, account_key),
        ).fetchone()
        if not row:
            return {
                "status": "unmeasured",
                "score": None,
                "trustConfidence": "insufficient",
                "measuredCount": 0,
                "source": "no_recommendation_accuracy_report",
            }
        payload = json_load(row["report_json"], {})
        overall = (
            payload.get("overall") if isinstance(payload.get("overall"), dict) else {}
        )
        score = payload.get("recommendationTrustScore")
        score_int = int(score) if isinstance(score, (int, float)) else None
        if score_int is None:
            status = "unmeasured"
        elif score_int < 50:
            status = "low"
        elif score_int < 70:
            status = "directional"
        else:
            status = "trusted"
        return {
            "status": status,
            "score": score_int,
            "trustConfidence": payload.get("trustConfidence") or "insufficient",
            "measuredCount": int(overall.get("measuredCount") or 0),
            "accuracyRate": overall.get("accuracyRate"),
            "reportId": payload.get("reportId") or row["id"],
            "reportGraphId": payload.get("reportGraphId"),
            "accountScope": row["account_key"] or "all_accounts",
            "windowDays": row["window_days"],
            "updatedAt": row["updated_at"],
            "source": "recommendation_accuracy_report",
        }

    def apply_recommendation_trust(
        self,
        *,
        score: int | float,
        confidence: str,
        confidence_reason: str,
        recommendation_trust: dict[str, Any],
    ) -> tuple[int, str, str, list[str]]:
        trust_score = recommendation_trust.get("score")
        if not isinstance(trust_score, int):
            return (
                int(max(0, min(100, round(score)))),
                confidence,
                confidence_reason,
                [],
            )
        risks = []
        adjusted_score = int(max(0, min(100, round(score))))
        adjusted_confidence = confidence
        adjusted_reason = confidence_reason
        if trust_score < 50:
            risks.append("low_recommendation_trust")
            adjusted_score = min(adjusted_score, max(25, trust_score + 20))
            adjusted_confidence = "low"
            adjusted_reason = f"{confidence_reason}; recommendation trust score {trust_score} is low from measured outcomes"
        elif trust_score < 70 and adjusted_confidence == "high":
            risks.append("directional_recommendation_trust")
            adjusted_score = min(adjusted_score, trust_score + 15)
            adjusted_confidence = "medium"
            adjusted_reason = f"{confidence_reason}; recommendation trust score {trust_score} is directional"
        return adjusted_score, adjusted_confidence, adjusted_reason, risks

    def recommendation_item_payload(
        self,
        *,
        campaign: dict[str, Any],
        campaign_graph_id: str | None,
        run_graph_id: str | None,
        rank: int,
        account: str | None,
        candidate: dict[str, Any],
        asset: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
        reference_pattern_graph_id: str | None,
        reference_pattern_rankings: list[dict[str, Any]],
        variation_preset_rankings: list[dict[str, Any]],
        recommendation_trust: dict[str, Any],
        persist: bool,
        run_id: str,
    ) -> dict[str, Any]:
        breakdown = candidate.get("breakdown") or {}
        performance_score = int(
            asset.get("performanceScore") or self.best_asset_history_score(asset) or 50
        )
        reference_score = self.reference_pattern_score(reference_pattern)
        audit_score = int(breakdown.get("quality") or 50)
        account_score = self.recommendation_account_score(asset, account)
        account_fit_evidence = self.recommendation_account_fit_evidence(
            campaign["id"], asset, account
        )
        novelty_score = int(breakdown.get("novelty") or 50)
        operational_score = self.operational_recommendation_score(asset)
        score = round(
            performance_score * 0.40
            + reference_score * 0.20
            + audit_score * 0.15
            + account_score * 0.10
            + novelty_score * 0.10
            + operational_score * 0.05
        )
        readiness = asset.get("export_readiness") or {}
        risks = list(candidate.get("blockingReasons") or []) + list(
            candidate.get("warnings") or []
        )
        if readiness.get("state") == "blocked":
            score = min(score, 45)
        confidence, confidence_reason = self.recommendation_confidence(
            asset, reference_pattern
        )
        score, confidence, confidence_reason, trust_risks = (
            self.apply_recommendation_trust(
                score=score,
                confidence=confidence,
                confidence_reason=confidence_reason,
                recommendation_trust=recommendation_trust,
            )
        )
        risks.extend(trust_risks)
        data_quality = self.recommendation_data_quality(asset, reference_pattern)
        account_memory_payload = account_fit_evidence.get("memory")
        recommended_variation_preset = (
            variation_preset_rankings[0].get("presetName")
            if variation_preset_rankings
            else "ig_subtle"
        )
        reference_pattern_evidence = self.recommendation_reference_pattern_evidence(
            reference_pattern_rankings, reference_pattern
        )
        variation_preset_evidence = self.recommendation_variation_preset_evidence(
            variation_preset_rankings, recommended_variation_preset
        )
        readiness_evidence = self.recommendation_readiness_evidence(
            asset, account=account
        )
        reasons = self.recommendation_reasons(
            performance_score=performance_score,
            reference_score=reference_score,
            audit_score=audit_score,
            account_score=account_score,
            novelty_score=novelty_score,
            operational_score=operational_score,
            candidate=candidate,
            reference_pattern=reference_pattern,
        )
        source_graph_id = self.graph_id_for(
            "source_assets", asset.get("source_asset_id"), entity_type="source_asset"
        )
        rendered_graph_id = self.graph_id_for(
            "rendered_assets", asset.get("id"), entity_type="rendered_asset"
        )
        latest_performance = asset.get("latestPerformance") or {}
        performance_graph_id = None
        recommendation_input_graph_id = None
        if latest_performance.get("id"):
            performance_graph_id = self.ensure_graph_node(
                "performance_snapshot",
                local_table="performance_snapshots",
                local_id=latest_performance["id"],
                payload=latest_performance,
            )
            recommendation_input_graph_id = self.ensure_graph_node(
                "recommendation_input",
                external_system="campaign_factory.recommendation_input",
                external_id=f"recommendation_input:{latest_performance['id']}",
                payload={
                    "performanceSnapshotId": latest_performance["id"],
                    "campaign": campaign["slug"],
                },
            )
        graph_evidence = {
            "campaignGraphId": campaign_graph_id,
            "runGraphId": run_graph_id,
            "referencePatternGraphId": reference_pattern_graph_id,
            "sourceAssetGraphId": source_graph_id,
            "renderedAssetGraphId": rendered_graph_id,
            "performanceSnapshotGraphId": performance_graph_id,
            "recommendationInputGraphId": recommendation_input_graph_id,
        }
        evidence = {
            "graph": graph_evidence,
            "reasons": reasons,
            "risks": sorted(set(str(risk) for risk in risks if risk)),
            "recommendationTrust": recommendation_trust,
            "accountFit": account_fit_evidence,
            "readiness": readiness_evidence,
            "referencePatternRankings": reference_pattern_evidence,
            "variationPresetRankings": variation_preset_evidence,
            "scores": {
                "performance": performance_score,
                "referencePattern": reference_score,
                "auditReadiness": audit_score,
                "accountFitFatigue": account_score,
                "novelty": novelty_score,
                "operationalReadiness": operational_score,
                "recommendationTrust": recommendation_trust.get("score"),
            },
        }
        item_key = f"{run_id}:{rank}:{asset.get('id')}"
        item_id = f"recitem_{hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:12]}"
        audio_context_tags = [
            (reference_pattern or {}).get("visualFormat"),
            (reference_pattern or {}).get("hookType"),
            (reference_pattern or {}).get("captionArchetype"),
            asset.get("recipe"),
        ]
        audio_recommendations = self.recommend_audio(
            platform=campaign.get("platform") or "instagram",
            campaign_slug=campaign.get("slug"),
            recommendation_item_id=None,
            content_tags=[str(tag) for tag in audio_context_tags if tag],
            account_tags=[
                str(tag) for tag in [account or self.asset_target_account(asset)] if tag
            ],
            account=account or self.asset_target_account(asset),
            limit=5,
        )
        selected_audio = self.selected_audio_from_asset(asset)
        audio_selection_status = self.recommendation_audio_selection_status(
            selected_audio=selected_audio,
            audio_recommendations=audio_recommendations,
        )
        audio_memory_evidence = {
            "recommendationCount": len(
                audio_recommendations.get("recommendations") or []
            ),
            "topAudioMemoryGraphIds": [
                item.get("audioMemoryGraphId")
                for item in (audio_recommendations.get("recommendations") or [])[:3]
                if item.get("audioMemoryGraphId")
            ],
        }
        target_account = account or self.asset_target_account(asset)
        caption = self.caption_guidance(reference_pattern, asset)
        decision_evidence = self.recommendation_decision_evidence(
            target_account=target_account,
            account_score=account_score,
            account_fit_evidence=account_fit_evidence,
            performance_score=performance_score,
            data_quality=data_quality,
            latest_performance=latest_performance,
            recommendation_trust=recommendation_trust,
            trust_risks=trust_risks,
            audio_recommendations=audio_recommendations,
            caption_guidance=caption,
            readiness_evidence=readiness_evidence,
            recommended_variation_preset=recommended_variation_preset,
            selected_audio=selected_audio,
            audio_selection_status=audio_selection_status,
            reasons=reasons,
            risks=sorted(set(str(risk) for risk in risks if risk)),
        )
        evidence["decision"] = decision_evidence
        recommendation_graph_id = None
        output = {
            "recommendationId": item_id,
            "recommendationGraphId": None,
            "status": "proposed",
            "campaignGraphId": campaign_graph_id,
            "referencePatternGraphId": reference_pattern_graph_id,
            "sourceAssetGraphId": source_graph_id,
            "renderedAssetGraphId": rendered_graph_id,
            "rank": rank,
            "score": int(max(0, min(100, score))),
            "confidence": confidence,
            "confidenceReason": confidence_reason,
            "autonomyLevel": self.autonomy_level(),
            "executionStatus": "not_started",
            "targetAccount": target_account,
            "renderedAssetId": asset.get("id"),
            "filename": asset.get("filename"),
            "referencePatternId": reference_pattern.get("id")
            if reference_pattern
            else None,
            "referencePattern": self.recommendation_reference_summary(
                reference_pattern
            ),
            "referencePatternEvidence": reference_pattern_evidence,
            "recommendedVariationPreset": recommended_variation_preset,
            "variationPresetEvidence": variation_preset_evidence,
            "readinessEvidence": readiness_evidence,
            "suggestedRecipe": asset.get("recipe")
            or self.first_suggested_recipe(reference_pattern),
            "hookGuidance": self.hook_guidance(reference_pattern, asset),
            "captionGuidance": caption,
            "audioRecommendations": audio_recommendations,
            "audioDecision": audio_recommendations.get("decision") or {},
            "audioMemoryEvidence": audio_memory_evidence,
            "decisionEvidence": decision_evidence,
            "selectedAudio": selected_audio,
            "audioSelectionStatus": audio_selection_status,
            "reasons": reasons,
            "risks": sorted(set(str(risk) for risk in risks if risk)),
            "scoreBreakdown": {
                "performance": performance_score,
                "referencePattern": reference_score,
                "auditReadiness": audit_score,
                "accountFitFatigue": account_score,
                "novelty": novelty_score,
                "operationalReadiness": operational_score,
                "recommendationTrust": recommendation_trust.get("score"),
            },
            "evidence": evidence,
            "dataQuality": data_quality,
            "accountMemory": account_memory_payload,
            "accountFitEvidence": account_fit_evidence,
            "decision": {},
            "outcome": {},
            "baseline": {},
            "exceptions": [],
            "measurementVersion": None,
            "acceptedAt": None,
            "rejectedAt": None,
            "executedAt": None,
            "postedAt": None,
            "measuredAt": None,
            "graphEvidence": graph_evidence,
        }
        if persist:
            recommendation_graph_id = self.ensure_graph_node(
                "recommendation_item",
                local_table="recommendation_items",
                local_id=item_id,
                payload={
                    key: value
                    for key, value in output.items()
                    if key != "recommendationGraphId"
                },
            )
            output["recommendationGraphId"] = recommendation_graph_id
            self.conn.execute(
                """
                INSERT INTO recommendation_items (
                  id, run_id, rank, target_account, reference_pattern_id, source_asset_id,
                  rendered_asset_id, recommendation_graph_id, status, score, confidence,
                  reasons_json, risks_json, evidence_json, data_quality_json, decision_json,
                  outcome_json, baseline_json, measurement_version, output_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', NULL, ?, ?)
                ON CONFLICT(run_id, rank) DO UPDATE SET
                  target_account = excluded.target_account,
                  reference_pattern_id = excluded.reference_pattern_id,
                  source_asset_id = excluded.source_asset_id,
                  rendered_asset_id = excluded.rendered_asset_id,
                  recommendation_graph_id = excluded.recommendation_graph_id,
                  score = excluded.score,
                  confidence = excluded.confidence,
                  reasons_json = excluded.reasons_json,
                  risks_json = excluded.risks_json,
                  evidence_json = excluded.evidence_json,
                  data_quality_json = excluded.data_quality_json,
                  output_json = excluded.output_json
                """,
                (
                    item_id,
                    run_id,
                    rank,
                    output["targetAccount"],
                    output["referencePatternId"],
                    asset.get("source_asset_id"),
                    asset.get("id"),
                    recommendation_graph_id,
                    output["score"],
                    confidence,
                    json.dumps(reasons, ensure_ascii=False, sort_keys=True),
                    json.dumps(output["risks"], ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        self._sanitize_for_storage(evidence),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(data_quality),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(output),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    self._utc_now(),
                ),
            )
            self.write_recommendation_graph_edges(
                performance_graph_id=performance_graph_id,
                recommendation_input_graph_id=recommendation_input_graph_id,
                run_graph_id=run_graph_id,
                item_graph_id=recommendation_graph_id,
                rendered_graph_id=rendered_graph_id,
                reference_pattern_graph_id=reference_pattern_graph_id,
            )
            self.write_audio_recommendation_graph_edges(
                recommendation_item_id=item_id,
                recommendation_graph_id=recommendation_graph_id,
                reference_pattern_graph_id=reference_pattern_graph_id,
                audio_recommendations=audio_recommendations,
                campaign_id=campaign["id"],
            )
        return output

    def recommendation_decision_evidence(
        self,
        *,
        target_account: str | None,
        account_score: int,
        account_fit_evidence: dict[str, Any],
        performance_score: int,
        data_quality: dict[str, Any],
        latest_performance: dict[str, Any],
        recommendation_trust: dict[str, Any],
        trust_risks: list[str],
        audio_recommendations: dict[str, Any],
        caption_guidance: str,
        readiness_evidence: dict[str, Any],
        recommended_variation_preset: str | None,
        selected_audio: dict[str, Any] | None = None,
        audio_selection_status: str | None = None,
        reasons: list[str] | None = None,
        risks: list[str] | None = None,
    ) -> dict[str, Any]:
        recommendations = audio_recommendations.get("recommendations") or []
        audio_decision = (
            audio_recommendations.get("decision")
            if isinstance(audio_recommendations.get("decision"), dict)
            else {}
        )
        status = audio_selection_status or (
            "recommended" if recommendations else "needs_operator_selection"
        )
        readiness_decision = self.recommendation_readiness_decision_evidence(
            readiness_evidence
        )
        learning_evidence = self.recommendation_learning_evidence(
            performance_score=performance_score,
            data_quality=data_quality,
            latest_performance=latest_performance,
            recommendation_trust=recommendation_trust,
            trust_risks=trust_risks,
        )
        audio_evidence = {
            "status": status,
            "selectedAudio": selected_audio,
            "primaryAudio": selected_audio
            or audio_decision.get("primaryAudio")
            or (recommendations[0] if recommendations else None),
            "recommendationCount": len(recommendations),
            "decisionConfidence": audio_decision.get("decisionConfidence"),
        }
        caption_evidence = {
            "guidance": caption_guidance,
            "captionHash": readiness_evidence.get("captionHash"),
            **self.recommendation_caption_evidence(readiness_evidence),
        }
        variation_safety = self.recommendation_variation_safety_evidence(
            readiness_evidence
        )
        variation_evidence = {
            "preset": recommended_variation_preset,
            "safety": variation_safety,
        }
        quality_evidence = self.recommendation_quality_evidence(readiness_evidence)
        why_now = self.recommendation_why_now_evidence(
            readiness_decision=readiness_decision,
            reasons=reasons or [],
            risks=risks or [],
        )
        return {
            "targetAccount": target_account,
            "account": {
                "score": account_score,
                "fitLevel": account_fit_evidence.get("level"),
                "reasons": account_fit_evidence.get("reasons") or [],
            },
            "learning": learning_evidence,
            "audio": audio_evidence,
            "caption": caption_evidence,
            "variation": variation_evidence,
            "quality": quality_evidence,
            "readiness": readiness_decision,
            "whyNow": why_now,
            "proofChecklist": self.recommendation_proof_checklist(
                account_score=account_score,
                account_fit_evidence=account_fit_evidence,
                learning_evidence=learning_evidence,
                audio_evidence=audio_evidence,
                caption_evidence=caption_evidence,
                variation_safety=variation_safety,
                quality_evidence=quality_evidence,
                readiness_decision=readiness_decision,
            ),
        }

    def recommendation_learning_evidence(
        self,
        *,
        performance_score: int,
        data_quality: dict[str, Any],
        latest_performance: dict[str, Any],
        recommendation_trust: dict[str, Any],
        trust_risks: list[str],
    ) -> dict[str, Any]:
        return {
            "performanceScore": performance_score,
            "latestPerformanceSnapshotId": latest_performance.get("id"),
            "dataQuality": {
                "level": data_quality.get("level"),
                "sampleSize": data_quality.get("sampleSize", 0),
                "missing": data_quality.get("missing") or [],
            },
            "recommendationTrust": {
                "status": recommendation_trust.get("status"),
                "score": recommendation_trust.get("score"),
                "measuredCount": recommendation_trust.get("measuredCount"),
                "source": recommendation_trust.get("source"),
            },
            "trustRisk": trust_risks[0] if trust_risks else None,
        }

    def recommendation_caption_evidence(
        self, readiness_evidence: dict[str, Any]
    ) -> dict[str, Any]:
        failure_reasons = [
            str(reason)
            for reason in readiness_evidence.get("publishabilityFailureReasons") or []
            if reason
        ]
        caption_reasons = [
            reason
            for reason in failure_reasons
            if self.recommendation_quality_failure_category(reason) == "caption"
        ]
        return {
            "status": "blocked" if caption_reasons else "ready",
            "blockingReasons": caption_reasons,
        }

    def recommendation_quality_evidence(
        self, readiness_evidence: dict[str, Any]
    ) -> dict[str, Any]:
        failure_reasons = [
            str(reason)
            for reason in readiness_evidence.get("publishabilityFailureReasons") or []
            if reason
        ]
        categories = sorted(
            {
                self.recommendation_quality_failure_category(reason)
                for reason in failure_reasons
            }
        )
        return {
            "status": "blocked" if failure_reasons else "passed",
            "blockingCategories": categories,
            "failureReasons": failure_reasons,
            "operatorScore": readiness_evidence.get("operatorScore"),
        }

    def recommendation_variation_safety_evidence(
        self, readiness_evidence: dict[str, Any]
    ) -> dict[str, Any]:
        failure_reasons = [
            str(reason)
            for reason in readiness_evidence.get("publishabilityFailureReasons") or []
            if reason
        ]
        safety_reasons = [
            reason
            for reason in failure_reasons
            if self.recommendation_quality_failure_category(reason) == "safety"
        ]
        return {
            "status": "blocked" if safety_reasons else "clear",
            "blockingReasons": safety_reasons,
            "authoritativeGate": "pdq_sscd_for_fanout",
            "ssimRole": "diagnostic_only",
        }

    def recommendation_readiness_decision_evidence(
        self, readiness_evidence: dict[str, Any]
    ) -> dict[str, Any]:
        blocking_reasons = [
            str(reason)
            for reason in readiness_evidence.get("blockingReasons") or []
            if reason
        ]
        failure_reasons = [
            str(reason)
            for reason in readiness_evidence.get("publishabilityFailureReasons") or []
            if reason
        ]
        blocked = bool(
            blocking_reasons
            or failure_reasons
            or readiness_evidence.get("state") == "blocked"
        )
        if "missing_rendered_assets" in blocking_reasons:
            next_action = "make_or_register_rendered_asset"
        elif blocking_reasons:
            next_action = "resolve_readiness_blockers"
        elif failure_reasons:
            next_action = "resolve_publishability_failures"
        else:
            next_action = "ready_for_operator_export_review"
        return {
            "state": readiness_evidence.get("state"),
            "verdict": "blocked" if blocked else "ready",
            "nextAction": next_action,
            "operatorScore": readiness_evidence.get("operatorScore"),
            "contentSurface": readiness_evidence.get("contentSurface"),
            "reviewState": readiness_evidence.get("reviewState"),
            "auditStatus": readiness_evidence.get("auditStatus"),
            "latestAuditVerdict": readiness_evidence.get("latestAuditVerdict"),
            "blockingReasons": blocking_reasons,
            "publishabilityFailureReasons": failure_reasons,
        }

    def recommendation_why_now_evidence(
        self,
        *,
        readiness_decision: dict[str, Any],
        reasons: list[str],
        risks: list[str],
    ) -> dict[str, Any]:
        return {
            "status": readiness_decision.get("verdict"),
            "nextAction": readiness_decision.get("nextAction"),
            "reasons": reasons,
            "risks": risks,
        }

    def recommendation_proof_checklist(
        self,
        *,
        account_score: int,
        account_fit_evidence: dict[str, Any],
        learning_evidence: dict[str, Any],
        audio_evidence: dict[str, Any],
        caption_evidence: dict[str, Any],
        variation_safety: dict[str, Any],
        quality_evidence: dict[str, Any],
        readiness_decision: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "accountFit": {
                "status": account_fit_evidence.get("level"),
                "score": account_score,
            },
            "learning": {
                "status": (learning_evidence.get("dataQuality") or {}).get("level"),
                "sampleSize": (learning_evidence.get("dataQuality") or {}).get(
                    "sampleSize", 0
                ),
                "latestPerformanceSnapshotId": learning_evidence.get(
                    "latestPerformanceSnapshotId"
                ),
            },
            "audio": {
                "status": audio_evidence.get("status"),
                "hasPrimaryAudio": bool(audio_evidence.get("primaryAudio")),
            },
            "caption": {
                "status": caption_evidence.get("status"),
                "hasCaptionHash": bool(caption_evidence.get("captionHash")),
            },
            "quality": {
                "status": quality_evidence.get("status"),
                "blockingCount": len(quality_evidence.get("failureReasons") or []),
            },
            "variationSafety": {
                "status": variation_safety.get("status"),
                "blockingCount": len(variation_safety.get("blockingReasons") or []),
            },
            "readiness": {
                "status": readiness_decision.get("verdict"),
                "nextAction": readiness_decision.get("nextAction"),
                "blockingCount": len(readiness_decision.get("blockingReasons") or [])
                + len(readiness_decision.get("publishabilityFailureReasons") or []),
            },
        }

    def recommendation_quality_failure_category(self, reason: str) -> str:
        lowered = reason.lower()
        if "audio" in lowered:
            return "audio"
        if "caption" in lowered:
            return "caption"
        if "visual" in lowered or "identity" in lowered or "wrong_visual" in lowered:
            return "visual"
        if "fingerprint" in lowered or "duplicate" in lowered:
            return "safety"
        if "approval" in lowered or "review" in lowered or "readiness" in lowered:
            return "review"
        return "quality"

    def selected_audio_from_asset(self, asset: dict[str, Any]) -> dict[str, Any] | None:
        caption_generation = (
            asset.get("captionGeneration")
            if isinstance(asset.get("captionGeneration"), dict)
            else {}
        )
        audio_intent = (
            caption_generation.get("audioIntent")
            or caption_generation.get("audio_intent")
            or {}
        )
        if not isinstance(audio_intent, dict):
            return None
        status = str(audio_intent.get("status") or "").strip().lower()
        if status not in {"selected", "attached", "verified"}:
            return None
        selection = (
            audio_intent.get("operator_selection")
            or audio_intent.get("operatorSelection")
            or {}
        )
        if not isinstance(selection, dict):
            return None
        audio_id = (
            selection.get("audio_id")
            or selection.get("platform_audio_id")
            or selection.get("audioId")
            or selection.get("platformAudioId")
        )
        if not audio_id:
            return None
        return {
            "audioId": str(audio_id),
            "audioTitle": selection.get("audio_title")
            or selection.get("title")
            or selection.get("audioTitle"),
            "audioArtist": selection.get("audio_artist")
            or selection.get("artist")
            or selection.get("audioArtist"),
            "audioType": selection.get("audio_type")
            or selection.get("type")
            or selection.get("audioType"),
            "status": status,
            "selectionSource": selection.get("selection_source")
            or selection.get("selectionSource"),
            "selectedAt": selection.get("selected_at") or selection.get("selectedAt"),
            "attachedAt": selection.get("attached_at") or selection.get("attachedAt"),
            "verifiedAt": selection.get("verified_at") or selection.get("verifiedAt"),
        }

    def recommendation_audio_selection_status(
        self,
        *,
        selected_audio: dict[str, Any] | None,
        audio_recommendations: dict[str, Any],
    ) -> str:
        if selected_audio:
            return str(selected_audio.get("status") or "selected")
        return (
            "recommended"
            if audio_recommendations.get("recommendations")
            else "needs_operator_selection"
        )

    def recommendation_readiness_evidence(
        self, asset: dict[str, Any], *, account: str | None
    ) -> dict[str, Any]:
        readiness = asset.get("export_readiness") or {}
        publishability = (
            readiness.get("publishability")
            if isinstance(readiness.get("publishability"), dict)
            else {}
        )
        audio_intent = (
            publishability.get("audioIntent")
            if isinstance(publishability.get("audioIntent"), dict)
            else {}
        )
        latest_audit = (
            asset.get("latest_audit")
            if isinstance(asset.get("latest_audit"), dict)
            else {}
        )
        return {
            "state": readiness.get("state") or "unknown",
            "operatorScore": int(readiness.get("operatorScore") or 0),
            "blockingReasons": readiness.get("blockingReasons") or [],
            "warnings": readiness.get("warnings") or [],
            "publishabilityFailureReasons": publishability.get("failureReasons")
            or publishability.get("publishability_failure_reasons")
            or [],
            "reviewState": asset.get("review_state"),
            "auditStatus": asset.get("audit_status"),
            "contentSurface": publishability.get("contentSurface")
            or publishability.get("content_surface")
            or asset.get("content_surface"),
            "audioStatus": audio_intent.get("status"),
            "captionHash": asset.get("captionHash") or asset.get("caption_hash"),
            "targetAccount": account or self.asset_target_account(asset),
            "latestAuditId": latest_audit.get("id"),
            "latestAuditVerdict": latest_audit.get("overallVerdict"),
        }

    def reference_only_recommendation_item(
        self,
        *,
        campaign: dict[str, Any],
        campaign_graph_id: str | None,
        run_graph_id: str | None,
        account: str | None,
        reference_pattern: dict[str, Any] | None,
        reference_pattern_graph_id: str | None,
        reference_pattern_rankings: list[dict[str, Any]],
        variation_preset_rankings: list[dict[str, Any]],
        recommendation_trust: dict[str, Any],
        persist: bool,
        run_id: str,
    ) -> dict[str, Any] | None:
        if not reference_pattern:
            return None
        item_key = f"{run_id}:reference_only:{reference_pattern.get('id')}"
        item_id = f"recitem_{hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:12]}"
        recommended_variation_preset = (
            variation_preset_rankings[0].get("presetName")
            if variation_preset_rankings
            else "ig_subtle"
        )
        reference_pattern_evidence = self.recommendation_reference_pattern_evidence(
            reference_pattern_rankings, reference_pattern
        )
        variation_preset_evidence = self.recommendation_variation_preset_evidence(
            variation_preset_rankings, recommended_variation_preset
        )
        target_account = account
        audio_context_tags = [
            reference_pattern.get("visualFormat"),
            reference_pattern.get("hookType"),
            reference_pattern.get("captionArchetype"),
            self.first_suggested_recipe(reference_pattern),
        ]
        audio_recommendations = self.recommend_audio(
            platform=campaign.get("platform") or "instagram",
            campaign_slug=campaign.get("slug"),
            recommendation_item_id=None,
            content_tags=[str(tag) for tag in audio_context_tags if tag],
            account_tags=[str(tag) for tag in [target_account] if tag],
            account=target_account,
            limit=5,
        )
        readiness_evidence = {
            "state": "blocked",
            "operatorScore": 0,
            "blockingReasons": ["missing_rendered_assets"],
            "warnings": [],
            "publishabilityFailureReasons": [],
            "reviewState": None,
            "auditStatus": None,
            "contentSurface": "reel",
            "audioStatus": (audio_recommendations.get("decision") or {}).get(
                "decisionConfidence"
            ),
            "captionHash": None,
            "targetAccount": target_account,
            "latestAuditId": None,
            "latestAuditVerdict": None,
        }
        account_fit_evidence = {
            "level": "low",
            "score": None,
            "account": target_account,
            "reasons": ["missing_rendered_assets"],
            "memory": None,
        }
        caption = self.caption_guidance(reference_pattern, {})
        why_now_reasons = [
            "active reference pattern is available for the next generation batch"
        ]
        why_now_risks = [
            "missing_rendered_assets",
            "missing_performance_history",
            *(
                ["low_recommendation_trust"]
                if recommendation_trust.get("status") == "low"
                else []
            ),
        ]
        decision_evidence = self.recommendation_decision_evidence(
            target_account=target_account,
            account_score=50,
            account_fit_evidence=account_fit_evidence,
            performance_score=50,
            data_quality={
                "level": "low",
                "sampleSize": 0,
                "missing": ["rendered_assets", "performance_history"],
            },
            latest_performance={},
            recommendation_trust=recommendation_trust,
            trust_risks=["low_recommendation_trust"]
            if recommendation_trust.get("status") == "low"
            else [],
            audio_recommendations=audio_recommendations,
            caption_guidance=caption,
            readiness_evidence=readiness_evidence,
            recommended_variation_preset=recommended_variation_preset,
            reasons=why_now_reasons,
            risks=why_now_risks,
        )
        score, confidence, confidence_reason, trust_risks = (
            self.apply_recommendation_trust(
                score=self.reference_pattern_score(reference_pattern),
                confidence="low",
                confidence_reason="No rendered assets are available yet; recommendation is based on the active reference pattern only.",
                recommendation_trust=recommendation_trust,
            )
        )
        output = {
            "recommendationId": item_id,
            "recommendationGraphId": None,
            "status": "proposed",
            "campaignGraphId": campaign_graph_id,
            "referencePatternGraphId": reference_pattern_graph_id,
            "sourceAssetGraphId": None,
            "renderedAssetGraphId": None,
            "rank": 1,
            "score": score,
            "confidence": confidence,
            "confidenceReason": confidence_reason,
            "autonomyLevel": self.autonomy_level(),
            "executionStatus": "not_started",
            "targetAccount": target_account,
            "renderedAssetId": None,
            "filename": None,
            "referencePatternId": reference_pattern.get("id"),
            "referencePattern": self.recommendation_reference_summary(
                reference_pattern
            ),
            "referencePatternEvidence": reference_pattern_evidence,
            "recommendedVariationPreset": recommended_variation_preset,
            "variationPresetEvidence": variation_preset_evidence,
            "readinessEvidence": readiness_evidence,
            "decisionEvidence": decision_evidence,
            "suggestedRecipe": self.first_suggested_recipe(reference_pattern),
            "hookGuidance": self.hook_guidance(reference_pattern, {}),
            "captionGuidance": caption,
            "audioRecommendations": audio_recommendations,
            "audioDecision": audio_recommendations.get("decision") or {},
            "audioMemoryEvidence": {
                "recommendationCount": len(
                    audio_recommendations.get("recommendations") or []
                ),
                "topAudioMemoryGraphIds": [
                    item.get("audioMemoryGraphId")
                    for item in (audio_recommendations.get("recommendations") or [])[:3]
                    if item.get("audioMemoryGraphId")
                ],
            },
            "selectedAudio": None,
            "audioSelectionStatus": "recommended"
            if audio_recommendations.get("recommendations")
            else "needs_operator_selection",
            "reasons": why_now_reasons,
            "risks": why_now_risks,
            "scoreBreakdown": {
                "performance": 50,
                "referencePattern": self.reference_pattern_score(reference_pattern),
                "auditReadiness": 0,
                "accountFitFatigue": 50,
                "novelty": 50,
                "operationalReadiness": 0,
                "recommendationTrust": recommendation_trust.get("score"),
            },
            "evidence": {
                "graph": {
                    "campaignGraphId": campaign_graph_id,
                    "runGraphId": run_graph_id,
                    "referencePatternGraphId": reference_pattern_graph_id,
                },
                "reasons": [
                    "active reference pattern is available for the next generation batch"
                ],
                "risks": [
                    "missing_rendered_assets",
                    "missing_performance_history",
                    *trust_risks,
                ],
                "recommendationTrust": recommendation_trust,
                "referencePatternRankings": reference_pattern_evidence,
                "variationPresetRankings": variation_preset_evidence,
                "readiness": readiness_evidence,
                "decision": decision_evidence,
            },
            "dataQuality": {
                "sampleSize": 0,
                "level": "low",
                "reasons": ["missing_rendered_assets", "missing_performance_history"],
            },
            "accountMemory": None,
            "accountFitEvidence": account_fit_evidence,
            "decision": {},
            "outcome": {},
            "baseline": {},
            "exceptions": [],
            "measurementVersion": None,
            "acceptedAt": None,
            "rejectedAt": None,
            "executedAt": None,
            "postedAt": None,
            "measuredAt": None,
            "graphEvidence": {
                "campaignGraphId": campaign_graph_id,
                "runGraphId": run_graph_id,
                "referencePatternGraphId": reference_pattern_graph_id,
            },
        }
        if persist:
            recommendation_graph_id = self.ensure_graph_node(
                "recommendation_item",
                local_table="recommendation_items",
                local_id=item_id,
                payload=output,
            )
            output["recommendationGraphId"] = recommendation_graph_id
            self.conn.execute(
                """
                INSERT INTO recommendation_items (
                  id, run_id, rank, target_account, reference_pattern_id,
                  recommendation_graph_id, status, score, confidence, reasons_json,
                  risks_json, evidence_json, data_quality_json, decision_json,
                  outcome_json, baseline_json, measurement_version, output_json, created_at
                )
                VALUES (?, ?, 1, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', NULL, ?, ?)
                ON CONFLICT(run_id, rank) DO UPDATE SET
                  recommendation_graph_id = excluded.recommendation_graph_id,
                  score = excluded.score,
                  confidence = excluded.confidence,
                  evidence_json = excluded.evidence_json,
                  data_quality_json = excluded.data_quality_json,
                  output_json = excluded.output_json
                """,
                (
                    item_id,
                    run_id,
                    account,
                    reference_pattern.get("id"),
                    recommendation_graph_id,
                    output["score"],
                    output["confidence"],
                    json.dumps(output["reasons"], ensure_ascii=False, sort_keys=True),
                    json.dumps(output["risks"], ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        self._sanitize_for_storage(output["evidence"]),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(output["dataQuality"]),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        self._sanitize_for_storage(output),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    self._utc_now(),
                ),
            )
            self.write_recommendation_graph_edges(
                performance_graph_id=None,
                recommendation_input_graph_id=None,
                run_graph_id=run_graph_id,
                item_graph_id=recommendation_graph_id,
                rendered_graph_id=None,
                reference_pattern_graph_id=reference_pattern_graph_id,
            )
            self.write_audio_recommendation_graph_edges(
                recommendation_item_id=item_id,
                recommendation_graph_id=recommendation_graph_id,
                reference_pattern_graph_id=reference_pattern_graph_id,
                audio_recommendations=audio_recommendations,
                campaign_id=campaign["id"],
            )
        return output

    def write_recommendation_graph_edges(
        self,
        *,
        performance_graph_id: str | None,
        recommendation_input_graph_id: str | None,
        run_graph_id: str | None,
        item_graph_id: str | None,
        rendered_graph_id: str | None,
        reference_pattern_graph_id: str | None,
    ) -> None:
        self.ensure_graph_edge(
            performance_graph_id,
            recommendation_input_graph_id,
            "performance_snapshot_to_recommendation_input",
        )
        self.ensure_graph_edge(
            recommendation_input_graph_id,
            run_graph_id,
            "recommendation_input_to_recommendation_run",
        )
        self.ensure_graph_edge(
            run_graph_id, item_graph_id, "recommendation_run_to_recommendation_item"
        )
        self.ensure_graph_edge(
            reference_pattern_graph_id,
            item_graph_id,
            "reference_pattern_to_recommendation_item",
        )
        self.ensure_graph_edge(
            rendered_graph_id, item_graph_id, "rendered_asset_to_recommendation_item"
        )

    def write_audio_recommendation_graph_edges(
        self,
        *,
        recommendation_item_id: str,
        recommendation_graph_id: str | None,
        reference_pattern_graph_id: str | None,
        audio_recommendations: dict[str, Any],
        campaign_id: str | None = None,
    ) -> None:
        for rec in audio_recommendations.get("recommendations") or []:
            if not isinstance(rec, dict):
                continue
            catalog_audio_id = rec.get("catalogAudioId") or rec.get("catalog_audio_id")
            if not catalog_audio_id:
                continue
            audio_graph_id = rec.get("audioMemoryGraphId") or self.graph_id_for(
                "audio_catalog",
                str(catalog_audio_id),
                entity_type="audio_memory",
                payload=rec,
            )
            audio_rec_id = f"audiorec_{hashlib.sha256(f'{recommendation_item_id}:{catalog_audio_id}'.encode()).hexdigest()[:12]}"
            audio_rec_graph_id = self.ensure_graph_node(
                "audio_recommendation",
                local_table="audio_selections",
                local_id=f"recommendation:{audio_rec_id}",
                payload={"recommendationItemId": recommendation_item_id, "audio": rec},
            )
            self.ensure_graph_edge_strict(
                recommendation_graph_id,
                audio_rec_graph_id,
                "recommendation_item_to_audio_recommendation",
                evidence={
                    "catalogAudioId": catalog_audio_id,
                    "selectionRank": rec.get("selectionRank"),
                },
                campaign_id=campaign_id,
                recommendation_item_id=recommendation_item_id,
                source_operation="audio_memory_recommendation",
            )
            self.ensure_graph_edge(
                audio_graph_id,
                audio_rec_graph_id,
                "audio_memory_to_audio_recommendation",
                evidence={"catalogAudioId": catalog_audio_id},
            )
            self.ensure_graph_edge(
                reference_pattern_graph_id,
                audio_graph_id,
                "reference_pattern_to_audio_memory",
                evidence={"source": "audio_memory_v1"},
            )

    def stored_recommendation_item_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = json_load(row.get("output_json"), {})
        if isinstance(payload, dict):
            payload.setdefault("recommendationId", row["id"])
            payload.setdefault(
                "recommendationGraphId", row.get("recommendation_graph_id")
            )
            payload["status"] = row.get("status") or payload.get("status") or "proposed"
            payload["executionStatus"] = (
                row.get("execution_status")
                or payload.get("executionStatus")
                or "not_started"
            )
            payload["evidence"] = json_load(
                row.get("evidence_json"), payload.get("evidence") or {}
            )
            payload["dataQuality"] = json_load(
                row.get("data_quality_json"), payload.get("dataQuality") or {}
            )
            payload["decision"] = json_load(
                row.get("decision_json"), payload.get("decision") or {}
            )
            payload["outcome"] = json_load(
                row.get("outcome_json"), payload.get("outcome") or {}
            )
            payload["baseline"] = json_load(
                row.get("baseline_json"), payload.get("baseline") or {}
            )
            payload["measurementVersion"] = row.get(
                "measurement_version"
            ) or payload.get("measurementVersion")
            payload["acceptedAt"] = row.get("accepted_at")
            payload["rejectedAt"] = row.get("rejected_at")
            payload["executedAt"] = row.get("executed_at")
            payload["postedAt"] = row.get("posted_at")
            payload["measuredAt"] = row.get("measured_at")
            payload["autonomyLevel"] = (
                payload.get("autonomyLevel") or self.autonomy_level()
            )
            payload["exceptions"] = self.exceptions_for_recommendation(row["id"])
            return payload
        return {
            "recommendationId": row["id"],
            "recommendationGraphId": row.get("recommendation_graph_id"),
            "status": row.get("status") or "proposed",
            "executionStatus": row.get("execution_status") or "not_started",
            "rank": row["rank"],
            "score": row["score"],
            "confidence": row["confidence"],
            "reasons": json_load(row.get("reasons_json"), []),
            "risks": json_load(row.get("risks_json"), []),
            "evidence": json_load(row.get("evidence_json"), {}),
            "dataQuality": json_load(row.get("data_quality_json"), {}),
            "decision": json_load(row.get("decision_json"), {}),
            "outcome": json_load(row.get("outcome_json"), {}),
            "baseline": json_load(row.get("baseline_json"), {}),
            "measurementVersion": row.get("measurement_version"),
            "autonomyLevel": self.autonomy_level(),
            "exceptions": self.exceptions_for_recommendation(row["id"]),
        }

    def exceptions_for_recommendation(
        self, recommendation_item_id: str
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM trust_exceptions
            WHERE recommendation_item_id = ?
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC
            """,
            (recommendation_item_id,),
        ).fetchall()
        return [self._exception_payload(dict(row)) for row in rows]

    def recommendation_item(self, recommendation_item_id: str) -> dict[str, Any]:
        row = self.recommendation_item_row(recommendation_item_id)
        return self.stored_recommendation_item_payload(row)

    def accept_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        decision = {
            "action": "accepted",
            "operator": operator,
            "notes": notes,
            "decidedAt": self._utc_now(),
        }
        return self.update_recommendation_lifecycle(
            recommendation_item_id,
            status="accepted",
            decision=decision,
            timestamp_column="accepted_at",
            event_type="recommendation_item_accepted",
            message="Recommendation accepted",
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def reject_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        reason: str | None = None,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        decision = {
            "action": "rejected",
            "reason": reason,
            "operator": operator,
            "notes": notes,
            "decidedAt": self._utc_now(),
        }
        return self.update_recommendation_lifecycle(
            recommendation_item_id,
            status="rejected",
            decision=decision,
            timestamp_column="rejected_at",
            event_type="recommendation_item_rejected",
            message="Recommendation rejected",
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def link_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        source_asset_id: str | None = None,
        render_job_id: str | None = None,
        rendered_asset_id: str | None = None,
        post_id: str | None = None,
        performance_snapshot_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        row = self.recommendation_item_row(recommendation_item_id)
        campaign = self.recommendation_item_campaign(row)
        item_graph_id = row.get("recommendation_graph_id") or self.graph_id_for(
            "recommendation_items",
            recommendation_item_id,
            entity_type="recommendation_item",
        )
        link_evidence = json_load(row.get("evidence_json"), {})
        links = link_evidence.setdefault("links", {})
        status = "executed"
        now = self._utc_now()
        updates: dict[str, Any] = {}
        if source_asset_id:
            source_graph_id = self.graph_id_for(
                "source_assets", source_asset_id, entity_type="source_asset"
            )
            self.ensure_graph_edge_strict(
                item_graph_id,
                source_graph_id,
                "recommendation_item_to_source_asset",
                evidence=evidence or {},
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                recommendation_item_id=recommendation_item_id,
                source_operation="link_recommendation_item",
            )
            links["sourceAssetId"] = source_asset_id
            links["sourceAssetGraphId"] = source_graph_id
            updates["source_asset_id"] = source_asset_id
        if render_job_id:
            render_graph_id = self.graph_id_for(
                "render_jobs", render_job_id, entity_type="render_job"
            )
            self.ensure_graph_edge_strict(
                item_graph_id,
                render_graph_id,
                "recommendation_item_to_render_job",
                evidence=evidence or {},
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                recommendation_item_id=recommendation_item_id,
                source_operation="link_recommendation_item",
            )
            links["renderJobId"] = render_job_id
            links["renderJobGraphId"] = render_graph_id
        if rendered_asset_id:
            rendered_graph_id = self.graph_id_for(
                "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
            )
            self.ensure_graph_edge_strict(
                item_graph_id,
                rendered_graph_id,
                "recommendation_item_to_rendered_asset",
                evidence=evidence or {},
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                recommendation_item_id=recommendation_item_id,
                source_operation="link_recommendation_item",
            )
            links["renderedAssetId"] = rendered_asset_id
            links["renderedAssetGraphId"] = rendered_graph_id
            updates["rendered_asset_id"] = rendered_asset_id
        if post_id:
            post_graph_id = self.ensure_graph_node(
                "threadsdash_post",
                external_system="threadsdash.posts",
                external_id=post_id,
                payload={"postId": post_id},
            )
            self.ensure_graph_edge_strict(
                item_graph_id,
                post_graph_id,
                "recommendation_item_to_threadsdash_post",
                evidence=evidence or {},
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                recommendation_item_id=recommendation_item_id,
                source_operation="link_recommendation_item",
            )
            links["postId"] = post_id
            links["postGraphId"] = post_graph_id
            status = "posted"
        if performance_snapshot_id:
            perf = self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE id = ?",
                (performance_snapshot_id,),
            ).fetchone()
            if not perf:
                raise ValueError(
                    f"performance snapshot not found: {performance_snapshot_id}"
                )
            perf_graph_id = self.ensure_graph_node(
                "performance_snapshot",
                local_table="performance_snapshots",
                local_id=performance_snapshot_id,
                payload=self._performance_snapshot_payload(dict(perf)),
            )
            self.ensure_graph_edge_strict(
                item_graph_id,
                perf_graph_id,
                "recommendation_item_to_performance_snapshot",
                evidence=evidence or {},
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                recommendation_item_id=recommendation_item_id,
                source_operation="link_recommendation_item",
            )
            links["performanceSnapshotId"] = performance_snapshot_id
            links["performanceSnapshotGraphId"] = perf_graph_id
            status = "posted"
        self.validate_recommendation_transition(
            row.get("status") or "proposed",
            status,
            admin_override=admin_override,
            override_reason=override_reason,
        )
        if evidence:
            link_evidence.setdefault("operatorEvidence", []).append(
                {"at": now, **self._sanitize_for_storage(evidence)}
            )
        if admin_override:
            link_evidence.setdefault("adminOverrides", []).append(
                {"at": now, "reason": override_reason, "toStatus": status}
            )
        set_parts = [
            "status = ?",
            "execution_status = ?",
            "evidence_json = ?",
            "output_json = ?",
            "executed_at = COALESCE(executed_at, ?)",
        ]
        params: list[Any] = [
            status,
            "completed",
            json.dumps(
                self._sanitize_for_storage(link_evidence),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "",
            now,
        ]
        if status == "posted":
            set_parts.append("posted_at = COALESCE(posted_at, ?)")
            params.append(now)
        for column, value in updates.items():
            set_parts.append(f"{column} = ?")
            params.append(value)
        payload = self.stored_recommendation_item_payload(dict(row))
        payload["status"] = status
        payload["evidence"] = link_evidence
        if source_asset_id:
            payload["sourceAssetGraphId"] = links.get("sourceAssetGraphId")
        if rendered_asset_id:
            payload["renderedAssetId"] = rendered_asset_id
            payload["renderedAssetGraphId"] = links.get("renderedAssetGraphId")
        payload["executedAt"] = payload.get("executedAt") or now
        if status == "posted":
            payload["postedAt"] = payload.get("postedAt") or now
        params[3] = json.dumps(
            self._sanitize_for_storage(payload), ensure_ascii=False, sort_keys=True
        )
        params.append(recommendation_item_id)
        self.conn.execute(
            f"UPDATE recommendation_items SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        self.record_event(
            "recommendation_item_linked",
            campaign_id=campaign["id"],
            rendered_asset_id=rendered_asset_id or row.get("rendered_asset_id"),
            status="success",
            message="Recommendation linked to lifecycle artifact",
            metadata={
                "recommendationItemId": recommendation_item_id,
                "status": status,
                "links": links,
            },
            commit=False,
        )
        self.conn.commit()
        return self.recommendation_item(recommendation_item_id)

    def measure_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        performance_snapshot_id: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        row = self.recommendation_item_row(recommendation_item_id)
        campaign = self.recommendation_item_campaign(row)
        if performance_snapshot_id:
            self.link_recommendation_item(
                recommendation_item_id, performance_snapshot_id=performance_snapshot_id
            )
            row = self.recommendation_item_row(recommendation_item_id)
        perf_rows = self.recommendation_performance_rows(row)
        if not perf_rows:
            raise ValueError(
                "recommendation has no linked or matching performance snapshots"
            )
        snapshots = [
            self._performance_snapshot_payload(dict(perf)) for perf in perf_rows
        ]
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            baseline_rows = []
        else:
            baseline_rows = self.conn.execute(
                f"""
                SELECT * FROM performance_snapshots
                WHERE campaign_id = ?
                  AND {learning_eligible_sql()}
                  AND (rendered_asset_id IS NULL OR rendered_asset_id != ?)
                ORDER BY snapshot_at DESC, created_at DESC
                """,
                (
                    campaign["id"],
                    cutover_iso,
                    row.get("rendered_asset_id") or "",
                ),
            ).fetchall()
        baseline_snapshots = [
            self._performance_snapshot_payload(dict(perf)) for perf in baseline_rows
        ]
        account_baselines = self._account_reward_baselines(
            snapshots + baseline_snapshots
        )
        outcome_summary = self._aggregate_performance(
            snapshots, account_baselines=account_baselines
        )
        outcome_score = self._performance_quality_score(outcome_summary)
        baseline_summary = self._aggregate_performance(
            baseline_snapshots, account_baselines=account_baselines
        )
        baseline_score = self._performance_quality_score(baseline_summary)
        status = "measured"
        baseline = self.recommendation_baseline_payload(
            baseline_summary,
            baseline_score=baseline_score,
            threshold=RECOMMENDATION_MEASUREMENT_THRESHOLD,
        )
        if (
            outcome_score is not None
            and baseline_score is not None
            and int(baseline_summary.get("count") or 0) >= 3
        ):
            if outcome_score >= baseline_score + RECOMMENDATION_MEASUREMENT_THRESHOLD:
                status = "proved"
            elif outcome_score <= baseline_score - RECOMMENDATION_MEASUREMENT_THRESHOLD:
                status = "disproved"
        outcome = {
            "status": status,
            "outcomeScore": outcome_score,
            "baselineScore": baseline_score,
            "snapshotCount": len(snapshots),
            "baselineSnapshotCount": len(baseline_snapshots),
            "snapshots": snapshots[:20],
            "measuredAt": self._utc_now(),
            "measurementVersion": RECOMMENDATION_MEASUREMENT_VERSION,
        }
        return self.update_recommendation_lifecycle(
            recommendation_item_id,
            status=status,
            outcome=outcome,
            baseline=baseline,
            measurement_version=RECOMMENDATION_MEASUREMENT_VERSION,
            timestamp_column="measured_at",
            event_type="recommendation_item_measured",
            message=f"Recommendation measured: {status}",
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def execute_accepted_recommendation(
        self,
        recommendation_item_id: str,
        *,
        mode: str = DEFAULT_AUTONOMY_LEVEL,
        force: bool = False,
        dry_run_render: bool = False,
        run_audit: bool = True,
        contentforge_base_url: str | None = None,
    ) -> dict[str, Any]:
        if mode not in AUTONOMY_LEVELS:
            raise ValueError(f"mode must be one of {sorted(AUTONOMY_LEVELS)}")
        row = self.recommendation_item_row(recommendation_item_id)
        campaign = self.recommendation_item_campaign(row)
        active_level = self.autonomy_level()
        if active_level == "level_1" or mode == "level_1":
            exception = self.create_exception(
                reason_code="autonomy_level_blocks_execution",
                severity="medium",
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                entity_graph_id=row.get("recommendation_graph_id"),
                recommendation_item_id=recommendation_item_id,
                payload={"activeLevel": active_level, "requestedMode": mode},
            )
            raise ValueError(
                f"auto execute blocked by autonomy level: {exception['id']}"
            )
        if row.get("status") not in {"accepted", "executed"}:
            exception = self.create_exception(
                reason_code="recommendation_not_accepted",
                severity="high",
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                entity_graph_id=row.get("recommendation_graph_id"),
                recommendation_item_id=recommendation_item_id,
                payload={"status": row.get("status")},
            )
            raise ValueError(
                f"recommendation must be accepted before execute: {exception['id']}"
            )
        pipeline_job = self.create_pipeline_job(
            "execute_recommendation",
            campaign["id"],
            {
                "recommendationItemId": recommendation_item_id,
                "mode": mode,
                "activeAutonomyLevel": active_level,
                "force": force,
                "dryRunRender": dry_run_render,
                "runAudit": run_audit,
                "contentforgeBaseUrl": contentforge_base_url,
            },
        )
        self.start_pipeline_job(pipeline_job["id"])
        steps: list[dict[str, Any]] = []
        self.conn.execute(
            "UPDATE recommendation_items SET execution_status = ? WHERE id = ?",
            ("running", recommendation_item_id),
        )
        self.conn.commit()
        linked_rendered_id = row.get("rendered_asset_id")
        existing_links = json_load(row.get("evidence_json"), {}).get("links") or {}
        if not force and not linked_rendered_id:
            linked_rendered_id = existing_links.get("renderedAssetId")
        try:
            if not linked_rendered_id and row.get("reference_pattern_id"):
                prepared = self.prepare_reel_from_reference(
                    campaign_slug=campaign["slug"],
                    reference_pattern_id=row["reference_pattern_id"],
                    variant_count=1,
                    notes=f"auto execute recommendation {recommendation_item_id}",
                    force_new=force,
                )
                steps.append(
                    {
                        "step": "prepare_from_reference",
                        "status": "completed",
                        "result": prepared,
                    }
                )
                rendered = self.run_reel_factory(
                    campaign_slug=campaign["slug"],
                    dry_run=dry_run_render,
                    max_outputs_per_clip=1,
                )
                steps.append(
                    {
                        "step": "run_reel",
                        "status": "completed",
                        "result": self.compact_execution_result(rendered),
                    }
                )
                synced = self.sync_reel_outputs(campaign_slug=campaign["slug"])
                steps.append(
                    {
                        "step": "sync_reel",
                        "status": "completed",
                        "result": self.compact_execution_result(synced),
                    }
                )
                synced_assets = synced.get("synced") or []
                if synced_assets:
                    linked_rendered_id = synced_assets[0].get("id")
            if linked_rendered_id:
                self.link_recommendation_item(
                    recommendation_item_id,
                    rendered_asset_id=linked_rendered_id,
                    evidence={
                        "source": "execute_accepted_recommendation",
                        "pipelineJobId": pipeline_job["id"],
                        "mode": mode,
                    },
                    admin_override=row.get("status") == "executed",
                    override_reason="refresh execution links"
                    if row.get("status") == "executed"
                    else None,
                )
            else:
                self.create_exception(
                    reason_code="execution_missing_rendered_asset",
                    severity="high",
                    campaign_id=campaign["id"],
                    account_id=row.get("target_account"),
                    entity_graph_id=row.get("recommendation_graph_id"),
                    recommendation_item_id=recommendation_item_id,
                    payload={"steps": steps},
                    commit=False,
                )
            if run_audit and linked_rendered_id:
                from .adapters.contentforge import audit_campaign

                audit_result = audit_campaign(
                    self,
                    campaign_slug=campaign["slug"],
                    contentforge_base_url=contentforge_base_url,
                )
                steps.append(
                    {
                        "step": "audit",
                        "status": "completed",
                        "result": self.compact_execution_result(audit_result),
                    }
                )
            current = self.recommendation_item_row(recommendation_item_id)
            asset_payload = None
            if linked_rendered_id:
                asset_payload = self._dashboard_rendered_asset(
                    self.rendered_asset(linked_rendered_id)
                )
                self.create_trust_exceptions_for_recommendation(
                    current, asset_payload, commit=False
                )
            exceptions = self.exceptions_for_recommendation(recommendation_item_id)
            blocking_exceptions = [
                item
                for item in exceptions
                if item.get("status") in {"open", "snoozed"}
                and item.get("severity") in {"medium", "high", "critical"}
            ]
            execution_status = (
                "blocked"
                if blocking_exceptions or not linked_rendered_id
                else "completed"
            )
            payload = self.stored_recommendation_item_payload(current)
            payload["executionStatus"] = execution_status
            payload["autonomyLevel"] = mode
            payload["execution"] = {
                "pipelineJobId": pipeline_job["id"],
                "steps": steps,
                "dryRunRender": dry_run_render,
                "runAudit": run_audit,
                "force": force,
            }
            self.conn.execute(
                "UPDATE recommendation_items SET execution_status = ?, output_json = ? WHERE id = ?",
                (
                    execution_status,
                    json.dumps(
                        self._sanitize_for_storage(payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    recommendation_item_id,
                ),
            )
            self.record_event(
                "recommendation_item_executed",
                campaign_id=campaign["id"],
                rendered_asset_id=linked_rendered_id,
                pipeline_job_id=pipeline_job["id"],
                status="success",
                message="Accepted recommendation executed",
                metadata={
                    "recommendationItemId": recommendation_item_id,
                    "mode": mode,
                    "force": force,
                    "executionStatus": execution_status,
                    "steps": [step["step"] for step in steps],
                },
                commit=False,
            )
            self.conn.commit()
            self.finish_pipeline_job(
                pipeline_job["id"],
                {
                    "steps": [step["step"] for step in steps],
                    "renderedAssetId": linked_rendered_id,
                    "executionStatus": execution_status,
                },
            )
            return {
                "schema": "campaign_factory.recommendation_execution.v1",
                "recommendation": self.recommendation_item(recommendation_item_id),
                "pipelineJobId": pipeline_job["id"],
                "steps": steps,
                "exceptions": exceptions,
                "publishesAutomatically": False,
            }
        except Exception as exc:
            self.conn.execute(
                "UPDATE recommendation_items SET execution_status = ? WHERE id = ?",
                ("failed", recommendation_item_id),
            )
            self.create_exception(
                reason_code="auto_execute_failed",
                severity="high",
                campaign_id=campaign["id"],
                account_id=row.get("target_account"),
                entity_graph_id=row.get("recommendation_graph_id"),
                recommendation_item_id=recommendation_item_id,
                payload={"error": str(exc), "steps": steps},
                commit=False,
            )
            self.record_event(
                "recommendation_item_execution_failed",
                campaign_id=campaign["id"],
                rendered_asset_id=linked_rendered_id,
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Recommendation execution failed: {exc}",
                metadata={
                    "recommendationItemId": recommendation_item_id,
                    "error": str(exc),
                },
                commit=False,
            )
            self.conn.commit()
            self.fail_pipeline_job(pipeline_job["id"], str(exc), {"steps": steps})
            raise

    def compact_execution_result(self, result: dict[str, Any]) -> dict[str, Any]:
        compact = {}
        for key in (
            "schema",
            "pipelineJobId",
            "campaign",
            "returncode",
            "elapsed_seconds",
        ):
            if key in result:
                compact[key] = result[key]
        for key in ("prepared", "reusedExisting", "synced", "reports", "runs"):
            if isinstance(result.get(key), list):
                compact[f"{key}Count"] = len(result[key])
        return compact or self._sanitize_for_storage(result)

    def create_trust_exceptions_for_recommendation(
        self,
        row: dict[str, Any],
        asset: dict[str, Any],
        *,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        campaign = self.recommendation_item_campaign(row)
        recommendation_item_id = row["id"]
        account_id = row.get("target_account") or self.asset_target_account(asset)
        entity_graph_id = row.get("recommendation_graph_id") or self.graph_id_for(
            "recommendation_items",
            recommendation_item_id,
            entity_type="recommendation_item",
        )
        created = []
        readiness = asset.get("export_readiness") or {}
        data_quality = json_load(row.get("data_quality_json"), {})
        account_fit = self.recommendation_account_fit_evidence(
            campaign["id"], asset, account_id
        )
        if not account_id:
            created.append(
                self.create_exception(
                    reason_code="missing_account_assignment",
                    severity="medium",
                    campaign_id=campaign["id"],
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={"renderedAssetId": asset.get("id")},
                    commit=False,
                )
            )
        for reason in readiness.get("blockingReasons") or []:
            created.append(
                self.create_exception(
                    reason_code=f"audit_blocked:{reason}",
                    severity="high",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={
                        "renderedAssetId": asset.get("id"),
                        "readiness": readiness,
                    },
                    commit=False,
                )
            )
        if data_quality.get("level") in {"low", "medium"}:
            created.append(
                self.create_exception(
                    reason_code=f"qc_confidence_{data_quality.get('level')}",
                    severity="medium"
                    if data_quality.get("level") == "medium"
                    else "high",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={"dataQuality": data_quality},
                    commit=False,
                )
            )
        fatigue = (account_fit.get("memory") or {}).get("fatigue") or {}
        if fatigue.get("level") in {"medium", "high"}:
            created.append(
                self.create_exception(
                    reason_code=f"account_fatigue_{fatigue.get('level')}",
                    severity="high" if fatigue.get("level") == "high" else "medium",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={"fatigue": fatigue},
                    commit=False,
                )
            )
        warnings = readiness.get("warnings") or []
        if any(
            "reuse" in str(warning) or "duplicate" in str(warning)
            for warning in warnings
        ):
            created.append(
                self.create_exception(
                    reason_code="duplicate_or_reuse_risk",
                    severity="medium",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={"warnings": warnings},
                    commit=False,
                )
            )
        audio = (
            asset.get("audioRecommendations")
            if isinstance(asset.get("audioRecommendations"), dict)
            else {}
        )
        if audio.get("recommendations") and not self.asset_has_final_audio_proof(asset):
            created.append(
                self.create_exception(
                    reason_code="unresolved_native_audio",
                    severity="high",
                    campaign_id=campaign["id"],
                    account_id=account_id,
                    entity_graph_id=entity_graph_id,
                    recommendation_item_id=recommendation_item_id,
                    payload={"audioRecommendations": audio},
                    commit=False,
                )
            )
        if commit:
            self.conn.commit()
        return created

    def asset_has_final_audio_proof(self, asset: dict[str, Any]) -> bool:
        caption_generation = (
            asset.get("captionGeneration")
            if isinstance(asset.get("captionGeneration"), dict)
            else {}
        )
        intent = (
            caption_generation.get("audioIntent")
            or caption_generation.get("audio_intent")
            or {}
        )
        if not isinstance(intent, dict):
            return False
        status = str(intent.get("status") or "").strip().lower()
        return status in {"attached", "verified", "not_required", "skipped"}

    def recommendation_item_row(self, recommendation_item_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM recommendation_items WHERE id = ?", (recommendation_item_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"recommendation item not found: {recommendation_item_id}")
        return dict(row)

    def recommendation_item_campaign(self, row: dict[str, Any]) -> dict[str, Any]:
        campaign = self.conn.execute(
            """
            SELECT c.*
            FROM recommendation_runs rr
            JOIN campaigns c ON c.id = rr.campaign_id
            WHERE rr.id = ?
            """,
            (row["run_id"],),
        ).fetchone()
        if not campaign:
            raise ValueError(f"campaign not found for recommendation item: {row['id']}")
        return dict(campaign)

    def update_recommendation_lifecycle(
        self,
        recommendation_item_id: str,
        *,
        status: str,
        decision: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        baseline: dict[str, Any] | None = None,
        measurement_version: str | None = None,
        timestamp_column: str | None = None,
        event_type: str,
        message: str,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        if status not in RECOMMENDATION_ITEM_STATUSES:
            raise ValueError(f"invalid recommendation status: {status}")
        row = self.recommendation_item_row(recommendation_item_id)
        current_status = row.get("status") or "proposed"
        self.validate_recommendation_transition(
            current_status,
            status,
            admin_override=admin_override,
            override_reason=override_reason,
        )
        payload = self.stored_recommendation_item_payload(row)
        now = self._utc_now()
        payload["status"] = status
        if decision is not None:
            payload["decision"] = self._sanitize_for_storage(decision)
        if outcome is not None:
            payload["outcome"] = self._sanitize_for_storage(outcome)
        if baseline is not None:
            payload["baseline"] = self._sanitize_for_storage(baseline)
        if measurement_version is not None:
            payload["measurementVersion"] = measurement_version
        if admin_override:
            decision_payload = dict(payload.get("decision") or {})
            decision_payload.setdefault("adminOverrides", []).append(
                {
                    "at": now,
                    "fromStatus": current_status,
                    "toStatus": status,
                    "reason": override_reason,
                }
            )
            payload["decision"] = decision_payload
            decision = decision_payload
        if timestamp_column:
            payload_key = {
                "accepted_at": "acceptedAt",
                "rejected_at": "rejectedAt",
                "executed_at": "executedAt",
                "posted_at": "postedAt",
                "measured_at": "measuredAt",
            }[timestamp_column]
            payload[payload_key] = row.get(timestamp_column) or now
        set_parts = ["status = ?", "output_json = ?"]
        params: list[Any] = [
            status,
            json.dumps(
                self._sanitize_for_storage(payload), ensure_ascii=False, sort_keys=True
            ),
        ]
        if decision is not None:
            set_parts.append("decision_json = ?")
            params.append(
                json.dumps(
                    self._sanitize_for_storage(decision),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if outcome is not None:
            set_parts.append("outcome_json = ?")
            params.append(
                json.dumps(
                    self._sanitize_for_storage(outcome),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if baseline is not None:
            set_parts.append("baseline_json = ?")
            params.append(
                json.dumps(
                    self._sanitize_for_storage(baseline),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        if measurement_version is not None:
            set_parts.append("measurement_version = ?")
            params.append(measurement_version)
        if timestamp_column:
            set_parts.append(f"{timestamp_column} = COALESCE({timestamp_column}, ?)")
            params.append(now)
        params.append(recommendation_item_id)
        self.conn.execute(
            f"UPDATE recommendation_items SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        if row.get("recommendation_graph_id"):
            self.ensure_graph_node(
                "recommendation_item",
                local_table="recommendation_items",
                local_id=recommendation_item_id,
                payload=payload,
            )
        campaign = self.recommendation_item_campaign(row)
        self.record_event(
            event_type,
            campaign_id=campaign["id"],
            rendered_asset_id=row.get("rendered_asset_id"),
            status="success",
            message=message,
            metadata={"recommendationItemId": recommendation_item_id, "status": status},
            commit=False,
        )
        self.conn.commit()
        return self.recommendation_item(recommendation_item_id)

    def validate_recommendation_transition(
        self,
        current_status: str,
        next_status: str,
        *,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> None:
        current_status = current_status or "proposed"
        if current_status == next_status:
            return
        if admin_override:
            if not override_reason:
                raise ValueError(
                    "override_reason is required when admin_override is true"
                )
            return
        allowed = RECOMMENDATION_STATUS_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise ValueError(
                f"invalid recommendation status transition: {current_status} -> {next_status}"
            )

    def recommendation_baseline_payload(
        self,
        baseline_summary: dict[str, Any],
        *,
        baseline_score: int | None,
        threshold: int,
    ) -> dict[str, Any]:
        count = int(baseline_summary.get("count") or 0)
        avg = baseline_summary.get("averages") or {}
        snapshots = []
        latest = baseline_summary.get("latest")
        if latest:
            snapshots.append(latest)
        confidence = (
            "usable" if count >= 3 and baseline_score is not None else "insufficient"
        )
        return {
            "baselineType": "campaign_account_history",
            "sampleSize": count,
            "avgScore": baseline_score,
            "medianScore": None,
            "threshold": threshold,
            "confidence": confidence,
            "averages": avg,
            "rates": baseline_summary.get("rates") or {},
            "latestSnapshot": snapshots[0] if snapshots else None,
            "measurementVersion": RECOMMENDATION_MEASUREMENT_VERSION,
        }

    def recommendation_performance_rows(self, row: dict[str, Any]) -> list[sqlite3.Row]:
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            return []
        predicate = learning_eligible_sql()
        evidence = json_load(row.get("evidence_json"), {})
        links = evidence.get("links") if isinstance(evidence, dict) else {}
        snapshot_id = (
            links.get("performanceSnapshotId") if isinstance(links, dict) else None
        )
        if snapshot_id:
            rows = self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE id = ? AND " + predicate,
                (snapshot_id, cutover_iso),
            ).fetchall()
            if rows:
                return rows
        if row.get("rendered_asset_id"):
            return self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE rendered_asset_id = ? AND "
                + predicate
                + " ORDER BY snapshot_at DESC, created_at DESC",
                (row["rendered_asset_id"], cutover_iso),
            ).fetchall()
        return []

    def best_asset_history_score(self, asset: dict[str, Any]) -> int | None:
        scores = [
            self._performance_quality_score(asset.get("sourcePerformance") or {}),
            self._performance_quality_score(asset.get("captionPerformance") or {}),
            self._performance_quality_score(asset.get("recipePerformance") or {}),
        ]
        available = [score for score in scores if score is not None]
        return max(available) if available else None

    def reference_pattern_score(self, pattern: dict[str, Any] | None) -> int:
        if not pattern:
            return 45
        rank = pattern.get("rank")
        score = 70
        if isinstance(rank, int):
            score = max(50, 92 - min(rank, 50))
        if pattern.get("audioRecommendations"):
            score += 4
        if pattern.get("captionFormulas"):
            score += 4
        if pattern.get("promptTemplate"):
            score += 3
        return int(max(0, min(100, score)))

    def recommendation_account_score(
        self, asset: dict[str, Any], account: str | None
    ) -> int:
        evidence = self.recommendation_account_fit_evidence(
            asset["campaign_id"], asset, account
        )
        if evidence.get("score") is not None:
            return int(evidence["score"])
        assignments = self.assignments_for_asset(asset["id"])
        if account and any(
            account in {row.get("instagram_account_id"), row.get("account_id")}
            for row in assignments
        ):
            return 72
        if assignments:
            return 62
        account_ids = asset.get("account_ids") or []
        if account and account in account_ids:
            return 65
        return 50

    def recommendation_account_fit_evidence(
        self,
        campaign_id: str,
        asset: dict[str, Any],
        account: str | None,
    ) -> dict[str, Any]:
        target = account or self.asset_target_account(asset)
        if not target:
            return {
                "level": "low",
                "score": None,
                "reasons": ["missing_account_assignment"],
                "memory": None,
            }
        memory = self._account_memory_for(campaign_id, target)
        if not memory:
            return {
                "level": "low",
                "score": None,
                "account": target,
                "reasons": ["account_memory_missing_or_not_rebuilt"],
                "memory": None,
            }
        score = int(memory.get("performanceScore") or 50)
        fatigue = memory.get("fatigue") or {}
        fatigue_level = fatigue.get("level")
        reasons = [
            f"account memory confidence {memory.get('confidence')} with {memory.get('sampleSize')} samples"
        ]
        if fatigue_level == "high":
            score -= 20
            reasons.append("high account fatigue pressure")
        elif fatigue_level == "medium":
            score -= 10
            reasons.append("medium account fatigue pressure")
        if memory.get("confidence") == "low":
            score = round((score + 50) / 2)
        return {
            "level": memory.get("confidence") or "low",
            "score": int(max(0, min(100, score))),
            "account": target,
            "reasons": reasons,
            "memory": memory,
        }

    def operational_recommendation_score(self, asset: dict[str, Any]) -> int:
        readiness = asset.get("export_readiness") or {}
        if readiness.get("state") == "ready":
            score = 100
        elif readiness.get("state") == "warning":
            score = 65
        else:
            score = 20
        audio = (
            asset.get("audioRecommendations")
            if isinstance(asset.get("audioRecommendations"), dict)
            else {}
        )
        if audio.get("recommendations") or audio.get("primaryStrategy"):
            score += 5
        return int(max(0, min(100, score)))

    def recommendation_confidence(
        self, asset: dict[str, Any], pattern: dict[str, Any] | None
    ) -> tuple[str, str]:
        summaries = [
            asset.get("sourcePerformance") or {},
            asset.get("captionPerformance") or {},
            asset.get("recipePerformance") or {},
        ]
        sample_size = sum(int(summary.get("count") or 0) for summary in summaries)
        completeness = 0
        completeness += 1 if asset.get("latest_audit") else 0
        completeness += 1 if pattern else 0
        completeness += 1 if sample_size else 0
        rendered_asset_id = asset.get("id") or asset.get("renderedAssetId")
        completeness += (
            1
            if asset.get("graphId")
            or self.graph_id_for(
                "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
            )
            else 0
        )
        if sample_size >= 10 and completeness >= 3:
            return (
                "high",
                f"{sample_size} matched performance samples and complete graph/audit context",
            )
        if sample_size >= 3 or completeness >= 3:
            return (
                "medium",
                f"{sample_size} matched performance samples with partial context",
            )
        return (
            "low",
            "Limited performance history; score is mostly quality, readiness, and reference-pattern based",
        )

    def recommendation_data_quality(
        self, asset: dict[str, Any], pattern: dict[str, Any] | None
    ) -> dict[str, Any]:
        summaries = [
            asset.get("sourcePerformance") or {},
            asset.get("captionPerformance") or {},
            asset.get("recipePerformance") or {},
        ]
        sample_size = sum(int(summary.get("count") or 0) for summary in summaries)
        missing = []
        if not sample_size:
            missing.append("performance_history")
        if not asset.get("latest_audit"):
            missing.append("audit_report")
        if not pattern:
            missing.append("reference_pattern")
        rendered_asset_id = asset.get("id") or asset.get("renderedAssetId")
        if not asset.get("graphId") and not self.graph_id_for(
            "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
        ):
            missing.append("rendered_asset_graph_id")
        if sample_size >= 10 and not missing:
            level = "high"
        elif sample_size >= 3 or len(missing) <= 1:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level,
            "sampleSize": sample_size,
            "missing": missing,
            "hasAudit": bool(asset.get("latest_audit")),
            "hasReferencePattern": bool(pattern),
            "hasGraphEvidence": not bool("rendered_asset_graph_id" in missing),
        }

    def recommendation_reasons(
        self,
        *,
        performance_score: int,
        reference_score: int,
        audit_score: int,
        account_score: int,
        novelty_score: int,
        operational_score: int,
        candidate: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
    ) -> list[str]:
        reasons = list(candidate.get("reasons") or [])
        if performance_score >= 70:
            reasons.append("performance history is positive")
        if reference_score >= 80 and reference_pattern:
            reasons.append(
                f"reference pattern is strong: {reference_pattern.get('label')}"
            )
        if audit_score >= 80:
            reasons.append("ContentForge/readiness quality is strong")
        if account_score > 55:
            reasons.append("account assignment or account fit is available")
        if novelty_score >= 80:
            reasons.append("low reuse/fatigue warning pressure")
        if operational_score >= 80:
            reasons.append("operational gates are ready or near-ready")
        return sorted(set(str(reason) for reason in reasons if reason))

    def asset_target_account(self, asset: dict[str, Any]) -> str | None:
        assignments = self.assignments_for_asset(asset["id"])
        for row in assignments:
            if row.get("instagram_account_id") or row.get("account_id"):
                return row.get("instagram_account_id") or row.get("account_id")
        account_ids = asset.get("account_ids") or []
        return str(account_ids[0]) if account_ids else None

    def recommendation_reference_summary(
        self, pattern: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not pattern:
            return None
        return {
            "id": pattern.get("id"),
            "clusterKey": pattern.get("clusterKey"),
            "rank": pattern.get("rank"),
            "label": pattern.get("label"),
            "visualFormat": pattern.get("visualFormat"),
            "hookType": pattern.get("hookType"),
            "captionArchetype": pattern.get("captionArchetype"),
        }

    def first_suggested_recipe(self, pattern: dict[str, Any] | None) -> str | None:
        recipes = (
            ((pattern or {}).get("raw") or {})
            .get("bank", {})
            .get("suggestedVariantRecipes")
            if pattern
            else []
        )
        if isinstance(recipes, list) and recipes:
            return str(recipes[0])
        suggested = (pattern or {}).get("suggestedVariantRecipes") if pattern else []
        return str(suggested[0]) if isinstance(suggested, list) and suggested else None

    def hook_guidance(
        self, pattern: dict[str, Any] | None, asset: dict[str, Any]
    ) -> str:
        if pattern and pattern.get("hookType"):
            return f"Use a {pattern['hookType']} hook from {pattern.get('label') or pattern.get('clusterKey')}."
        caption = asset.get("caption")
        return (
            f"Adapt the existing hook/caption: {caption[:120]}"
            if caption
            else "Use a proven short curiosity hook."
        )

    def caption_guidance(
        self, pattern: dict[str, Any] | None, asset: dict[str, Any]
    ) -> str:
        formulas = (pattern or {}).get("captionFormulas") or []
        if formulas and isinstance(formulas[0], dict):
            formula = formulas[0].get("formula") or formulas[0].get("label")
            if formula:
                return str(formula)
        caption = asset.get("caption")
        return (
            caption[:160]
            if caption
            else "Keep caption short, native, and matched to the visual pattern."
        )
