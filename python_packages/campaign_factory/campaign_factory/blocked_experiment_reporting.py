from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any

from pipeline_contracts import validate_experiment_assignment_receipt

from .learning_governance import (
    authorize_experiment_policy,
    register_experiment_interpretation,
    register_experiment_measurement,
    rollback_experiment_policy,
)
from .observed_experiment_reporting import (
    BLOCKED_ASSIGNMENT_METHOD,
    BLOCKED_MEASUREMENT_PLAN,
    EXPERIMENT_FACTORS,
    _guardrail_summary,
    _json_object,
    _matched_pair,
    _round,
    _sha256,
)

MIN_VALID_PAIRS = 96
MIN_CLUSTER_ESS = 75.0
MIN_ACCOUNTS = 48
MIN_SOURCE_FAMILY_BLOCKS = 96
MIN_DESIGN_EFFECT = 1.25
ACCOUNT_INTRACLUSTER_CORRELATION = 0.10


def blocked_experiment_report(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    record_interpretation: bool = False,
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    if experiment["assignment_method"] != BLOCKED_ASSIGNMENT_METHOD:
        raise ValueError("experiment is not a within-account/source-family block")
    changed_variable = str(experiment["changed_variable"])
    if changed_variable not in EXPERIMENT_FACTORS:
        raise ValueError("blocked experiment factor is invalid")
    variants = json.loads(experiment["variants_json"] or "[]")
    if len(variants) != 2 or len(set(variants)) != 2:
        raise ValueError("blocked experiment requires two distinct variants")
    controlled = set(json.loads(experiment["controlled_variables_json"] or "[]"))
    required_controls = {
        "creator",
        "account",
        "content_intent",
        "observation_cohort",
        "publication_window",
        *EXPERIMENT_FACTORS,
    } - {changed_variable}
    if controlled != required_controls:
        raise ValueError("blocked experiment controls are incomplete")
    interpretation = _json_object(experiment["interpretation_json"])
    if interpretation.get("measurementPlan") != BLOCKED_MEASUREMENT_PLAN:
        raise ValueError("blocked measurement plan was not predeclared")

    events = conn.execute(
        """
        SELECT e.plan_item_id, e.receipt_json
        FROM creative_plan_item_events e
        JOIN creative_plan_items i ON i.id = e.plan_item_id
        WHERE e.event_type = 'experiment_assignment' AND i.experiment_id = ?
        ORDER BY e.created_at, e.plan_item_id
        """,
        (experiment_id,),
    ).fetchall()
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for event in events:
        receipt = json.loads(event["receipt_json"])
        validate_experiment_assignment_receipt(receipt)
        if receipt.get("experimentId") != experiment_id:
            raise ValueError("assignment receipt belongs to another experiment")
        if receipt.get("assignmentAlgorithmVersion") != BLOCKED_ASSIGNMENT_METHOD:
            raise ValueError("assignment receipt is not within-account blocked")
        grouped[str(receipt["pairId"])].append((str(event["plan_item_id"]), receipt))

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    experiment_assets = {
        str(receipt["assignedAssetId"])
        for rows in grouped.values()
        for _, receipt in rows
    }
    for pair_id, rows in sorted(grouped.items()):
        pair, reasons = _matched_pair(
            conn,
            pair_id=pair_id,
            rows=rows,
            experiment_asset_ids=experiment_assets,
            observation_bucket="24h",
            require_reconciled_revision=True,
        )
        confirmation, confirmation_reasons = _matched_pair(
            conn,
            pair_id=pair_id,
            rows=rows,
            experiment_asset_ids=experiment_assets,
            observation_bucket="72h",
            require_reconciled_revision=True,
        )
        reasons.extend(f"confirmatory_{reason}" for reason in confirmation_reasons)
        if reasons:
            excluded.append({"pairId": pair_id, "reasons": sorted(set(reasons))})
            continue
        if pair is not None and confirmation is not None:
            pair["confirmatory72h"] = confirmation
            pair["changedVariable"] = changed_variable
            pair["sourceFamilyBlockId"] = rows[0][1]["sourceFamilyBlockId"]
            included.append(pair)

    blocks = _cluster_blocks(included)
    lifts = [float(block["primaryLift"]) for block in blocks]
    confirmatory_lifts = [float(block["confirmatoryLift"]) for block in blocks]
    cluster_summary = _cluster_summary(blocks)
    interval = (
        _hierarchical_cluster_interval(blocks, seed=_sha256([experiment_id, blocks]))
        if blocks
        else None
    )
    median_lift = median(lifts) if lifts else None
    positive_percentage = (
        sum(value > 0 for value in lifts) / len(lifts) if lifts else None
    )
    confirmatory_median = median(confirmatory_lifts) if confirmatory_lifts else None
    confirmatory_positive = (
        sum(value > 0 for value in confirmatory_lifts) / len(confirmatory_lifts)
        if confirmatory_lifts
        else None
    )
    confirmatory_pass = bool(
        confirmatory_median is not None
        and confirmatory_median > 0
        and confirmatory_positive is not None
        and confirmatory_positive >= 0.60
    )
    guardrails = _guardrail_summary(included)
    status = _promotion_status(
        pair_count=len(included),
        cluster_summary=cluster_summary,
        median_lift=median_lift,
        positive_percentage=positive_percentage,
        interval=interval,
        guardrails_pass=bool(guardrails["pass"]),
        confirmatory_pass=confirmatory_pass,
    )
    report = {
        "schema": "creator_os.blocked_experiment_report.v1",
        "experimentId": experiment_id,
        "changedVariable": changed_variable,
        "variants": variants,
        "measurementPlan": BLOCKED_MEASUREMENT_PLAN,
        "includedPairCount": len(included),
        "excludedPairCount": len(excluded),
        "medianPairedLift": _round(median_lift),
        "positivePairPercentage": _round(positive_percentage),
        "clusterBootstrap95": (
            {"lower": _round(interval[0]), "upper": _round(interval[1])}
            if interval
            else None
        ),
        "clusterAnalysis": cluster_summary,
        "guardrails": guardrails,
        "confirmatory72h": {
            "medianPairedLift": _round(confirmatory_median),
            "positivePairPercentage": _round(confirmatory_positive),
            "pass": confirmatory_pass,
        },
        "interpretation": {
            "status": status,
            "operatorDecisionRequired": True,
            "productionUsageChanged": False,
        },
        "pairs": included,
        "blocks": blocks,
        "exclusions": excluded,
        "automaticProductionExpansion": False,
        "changedDecisionProof": {
            "receiptSchema": "campaign_factory.learning_decision_receipt.v1",
            "requiredTrueFields": ["learningInfluenced", "finalChoiceChanged"],
        },
        "fingerprint": "",
    }
    report["fingerprint"] = _sha256(report)
    if record_interpretation:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            UPDATE creative_plan_experiments
            SET interpretation_json = ?, status = 'MEASURED', updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(report, sort_keys=True), now, experiment_id),
        )
        register_experiment_measurement(
            conn, experiment_id=experiment_id, report=report
        )
        conn.commit()
    return report


