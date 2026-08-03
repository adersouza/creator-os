from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .audio_learning_policy import measured_audio_performance
from .blocked_experiment_assignment import asset_source_family
from .blocked_experiment_reporting import apply_adopted_experiment_policy
from .learning_governance import (
    MINIMUM_POLICY_SAMPLE_COUNT,
    register_recommendation,
    resolve_active_learning_policy,
)
from .learning_score import (
    SUPPORTED_OBJECTIVES,
    account_reward_baselines,
    learning_summary,
)
from .persistence import json_load

LEARNING_RECOMMENDATION_SCOPE = "learning_consumption"
LEARNING_RECOMMENDATION_VERSION = "learning_consumption.v2"
PRIMARY_POLICY_BUCKET = "approximately_24h"
CONFIRMATORY_POLICY_BUCKET = "approximately_72h"
PRODUCTION_BUCKETS = (PRIMARY_POLICY_BUCKET,)
RECOMMENDATION_MAX_AGE_DAYS = 42
AUDIO_LEARNING_OBJECTIVE = "content_testing"
AUDIO_LEARNING_POLICY_VERSION = "exact_outcome_context_v1"

RECOMMENDATION_STATES = {
    "INELIGIBLE",
    "ADVISORY",
    "SUPERVISED_ACTIVE",
    "EXPIRED",
    "BLOCKED",
}


def evidence_tier(
    sample_count: int, *, controlled_matched_experiment: bool = False
) -> str:
    if controlled_matched_experiment:
        return "causal_evidence_candidate"
    if sample_count >= 10:
        return "stronger_directional_evidence"
    if sample_count >= 5:
        return "preliminary_direction"
    if sample_count >= 3:
        return "early_advisory"
    return "insufficient_evidence"


def observation_bucket(published_at: object, snapshot_at: object) -> str | None:
    published = _parse_time(published_at)
    observed = _parse_time(snapshot_at)
    if published is None or observed is None or observed < published:
        return None
    hours = (observed - published).total_seconds() / 3600
    if 0.75 <= hours <= 3:
        return "approximately_1h"
    if 20 <= hours <= 28:
        return "approximately_24h"
    if 68 <= hours <= 76:
        return "approximately_72h"
    return None


