"""Append-only governance for learning evidence and production policy."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .learning_score import learning_ineligibility_reasons
from .persistence import json_load

MINIMUM_POLICY_SAMPLE_COUNT = 10

REGISTRY_SCHEMA = "campaign_factory.learning_governance_registry.v1"
ELIGIBILITY_SCHEMA = "campaign_factory.learning_eligibility.v1"

_STATES = {
    "designed",
    "assigned",
    "measured",
    "interpreted",
    "recommended",
    "policy_authorized",
    "rolled_back",
}
_EVIDENCE_CLASSES = {
    "correlation",
    "experiment_result",
    "operator_preference",
    "production_rule",
}
_JSON_FIELDS = (
    "hypothesis_json",
    "assignment_refs_json",
    "cohort_refs_json",
    "metric_contract_json",
    "sample_requirement_json",
    "measurement_window_json",
    "result_json",
    "operator_interpretation_json",
    "recommendation_json",
    "production_policy_json",
    "rollback_json",
    "eligibility_json",
)
_TRANSITIONS = {
    "designed": {"assigned", "measured"},
    "assigned": {"assigned", "measured"},
    "measured": {"measured", "interpreted", "recommended"},
    "interpreted": {"measured", "recommended", "policy_authorized"},
    "recommended": {"policy_authorized"},
    "policy_authorized": {"rolled_back"},
    "rolled_back": set(),
}


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def append_learning_governance_revision(
    conn: sqlite3.Connection,
    *,
    root_id: str,
    event_key: str,
    state: str,
    evidence_class: str,
    creator: str,
    content_intent: str,
    creator_identity_profile: str = "",
    account_id: str = "",
    campaign_id: str | None = None,
    experiment_id: str | None = None,
    recommendation_item_id: str | None = None,
    knowledge_pack_id: str | None = None,
    created_at: str | None = None,
    **snapshots: Any,
) -> dict[str, Any]:
    """Append one full immutable revision; exact event replays are idempotent."""

    if state not in _STATES:
        raise ValueError(f"unsupported learning governance state: {state}")
    if evidence_class not in _EVIDENCE_CLASSES:
        raise ValueError(f"unsupported learning evidence class: {evidence_class}")
    if not root_id.strip() or not event_key.strip():
        raise ValueError("learning governance root_id and event_key are required")
    if not creator.strip() or not content_intent.strip():
        raise ValueError("learning governance creator and content_intent are required")
    existing = conn.execute(
        "SELECT * FROM learning_governance_registry WHERE event_key = ?",
        (event_key,),
    ).fetchone()
    if existing is not None:
        if (
            existing["root_id"] != root_id
            or existing["state"] != state
            or existing["evidence_class"] != evidence_class
        ):
            raise ValueError("learning governance event replay conflicts")
        return _registry_row(existing)
    previous = conn.execute(
        """
        SELECT * FROM learning_governance_registry
        WHERE root_id = ? ORDER BY revision DESC LIMIT 1
        """,
        (root_id,),
    ).fetchone()
    if previous is None:
        if state not in {"designed", "recommended"}:
            raise ValueError(
                f"learning governance root must start at designed: {state}"
            )
        revision = 1
        previous_id = None
        inherited: dict[str, Any] = {}
    else:
        previous_state = str(previous["state"])
        if state not in _TRANSITIONS[previous_state]:
            raise ValueError(
                f"illegal learning governance transition: {previous_state}->{state}"
            )
        revision = int(previous["revision"]) + 1
        previous_id = str(previous["id"])
        inherited = dict(previous)
        immutable_scope = {
            "creator": creator,
            "creator_identity_profile": creator_identity_profile,
            "account_id": account_id,
            "content_intent": content_intent,
            "campaign_id": campaign_id,
            "experiment_id": experiment_id,
            "recommendation_item_id": recommendation_item_id,
            "knowledge_pack_id": knowledge_pack_id,
        }
        for key, supplied in immutable_scope.items():
            prior = inherited.get(key)
            if supplied in {None, ""}:
                immutable_scope[key] = prior
            elif prior not in {None, "", supplied}:
                raise ValueError(f"learning governance scope changed: {key}")
        creator = str(immutable_scope["creator"] or "")
        creator_identity_profile = str(
            immutable_scope["creator_identity_profile"] or ""
        )
        account_id = str(immutable_scope["account_id"] or "")
        content_intent = str(immutable_scope["content_intent"] or "")
        campaign_id = immutable_scope["campaign_id"]
        experiment_id = immutable_scope["experiment_id"]
        recommendation_item_id = immutable_scope["recommendation_item_id"]
        knowledge_pack_id = immutable_scope["knowledge_pack_id"]
    created_at = created_at or _now()
    encoded: dict[str, str] = {}
    for field in _JSON_FIELDS:
        if field in snapshots:
            value = snapshots[field]
        elif inherited:
            value = json_load(
                inherited.get(field), [] if field.endswith("s_json") else {}
            )
        else:
            value = [] if field in {"assignment_refs_json", "cohort_refs_json"} else {}
        encoded[field] = _json(value)
    fingerprint_payload = {
        "schema": REGISTRY_SCHEMA,
        "rootId": root_id,
        "revision": revision,
        "previousRevisionId": previous_id,
        "eventKey": event_key,
        "campaignId": campaign_id,
        "experimentId": experiment_id,
        "recommendationItemId": recommendation_item_id,
        "knowledgePackId": knowledge_pack_id,
        "creator": creator,
        "creatorIdentityProfile": creator_identity_profile,
        "accountId": account_id,
        "contentIntent": content_intent,
        "evidenceClass": evidence_class,
        "state": state,
        "snapshots": {field: json_load(value, {}) for field, value in encoded.items()},
        "createdAt": created_at,
    }
    fingerprint = canonical_fingerprint(fingerprint_payload)
    revision_id = f"lgov_{fingerprint[:24]}"
    conn.execute(
        f"""
        INSERT INTO learning_governance_registry (
          id, root_id, revision, previous_revision_id, event_key,
          campaign_id, experiment_id, recommendation_item_id, knowledge_pack_id,
          creator, creator_identity_profile, account_id, content_intent,
          evidence_class, state, {", ".join(_JSON_FIELDS)},
          record_fingerprint, created_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
          {", ".join("?" for _ in _JSON_FIELDS)}, ?, ?
        )
        """,
        (
            revision_id,
            root_id,
            revision,
            previous_id,
            event_key,
            campaign_id,
            experiment_id,
            recommendation_item_id,
            knowledge_pack_id,
            creator,
            creator_identity_profile,
            account_id,
            content_intent,
            evidence_class,
            state,
            *(encoded[field] for field in _JSON_FIELDS),
            fingerprint,
            created_at,
        ),
    )
    return _registry_row(
        conn.execute(
            "SELECT * FROM learning_governance_registry WHERE id = ?", (revision_id,)
        ).fetchone()
    )


def register_experiment_design(
    conn: sqlite3.Connection, receipt: Mapping[str, Any]
) -> dict[str, Any]:
    experiment_id = str(receipt["experimentId"])
    result = append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=f"experiment_design:{experiment_id}:{canonical_fingerprint(receipt)}",
        state="designed",
        evidence_class="experiment_result",
        experiment_id=experiment_id,
        creator=str(receipt["creator"]),
        account_id="",
        content_intent=str(receipt["contentIntent"]),
        hypothesis_json={
            "hypothesis": receipt.get("hypothesis"),
            "changedVariable": receipt.get("changedVariable"),
            "variants": receipt.get("variants"),
            "controlledVariables": receipt.get("controlledVariables"),
        },
        metric_contract_json=receipt.get("measurementPlan") or {},
        sample_requirement_json={
            "warning": receipt.get("minimumSampleWarning"),
        },
        measurement_window_json={
            "requiredObservationCohort": receipt.get("requiredObservationCohort"),
        },
    )
    return result


def register_experiment_assignment(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    pair_id: str,
    assignments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    return append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=(
            f"experiment_assignment:{experiment_id}:{pair_id}:"
            f"{canonical_fingerprint(assignments)}"
        ),
        state="assigned",
        evidence_class="experiment_result",
        experiment_id=experiment_id,
        creator=str(experiment["creator"]),
        content_intent=str(experiment["content_intent"]),
        assignment_refs_json=[dict(item) for item in assignments],
        cohort_refs_json=[
            {
                "pairId": pair_id,
                "planItemId": item.get("planItemId"),
                "observationCohorts": item.get("observationCohorts"),
                "eligibleSlot": item.get("eligibleSlot"),
            }
            for item in assignments
        ],
    )


def register_experiment_measurement(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    return append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=f"experiment_measurement:{experiment_id}:{report['fingerprint']}",
        state="measured",
        evidence_class="experiment_result",
        experiment_id=experiment_id,
        creator=str(experiment["creator"]),
        content_intent=str(experiment["content_intent"]),
        result_json=dict(report),
        eligibility_json={
            "includedPairCount": report.get("includedPairCount"),
            "excludedPairCount": report.get("excludedPairCount"),
            "exclusions": report.get("exclusions") or [],
        },
    )


def register_experiment_interpretation(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    return append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=f"experiment_interpretation:{experiment_id}:{decision['reportFingerprint']}:{decision['decision']}",
        state="interpreted",
        evidence_class="operator_preference",
        experiment_id=experiment_id,
        creator=str(experiment["creator"]),
        content_intent=str(experiment["content_intent"]),
        operator_interpretation_json=dict(decision),
    )


def authorize_experiment_policy(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    if decision.get("decision") != "adopt":
        raise ValueError("only an adopted experiment can authorize a policy")
    return append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=(
            f"experiment_policy:{experiment_id}:"
            f"{decision['reportFingerprint']}:{decision['adoptedVariant']}"
        ),
        state="policy_authorized",
        evidence_class="production_rule",
        experiment_id=experiment_id,
        creator=str(experiment["creator"]),
        content_intent=str(experiment["content_intent"]),
        production_policy_json={
            "changedVariable": experiment["changed_variable"],
            "adoptedVariant": decision["adoptedVariant"],
            "reportFingerprint": decision["reportFingerprint"],
            "operator": decision["operator"],
            "reason": decision["reason"],
            "authorizedAt": decision["decidedAt"],
            "automaticExpansion": False,
        },
    )


def rollback_experiment_policy(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    rollback: Mapping[str, Any],
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    return append_learning_governance_revision(
        conn,
        root_id=f"experiment:{experiment_id}",
        event_key=(
            f"experiment_policy_rollback:{experiment_id}:"
            f"{rollback['rolledBackDecisionFingerprint']}"
        ),
        state="rolled_back",
        evidence_class="production_rule",
        experiment_id=experiment_id,
        creator=str(experiment["creator"]),
        content_intent=str(experiment["content_intent"]),
        rollback_json=dict(rollback),
    )


def register_recommendation(
    conn: sqlite3.Connection,
    *,
    recommendation_item_id: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT ri.id, rr.campaign_id
        FROM recommendation_items ri
        JOIN recommendation_runs rr ON rr.id = ri.run_id
        WHERE ri.id = ?
        """,
        (recommendation_item_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"recommendation not found: {recommendation_item_id}")
    fingerprint = str(evidence.get("recommendationFingerprint") or "")
    if not fingerprint:
        raise ValueError("recommendation fingerprint is required")
    return append_learning_governance_revision(
        conn,
        root_id=f"recommendation:{recommendation_item_id}",
        event_key=f"recommendation:{recommendation_item_id}:{fingerprint}",
        state="recommended",
        evidence_class="correlation",
        campaign_id=str(row["campaign_id"]),
        recommendation_item_id=recommendation_item_id,
        knowledge_pack_id=str(evidence.get("knowledgePackId") or "") or None,
        creator=str(evidence.get("creatorId") or ""),
        creator_identity_profile=str(evidence.get("creatorIdentityProfile") or ""),
        account_id=str(evidence.get("accountId") or ""),
        content_intent=str(evidence.get("contentIntent") or ""),
        recommendation_json={
            "recommendationFingerprint": fingerprint,
            "classification": evidence.get("classification"),
            "evidenceTier": evidence.get("evidenceTier"),
            "sampleCount": evidence.get("sampleCount"),
            "measuredOutcomeIds": evidence.get("measuredOutcomeIds") or [],
        },
    )


