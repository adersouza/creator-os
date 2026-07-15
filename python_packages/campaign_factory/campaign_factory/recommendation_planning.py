from __future__ import annotations

import hashlib
import json
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)
from pipeline_contracts import validate_recommendation_next_batch

from .persistence import json_load
from .recommendation_constants import (
    REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES,
)


class RecommendationPlanningMixin:
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
        eligible_reference_pattern_rankings = [
            item
            for item in reference_pattern_rankings
            if item.get("recommendationStatus") == "eligible"
        ]
        reference_pattern = (
            eligible_reference_pattern_rankings[0]["pattern"]
            if eligible_reference_pattern_rankings
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
            ranking.get("assets") or [], account=account
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
                "\n                INSERT INTO recommendation_runs (\n                  id, campaign_id, scope, scoring_version, input_hash,\n                  input_snapshot_json, created_at, updated_at\n                )\n                VALUES (?, ?, 'next_batch', 'recommendation_score.v1', ?, ?, ?, ?)\n                ON CONFLICT(campaign_id, scope, input_hash) DO UPDATE SET\n                  scoring_version = excluded.scoring_version,\n                  input_snapshot_json = excluded.input_snapshot_json,\n                  updated_at = excluded.updated_at\n                ",
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
        self, candidates: list[dict[str, Any]], *, account: str | None
    ) -> list[dict[str, Any]]:
        if not account:
            return candidates
        return sorted(
            candidates,
            key=lambda candidate: (
                self.recommendation_account_score(
                    self.rendered_asset(candidate["renderedAssetId"]), account
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
            "\n            SELECT * FROM recommendation_runs\n            WHERE campaign_id = ?\n            ORDER BY created_at DESC\n            LIMIT ?\n            ",
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
                f"\n                SELECT * FROM performance_snapshots\n                WHERE campaign_id = ? AND {learning_eligible_sql()}\n                ORDER BY snapshot_at DESC, created_at DESC\n                ",
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
                    "recommendationStatus": "eligible"
                    if int(performance.get("count") or 0)
                    >= REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES
                    else "advisory",
                    "performanceScore": self._performance_quality_score(performance),
                    "planningScore": self._performance_planning_score(performance),
                    "bandit": (performance.get("learning") or {}).get("bandit"),
                    "performance": performance,
                }
            )
        return sorted(
            rankings,
            key=lambda item: (
                0 if item.get("recommendationStatus") == "eligible" else 1,
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
                f"\n                SELECT * FROM performance_snapshots\n                WHERE campaign_id = ? AND {learning_eligible_sql()}\n                ORDER BY snapshot_at DESC, created_at DESC\n                ",
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
                    "recommendationStatus",
                )
                if item.get(key) is not None
            }
            learning = (item.get("performance") or {}).get("learning") or {}
            if learning:
                row["learning"] = learning
            compact.append(row)
        return compact

    def recommendation_reference_pattern_evidence(
        self, rankings: list[dict[str, Any]], selected_pattern: dict[str, Any] | None
    ) -> dict[str, Any]:
        selected_pattern_id = (selected_pattern or {}).get("id")
        selected_ranking = next(
            (item for item in rankings if item.get("patternId") == selected_pattern_id),
            None,
        )
        measured_examples = int((selected_ranking or {}).get("sampleSize") or 0)
        recommendation_status = (
            "eligible"
            if measured_examples >= REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES
            else "advisory"
        )
        return {
            "selectedPatternId": (selected_pattern or {}).get("id"),
            "selectedClusterKey": (selected_pattern or {}).get("clusterKey"),
            "selectionSource": "performance_snapshots"
            if recommendation_status == "eligible"
            else "active_or_static_fallback",
            "recommendationStatus": recommendation_status,
            "measuredExampleCount": measured_examples,
            "minimumMeasuredExamples": REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES,
            "operatorApprovalRequired": recommendation_status == "advisory",
            "rankings": self.compact_recommendation_rankings(rankings),
        }

    def recommendation_variation_preset_evidence(
        self, rankings: list[dict[str, Any]], selected_preset: str | None
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
            "\n            SELECT * FROM recommendation_accuracy_reports\n            WHERE campaign_id = ?\n              AND account_key IN (?, '')\n            ORDER BY CASE WHEN account_key = ? THEN 0 ELSE 1 END, updated_at DESC\n            LIMIT 1\n            ",
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
        return (adjusted_score, adjusted_confidence, adjusted_reason, risks)

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
            performance_score * 0.4
            + reference_score * 0.2
            + audit_score * 0.15
            + account_score * 0.1
            + novelty_score * 0.1
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
        if reference_pattern_evidence["recommendationStatus"] == "advisory":
            risks.append("reference_pattern_evidence_advisory")
            confidence = "low"
            confidence_reason = f"{confidence_reason}; reference pattern has fewer than {REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES} measured examples"
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
            selected_audio=selected_audio, audio_recommendations=audio_recommendations
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
            "advisory": reference_pattern_evidence["recommendationStatus"]
            == "advisory",
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
                "\n                INSERT INTO recommendation_items (\n                  id, run_id, rank, target_account, reference_pattern_id, source_asset_id,\n                  rendered_asset_id, recommendation_graph_id, status, score, confidence,\n                  reasons_json, risks_json, evidence_json, data_quality_json, decision_json,\n                  outcome_json, baseline_json, measurement_version, output_json, created_at\n                )\n                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', NULL, ?, ?)\n                ON CONFLICT(run_id, rank) DO UPDATE SET\n                  target_account = excluded.target_account,\n                  reference_pattern_id = excluded.reference_pattern_id,\n                  source_asset_id = excluded.source_asset_id,\n                  rendered_asset_id = excluded.rendered_asset_id,\n                  recommendation_graph_id = excluded.recommendation_graph_id,\n                  score = excluded.score,\n                  confidence = excluded.confidence,\n                  reasons_json = excluded.reasons_json,\n                  risks_json = excluded.risks_json,\n                  evidence_json = excluded.evidence_json,\n                  data_quality_json = excluded.data_quality_json,\n                  output_json = excluded.output_json\n                ",
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
