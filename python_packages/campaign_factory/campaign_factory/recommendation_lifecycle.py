from __future__ import annotations

import hashlib
import json
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)

from .persistence import json_load
from .recommendation_constants import (
    AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY_LEVEL,
    RECOMMENDATION_ITEM_STATUSES,
    RECOMMENDATION_MEASUREMENT_THRESHOLD,
    RECOMMENDATION_MEASUREMENT_VERSION,
)


class RecommendationLifecycleMixin:
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
            "reference_pattern_evidence_advisory",
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
            "advisory": True,
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
                    "reference_pattern_evidence_advisory",
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
                "\n                INSERT INTO recommendation_items (\n                  id, run_id, rank, target_account, reference_pattern_id,\n                  recommendation_graph_id, status, score, confidence, reasons_json,\n                  risks_json, evidence_json, data_quality_json, decision_json,\n                  outcome_json, baseline_json, measurement_version, output_json, created_at\n                )\n                VALUES (?, ?, 1, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', NULL, ?, ?)\n                ON CONFLICT(run_id, rank) DO UPDATE SET\n                  recommendation_graph_id = excluded.recommendation_graph_id,\n                  score = excluded.score,\n                  confidence = excluded.confidence,\n                  evidence_json = excluded.evidence_json,\n                  data_quality_json = excluded.data_quality_json,\n                  output_json = excluded.output_json\n                ",
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
            "\n            SELECT * FROM trust_exceptions\n            WHERE recommendation_item_id = ?\n            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC\n            ",
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
                f"\n                SELECT * FROM performance_snapshots\n                WHERE campaign_id = ?\n                  AND {learning_eligible_sql()}\n                  AND (rendered_asset_id IS NULL OR rendered_asset_id != ?)\n                ORDER BY snapshot_at DESC, created_at DESC\n                ",
                (campaign["id"], cutover_iso, row.get("rendered_asset_id") or ""),
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
            and (int(baseline_summary.get("count") or 0) >= 3)
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
                "contentForgeMode": "cli_local",
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
        if not force and (not linked_rendered_id):
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
        self, row: dict[str, Any], asset: dict[str, Any], *, commit: bool = True
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
        if audio.get("recommendations") and (
            not self.asset_has_final_audio_proof(asset)
        ):
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
            "\n            SELECT c.*\n            FROM recommendation_runs rr\n            JOIN campaigns c ON c.id = rr.campaign_id\n            WHERE rr.id = ?\n            ",
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