def authorize_learning_policy(
    conn: sqlite3.Connection,
    *,
    recommendation_item_id: str,
    operator: str,
    reason: str,
    expected_recommendation_fingerprint: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    if not operator.strip() or not reason.strip():
        raise ValueError("policy authorization requires operator and reason")
    row = conn.execute(
        """
        SELECT ri.*, rr.campaign_id
        FROM recommendation_items ri
        JOIN recommendation_runs rr ON rr.id = ri.run_id
        WHERE ri.id = ?
        """,
        (recommendation_item_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"recommendation not found: {recommendation_item_id}")
    if str(row["status"]) != "accepted":
        raise ValueError("recommendation must be accepted before policy authorization")
    evidence = json_load(row["evidence_json"], {})
    fingerprint = str(evidence.get("recommendationFingerprint") or "")
    core = evidence.get("recommendationCore")
    measured_outcome_ids = (
        core.get("measuredOutcomeIds") if isinstance(core, Mapping) else []
    )
    unique_outcome_ids = {
        str(outcome_id).strip()
        for outcome_id in measured_outcome_ids or []
        if str(outcome_id).strip()
    }
    sample_count = int(evidence.get("sampleCount") or 0)
    if (
        not fingerprint
        or not isinstance(core, Mapping)
        or canonical_fingerprint(dict(core)) != fingerprint
        or evidence.get("eligibleForOperatorApproval") is not True
        or core.get("observationBucket") != "approximately_24h"
        or sample_count < MINIMUM_POLICY_SAMPLE_COUNT
        or sample_count != len(unique_outcome_ids)
    ):
        raise ValueError(
            "recommendation evidence is not eligible for policy authorization"
        )
    if (
        expected_recommendation_fingerprint
        and expected_recommendation_fingerprint != fingerprint
    ):
        raise ValueError("recommendation fingerprint does not match authorization")
    root_id = f"recommendation:{recommendation_item_id}"
    latest = _latest_revision(conn, root_id)
    if latest is None:
        register_recommendation(
            conn,
            recommendation_item_id=recommendation_item_id,
            evidence=evidence,
        )
        latest = _latest_revision(conn, root_id)
    if latest is not None and latest["state"] == "policy_authorized":
        policy = latest["productionPolicy"]
        if (
            policy.get("recommendationFingerprint") == fingerprint
            and policy.get("expiresAt") == expires_at
        ):
            return latest
        raise ValueError("a different production policy is already active")
    result = append_learning_governance_revision(
        conn,
        root_id=root_id,
        event_key=(
            f"policy_authorize:{recommendation_item_id}:{fingerprint}:"
            f"{canonical_fingerprint([operator, reason, expires_at])}"
        ),
        state="policy_authorized",
        evidence_class="production_rule",
        campaign_id=str(row["campaign_id"]),
        recommendation_item_id=recommendation_item_id,
        knowledge_pack_id=str(evidence.get("knowledgePackId") or "") or None,
        creator=str(evidence.get("creatorId") or ""),
        creator_identity_profile=str(evidence.get("creatorIdentityProfile") or ""),
        account_id=str(evidence.get("accountId") or ""),
        content_intent=str(evidence.get("contentIntent") or ""),
        production_policy_json={
            "recommendationFingerprint": fingerprint,
            "scope": {
                "creator": evidence.get("creatorId"),
                "creatorIdentityProfile": evidence.get("creatorIdentityProfile"),
                "account": evidence.get("accountId"),
                "intent": evidence.get("contentIntent"),
            },
            "operator": operator,
            "reason": reason,
            "authorizedAt": _now(),
            "expiresAt": expires_at,
            "automaticExpansion": False,
        },
    )
    conn.commit()
    return result


def rollback_learning_policy(
    conn: sqlite3.Connection,
    *,
    recommendation_item_id: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    if not operator.strip() or not reason.strip():
        raise ValueError("policy rollback requires operator and reason")
    root_id = f"recommendation:{recommendation_item_id}"
    latest = _latest_revision(conn, root_id)
    if latest is None or latest["state"] != "policy_authorized":
        raise ValueError("no active production policy to roll back")
    result = append_learning_governance_revision(
        conn,
        root_id=root_id,
        event_key=(
            f"policy_rollback:{recommendation_item_id}:"
            f"{canonical_fingerprint([latest['id'], operator, reason])}"
        ),
        state="rolled_back",
        evidence_class="production_rule",
        creator=str(latest["creator"]),
        creator_identity_profile=str(latest["creatorIdentityProfile"]),
        account_id=str(latest["accountId"]),
        content_intent=str(latest["contentIntent"]),
        campaign_id=latest.get("campaignId"),
        recommendation_item_id=recommendation_item_id,
        knowledge_pack_id=latest.get("knowledgePackId"),
        rollback_json={
            "rolledBackRevisionId": latest["id"],
            "rolledBackFingerprint": latest["recordFingerprint"],
            "operator": operator,
            "reason": reason,
            "rolledBackAt": _now(),
        },
    )
    conn.commit()
    return result


def resolve_active_learning_policy(
    conn: sqlite3.Connection,
    *,
    recommendation_item_id: str,
    recommendation_fingerprint: str,
    creator: str,
    creator_identity_profile: str,
    account_id: str | None,
    content_intent: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    try:
        latest = _latest_revision(conn, f"recommendation:{recommendation_item_id}")
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if latest is None or latest["state"] != "policy_authorized":
        return None
    if (
        latest["creator"] != creator
        or latest["creatorIdentityProfile"] != creator_identity_profile
        or latest["accountId"] != (account_id or "")
        or latest["contentIntent"] != content_intent
    ):
        return None
    policy = latest["productionPolicy"]
    if policy.get("recommendationFingerprint") != recommendation_fingerprint:
        return None
    expires_at = _parse_time(policy.get("expiresAt"))
    if expires_at is not None and expires_at <= (now or datetime.now(UTC)):
        return None
    return latest


def learning_policy_status(
    conn: sqlite3.Connection, *, recommendation_item_id: str
) -> dict[str, Any]:
    latest = _latest_revision(conn, f"recommendation:{recommendation_item_id}")
    expires_at = (
        _parse_time(latest["productionPolicy"].get("expiresAt")) if latest else None
    )
    active = bool(
        latest
        and latest["state"] == "policy_authorized"
        and (expires_at is None or expires_at > datetime.now(UTC))
    )
    return {
        "schema": "campaign_factory.learning_policy_status.v1",
        "recommendationItemId": recommendation_item_id,
        "active": active,
        "latestRevision": latest,
    }


def canonical_learning_eligibility(
    conn: sqlite3.Connection,
    snapshot: Mapping[str, Any],
    *,
    include_base_learning: bool = True,
    required_observation_bucket: str | None = None,
) -> dict[str, Any]:
    """Evaluate canonical exclusions and bind their mutable source state."""

    item = dict(snapshot)
    reasons = learning_ineligibility_reasons(item) if include_base_learning else []
    rendered_asset_id = str(
        item.get("rendered_asset_id") or item.get("renderedAssetId") or ""
    )
    asset_state: dict[str, Any] = {}
    if rendered_asset_id:
        asset = conn.execute(
            """
            SELECT id, review_state, content_hash, metadata_json
            FROM rendered_assets WHERE id = ?
            """,
            (rendered_asset_id,),
        ).fetchone()
        if asset is None:
            reasons.append("rendered_asset_missing")
        else:
            metadata = json_load(asset["metadata_json"], {})
            asset_state = {
                "id": asset["id"],
                "reviewState": asset["review_state"],
                "contentHash": asset["content_hash"],
                "lifecycleStatus": metadata.get("lifecycleStatus"),
                "creativeDecision": metadata.get("creativeDecision"),
                "generationStatus": metadata.get("generationStatus"),
                "learningEligible": metadata.get("learningEligible"),
            }
            if asset["review_state"] == "rejected" or (
                metadata.get("creativeDecision") == "rejected"
            ):
                reasons.append("operator_rejected_asset")
            if metadata.get("lifecycleStatus") == "operator_removed":
                reasons.append("operator_removed_asset")
            if metadata.get("learningEligible") is False:
                reasons.append("asset_learning_disabled")
            generation_status = metadata.get("generationStatus")
            if generation_status and generation_status != "completed":
                reasons.append("failed_generation")
            if any(
                metadata.get(flag) is True
                for flag in ("technicalFailure", "providerFailure", "qcFailure")
            ):
                reasons.append("failed_generation")
    published_at = item.get("published_at") or item.get("publishedAt")
    snapshot_at = item.get("snapshot_at") or item.get("snapshotAt")
    bucket = _observation_bucket(published_at, snapshot_at)
    if required_observation_bucket:
        if bucket is None:
            reasons.append("missing_or_late_observation_window")
        elif bucket != required_observation_bucket:
            reasons.append("wrong_observation_window")
    post_id = str(item.get("post_id") or item.get("postId") or "")
    final_sha = str(
        item.get("content_hash")
        or item.get("finalMediaSha256")
        or asset_state.get("contentHash")
        or ""
    )
    duplicate_anchor: dict[str, Any] = {}
    if post_id and final_sha:
        canonical = conn.execute(
            """
            SELECT post_id, MIN(published_at) AS first_published_at
            FROM performance_snapshots
            WHERE content_hash = ? AND post_id <> ''
            GROUP BY post_id
            ORDER BY julianday(first_published_at), first_published_at, post_id
            LIMIT 1
            """,
            (final_sha,),
        ).fetchone()
        if canonical is not None:
            duplicate_anchor = {
                "canonicalPostId": canonical["post_id"],
                "firstPublishedAt": canonical["first_published_at"],
            }
            if str(canonical["post_id"]) != post_id:
                reasons.append("duplicate_exact_final_media_outcome")
    raw = _json_object(item.get("raw_json") or item.get("rawJson"))
    if _recursive_truthy(
        raw,
        "experiment_contaminated",
        "experimentContaminated",
        "cohort_contaminated",
        "cohortContaminated",
    ):
        reasons.append("experiment_contamination")
    reasons = sorted(set(reasons))
    evidence = {
        "schema": ELIGIBILITY_SCHEMA,
        "snapshotId": item.get("id") or item.get("performanceSnapshotId"),
        "postId": post_id or None,
        "renderedAssetId": rendered_asset_id or None,
        "finalMediaSha256": final_sha or None,
        "observationBucket": bucket,
        "requiredObservationBucket": required_observation_bucket,
        "assetState": asset_state,
        "duplicateAnchor": duplicate_anchor,
        "eligible": not reasons,
        "reasons": reasons,
    }
    evidence["fingerprint"] = canonical_fingerprint(evidence)
    return evidence


def _latest_revision(conn: sqlite3.Connection, root_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM learning_governance_registry
        WHERE root_id = ? ORDER BY revision DESC LIMIT 1
        """,
        (root_id,),
    ).fetchone()
    return _registry_row(row) if row is not None else None


def _registry_row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(row)
    result = {
        "schema": REGISTRY_SCHEMA,
        "id": raw["id"],
        "rootId": raw["root_id"],
        "revision": raw["revision"],
        "previousRevisionId": raw["previous_revision_id"],
        "eventKey": raw["event_key"],
        "campaignId": raw["campaign_id"],
        "experimentId": raw["experiment_id"],
        "recommendationItemId": raw["recommendation_item_id"],
        "knowledgePackId": raw["knowledge_pack_id"],
        "creator": raw["creator"],
        "creatorIdentityProfile": raw["creator_identity_profile"],
        "accountId": raw["account_id"],
        "contentIntent": raw["content_intent"],
        "evidenceClass": raw["evidence_class"],
        "state": raw["state"],
        "recordFingerprint": raw["record_fingerprint"],
        "createdAt": raw["created_at"],
    }
    for field in _JSON_FIELDS:
        camel = "".join(
            [field.removesuffix("_json").split("_")[0]]
            + [part.capitalize() for part in field.removesuffix("_json").split("_")[1:]]
        )
        result[camel] = json_load(
            raw[field],
            [] if field in {"assignment_refs_json", "cohort_refs_json"} else {},
        )
    return result


def _observation_bucket(published_at: Any, snapshot_at: Any) -> str | None:
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


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _recursive_truthy(value: Any, *keys: str) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in keys and nested is True:
                return True
            if _recursive_truthy(nested, *keys):
                return True
    elif isinstance(value, list):
        return any(_recursive_truthy(item, *keys) for item in value)
    return False


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
