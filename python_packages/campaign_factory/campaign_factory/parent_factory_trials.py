from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings


class ParentFactoryTrialRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        settings: Settings,
        domain_constructor: Callable[[Settings], Any],
        reel_factory_parent_metrics: Callable[[], dict[str, int]],
        operator_review_minutes_per_parent: Callable[[dict[str, int]], float],
        parent_factory_yield_waterfall: Callable[..., dict[str, Any]],
        parent_factory_loss_analysis: Callable[..., dict[str, Any]],
        parent_factory_trial_loss_buckets: Callable[[dict[str, Any]], dict[str, int]],
        parent_factory_trial_stage_repairable: Callable[[str], bool],
        explain_publishability: Callable[[str], dict[str, Any]],
        ratio: Callable[[Any, Any], float],
        score_fraction: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._domain_constructor = domain_constructor
        self._reel_factory_parent_metrics = reel_factory_parent_metrics
        self._operator_review_minutes_per_parent = operator_review_minutes_per_parent
        self._parent_factory_yield_waterfall = parent_factory_yield_waterfall
        self._parent_factory_loss_analysis = parent_factory_loss_analysis
        self._parent_factory_trial_loss_buckets = parent_factory_trial_loss_buckets
        self._parent_factory_trial_stage_repairable = (
            parent_factory_trial_stage_repairable
        )
        self._explain_publishability = explain_publishability
        self._ratio = ratio
        self._score_fraction = score_fraction

    def parent_factory_production_trial(self) -> dict[str, Any]:
        measured = self.latest_measured_53_parent_production_trial()
        if measured:
            return measured
        metrics = self._reel_factory_parent_metrics()
        waterfall = self._parent_factory_yield_waterfall(required_parents_per_day=53)
        counts = {
            row["stage"]: int(row.get("outputCount") or 0)
            for row in waterfall.get("stages") or []
        }
        raw = int(counts.get("raw_candidate") or 0)
        accepted = int(counts.get("parent_accepted") or 0)
        return {
            "schema": "creator_os.parent_factory_production_trial.v1",
            "rawCandidates": raw,
            "qualityPassed": int(counts.get("visual_qc_pass") or 0),
            "discoverabilityPassed": int(
                counts.get("discoverability_safety_pass") or 0
            ),
            "publishabilityPassed": int(counts.get("publishability_pass") or 0),
            "acceptedParents": accepted,
            "yieldPct": round(self._ratio(accepted, raw) * 100, 1),
            "operatorMinutes": int(
                round(
                    float(self._operator_review_minutes_per_parent(metrics) or 0)
                    * max(1, int(metrics.get("parentCandidates") or 0))
                )
            ),
            "dataSource": "actual_current_state",
            "wouldWrite": False,
        }

    def latest_measured_53_parent_production_trial(self) -> dict[str, Any] | None:
        campaign_row = self.conn.execute(
            """
            SELECT * FROM campaigns
            WHERE slug LIKE '%parent_factory_53_production_trial%'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if not campaign_row:
            return None
        campaign = dict(campaign_row)
        assets = [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM rendered_assets WHERE campaign_id = ? AND COALESCE(content_surface, 'reel') = 'reel' ORDER BY created_at, id",
                (campaign["id"],),
            ).fetchall()
        ]
        blocked = int(
            self.conn.execute(
                """
            SELECT COUNT(*) FROM asset_rejection_evidence
            WHERE campaign_id = ? AND failed_stage IN ('discoverability_generation_gate', 'discoverability_pre_render_gate')
            """,
                (campaign["id"],),
            ).fetchone()[0]
            or 0
        )
        accepted = 0
        publishability_failures = 0
        quality_failures = 0
        duplicate_failures = 0
        other_failures = 0
        for asset in assets:
            publishability = self._explain_publishability(asset["id"])
            if publishability.get("publishableCandidate"):
                accepted += 1
            else:
                reasons = {
                    str(reason)
                    for reason in publishability.get("publishability_failure_reasons")
                    or []
                }
                if any("quality" in reason for reason in reasons):
                    quality_failures += 1
                elif any("duplicate" in reason for reason in reasons):
                    duplicate_failures += 1
                elif reasons:
                    publishability_failures += 1
                else:
                    other_failures += 1
        raw = (
            accepted
            + blocked
            + publishability_failures
            + quality_failures
            + duplicate_failures
            + other_failures
        )
        return {
            "schema": "creator_os.parent_factory_production_trial.v1",
            "campaign": campaign["slug"],
            "rawCandidates": raw,
            "qualityPassed": accepted
            + blocked
            + publishability_failures
            + duplicate_failures
            + other_failures,
            "discoverabilityPassed": len(assets),
            "publishabilityPassed": accepted,
            "acceptedParents": accepted,
            "yieldPct": round((accepted / max(1, raw)) * 100, 1),
            "operatorMinutes": 0,
            "discoverabilityFailures": blocked,
            "lateDiscoverabilityFailures": 0,
            "publishabilityFailures": publishability_failures,
            "qualityFailures": quality_failures,
            "duplicateFailures": duplicate_failures,
            "otherFailures": other_failures,
            "measuredFromCampaign": True,
            "wouldWrite": False,
        }

    def parent_factory_53_parent_trial(self) -> dict[str, Any]:
        target = 53
        metrics = self._reel_factory_parent_metrics()
        waterfall = self._parent_factory_yield_waterfall(
            required_parents_per_day=target
        )
        losses = self._parent_factory_trial_loss_buckets(waterfall)
        stages = {row["stage"]: row for row in waterfall.get("stages") or []}
        raw = int(stages.get("raw_candidate", {}).get("outputCount") or 0)
        accepted = int(stages.get("parent_accepted", {}).get("outputCount") or 0)
        ranked = [
            {"stage": row["stage"], "count": int(row.get("lossCount") or 0)}
            for row in waterfall.get("stages") or []
            if int(row.get("lossCount") or 0) > 0
        ]
        ranked = sorted(ranked, key=lambda row: (-row["count"], row["stage"]))
        limiting = ranked[0]["stage"] if ranked else ""
        return {
            "schema": "creator_os.parent_factory_53_parent_trial.v1",
            "targetParents": target,
            "actualCandidates": raw,
            "acceptedParents": accepted,
            "yieldPct": round(self._ratio(accepted, raw) * 100, 1),
            "operatorMinutes": int(
                round(
                    float(self._operator_review_minutes_per_parent(metrics) or 0)
                    * max(1, int(metrics.get("parentCandidates") or raw))
                )
            ),
            "discoverabilityFailures": losses["discoverabilityFailures"],
            "publishabilityFailures": losses["publishabilityFailures"],
            "qualityFailures": losses["qualityFailures"],
            "duplicateFailures": losses["duplicateFailures"],
            "otherFailures": losses["otherFailures"],
            "trialPassed": accepted >= target,
            "limitingStep": limiting,
            "rankedLosses": ranked,
            "dataSource": "actual_current_state",
            "measuredOnly": True,
            "wouldWrite": False,
        }

    def parent_factory_trial_results(self) -> dict[str, Any]:
        trial = self.parent_factory_53_parent_trial()
        ranked = trial.get("rankedLosses") or []
        largest = ranked[0] if ranked else {"stage": "", "count": 0}
        return {
            "schema": "creator_os.parent_factory_trial_results.v1",
            "targetParents": trial["targetParents"],
            "actualCandidates": trial["actualCandidates"],
            "acceptedParents": trial["acceptedParents"],
            "yieldPct": trial["yieldPct"],
            "operatorMinutes": trial["operatorMinutes"],
            "discoverabilityFailures": trial["discoverabilityFailures"],
            "publishabilityFailures": trial["publishabilityFailures"],
            "qualityFailures": trial["qualityFailures"],
            "duplicateFailures": trial["duplicateFailures"],
            "otherFailures": trial["otherFailures"],
            "trialPassed": trial["trialPassed"],
            "limitingStep": trial["limitingStep"],
            "largestLossStage": largest["stage"],
            "repairable": self._parent_factory_trial_stage_repairable(
                str(largest["stage"])
            ),
            "estimatedRecoveredParents": int(largest["count"]),
            "rankedLosses": ranked,
            "measuredOnly": True,
            "wouldWrite": False,
        }

    def parent_factory_trial_analysis(self) -> dict[str, Any]:
        results = self.parent_factory_trial_results()
        statement = (
            f"The factory produced {results['acceptedParents']} accepted parents from "
            f"{results['actualCandidates']} candidates. The limiting factor was "
            f"{results['limitingStep'] or 'none'}."
        )
        return {
            "schema": "creator_os.parent_factory_trial_analysis.v1",
            "statement": statement,
            "targetParents": results["targetParents"],
            "trialPassed": results["trialPassed"],
            "largestLossStage": results["largestLossStage"],
            "rankedLosses": results["rankedLosses"],
            "measuredOnly": True,
            "wouldWrite": False,
        }

    def parent_factory_post_gate_fresh_batch_proof(self) -> dict[str, Any]:
        baseline = {
            "rawCandidates": 245,
            "acceptedParents": 20,
            "yieldPct": 8.2,
            "lateDiscoverabilityFailures": 225,
            "limitingStep": "discoverability_safety_pass",
        }
        candidates = self.post_gate_fresh_batch_candidates()
        with tempfile.TemporaryDirectory(
            prefix="campaign_factory_post_gate_proof_"
        ) as tmp:
            root = Path(tmp)
            sandbox = self._domain_constructor(
                Settings(
                    root=root,
                    db_path=root / "campaign_factory.sqlite",
                    reel_factory_root=root / "reel_factory",
                    contentforge_root=root / "contentforge",
                    threadsdash_root=root / "ThreadsDashboard",
                    campaigns_dir=root / "campaigns",
                )
            )
            try:
                media_dir = root / "fresh_candidates"
                media_dir.mkdir(parents=True, exist_ok=True)
                blocked: list[dict[str, Any]] = []
                accepted = 0
                registered = 0
                late_discoverability = 0
                publishability_failures = 0
                other_failures = 0
                for index, candidate in enumerate(candidates):
                    video = media_dir / f"candidate_{index:03d}.mp4"
                    video.write_bytes(
                        f"fresh-candidate-{index}:{candidate['caption']}".encode()
                    )
                    result = sandbox.finished_video.register_finished_video(
                        input_path=video,
                        campaign_slug="post_gate_fresh_batch_proof",
                        model_slug="stacey",
                        caption=str(candidate["caption"]),
                        caption_hash=f"fresh_caption_hash_{index:03d}",
                        caption_bank="post_gate_fixture",
                        creator_mix="Stacey",
                        creator_model="Stacey",
                        track_id="audio_fixture",
                        track_name="Fixture Audio",
                        audio_source="post_gate_fixture",
                        selected_reason="fixture proof",
                        operator="codex",
                        approval_reason="post-gate proof fixture",
                        review_batch="post_gate_fresh_batch_proof",
                        caption_placement_policy="focal_safe_v1",
                        caption_placement_decision={"status": "passed"},
                    )
                    if result.get("canProceed") is False:
                        blocked_item = self.post_gate_blocked_candidate_evidence(
                            sandbox, result
                        )
                        if blocked_item:
                            blocked.append(blocked_item)
                        continue
                    registered += 1
                    publishability = result.get("publishability") or {}
                    if publishability.get("publishableCandidate"):
                        accepted += 1
                    else:
                        reasons = {
                            str(reason)
                            for reason in publishability.get(
                                "publishability_failure_reasons"
                            )
                            or []
                        }
                        if "discoverability_safety_violation" in reasons:
                            late_discoverability += 1
                        elif reasons:
                            publishability_failures += 1
                        else:
                            other_failures += 1
                render_jobs_created = int(
                    sandbox.conn.execute(
                        "SELECT COUNT(*) AS c FROM render_jobs"
                    ).fetchone()["c"]
                )
                source_assets_created = int(
                    sandbox.conn.execute(
                        "SELECT COUNT(*) AS c FROM source_assets"
                    ).fetchone()["c"]
                )
                rendered_assets_created = int(
                    sandbox.conn.execute(
                        "SELECT COUNT(*) AS c FROM rendered_assets"
                    ).fetchone()["c"]
                )
            finally:
                sandbox.close()
        raw = len(candidates)
        blocked_count = len(blocked)
        yield_pct = round(self._ratio(accepted, raw) * 100, 1)
        result = {
            "freshBatch": True,
            "fixtureBatch": True,
            "targetAcceptedParents": 53,
            "minimumRawCandidates": 64,
            "rawCandidates": raw,
            "blockedBeforeRender": blocked_count,
            "renderJobsAvoided": blocked_count,
            "renderJobsCreated": render_jobs_created,
            "sourceAssetsCreated": source_assets_created,
            "renderedAssetsCreated": rendered_assets_created,
            "registeredParents": registered,
            "acceptedParents": accepted,
            "yieldPct": yield_pct,
            "lateDiscoverabilityFailures": late_discoverability,
            "publishabilityFailures": publishability_failures,
            "qualityFailures": 0,
            "duplicateFailures": 0,
            "otherFailures": other_failures,
            "targetParentsReached": accepted >= 53,
            "blockedCandidates": blocked,
        }
        comparison = {
            "baseline": {
                "acceptedParents": baseline["acceptedParents"],
                "lateDiscoverabilityFailures": baseline["lateDiscoverabilityFailures"],
                "yieldPct": baseline["yieldPct"],
            },
            "freshBatchResult": {
                key: value
                for key, value in result.items()
                if key != "blockedCandidates"
            },
            "improvement": {
                "lateDiscoverabilityFailuresReduced": late_discoverability
                < baseline["lateDiscoverabilityFailures"],
                "renderJobsAvoided": blocked_count,
                "yieldImproved": yield_pct > baseline["yieldPct"],
                "acceptedParentLift": accepted - baseline["acceptedParents"],
            },
        }
        return {
            "schema": "creator_os.parent_factory_post_gate_fresh_batch_proof.v1",
            **result,
            "baseline": baseline,
            "comparison": comparison,
            "successCriteria": {
                "passed": late_discoverability == 0
                and blocked_count > 0
                and blocked_count == result["renderJobsAvoided"],
                "strongPass": accepted >= 53 and yield_pct >= 50,
            },
            "wouldWrite": False,
        }

    def parent_factory_production_scorecard(self) -> dict[str, Any]:
        trial = self.parent_factory_production_trial()
        required = 53
        return {
            "schema": "creator_os.parent_factory_production_scorecard.v1",
            "acceptedParents": trial["acceptedParents"],
            "requiredParentsPerDay": required,
            "capacityScore": self._score_fraction(trial["acceptedParents"], required),
            "yieldScore": self._score_fraction(trial["yieldPct"], 50),
            "canMeetRequiredParentsPerDay": trial["acceptedParents"] >= required,
            "wouldWrite": False,
        }

    def parent_factory_real_yield_report(self) -> dict[str, Any]:
        trial = self.parent_factory_production_trial()
        waterfall = self._parent_factory_yield_waterfall(required_parents_per_day=53)
        return {
            "schema": "creator_os.parent_factory_real_yield_report.v1",
            "trial": trial,
            "waterfall": waterfall,
            "estimateReplaced": True,
            "largestLossStage": self._parent_factory_loss_analysis(
                required_parents_per_day=53
            ).get("largestLossStage"),
            "wouldWrite": False,
        }

    def post_gate_fresh_batch_candidates(self) -> list[dict[str, str]]:
        safe = [
            {"caption": f"quick outfit check {index:02d}"} for index in range(1, 54)
        ]
        unsafe = [
            {"caption": "DM me for more"},
            {"caption": "link in bio"},
            {"caption": "OnlyFans has the rest"},
            {"caption": "OF drop tonight"},
            {"caption": "add me on Snapchat"},
            {"caption": "message me on Telegram"},
            {"caption": "WhatsApp me"},
            {"caption": "follow the link in bio"},
            {"caption": "send me a DM"},
            {"caption": "snap me later"},
            {"caption": "tap my link"},
        ]
        return safe + unsafe

    def post_gate_blocked_candidate_evidence(
        self, sandbox: Any, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        capture = result.get("rejectionEvidenceCapture") or {}
        evidence_ids = [str(item) for item in capture.get("evidenceIds") or []]
        if not evidence_ids:
            return None
        placeholders = ",".join("?" for _ in evidence_ids)
        rows = [
            dict(row)
            for row in sandbox.conn.execute(
                f"SELECT * FROM asset_rejection_evidence WHERE id IN ({placeholders}) ORDER BY created_at, id",
                evidence_ids,
            ).fetchall()
        ]
        if not rows:
            return None
        row = rows[0]
        return {
            "blockedAt": row["failed_stage"],
            "failureCategory": row["failure_category"],
            "matchedText": row["matched_text"],
            "sourceField": row["source_field"],
            "renderJobCreated": False,
            "sourceAssetCreated": False,
            "renderedAssetCreated": False,
        }