def recommendation_fingerprint(core: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(core),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validate_pack_fingerprint(pack: Mapping[str, Any]) -> None:
    core = {
        key: value
        for key, value in pack.items()
        if key not in {"schema", "packId", "sourceFingerprint", "generatedAt"}
    }
    fingerprint = recommendation_fingerprint(core)
    if pack.get("sourceFingerprint") != fingerprint:
        raise ValueError("knowledge pack sourceFingerprint does not match payload")
    if pack.get("packId") != f"kp_{fingerprint[:16]}":
        raise ValueError("knowledge pack packId does not match sourceFingerprint")


def build_measured_recommendations(
    pack: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    validate_pack_fingerprint(pack)
    reference_now = now or datetime.now(UTC)
    prompt_by_id = {
        str(card.get("id")): card
        for card in pack.get("promptCards") or []
        if isinstance(card, Mapping) and card.get("id")
    }
    recommendations: list[dict[str, Any]] = []
    for pattern in pack.get("patternCards") or []:
        if not isinstance(pattern, Mapping):
            continue
        grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = (
            defaultdict(list)
        )
        invalid_reasons: set[str] = set()
        eligible_provenance: list[dict[str, Any]] = []
        for provenance in pattern.get("measuredOutcomeProvenance") or []:
            if not isinstance(provenance, Mapping):
                invalid_reasons.add("invalid_outcome_provenance")
                continue
            outcome = provenance.get("outcome")
            if not isinstance(outcome, Mapping):
                invalid_reasons.add("missing_outcome")
                continue
            reasons = production_outcome_ineligibility_reasons(outcome)
            if reasons:
                invalid_reasons.update(reasons)
                continue
            eligible_provenance.append(dict(provenance))
            grouped[
                (
                    str(outcome["creatorId"]),
                    str(outcome["creatorIdentityProfile"]),
                    str(outcome["accountId"]),
                    str(outcome["contentIntent"]),
                    str(outcome["observationBucket"]),
                )
            ].append(dict(provenance))
        for scope, outcomes in sorted(grouped.items()):
            (
                creator_id,
                creator_identity_profile,
                account_id,
                content_intent,
                bucket,
            ) = scope
            recommendations.append(
                _pattern_recommendation(
                    pack=pack,
                    pattern=pattern,
                    prompt_by_id=prompt_by_id,
                    outcomes=outcomes,
                    creator_id=creator_id,
                    creator_identity_profile=creator_identity_profile,
                    account_id=account_id,
                    content_intent=content_intent,
                    bucket=bucket,
                    now=reference_now,
                    scope_pool=eligible_provenance,
                )
            )
        if not grouped and pattern.get("measuredOutcomeProvenance"):
            recommendations.append(
                _ineligible_pattern_recommendation(
                    pack=pack,
                    pattern=pattern,
                    reasons=sorted(invalid_reasons or {"no_eligible_outcome"}),
                )
            )
    return sorted(
        recommendations,
        key=lambda item: (
            str(item.get("campaignId") or ""),
            str(item.get("creatorId") or ""),
            str(item.get("accountId") or ""),
            str(item.get("contentIntent") or ""),
            -int(item.get("score") or 0),
            str(item["recommendationFingerprint"]),
        ),
    )


def build_audio_recommendations(
    conn: Any,
    *,
    pack: Mapping[str, Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    validate_pack_fingerprint(pack)
    reference_now = now or datetime.now(UTC)
    grouped: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    rows = conn.execute(
        "SELECT * FROM audio_performance_rollups ORDER BY id"
    ).fetchall()
    for row in rows:
        stats = json_load(row["stats_json"], {})
        links = stats.get("exactPublicationLinkages")
        if not isinstance(links, list):
            one = stats.get("exactPublicationLinkage")
            links = [one] if isinstance(one, Mapping) else []
        for link in links:
            if not isinstance(link, Mapping):
                continue
            required = (
                "tiktokMusicId",
                "trackSha256",
                "acousticFingerprint",
                "segmentStartSeconds",
                "segmentEndSeconds",
                "processedSegmentSha256",
                "instagramMediaId",
                "creator",
                "creatorIdentityProfile",
                "account",
                "intent",
                "observationBucket",
                "finalMediaSha256",
            )
            if any(
                link.get(field) is None
                or (
                    isinstance(link.get(field), str)
                    and not str(link.get(field)).strip()
                )
                for field in required
            ):
                continue
            grouped[
                (
                    str(row["campaign_id"]),
                    str(link["creator"]),
                    str(link["creatorIdentityProfile"]),
                    str(link["account"]),
                    str(link["intent"]),
                    str(link["observationBucket"]),
                    str(row["audio_catalog_id"]),
                )
            ].append({**dict(link), "rollupScore": row["score"]})
    recommendations: list[dict[str, Any]] = []
    for scope, links in sorted(grouped.items()):
        campaign_id, creator, identity, account, intent, bucket, catalog_id = scope
        unique = {
            str(link["instagramMediaId"]): link
            for link in links
            if link.get("instagramMediaId")
        }
        sample_count = len(unique)
        eligible = (
            sample_count >= MINIMUM_POLICY_SAMPLE_COUNT and bucket in PRODUCTION_BUCKETS
        )
        latest = max(str(link.get("snapshotAt") or "") for link in unique.values())
        score = max(float(link.get("rollupScore") or 0.0) for link in unique.values())
        core = {
            "schema": LEARNING_RECOMMENDATION_VERSION,
            "recommendationKind": "audio",
            "knowledgePackId": pack["packId"],
            "knowledgePackSourceFingerprint": pack["sourceFingerprint"],
            "campaignId": campaign_id,
            "creatorId": creator,
            "creatorIdentityProfile": identity,
            "accountId": account,
            "contentIntent": intent,
            "observationBucket": bucket,
            "referencePatternId": None,
            "measuredOutcomeIds": sorted(unique),
            "preferredAudioCatalogId": catalog_id,
        }
        fingerprint = recommendation_fingerprint(core)
        age_days = max(
            0.0,
            (reference_now - (_parse_time(latest) or reference_now)).total_seconds()
            / 86400,
        )
        recommendations.append(
            {
                **core,
                "recommendationCore": core,
                "recommendationFingerprint": fingerprint,
                "classification": "ADVISORY",
                "eligibleForOperatorApproval": eligible,
                "evidenceTier": evidence_tier(sample_count),
                "evidenceLabel": evidence_tier(sample_count).replace("_", " "),
                "sampleCount": sample_count,
                "score": int(round(score)),
                "confidence": "medium" if eligible else "low",
                "latestObservationAt": latest,
                "recencyDays": round(age_days, 4),
                "reasons": [
                    f"{sample_count} exact publication-linked audio outcomes",
                    f"observation cohort {bucket}",
                    "existing Campaign audio performance score reused",
                ],
                "risks": [] if eligible else ["insufficient_or_early_audio_evidence"],
            }
        )
    return recommendations


def production_outcome_ineligibility_reasons(
    outcome: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    required = (
        "performanceSnapshotId",
        "instagramMediaId",
        "creatorId",
        "creatorIdentityProfile",
        "accountId",
        "contentIntent",
        "publishedAt",
        "snapshotAt",
        "observationBucket",
        "sourceAssetId",
        "sourceSha256",
        "finalMediaSha256",
    )
    for field in required:
        if not str(outcome.get(field) or "").strip():
            reasons.append(f"missing_{field}")
    if outcome.get("historySource") != "metric_history":
        reasons.append("fallback_history_source")
    if outcome.get("metricsEligible") is not True:
        reasons.append("metrics_not_eligible")
    if outcome.get("lineageV2Valid") is not True:
        reasons.append("invalid_lineage")
    if outcome.get("publicationStatus") != "published":
        reasons.append("failed_or_unpublished")
    if outcome.get("fixture") is True:
        reasons.append("fixture")
    # A boolean assertion cannot establish a controlled experiment. The governed
    # observed-experiment lane validates the immutable design and assignment
    # receipts separately; generic knowledge-pack outcomes must fail closed.
    if outcome.get("controlledMatchedExperiment") is True:
        reasons.append("unverified_experiment_evidence")
    governance = outcome.get("governanceEligibility")
    if isinstance(governance, Mapping):
        if governance.get("eligible") is not True:
            reasons.extend(
                f"governance_{reason}" for reason in governance.get("reasons") or []
            )
        if not str(governance.get("fingerprint") or "").strip():
            reasons.append("missing_governance_fingerprint")
    objective = str(outcome.get("learningObjective") or "").strip()
    if objective and objective not in SUPPORTED_OBJECTIVES:
        reasons.append("unsupported_learning_objective")
    expected_bucket = observation_bucket(
        outcome.get("publishedAt"), outcome.get("snapshotAt")
    )
    if expected_bucket is None:
        reasons.append("unknown_observation_age")
    elif outcome.get("observationBucket") != expected_bucket:
        reasons.append("observation_bucket_mismatch")
    return sorted(set(reasons))


def persist_measured_recommendations(
    conn: Any,
    recommendations: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    by_campaign: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for recommendation in recommendations:
        campaign_id = str(recommendation.get("campaignId") or "").strip()
        if campaign_id:
            by_campaign[campaign_id].append(recommendation)
    inserted_runs = 0
    inserted_items = 0
    unchanged_items = 0
    superseded_items = 0
    with conn:
        current_pack_id = str(pack["packId"])
        current_pack_fingerprint = str(pack["sourceFingerprint"])
        historical = conn.execute(
            """
            SELECT ri.id, ri.status, ri.evidence_json, ri.decision_json
            FROM recommendation_items ri
            JOIN recommendation_runs rr ON rr.id = ri.run_id
            WHERE rr.scope = ? AND ri.status IN ('proposed', 'accepted')
            """,
            (LEARNING_RECOMMENDATION_SCOPE,),
        ).fetchall()
        for row in historical:
            evidence = json_load(row["evidence_json"], {})
            if (
                evidence.get("knowledgePackId") == current_pack_id
                and evidence.get("knowledgePackSourceFingerprint")
                == current_pack_fingerprint
            ):
                continue
            decision = json_load(row["decision_json"], {})
            decision["supersession"] = {
                "schema": "campaign_factory.recommendation_supersession.v1",
                "reason": "knowledge_pack_changed",
                "previousKnowledgePackId": evidence.get("knowledgePackId"),
                "previousKnowledgePackSourceFingerprint": evidence.get(
                    "knowledgePackSourceFingerprint"
                ),
                "currentKnowledgePackId": current_pack_id,
                "currentKnowledgePackSourceFingerprint": current_pack_fingerprint,
                "supersededAt": now,
            }
            conn.execute(
                """
                UPDATE recommendation_items
                SET status = 'superseded', decision_json = ?
                WHERE id = ? AND status IN ('proposed', 'accepted')
                """,
                (
                    json.dumps(decision, ensure_ascii=False, sort_keys=True),
                    row["id"],
                ),
            )
            superseded_items += 1
        for campaign_id, items in sorted(by_campaign.items()):
            campaign_exists = conn.execute(
                "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if campaign_exists is None:
                continue
            input_core = {
                "schema": LEARNING_RECOMMENDATION_VERSION,
                "campaignId": campaign_id,
                "knowledgePackId": pack["packId"],
                "knowledgePackSourceFingerprint": pack["sourceFingerprint"],
                "recommendationFingerprints": [
                    item["recommendationFingerprint"] for item in items
                ],
            }
            input_hash = recommendation_fingerprint(input_core)
            run_id = f"recrun_learning_{input_hash[:16]}"
            existing_run = conn.execute(
                "SELECT 1 FROM recommendation_runs WHERE id = ?", (run_id,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO recommendation_runs (
                  id, campaign_id, scope, scoring_version, input_hash,
                  input_snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    campaign_id,
                    LEARNING_RECOMMENDATION_SCOPE,
                    LEARNING_RECOMMENDATION_VERSION,
                    input_hash,
                    json.dumps(input_core, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            inserted_runs += int(existing_run is None)
            for rank, recommendation in enumerate(items, start=1):
                item_id = (
                    "recitem_learning_"
                    + str(recommendation["recommendationFingerprint"])[:16]
                )
                existing_item = conn.execute(
                    "SELECT evidence_json FROM recommendation_items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                evidence = dict(recommendation)
                previous = conn.execute(
                    """
                    SELECT ri.id
                    FROM recommendation_items ri
                    JOIN recommendation_runs rr ON rr.id = ri.run_id
                    WHERE rr.scope = ? AND rr.campaign_id = ?
                      AND ri.reference_pattern_id = ? AND ri.id <> ?
                    ORDER BY ri.created_at DESC LIMIT 1
                    """,
                    (
                        LEARNING_RECOMMENDATION_SCOPE,
                        campaign_id,
                        recommendation.get("referencePatternId"),
                        item_id,
                    ),
                ).fetchone()
                evidence["previousRecommendationId"] = (
                    str(previous["id"]) if previous else None
                )
                conn.execute(
                    """
                    INSERT INTO recommendation_items (
                      id, run_id, rank, target_account, reference_pattern_id,
                      source_asset_id, status, execution_status, score, confidence,
                      reasons_json, risks_json, evidence_json, data_quality_json,
                      decision_json, outcome_json, baseline_json, output_json,
                      created_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, NULL, 'proposed', 'not_started', ?, ?,
                      ?, ?, ?, ?, '{}', '{}', '{}', ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                      evidence_json = excluded.evidence_json,
                      data_quality_json = excluded.data_quality_json,
                      output_json = excluded.output_json
                    """,
                    (
                        item_id,
                        run_id,
                        rank,
                        recommendation.get("accountId"),
                        recommendation.get("referencePatternId"),
                        int(recommendation.get("score") or 0),
                        str(recommendation.get("confidence") or "low"),
                        json.dumps(
                            recommendation.get("reasons") or [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(
                            recommendation.get("risks") or [],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        json.dumps(
                            {
                                "sampleSize": recommendation.get("sampleCount"),
                                "observationBucket": recommendation.get(
                                    "observationBucket"
                                ),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                register_recommendation(
                    conn,
                    recommendation_item_id=item_id,
                    evidence=evidence,
                )
                if existing_item is None:
                    inserted_items += 1
                else:
                    unchanged_items += 1
    return {
        "runsInserted": inserted_runs,
        "itemsInserted": inserted_items,
        "itemsUnchanged": unchanged_items,
        "itemsSuperseded": superseded_items,
    }


def apply_learning_to_production_plan(
    conn: Any,
    *,
    creator: str,
    creator_identity_profile: str,
    account: str | None,
    intent: str,
    sources: Sequence[Mapping[str, Any]],
    base_prompt: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    base_sources = [dict(source) for source in sources]
    base_order = [str(source["id"]) for source in base_sources]
    decision = {
        "schema": "campaign_factory.learning_decision_receipt.v1",
        "learningConsulted": False,
        "learningEligible": False,
        "learningApplied": False,
        "finalChoiceChanged": False,
        "knowledgePackId": None,
        "knowledgePackSourceFingerprint": None,
        "recommendationIds": [],
        "match": {
            "creator": creator,
            "creatorIdentityProfile": creator_identity_profile,
            "account": account,
            "intent": intent,
        },
        "eligibleCandidateSetBeforeLearning": base_order,
        "baseOrdering": base_order,
        "learnedScoreAdjustments": [],
        "finalSelectedSource": base_order[0] if base_order else None,
        "finalSelectedPattern": None,
        "finalSelectedAudio": None,
        "learningInfluenced": False,
        "reason": "deterministic_production_default",
        "fallbackReason": None,
    }
    try:
        row = conn.execute(
            """
            SELECT * FROM reference_knowledge_packs
            ORDER BY generated_at DESC, imported_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
    except Exception as exc:
        if "no such table" not in str(exc).lower():
            raise
        decision["fallbackReason"] = "no_persisted_pack"
        return _apply_blocked_source_family_policy(
            conn,
            creator=creator,
            account=account,
            intent=intent,
            sources=base_sources,
            prompt=base_prompt,
            decision=decision,
        )
    if row is None:
        decision["fallbackReason"] = "no_persisted_pack"
        return _apply_blocked_source_family_policy(
            conn,
            creator=creator,
            account=account,
            intent=intent,
            sources=base_sources,
            prompt=base_prompt,
            decision=decision,
        )
    decision["learningConsulted"] = True
    pack = json_load(row["payload_json"], {})
    try:
        validate_pack_fingerprint(pack)
    except ValueError:
        decision["fallbackReason"] = "no_eligible_recommendation"
        decision["reason"] = "invalid_knowledge_pack_fingerprint"
        return _apply_blocked_source_family_policy(
            conn,
            creator=creator,
            account=account,
            intent=intent,
            sources=base_sources,
            prompt=base_prompt,
            decision=decision,
        )
    decision["knowledgePackId"] = pack.get("packId")
    decision["knowledgePackSourceFingerprint"] = pack.get("sourceFingerprint")
    rows = conn.execute(
        """
        SELECT ri.*, rr.input_snapshot_json
        FROM recommendation_items ri
        JOIN recommendation_runs rr ON rr.id = ri.run_id
        WHERE rr.scope = ? AND ri.status IN ('proposed', 'accepted', 'rejected')
        ORDER BY ri.score DESC, ri.created_at DESC, ri.id
        """,
        (LEARNING_RECOMMENDATION_SCOPE,),
    ).fetchall()
    if not rows:
        decision["fallbackReason"] = "no_eligible_recommendation"
        return _apply_blocked_source_family_policy(
            conn,
            creator=creator,
            account=account,
            intent=intent,
            sources=base_sources,
            prompt=base_prompt,
            decision=decision,
        )
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    mismatch_reasons: set[str] = set()
    reference_now = now or datetime.now(UTC)
    for stored in rows:
        evidence = json_load(stored["evidence_json"], {})
        if evidence.get("knowledgePackId") != pack.get("packId"):
            mismatch_reasons.add("expired_evidence")
            continue
        core = evidence.get("recommendationCore")
        if not isinstance(core, Mapping) or recommendation_fingerprint(
            core
        ) != evidence.get("recommendationFingerprint"):
            mismatch_reasons.add("no_eligible_recommendation")
            continue
        if evidence.get("creatorId") != creator:
            mismatch_reasons.add("no_creator_match")
            continue
        if evidence.get("creatorIdentityProfile") != creator_identity_profile:
            mismatch_reasons.add("no_creator_match")
            continue
        if evidence.get("accountId") != account:
            mismatch_reasons.add("no_account_match")
            continue
        if evidence.get("contentIntent") != intent:
            mismatch_reasons.add("no_intent_match")
            continue
        if evidence.get("classification") != "ADVISORY":
            mismatch_reasons.add("no_eligible_recommendation")
            continue
        latest = _parse_time(evidence.get("latestObservationAt"))
        if (
            latest is None
            or (reference_now - latest).total_seconds()
            > RECOMMENDATION_MAX_AGE_DAYS * 86400
        ):
            mismatch_reasons.add("expired_evidence")
            continue
        if stored["status"] == "rejected":
            mismatch_reasons.add("operator_not_approved")
            continue
        if stored["status"] != "accepted":
            mismatch_reasons.add("advisory_only")
            continue
        policy = resolve_active_learning_policy(
            conn,
            recommendation_item_id=str(stored["id"]),
            recommendation_fingerprint=str(
                evidence.get("recommendationFingerprint") or ""
            ),
            creator=creator,
            creator_identity_profile=creator_identity_profile,
            account_id=account,
            content_intent=intent,
            now=reference_now,
        )
        if policy is None:
            mismatch_reasons.add("production_policy_not_authorized")
            continue
        evidence["productionPolicyRevision"] = policy
        matched.append((dict(stored), evidence))
    if not matched:
        priority = (
            "no_creator_match",
            "no_account_match",
            "no_intent_match",
            "advisory_only",
            "production_policy_not_authorized",
            "expired_evidence",
            "operator_not_approved",
            "no_eligible_recommendation",
        )
        decision["fallbackReason"] = next(
            (reason for reason in priority if reason in mismatch_reasons),
            "no_eligible_recommendation",
        )
        return _apply_blocked_source_family_policy(
            conn,
            creator=creator,
            account=account,
            intent=intent,
            sources=base_sources,
            prompt=base_prompt,
            decision=decision,
        )
    stored, evidence = matched[0]
    selected_sources = list(base_sources)
    preferred_sha = str(evidence.get("preferredSourceSha256") or "")
    if preferred_sha:
        preferred = [
            source
            for source in selected_sources
            if str(source.get("content_hash") or "") == preferred_sha
            and str(source.get("status") or "").lower() == "approved"
        ]
        if preferred:
            selected_sources = preferred + [
                source
                for source in selected_sources
                if str(source.get("content_hash") or "") != preferred_sha
            ]
    selected_prompt = base_prompt
    preferred_prompt = str(evidence.get("preferredPrompt") or "").strip()
    if preferred_prompt and _prompt_is_imported_and_approved(
        conn,
        reference_pattern_id=str(evidence.get("referencePatternId") or ""),
        prompt=preferred_prompt,
    ):
        selected_prompt = preferred_prompt
    final_order = [str(source["id"]) for source in selected_sources]
    influenced = final_order != base_order or selected_prompt != base_prompt
    decision.update(
        {
            "recommendationIds": [str(stored["id"])],
            "learningEligible": True,
            "learningApplied": True,
            "finalChoiceChanged": influenced,
            "learnedScoreAdjustments": [
                {
                    "recommendationId": str(stored["id"]),
                    "score": stored["score"],
                    "preferredSourceSha256": preferred_sha or None,
                    "promptChanged": selected_prompt != base_prompt,
                }
            ],
            "finalSelectedSource": final_order[0] if final_order else None,
            "finalSelectedPattern": evidence.get("referencePatternId"),
            "learningInfluenced": influenced,
            "reason": (
                "operator_authorized_learning_policy"
                if influenced
                else "authorized_policy_left_choice_unchanged"
            ),
            "fallbackReason": None if influenced else "final_choice_unchanged",
        }
    )
    return _apply_blocked_source_family_policy(
        conn,
        creator=creator,
        account=account,
        intent=intent,
        sources=selected_sources,
        prompt=selected_prompt,
        decision=decision,
    )


def _apply_blocked_source_family_policy(
    conn: Any,
    *,
    creator: str,
    account: str | None,
    intent: str,
    sources: list[dict[str, Any]],
    prompt: str,
    decision: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    if account is None or not sources:
        return sources, prompt, decision
    families = [
        asset_source_family(source, fallback_to_asset_identity=False)
        for source in sources
    ]
    if not all(families):
        return sources, prompt, decision
    eligible_families = list(dict.fromkeys(families))
    base_family = families[0]
    selected_family, policy_receipt = apply_adopted_experiment_policy(
        conn,
        creator=creator,
        account_id=account,
        content_intent=intent,
        changed_variable="source_family",
        eligible_values=eligible_families,
        base_value=base_family,
    )
    if not policy_receipt["learningApplied"]:
        return sources, prompt, decision
    selected_sources = [
        source
        for source in sources
        if asset_source_family(source, fallback_to_asset_identity=False)
        == selected_family
    ]
    changed = selected_sources != sources
    decision.update(
        {
            "learningConsulted": True,
            "learningEligible": True,
            "learningApplied": True,
            "learningInfluenced": bool(decision["learningInfluenced"] or changed),
            "finalChoiceChanged": bool(decision["finalChoiceChanged"] or changed),
            "finalSelectedSource": (
                str(selected_sources[0]["id"]) if selected_sources else None
            ),
            "blockedExperimentPolicy": policy_receipt,
            "eligibleFactorValuesBeforeLearning": eligible_families,
            "baseFactorValue": base_family,
            "finalFactorValue": selected_family,
            "reason": (
                "operator_adopted_blocked_experiment"
                if changed
                else "adopted_experiment_policy_left_choice_unchanged"
            ),
            "fallbackReason": None if changed else "final_choice_unchanged",
        }
    )
    return selected_sources, prompt, decision


def recommendation_state(
    stored_status: str,
    evidence: Mapping[str, Any],
    *,
    current_pack_id: str | None,
    now: datetime | None = None,
) -> str:
    if stored_status == "rejected":
        return "BLOCKED"
    if stored_status == "superseded":
        return "EXPIRED"
    if evidence.get("knowledgePackId") != current_pack_id:
        return "EXPIRED"
    latest = _parse_time(evidence.get("latestObservationAt"))
    reference_now = now or datetime.now(UTC)
    if (
        latest is None
        or (reference_now - latest).total_seconds()
        > RECOMMENDATION_MAX_AGE_DAYS * 86400
    ):
        return "EXPIRED"
    if evidence.get("classification") == "INELIGIBLE":
        return "INELIGIBLE"
    if (
        stored_status == "accepted"
        and evidence.get("eligibleForOperatorApproval") is True
        and int(evidence.get("sampleCount") or 0) >= MINIMUM_POLICY_SAMPLE_COUNT
    ):
        return "SUPERVISED_ACTIVE"
    return "ADVISORY"


def approved_audio_performance(
    conn: Any,
    *,
    creator: str,
    creator_identity_profile: str,
    account: str | None,
    intent: str,
    now: datetime | None = None,
) -> tuple[dict[str, float], list[str]]:
    try:
        pack = conn.execute(
            """
            SELECT id FROM reference_knowledge_packs
            ORDER BY generated_at DESC, imported_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return {}, []
        raise
    if pack is None:
        return {}, []
    current_pack_id = str(pack["id"])
    rows = conn.execute(
        """
        SELECT ri.* FROM recommendation_items ri
        JOIN recommendation_runs rr ON rr.id = ri.run_id
        WHERE rr.scope = ? AND ri.status = 'accepted'
        ORDER BY ri.score DESC, ri.id
        """,
        (LEARNING_RECOMMENDATION_SCOPE,),
    ).fetchall()
    scores: dict[str, float] = {}
    recommendation_ids: list[str] = []
    for row in rows:
        evidence = json_load(row["evidence_json"], {})
        if evidence.get("recommendationKind") != "audio":
            continue
        policy = resolve_active_learning_policy(
            conn,
            recommendation_item_id=str(row["id"]),
            recommendation_fingerprint=str(
                evidence.get("recommendationFingerprint") or ""
            ),
            creator=creator,
            creator_identity_profile=creator_identity_profile,
            account_id=account,
            content_intent=intent,
            now=now,
        )
        if (
            evidence.get("creatorId") != creator
            or evidence.get("creatorIdentityProfile") != creator_identity_profile
            or evidence.get("accountId") != account
            or evidence.get("contentIntent") != intent
            or recommendation_state(
                str(row["status"]),
                evidence,
                current_pack_id=current_pack_id,
                now=now,
            )
            != "SUPERVISED_ACTIVE"
            or policy is None
        ):
            continue
        catalog_id = str(evidence.get("preferredAudioCatalogId") or "")
        if catalog_id:
            scores[catalog_id] = float(row["score"] or 0.0)
            recommendation_ids.append(str(row["id"]))
    return scores, recommendation_ids


def _ranking_adjustment(score: float) -> float:
    return round(max(-8.0, min(10.0, (float(score) - 50.0) * 0.2)), 4)


def audio_policy_for_candidates(
    conn: Any,
    *,
    candidates: Sequence[Any],
    creator: str,
    creator_identity_profile: str,
    account: str | None,
    intent: str,
    now: datetime,
) -> dict[str, Any]:
    approved_scores, recommendation_ids = approved_audio_performance(
        conn,
        creator=creator,
        creator_identity_profile=creator_identity_profile,
        account=account,
        intent=intent,
        now=now,
    )
    catalog_to_track = {
        str(candidate.advisory_labels.get("audioCatalogId")): str(
            candidate.canonical_track_id or candidate.candidate_id
        )
        for candidate in candidates
        if candidate.advisory_labels.get("audioCatalogId")
    }
    measured_scores, measured_evidence = measured_audio_performance(
        conn,
        catalog_ids=set(catalog_to_track),
        creator=creator,
        creator_identity_profile=creator_identity_profile,
        account=account,
        intent=intent,
        now=now,
        observation_bucket=observation_bucket,
        production_buckets=PRODUCTION_BUCKETS,
        minimum_examples=MINIMUM_POLICY_SAMPLE_COUNT,
        objective=AUDIO_LEARNING_OBJECTIVE,
        policy_version=AUDIO_LEARNING_POLICY_VERSION,
    )
    combined = {
        catalog_id: _ranking_adjustment(score)
        for catalog_id, score in approved_scores.items()
        if catalog_id in catalog_to_track
    }
    combined.update(measured_scores)
    return {
        "policyVersion": AUDIO_LEARNING_POLICY_VERSION,
        "scoreAdjustments": {
            catalog_to_track[catalog_id]: adjustment
            for catalog_id, adjustment in combined.items()
        },
        "recommendationIds": recommendation_ids,
        "measuredEvidence": measured_evidence,
        "preferredSegmentOffsets": {
            catalog_to_track[str(item["audioCatalogId"])]: [
                float(item["bestSegmentOffsetSeconds"])
            ]
            for item in measured_evidence
            if item.get("bestSegmentOffsetSeconds") is not None
        },
    }


def audio_performance_for_candidates(
    conn: Any,
    *,
    candidates: Sequence[Any],
    creator: str,
    creator_identity_profile: str,
    account: str | None,
    intent: str,
    now: datetime,
) -> tuple[dict[str, float], list[str]]:
    policy = audio_policy_for_candidates(
        conn,
        candidates=candidates,
        creator=creator,
        creator_identity_profile=creator_identity_profile,
        account=account,
        intent=intent,
        now=now,
    )
    return policy["scoreAdjustments"], policy["recommendationIds"]


def persist_learning_decision_receipt(
    conn: Any,
    *,
    decision: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> str:
    """Persist one idempotent receipt after an applied create invocation."""

    output_lineage = []
    for result in results:
        nested = result.get("result")
        nested = nested if isinstance(nested, Mapping) else {}
        fulfillment = nested.get("audioFulfillment")
        fulfillment = fulfillment if isinstance(fulfillment, Mapping) else {}
        registered = nested.get("registeredAsset")
        registered = registered if isinstance(registered, Mapping) else {}
        output_lineage.append(
            {
                "jobId": result.get("jobId"),
                "status": result.get("status"),
                "renderedAssetId": registered.get("id"),
                "finalMediaSha256": (
                    fulfillment.get("finalVideoSha256")
                    or registered.get("content_hash")
                ),
                "audioSelection": (
                    (fulfillment.get("receipt") or {}).get("selection")
                    if isinstance(fulfillment.get("receipt"), Mapping)
                    else None
                ),
            }
        )
    payload = {**dict(decision), "outputLineage": output_lineage}
    fingerprint = recommendation_fingerprint(payload)
    receipt_id = f"decision_learning_{fingerprint[:16]}"
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    match = decision.get("match")
    match = match if isinstance(match, Mapping) else {}
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'manager_decisions'"
    ).fetchone()
    if table is None:
        return receipt_id
    with conn:
        conn.execute(
            """
            INSERT INTO manager_decisions (
              id, creator, account_id, rendered_asset_id, content_surface,
              decision_type, reason, source_system, explanation,
              context_snapshot_json, decision_payload_json, status,
              created_at, updated_at
            ) VALUES (?, ?, ?, NULL, 'reel', 'learning_consumption', ?, ?,
                      ?, ?, ?, 'recorded', ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                receipt_id,
                match.get("creator"),
                match.get("account"),
                decision.get("reason") or "learning_not_applied",
                LEARNING_RECOMMENDATION_SCOPE,
                (
                    "Learning changed an approved choice."
                    if decision.get("learningInfluenced")
                    else "Deterministic production behavior remained active."
                ),
                json.dumps(dict(decision), ensure_ascii=False, sort_keys=True),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
    return receipt_id


def merge_audio_learning_decision(
    decision: dict[str, Any], results: Sequence[Mapping[str, Any]]
) -> None:
    recommendation_ids = set(decision.get("recommendationIds") or [])
    audio_influenced = False
    selected_audio: list[Any] = []
    for result in results:
        nested = result.get("result")
        nested = nested if isinstance(nested, Mapping) else {}
        fulfillment = nested.get("audioFulfillment")
        fulfillment = fulfillment if isinstance(fulfillment, Mapping) else {}
        receipt = fulfillment.get("receipt")
        receipt = receipt if isinstance(receipt, Mapping) else {}
        learning = receipt.get("learning")
        learning = learning if isinstance(learning, Mapping) else {}
        recommendation_ids.update(
            str(value) for value in learning.get("recommendationIds") or []
        )
        audio_influenced = audio_influenced or bool(learning.get("influencedRanking"))
        if receipt.get("selection"):
            selected_audio.append(receipt["selection"])
    decision["recommendationIds"] = sorted(recommendation_ids)
    decision["finalSelectedAudio"] = selected_audio or None
    if audio_influenced:
        decision["learningEligible"] = True
        decision["learningApplied"] = True
        decision["finalChoiceChanged"] = True
        decision["learningInfluenced"] = True
        decision["reason"] = "operator_approved_audio_recommendation_changed_ranking"
        decision["fallbackReason"] = None
    elif recommendation_ids and not decision.get("learningInfluenced"):
        decision["learningEligible"] = True
        decision["learningApplied"] = True
        decision["reason"] = "approved_recommendation_left_choice_unchanged"
        decision["fallbackReason"] = "final_choice_unchanged"


def _pattern_recommendation(
    *,
    pack: Mapping[str, Any],
    pattern: Mapping[str, Any],
    prompt_by_id: Mapping[str, Mapping[str, Any]],
    outcomes: list[dict[str, Any]],
    creator_id: str,
    creator_identity_profile: str,
    account_id: str,
    content_intent: str,
    bucket: str,
    now: datetime,
    scope_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    unique = {
        str((item.get("outcome") or {}).get("performanceSnapshotId")): item
        for item in outcomes
        if (item.get("outcome") or {}).get("performanceSnapshotId")
    }
    outcomes = [unique[key] for key in sorted(unique)]
    sample_count = len(outcomes)
    production_eligible = (
        sample_count >= MINIMUM_POLICY_SAMPLE_COUNT and bucket in PRODUCTION_BUCKETS
    )
    tier = evidence_tier(sample_count)
    latest_observation = max(
        str((item.get("outcome") or {}).get("snapshotAt") or "") for item in outcomes
    )
    age_days = max(
        0.0,
        (now - (_parse_time(latest_observation) or now)).total_seconds() / 86400,
    )
    metrics_snapshots = [
        {
            "instagramAccountId": account_id,
            "snapshotAt": (item.get("outcome") or {}).get("snapshotAt"),
            "metrics": (item.get("outcome") or {}).get("metrics") or {},
        }
        for item in outcomes
    ]
    objectives = {
        str((item.get("outcome") or {}).get("learningObjective") or "").strip()
        for item in outcomes
    }
    objectives.discard("")
    objective = next(iter(objectives)) if len(objectives) == 1 else None
    baseline_values = [
        (item.get("baselineProvenance") or {}).get("medianValue") for item in outcomes
    ]
    baseline = next(
        (
            float(value)
            for value in baseline_values
            if isinstance(value, (int, float)) and value > 0
        ),
        0.35,
    )
    baselines = (
        account_reward_baselines(metrics_snapshots, objective=objective)
        if objective
        else {account_id: baseline}
    )
    learning = learning_summary(
        metrics_snapshots,
        account_baselines=baselines,
        reference_now=_parse_time(latest_observation) or now,
        objective=objective,
    )
    source_hashes = {
        str((item.get("outcome") or {}).get("sourceSha256") or "") for item in outcomes
    }
    source_hashes.discard("")
    preferred_source = next(iter(source_hashes)) if len(source_hashes) == 1 else None
    prompt = _preferred_prompt(pattern, prompt_by_id)
    campaign_ids = {
        str((item.get("outcome") or {}).get("campaignId") or "") for item in outcomes
    }
    campaign_ids.discard("")
    campaign_id = next(iter(campaign_ids)) if len(campaign_ids) == 1 else None
    core = {
        "schema": LEARNING_RECOMMENDATION_VERSION,
        "knowledgePackId": pack["packId"],
        "knowledgePackSourceFingerprint": pack["sourceFingerprint"],
        "campaignId": campaign_id,
        "creatorId": creator_id,
        "creatorIdentityProfile": creator_identity_profile,
        "accountId": account_id,
        "contentIntent": content_intent,
        "learningObjective": objective,
        "observationBucket": bucket,
        "referencePatternId": _imported_pattern_id(pattern),
        "sourcePatternCardId": str(pattern.get("id") or ""),
        "measuredOutcomeIds": sorted(unique),
        "preferredSourceSha256": preferred_source,
        "preferredPrompt": prompt,
    }
    fingerprint = recommendation_fingerprint(core)
    reasons = [
        f"{sample_count} equal-age canonical measured outcomes",
        f"observation cohort {bucket}",
        "account-normalized decay-and-shrinkage score reused",
    ]
    risks = []
    if bucket == "approximately_1h":
        risks.append("one_hour_evidence_is_advisory_only")
    if bucket == CONFIRMATORY_POLICY_BUCKET:
        risks.append("seventy_two_hour_evidence_is_confirmatory_only")
    if sample_count < MINIMUM_POLICY_SAMPLE_COUNT:
        risks.append("insufficient_samples")
    return {
        **core,
        "recommendationCore": core,
        "recommendationFingerprint": fingerprint,
        "classification": "ADVISORY",
        "eligibleForOperatorApproval": production_eligible,
        "evidenceTier": tier,
        "evidenceLabel": tier.replace("_", " "),
        "hierarchicalEvidence": _hierarchical_evidence(
            scope_pool,
            account_id=account_id,
            creator_id=creator_id,
            creator_identity_profile=creator_identity_profile,
            content_intent=content_intent,
            bucket=bucket,
        ),
        "sampleCount": sample_count,
        "score": int(learning.get("score") or 0),
        "scoringVersion": learning.get("scoringVersion"),
        "confidence": "medium" if production_eligible else "low",
        "latestObservationAt": latest_observation,
        "recencyDays": round(age_days, 4),
        "reasons": reasons,
        "risks": risks,
    }


def _ineligible_pattern_recommendation(
    *,
    pack: Mapping[str, Any],
    pattern: Mapping[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    core = {
        "schema": LEARNING_RECOMMENDATION_VERSION,
        "knowledgePackId": pack["packId"],
        "knowledgePackSourceFingerprint": pack["sourceFingerprint"],
        "campaignId": None,
        "creatorId": None,
        "creatorIdentityProfile": None,
        "accountId": None,
        "contentIntent": None,
        "observationBucket": None,
        "referencePatternId": _imported_pattern_id(pattern),
        "sourcePatternCardId": str(pattern.get("id") or ""),
        "measuredOutcomeIds": [],
        "preferredSourceSha256": None,
        "preferredPrompt": None,
    }
    return {
        **core,
        "recommendationCore": core,
        "recommendationFingerprint": recommendation_fingerprint(core),
        "classification": "INELIGIBLE",
        "eligibleForOperatorApproval": False,
        "evidenceTier": "insufficient_evidence",
        "evidenceLabel": "insufficient evidence",
        "sampleCount": 0,
        "score": 0,
        "confidence": "low",
        "latestObservationAt": None,
        "recencyDays": None,
        "reasons": reasons,
        "risks": reasons,
    }


def _hierarchical_evidence(
    provenance: list[dict[str, Any]],
    *,
    account_id: str,
    creator_id: str,
    creator_identity_profile: str,
    content_intent: str,
    bucket: str,
) -> list[dict[str, Any]]:
    def unique_count(items: list[dict[str, Any]]) -> int:
        return len(
            {
                str((item.get("outcome") or {}).get("performanceSnapshotId"))
                for item in items
                if (item.get("outcome") or {}).get("performanceSnapshotId")
            }
        )

    comparable = [
        item
        for item in provenance
        if (item.get("outcome") or {}).get("contentIntent") == content_intent
        and (item.get("outcome") or {}).get("observationBucket") == bucket
    ]
    exact = [
        item
        for item in comparable
        if (item.get("outcome") or {}).get("accountId") == account_id
    ]
    creator = [
        item
        for item in comparable
        if (item.get("outcome") or {}).get("creatorId") == creator_id
        and (item.get("outcome") or {}).get("creatorIdentityProfile")
        == creator_identity_profile
    ]
    account_groups = {
        str((item.get("outcome") or {}).get("accountGroupId") or "").strip()
        for item in exact
    }
    account_groups.discard("")
    rows = [
        {
            "scope": "account",
            "scopeId": account_id,
            "sampleCount": unique_count(exact),
            "evidenceTier": evidence_tier(unique_count(exact)),
            "activation": "operator_approval_eligible",
        }
    ]
    if len(account_groups) == 1:
        group_id = next(iter(account_groups))
        group = [
            item
            for item in creator
            if str((item.get("outcome") or {}).get("accountGroupId") or "") == group_id
        ]
        rows.append(
            {
                "scope": "account_group",
                "scopeId": group_id,
                "sampleCount": unique_count(group),
                "evidenceTier": evidence_tier(unique_count(group)),
                "activation": "advisory_only",
            }
        )
    rows.extend(
        [
            {
                "scope": "creator",
                "scopeId": creator_id,
                "sampleCount": unique_count(creator),
                "evidenceTier": evidence_tier(unique_count(creator)),
                "activation": "advisory_only",
            },
            {
                "scope": "global",
                "scopeId": None,
                "sampleCount": unique_count(comparable),
                "evidenceTier": evidence_tier(unique_count(comparable)),
                "activation": "advisory_only",
            },
        ]
    )
    return rows


def _preferred_prompt(
    pattern: Mapping[str, Any],
    prompt_by_id: Mapping[str, Mapping[str, Any]],
) -> str | None:
    for prompt_id in pattern.get("promptCardIds") or []:
        card = prompt_by_id.get(str(prompt_id))
        if not card:
            continue
        payload = card.get("prompt")
        if not isinstance(payload, Mapping):
            continue
        for key in ("mainPrompt", "motionPrompt", "prompt"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
    return None


def _imported_pattern_id(pattern: Mapping[str, Any]) -> str:
    cluster_key = str(
        pattern.get("clusterKey") or pattern.get("label") or pattern.get("id") or ""
    )
    return "refpat_" + hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:16]


def _prompt_is_imported_and_approved(
    conn: Any,
    *,
    reference_pattern_id: str,
    prompt: str,
) -> bool:
    row = conn.execute(
        "SELECT prompt_template_json FROM reference_patterns WHERE id = ?",
        (reference_pattern_id,),
    ).fetchone()
    if row is None:
        return False
    payload = json_load(row["prompt_template_json"], {})
    return prompt in {
        str(payload.get(key) or "").strip()
        for key in ("mainPrompt", "motionPrompt", "prompt")
    }


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