def record_blocked_experiment_decision(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    operator: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    normalized = decision.strip().lower()
    if normalized not in {"continue", "stop", "adopt", "reject"}:
        raise ValueError("unsupported blocked experiment decision")
    if not operator.strip() or not reason.strip():
        raise ValueError("experiment decision requires operator and reason")
    row = conn.execute(
        "SELECT interpretation_json, variants_json FROM creative_plan_experiments WHERE id = ?",
        (experiment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    report = _json_object(row["interpretation_json"])
    if report.get("schema") != "creator_os.blocked_experiment_report.v1":
        raise ValueError("record a blocked experiment report before deciding")
    if (
        normalized == "adopt"
        and _json_object(report.get("interpretation")).get("status")
        != "operator_review_eligible"
    ):
        raise ValueError("only an operator-review-eligible result can be adopted")
    variants = json.loads(row["variants_json"] or "[]")
    receipt = {
        "schema": "creator_os.blocked_experiment_decision.v1",
        "experimentId": experiment_id,
        "operator": operator,
        "decision": normalized,
        "reason": reason,
        "reportFingerprint": report["fingerprint"],
        "productionUsageChanged": normalized == "adopt",
        "adoptedVariant": variants[1] if normalized == "adopt" else None,
        "automaticExpansion": False,
        "decidedAt": datetime.now(UTC).isoformat(),
    }
    report["operatorDecision"] = receipt
    conn.execute(
        """
        UPDATE creative_plan_experiments
        SET interpretation_json = ?, status = 'DECIDED', updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(report, sort_keys=True), receipt["decidedAt"], experiment_id),
    )
    register_experiment_interpretation(
        conn, experiment_id=experiment_id, decision=receipt
    )
    if normalized == "adopt":
        authorize_experiment_policy(conn, experiment_id=experiment_id, decision=receipt)
    conn.commit()
    return receipt


def rollback_blocked_experiment_policy(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    if not operator.strip() or not reason.strip():
        raise ValueError("experiment rollback requires operator and reason")
    row = conn.execute(
        "SELECT interpretation_json FROM creative_plan_experiments WHERE id = ?",
        (experiment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    report = _json_object(row["interpretation_json"])
    decision = _json_object(report.get("operatorDecision"))
    if decision.get("decision") != "adopt" or report.get("policyRollback"):
        raise ValueError("no active adopted experiment policy to roll back")
    receipt = {
        "schema": "creator_os.blocked_experiment_rollback.v1",
        "experimentId": experiment_id,
        "operator": operator,
        "reason": reason,
        "decision": "rollback",
        "reportFingerprint": report["fingerprint"],
        "rolledBackDecisionFingerprint": _sha256(decision),
        "productionUsageChanged": True,
        "rolledBackAt": datetime.now(UTC).isoformat(),
    }
    report["policyRollback"] = receipt
    conn.execute(
        """
        UPDATE creative_plan_experiments
        SET interpretation_json = ?, status = 'ROLLED_BACK', updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(report, sort_keys=True), receipt["rolledBackAt"], experiment_id),
    )
    rollback_experiment_policy(conn, experiment_id=experiment_id, rollback=receipt)
    conn.commit()
    return receipt


def apply_adopted_experiment_policy(
    conn: sqlite3.Connection,
    *,
    creator: str,
    account_id: str,
    content_intent: str,
    changed_variable: str,
    eligible_values: list[str],
    base_value: str,
) -> tuple[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, account_scope_json, variants_json, interpretation_json
        FROM creative_plan_experiments
        WHERE creator = ? AND content_intent = ? AND changed_variable = ?
          AND assignment_method = ? AND status = 'DECIDED'
        ORDER BY updated_at DESC, id DESC
        """,
        (creator, content_intent, changed_variable, BLOCKED_ASSIGNMENT_METHOD),
    ).fetchall()
    selected = base_value
    experiment_id = None
    report_fingerprint = None
    for row in rows:
        if account_id not in json.loads(row["account_scope_json"] or "[]"):
            continue
        report = _json_object(row["interpretation_json"])
        decision = _json_object(report.get("operatorDecision"))
        if decision.get("decision") != "adopt" or report.get("policyRollback"):
            continue
        candidate = str(decision.get("adoptedVariant") or "")
        if candidate in eligible_values:
            selected = candidate
            experiment_id = str(row["id"])
            report_fingerprint = str(decision.get("reportFingerprint") or "")
            break
    changed = selected != base_value
    receipt = {
        "schema": "campaign_factory.learning_decision_receipt.v1",
        "learningConsulted": True,
        "learningEligible": experiment_id is not None,
        "learningApplied": experiment_id is not None,
        "learningInfluenced": changed,
        "finalChoiceChanged": changed,
        "changedVariable": changed_variable,
        "eligibleCandidateSetBeforeLearning": list(eligible_values),
        "baseValue": base_value,
        "finalValue": selected,
        "experimentId": experiment_id,
        "reportFingerprint": report_fingerprint,
        "reason": (
            "operator_adopted_blocked_experiment"
            if experiment_id is not None
            else "no_active_experiment_policy"
        ),
    }
    return selected, receipt


def _cluster_blocks(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        account = str(pair["control"]["accountId"])
        if pair["treatment"]["accountId"] != account:
            raise ValueError("blocked experiment pair crossed accounts")
        family = str(pair["sourceFamilyBlockId"])
        grouped[(account, family)].append(pair)
    blocks = []
    for (account, family), values in sorted(grouped.items()):
        blocks.append(
            {
                "accountId": account,
                "sourceFamilyBlockId": family,
                "pairCount": len(values),
                "primaryLift": median(float(item["primaryLift"]) for item in values),
                "confirmatoryLift": median(
                    float(item["confirmatory72h"]["primaryLift"]) for item in values
                ),
            }
        )
    return blocks


def _cluster_summary(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not blocks:
        return {
            "rawPairBlocks": 0,
            "accountClusterCount": 0,
            "sourceFamilyBlockCount": 0,
            "designEffect": None,
            "clusterAdjustedEffectiveSampleSize": 0.0,
        }
    by_account: dict[str, int] = defaultdict(int)
    for block in blocks:
        by_account[str(block["accountId"])] += 1
    mean_account_size = len(blocks) / len(by_account)
    account_effect = 1 + (mean_account_size - 1) * ACCOUNT_INTRACLUSTER_CORRELATION
    design_effect = max(MIN_DESIGN_EFFECT, account_effect)
    return {
        "rawPairBlocks": len(blocks),
        "accountClusterCount": len(by_account),
        "sourceFamilyBlockCount": len(blocks),
        "assumedAccountIntraclusterCorrelation": ACCOUNT_INTRACLUSTER_CORRELATION,
        "designEffect": round(design_effect, 6),
        "clusterAdjustedEffectiveSampleSize": round(len(blocks) / design_effect, 6),
    }


def _hierarchical_cluster_interval(
    blocks: list[dict[str, Any]], *, seed: str, iterations: int = 4000
) -> tuple[float, float]:
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_account[str(block["accountId"])].append(block)
    accounts = sorted(by_account)
    rng = random.Random(int(seed[:16], 16))
    samples = []
    for _ in range(iterations):
        values: list[float] = []
        for account in rng.choices(accounts, k=len(accounts)):
            account_blocks = by_account[account]
            values.extend(
                float(block["primaryLift"])
                for block in rng.choices(account_blocks, k=len(account_blocks))
            )
        samples.append(median(values))
    samples.sort()
    return (
        samples[math.floor(0.025 * (iterations - 1))],
        samples[math.ceil(0.975 * (iterations - 1))],
    )


def _promotion_status(
    *,
    pair_count: int,
    cluster_summary: dict[str, Any],
    median_lift: float | None,
    positive_percentage: float | None,
    interval: tuple[float, float] | None,
    guardrails_pass: bool,
    confirmatory_pass: bool,
) -> str:
    if pair_count < 48:
        return "insufficient"
    if pair_count < MIN_VALID_PAIRS:
        return "screening_only"
    if (
        cluster_summary["clusterAdjustedEffectiveSampleSize"] >= MIN_CLUSTER_ESS
        and cluster_summary["accountClusterCount"] >= MIN_ACCOUNTS
        and cluster_summary["sourceFamilyBlockCount"] >= MIN_SOURCE_FAMILY_BLOCKS
        and median_lift is not None
        and median_lift >= 0.10
        and positive_percentage is not None
        and positive_percentage >= 0.60
        and interval is not None
        and interval[0] > 0
        and guardrails_pass
        and confirmatory_pass
    ):
        return "operator_review_eligible"
    return "inconclusive"


def decision_fingerprint(receipt: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
