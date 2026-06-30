from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


class RecommendationAccuracyRepository:
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
        audio_selection_payload: Callable[[str], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._json_load = json_load
        self._sanitize_for_storage = sanitize_for_storage
        self._campaign_by_slug = campaign_by_slug
        self._graph_id_for = graph_id_for
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._audio_selection_payload = audio_selection_payload

    def recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
        persist: bool = True,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        self.rebuild_recommendation_accuracy_observations(
            campaign["id"], account=account
        )
        observations = self.recommendation_accuracy_observations(
            campaign["id"],
            account=account,
            window_days=window_days,
        )
        prior_observations = self.recommendation_accuracy_observations(
            campaign["id"],
            account=account,
            before_window_days=window_days,
        )
        report = self.recommendation_accuracy_report_payload(
            campaign,
            observations,
            prior_observations,
            account=account,
            window_days=window_days,
        )
        if persist:
            self.persist_recommendation_accuracy_report(
                report, campaign["id"], account=account, window_days=window_days
            )
        return report

    def rebuild_recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        return self.recommendation_accuracy(
            campaign_slug, account=account, window_days=window_days, persist=True
        )

    def recommendation_proof_summary(self, campaign_id: str) -> dict[str, Any]:
        self.rebuild_recommendation_accuracy_observations(
            campaign_id, account=None, commit=True
        )
        rows = [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM recommendation_accuracy_observations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        ]
        segment = self.accuracy_segment(rows)
        return {
            "measuredCount": segment["measuredCount"],
            "provedCount": segment["provedCount"],
            "disprovedCount": segment["disprovedCount"],
            "inconclusiveCount": segment["inconclusiveCount"],
            "accuracyRate": segment["accuracyRate"],
            "recommendationTrustScore": self.recommendation_trust_score(rows, []),
        }

    def rebuild_recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT ri.*, rr.campaign_id
            FROM recommendation_items ri
            JOIN recommendation_runs rr ON rr.id = ri.run_id
            WHERE rr.campaign_id = ?
              AND ri.status IN ('measured', 'proved', 'disproved')
        """
        params: list[Any] = [campaign_id]
        if account:
            query += " AND ri.target_account = ?"
            params.append(account)
        query += " ORDER BY COALESCE(ri.measured_at, ri.created_at) DESC"
        rows = [dict(row) for row in self.conn.execute(query, params).fetchall()]
        observations = []
        for row in rows:
            observations.append(
                self.upsert_recommendation_accuracy_observation(row, commit=False)
            )
        if commit:
            self.conn.commit()
        return observations

    def upsert_recommendation_accuracy_observation(
        self, row: dict[str, Any], *, commit: bool = False
    ) -> dict[str, Any]:
        now = self._utc_now()
        output = self._json_load(row.get("output_json"), {})
        outcome = self._json_load(row.get("outcome_json"), {})
        baseline = self._json_load(row.get("baseline_json"), {})
        data_quality = self._json_load(row.get("data_quality_json"), {})
        evidence = self._json_load(row.get("evidence_json"), {})
        status = row.get("status") or "measured"
        outcome_score = outcome.get("outcomeScore")
        baseline_score = outcome.get("baselineScore")
        lift = None
        if outcome_score is not None and baseline_score is not None:
            lift = int(outcome_score) - int(baseline_score)
        is_success = None
        if status == "proved":
            is_success = 1
        elif status == "disproved":
            is_success = 0
        is_inconclusive = 1 if status == "measured" else 0
        data_quality_level = str(
            data_quality.get("level")
            or output.get("dataQuality", {}).get("level")
            or "low"
        )
        confidence = str(row.get("confidence") or output.get("confidence") or "low")
        confidence_bucket = self.recommendation_confidence_bucket(
            confidence, data_quality_level
        )
        selection = self.recommendation_audio_selection(row["id"])
        audio_match_status = self.recommendation_audio_match_status(output, selection)
        selected_audio_key = (
            selection.get("audioKey")
            or selection.get("catalogAudioId")
            or selection.get("platformAudioId")
        )
        measured_at = (
            row.get("measured_at") or outcome.get("measuredAt") or row.get("created_at")
        )
        observation_id = (
            f"recacc_{hashlib.sha256(row['id'].encode('utf-8')).hexdigest()[:12]}"
        )
        payload = {
            "recommendationItemId": row["id"],
            "recommendationRunId": row["run_id"],
            "campaignId": row["campaign_id"],
            "accountId": row.get("target_account"),
            "referencePatternId": row.get("reference_pattern_id"),
            "status": status,
            "confidence": confidence,
            "confidenceBucket": confidence_bucket,
            "dataQualityLevel": data_quality_level,
            "outcome": outcome,
            "baseline": baseline,
            "outcomeScore": outcome_score,
            "baselineScore": baseline_score,
            "lift": lift,
            "isSuccess": is_success,
            "isInconclusive": bool(is_inconclusive),
            "measurementVersion": row.get("measurement_version")
            or outcome.get("measurementVersion"),
            "measuredAt": measured_at,
            "audio": {
                "matchStatus": audio_match_status,
                "selectedAudioKey": selected_audio_key,
                "selection": selection or None,
            },
            "evidence": evidence,
            "complete": outcome_score is not None and baseline_score is not None,
        }
        self.conn.execute(
            """
            INSERT INTO recommendation_accuracy_observations (
              id, campaign_id, account_id, recommendation_item_id, recommendation_run_id,
              reference_pattern_id, selected_audio_key, audio_match_status, status,
              confidence, confidence_bucket, data_quality_level, outcome_score,
              baseline_score, lift, is_success, is_inconclusive, measured_at,
              measurement_version, payload_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recommendation_item_id) DO UPDATE SET
              campaign_id = excluded.campaign_id,
              account_id = excluded.account_id,
              recommendation_run_id = excluded.recommendation_run_id,
              reference_pattern_id = excluded.reference_pattern_id,
              selected_audio_key = excluded.selected_audio_key,
              audio_match_status = excluded.audio_match_status,
              status = excluded.status,
              confidence = excluded.confidence,
              confidence_bucket = excluded.confidence_bucket,
              data_quality_level = excluded.data_quality_level,
              outcome_score = excluded.outcome_score,
              baseline_score = excluded.baseline_score,
              lift = excluded.lift,
              is_success = excluded.is_success,
              is_inconclusive = excluded.is_inconclusive,
              measured_at = excluded.measured_at,
              measurement_version = excluded.measurement_version,
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            (
                observation_id,
                row["campaign_id"],
                row.get("target_account"),
                row["id"],
                row["run_id"],
                row.get("reference_pattern_id"),
                selected_audio_key,
                audio_match_status,
                status,
                confidence,
                confidence_bucket,
                data_quality_level,
                outcome_score,
                baseline_score,
                lift,
                is_success,
                is_inconclusive,
                measured_at,
                row.get("measurement_version") or outcome.get("measurementVersion"),
                json.dumps(
                    self._sanitize_for_storage(payload),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
            ),
        )
        observation_graph_id = self._ensure_graph_node(
            "recommendation_accuracy_observation",
            local_table="recommendation_accuracy_observations",
            local_id=observation_id,
            payload=payload,
        )
        item_graph_id = row.get("recommendation_graph_id") or self._graph_id_for(
            "recommendation_items", row["id"], entity_type="recommendation_item"
        )
        self._ensure_graph_edge(
            item_graph_id,
            observation_graph_id,
            "recommendation_item_to_recommendation_accuracy_observation",
        )
        for snapshot_id in self.recommendation_outcome_snapshot_ids(outcome, evidence):
            perf_graph_id = self._graph_id_for(
                "performance_snapshots", snapshot_id, entity_type="performance_snapshot"
            )
            self._ensure_graph_edge(
                perf_graph_id,
                observation_graph_id,
                "performance_snapshot_to_recommendation_accuracy_observation",
            )
        if selection.get("id"):
            selection_graph_id = self._graph_id_for(
                "audio_selections",
                selection["id"],
                entity_type="audio_selection",
                payload=selection,
            )
            self._ensure_graph_edge(
                selection_graph_id,
                observation_graph_id,
                "audio_selection_to_recommendation_accuracy_observation",
            )
        if commit:
            self.conn.commit()
        return payload | {"id": observation_id, "graphId": observation_graph_id}

    def recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        window_days: int | None = None,
        before_window_days: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
            SELECT * FROM recommendation_accuracy_observations
            WHERE campaign_id = ?
              AND (? IS NULL OR account_id = ?)
            ORDER BY COALESCE(measured_at, updated_at) DESC
            """,
                (campaign_id, account, account),
            ).fetchall()
        ]
        now = datetime.now(UTC)
        filtered = []
        for row in rows:
            observed_at = self.parse_datetime(
                row.get("measured_at") or row.get("updated_at")
            )
            if (
                window_days is not None
                and observed_at
                and observed_at < now - timedelta(days=max(1, int(window_days)))
            ):
                continue
            if (
                before_window_days is not None
                and observed_at
                and observed_at >= now - timedelta(days=max(1, int(before_window_days)))
            ):
                continue
            payload = self._json_load(row.get("payload_json"), {})
            payload.update(
                {
                    "id": row["id"],
                    "accountId": row["account_id"],
                    "referencePatternId": row["reference_pattern_id"],
                    "selectedAudioKey": row["selected_audio_key"],
                    "audioMatchStatus": row["audio_match_status"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "confidenceBucket": row["confidence_bucket"],
                    "dataQualityLevel": row["data_quality_level"],
                    "outcomeScore": row["outcome_score"],
                    "baselineScore": row["baseline_score"],
                    "lift": row["lift"],
                    "isSuccess": row["is_success"],
                    "isInconclusive": bool(row["is_inconclusive"]),
                    "measuredAt": row["measured_at"],
                    "updatedAt": row["updated_at"],
                }
            )
            filtered.append(payload)
        return filtered

    def recommendation_accuracy_report_payload(
        self,
        campaign: dict[str, Any],
        observations: list[dict[str, Any]],
        prior_observations: list[dict[str, Any]],
        *,
        account: str | None,
        window_days: int,
    ) -> dict[str, Any]:
        overall = self.accuracy_segment(observations)
        calibration = self.accuracy_grouped(observations, "confidenceBucket")
        drift = self.recommendation_accuracy_drift(observations, prior_observations)
        trust = self.recommendation_trust_score(observations, drift)
        return {
            "schema": "campaign_factory.recommendation_accuracy_report.v1",
            "campaign": campaign["slug"],
            "campaignGraphId": self._graph_id_for(
                "campaigns",
                campaign["id"],
                entity_type="campaign",
                payload={"slug": campaign["slug"]},
            ),
            "account": account,
            "windowDays": int(window_days),
            "generatedAt": self._utc_now(),
            "recommendationTrustScore": trust,
            "trustConfidence": self.recommendation_trust_confidence(
                overall["measuredCount"]
            ),
            "overall": overall,
            "calibration": calibration,
            "segments": {
                "accounts": self.accuracy_grouped(observations, "accountId"),
                "dataQuality": self.accuracy_grouped(observations, "dataQualityLevel"),
                "referencePatterns": self.accuracy_grouped(
                    observations, "referencePatternId"
                ),
                "selectedAudio": self.accuracy_grouped(
                    observations, "selectedAudioKey"
                ),
                "audioMatchStatus": self.accuracy_grouped(
                    observations, "audioMatchStatus"
                ),
            },
            "drift": drift,
            "observations": observations[:100],
            "warnings": []
            if observations
            else ["no_measured_recommendations_in_window"],
        }

    def persist_recommendation_accuracy_report(
        self,
        report: dict[str, Any],
        campaign_id: str,
        *,
        account: str | None,
        window_days: int,
    ) -> str:
        now = self._utc_now()
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "campaignId": campaign_id,
                    "account": account,
                    "windowDays": window_days,
                    "observationIds": [
                        item.get("id") for item in report.get("observations") or []
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        account_key = account or ""
        report_key = f"{campaign_id}:{account_key}:{window_days}:{input_hash}"
        report_id = f"recacc_report_{hashlib.sha256(report_key.encode('utf-8')).hexdigest()[:12]}"
        report["reportId"] = report_id
        report_graph_id = self._ensure_graph_node(
            "recommendation_accuracy_report",
            local_table="recommendation_accuracy_reports",
            local_id=report_id,
            payload=report,
        )
        report["reportGraphId"] = report_graph_id
        self.conn.execute(
            """
            INSERT INTO recommendation_accuracy_reports (
              id, campaign_id, account_id, account_key, window_days, input_hash, report_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, account_key, window_days, input_hash) DO UPDATE SET
              report_json = excluded.report_json,
              updated_at = excluded.updated_at
            """,
            (
                report_id,
                campaign_id,
                account,
                account_key,
                int(window_days),
                input_hash,
                json.dumps(
                    self._sanitize_for_storage(report),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                now,
            ),
        )
        self._ensure_graph_node(
            "recommendation_accuracy_report",
            local_table="recommendation_accuracy_reports",
            local_id=report_id,
            payload=report,
        )
        for observation in report.get("observations") or []:
            observation_graph_id = self._graph_id_for(
                "recommendation_accuracy_observations",
                observation.get("id"),
                entity_type="recommendation_accuracy_observation",
                payload=observation,
            )
            self._ensure_graph_edge(
                observation_graph_id,
                report_graph_id,
                "recommendation_accuracy_observation_to_report",
            )
        self.conn.commit()
        return report_id

    def accuracy_segment(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        measured_count = len(observations)
        proved = sum(1 for item in observations if item.get("status") == "proved")
        disproved = sum(1 for item in observations if item.get("status") == "disproved")
        inconclusive = sum(
            1
            for item in observations
            if item.get("status") == "measured" or item.get("isInconclusive")
        )
        denominator = proved + disproved
        lifts = [
            int(item["lift"]) for item in observations if item.get("lift") is not None
        ]
        return {
            "measuredCount": measured_count,
            "provedCount": proved,
            "disprovedCount": disproved,
            "inconclusiveCount": inconclusive,
            "accuracyDenominator": denominator,
            "accuracyRate": round(proved / denominator, 4) if denominator else None,
            "averageLift": round(sum(lifts) / len(lifts), 2) if lifts else None,
        }

    def accuracy_grouped(
        self, observations: list[dict[str, Any]], key: str
    ) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in observations:
            value = item.get(key)
            if value is None or value == "":
                value = "unknown"
            buckets.setdefault(str(value), []).append(item)
        grouped = []
        for value, rows in buckets.items():
            segment = self.accuracy_segment(rows)
            segment["key"] = value
            grouped.append(segment)
        grouped.sort(
            key=lambda item: (item["measuredCount"], item.get("accuracyRate") or -1),
            reverse=True,
        )
        return grouped

    def recommendation_accuracy_drift(
        self,
        recent: list[dict[str, Any]],
        prior: list[dict[str, Any]],
        *,
        min_sample: int = 5,
        drop_threshold: float = 0.15,
    ) -> list[dict[str, Any]]:
        warnings = []
        for dimension in (
            "confidenceBucket",
            "dataQualityLevel",
            "referencePatternId",
            "selectedAudioKey",
            "audioMatchStatus",
        ):
            recent_groups = {
                item["key"]: item for item in self.accuracy_grouped(recent, dimension)
            }
            prior_groups = {
                item["key"]: item for item in self.accuracy_grouped(prior, dimension)
            }
            for key, recent_segment in recent_groups.items():
                prior_segment = prior_groups.get(key)
                if not prior_segment:
                    continue
                if (
                    recent_segment["accuracyDenominator"] < min_sample
                    or prior_segment["accuracyDenominator"] < min_sample
                ):
                    continue
                recent_rate = recent_segment.get("accuracyRate")
                prior_rate = prior_segment.get("accuracyRate")
                if recent_rate is None or prior_rate is None:
                    continue
                drop = prior_rate - recent_rate
                if drop >= drop_threshold:
                    warnings.append(
                        {
                            "dimension": dimension,
                            "key": key,
                            "recentAccuracy": recent_rate,
                            "priorAccuracy": prior_rate,
                            "drop": round(drop, 4),
                            "recentSample": recent_segment["accuracyDenominator"],
                            "priorSample": prior_segment["accuracyDenominator"],
                        }
                    )
        warnings.sort(key=lambda item: item["drop"], reverse=True)
        return warnings[:10]

    def recommendation_trust_score(
        self, observations: list[dict[str, Any]], drift: list[dict[str, Any]]
    ) -> int:
        segment = self.accuracy_segment(observations)
        accuracy = segment.get("accuracyRate")
        if accuracy is None:
            score = 35
        else:
            score = round(accuracy * 70) + 15
        measured = segment["measuredCount"]
        if measured >= 30:
            score += 10
        elif measured >= 10:
            score += 5
        elif measured < 3:
            score -= 15
        incomplete = sum(
            1
            for item in observations
            if not (
                item.get("outcomeScore") is not None
                and item.get("baselineScore") is not None
            )
        )
        if observations:
            score -= round((incomplete / len(observations)) * 15)
        weak = sum(1 for item in observations if item.get("confidenceBucket") == "weak")
        if observations:
            score -= round((weak / len(observations)) * 10)
        score -= min(25, len(drift) * 5)
        return int(max(0, min(100, score)))

    def recommendation_trust_confidence(self, measured_count: int) -> str:
        if measured_count >= 30:
            return "strong"
        if measured_count >= 10:
            return "usable"
        if measured_count >= 3:
            return "directional"
        return "insufficient"

    def recommendation_confidence_bucket(
        self, confidence: str, data_quality_level: str
    ) -> str:
        if confidence == "high":
            return "strong"
        if confidence == "medium":
            return "directional" if data_quality_level == "low" else "usable"
        return "weak"

    def recommendation_audio_selection(
        self, recommendation_item_id: str
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM audio_selections WHERE recommendation_item_id = ? ORDER BY selected_at DESC, updated_at DESC LIMIT 1",
            (recommendation_item_id,),
        ).fetchone()
        if not row:
            return {}
        payload = self._audio_selection_payload(row["id"])
        audio = payload.get("audio") or {}
        return {
            "id": payload["id"],
            "status": payload.get("status"),
            "catalogAudioId": payload.get("audioCatalogId")
            or audio.get("catalogAudioId")
            or audio.get("catalog_audio_id"),
            "audioKey": payload.get("audioKey") or audio.get("audioKey"),
            "platformAudioId": audio.get("platformAudioId")
            or audio.get("platform_audio_id"),
            "audioTitle": audio.get("audioTitle") or audio.get("audio_title"),
            "payload": payload,
        }

    def recommendation_audio_match_status(
        self, output: dict[str, Any], selection: dict[str, Any]
    ) -> str:
        if not selection:
            audio_status = output.get("audioSelectionStatus")
            return str(audio_status or "unknown")
        if selection.get("status") in {"skipped", "blocked"}:
            return str(selection["status"])
        selected_keys = {
            str(value)
            for value in (
                selection.get("catalogAudioId"),
                selection.get("audioKey"),
                selection.get("platformAudioId"),
            )
            if value
        }
        recommendations = (output.get("audioRecommendations") or {}).get(
            "recommendations"
        ) or []
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            rec_keys = {
                str(value)
                for value in (
                    rec.get("catalogAudioId"),
                    rec.get("catalog_audio_id"),
                    rec.get("audioKey"),
                    rec.get("platformAudioId"),
                    rec.get("platform_audio_id"),
                    rec.get("audioId"),
                )
                if value
            }
            if selected_keys & rec_keys:
                return "recommended_audio_selected"
        return "manual_override"

    def recommendation_outcome_snapshot_ids(
        self, outcome: dict[str, Any], evidence: dict[str, Any]
    ) -> list[str]:
        ids = []
        links = evidence.get("links") if isinstance(evidence.get("links"), dict) else {}
        if links.get("performanceSnapshotId"):
            ids.append(str(links["performanceSnapshotId"]))
        for snapshot in outcome.get("snapshots") or []:
            if isinstance(snapshot, dict) and snapshot.get("id"):
                ids.append(str(snapshot["id"]))
        return list(dict.fromkeys(ids))

    def parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
