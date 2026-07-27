"""Versioned, supervised seven-day content planning inside Campaign Factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import get_settings
from .learning_consumption import apply_learning_to_production_plan
from .production_lane import _CREATOR_SOUL_IDS
from .production_prompts import INTENT_PROMPTS

POLICY_PATH = Path(__file__).with_name("config") / "content_director_policy.json"
SUPPORTED_INTENTS = frozenset(
    {
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    }
)
UNRESOLVED_INTENTS = frozenset(
    {"talking_selfie", "talking_motion_copy", "motion_copy", "dance"}
)
AUTONOMY_MODES = frozenset({"SHADOW", "SUPERVISED", "APPROVED_PLAN_AUTOPILOT"})
PLAN_STATES = frozenset(
    {
        "DRAFT",
        "REVIEWED",
        "APPROVED",
        "BLOCKED",
        "GENERATION_READY",
        "GENERATING",
        "RECONCILING",
        "REVIEW_READY",
        "CREATIVE_APPROVED",
        "REJECTED",
        "EXPORT_READY",
        "EXPORTED",
        "SCHEDULE_READY",
        "SCHEDULED",
        "PUBLISHING",
        "PUBLISHED",
        "MEASURING",
        "LEARNED",
        "CANCELLED",
    }
)
PLAN_TRANSITIONS = {
    "DRAFT": {"REVIEWED", "APPROVED", "BLOCKED", "CANCELLED"},
    "REVIEWED": {"APPROVED", "BLOCKED", "CANCELLED"},
    "APPROVED": {"GENERATION_READY", "BLOCKED", "CANCELLED"},
    "BLOCKED": {"DRAFT", "APPROVED", "CANCELLED"},
    "GENERATION_READY": {"GENERATING", "BLOCKED", "CANCELLED"},
    "GENERATING": {"RECONCILING", "REVIEW_READY", "BLOCKED"},
    "RECONCILING": {"REVIEW_READY", "BLOCKED"},
    "REVIEW_READY": {"CREATIVE_APPROVED", "REJECTED", "BLOCKED"},
    "CREATIVE_APPROVED": {"EXPORT_READY", "REJECTED"},
    "REJECTED": {"CANCELLED"},
    "EXPORT_READY": {"EXPORTED", "BLOCKED"},
    "EXPORTED": {"SCHEDULE_READY", "BLOCKED"},
    "SCHEDULE_READY": {"SCHEDULED", "BLOCKED"},
    "SCHEDULED": {"PUBLISHING", "BLOCKED"},
    "PUBLISHING": {"PUBLISHED", "RECONCILING", "BLOCKED"},
    "PUBLISHED": {"MEASURING"},
    "MEASURING": {"LEARNED", "BLOCKED"},
    "LEARNED": set(),
    "CANCELLED": set(),
}


@dataclass(frozen=True)
class PlanningRequest:
    creator: str
    horizon_days: int
    accounts: tuple[str, ...]
    objective: str
    output_count: int | None
    timezone: str
    autonomy_mode: str
    max_credits: float | None
    start_date: date


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _safe_file(path_value: object, expected_sha: str) -> Path | None:
    path = Path(str(path_value or "")).expanduser()
    if path.is_symlink() or not path.is_file():
        return None
    resolved = path.resolve()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return resolved if digest == expected_sha else None


def _source_compatibility(row: dict[str, Any]) -> set[str]:
    compatible = {
        "passive_selfie",
        "flirty_portrait",
        "lifestyle",
        "animate_existing",
    }
    try:
        notes = json.loads(str(row.get("notes") or "{}"))
    except json.JSONDecodeError:
        notes = {}
    declared = notes.get("intentCompatibility")
    if isinstance(declared, list):
        compatible = {str(value) for value in declared} & SUPPORTED_INTENTS
    source_class = str(notes.get("sourceClass") or "").lower()
    if source_class in {"full_body", "mid_body", "mirror"}:
        compatible.add("outfit")
    return compatible


def _approved_sources(conn: sqlite3.Connection, creator: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.*, m.slug AS creator_slug, c.slug AS campaign_slug
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        JOIN campaigns c ON c.id = s.campaign_id
        WHERE lower(m.slug) = lower(?)
          AND s.media_type = 'image'
          AND lower(s.status) = 'approved'
        ORDER BY s.updated_at DESC, s.id
        """,
        (creator,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stored in rows:
        row = dict(stored)
        sha = str(row["content_hash"])
        path = _safe_file(row["stored_path"], sha)
        if path is None or sha in seen:
            continue
        seen.add(sha)
        row["stored_path"] = str(path)
        row["compatibleIntents"] = sorted(_source_compatibility(row))
        result.append(row)
    return result


def _approved_patterns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM reference_patterns ORDER BY rank, imported_at DESC, id"
    ).fetchall()
    result: list[dict[str, Any]] = []
    for stored in rows:
        row = dict(stored)
        try:
            raw = json.loads(str(row.get("raw_json") or "{}"))
            prompt = json.loads(str(row.get("prompt_template_json") or "{}"))
        except json.JSONDecodeError:
            continue
        if str(raw.get("approvalStatus") or "").lower() not in {
            "approved",
            "accepted",
            "operator_approved",
        }:
            continue
        text = next(
            (
                str(prompt.get(key) or "").strip()
                for key in ("mainPrompt", "motionPrompt", "prompt")
                if str(prompt.get(key) or "").strip()
            ),
            "",
        )
        if not text:
            continue
        result.append(
            {
                "id": row["id"],
                "family": str(raw.get("patternFamily") or "visual_first"),
                "prompt": text,
                "rank": int(row.get("rank") or 9999),
                "label": row["label"],
            }
        )
    return result


def _account_state(conn: sqlite3.Connection, handle: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, handle, model_id, account_group_id, threadsdash_is_active,
               threadsdash_status, threadsdash_needs_reauth,
               threadsdash_projection_observed_at
        FROM accounts WHERE lower(handle) = lower(?) AND platform = 'instagram'
        """,
        (handle.lstrip("@"),),
    ).fetchone()
    if row is None:
        return {
            "handle": handle,
            "eligible": False,
            "reason": "account_projection_missing",
            "accountId": None,
        }
    item = dict(row)
    eligible = (
        item.get("threadsdash_is_active") == 1
        and item.get("threadsdash_needs_reauth") in {0, None}
        and str(item.get("threadsdash_status") or "").lower()
        not in {"blocked", "restricted", "disabled", "reauth_required"}
    )
    return {
        "handle": item["handle"],
        "accountId": item["id"],
        "accountGroupId": item.get("account_group_id"),
        "eligible": eligible,
        "reason": "healthy_projection" if eligible else "account_projection_unhealthy",
        "projectionObservedAt": item.get("threadsdash_projection_observed_at"),
    }


def _exploration_classes(count: int, objective_policy: dict[str, Any]) -> list[str]:
    if count <= 0:
        return []
    explore = round(count * float(objective_policy["explore"]))
    variation = round(count * float(objective_policy["controlledVariation"]))
    if explore + variation > count:
        explore = max(0, count - variation)
    exploit = count - explore - variation
    classes = (
        ["EXPLOIT"] * exploit
        + ["CONTROLLED_VARIATION"] * variation
        + ["EXPLORE"] * explore
    )
    return classes[:count]


def _plan_count(request: PlanningRequest, policy: dict[str, Any]) -> int:
    requested = request.output_count
    if requested is not None:
        if not 1 <= requested <= 100:
            raise ValueError("output count must be between 1 and 100")
        return requested
    per_account = int(policy["weeklyOutputTargetPerAccount"])
    scaled = max(1, round(per_account * request.horizon_days / 7))
    return scaled * max(1, len(request.accounts))


def build_plan(conn: sqlite3.Connection, request: PlanningRequest) -> dict[str, Any]:
    creator = request.creator.strip().lower()
    if creator not in _CREATOR_SOUL_IDS:
        raise ValueError(f"unknown creator identity: {request.creator}")
    if request.objective not in _policy()["objectives"]:
        raise ValueError(f"unsupported objective: {request.objective}")
    if request.autonomy_mode not in AUTONOMY_MODES:
        raise ValueError(f"unsupported autonomy mode: {request.autonomy_mode}")
    if not 1 <= request.horizon_days <= 31:
        raise ValueError("horizon must be between 1 and 31 days")
    if not request.accounts:
        raise ValueError("at least one account is required")

    policy = _policy()
    objective_policy = dict(policy["objectives"][request.objective])
    count = _plan_count(request, policy)
    sources = _approved_sources(conn, creator)
    patterns = _approved_patterns(conn)
    account_states = [_account_state(conn, account) for account in request.accounts]
    account_by_handle = {str(row["handle"]): row for row in account_states}
    horizon_end = request.start_date + timedelta(days=request.horizon_days - 1)
    classes = _exploration_classes(count, objective_policy)
    intents = [
        intent
        for intent in policy["intentMix"]
        if intent in SUPPORTED_INTENTS
        and any(intent in source["compatibleIntents"] for source in sources)
    ]
    if not intents:
        intents = ["passive_selfie"]

    plan_items: list[dict[str, Any]] = []
    source_usage: dict[str, int] = {}
    for index in range(count):
        intent = intents[index % len(intents)]
        account = request.accounts[index % len(request.accounts)]
        state = account_by_handle.get(account) or _account_state(conn, account)
        compatible = [
            source for source in sources if intent in source["compatibleIntents"]
        ]
        base_prompt = INTENT_PROMPTS[intent]
        pattern = patterns[index % len(patterns)] if patterns else None
        if pattern:
            base_prompt = pattern["prompt"]
        learning_sources, learned_prompt, learning = apply_learning_to_production_plan(
            conn,
            creator=creator,
            creator_identity_profile=_CREATOR_SOUL_IDS[creator],
            account=account,
            intent=intent,
            sources=compatible,
            base_prompt=base_prompt,
        )
        source = None
        if learning_sources:
            minimum_usage = min(
                source_usage.get(str(candidate["id"]), 0)
                for candidate in learning_sources
            )
            source = next(
                candidate
                for candidate in learning_sources
                if source_usage.get(str(candidate["id"]), 0) == minimum_usage
            )
            source_id = str(source["id"])
            source_usage[source_id] = source_usage.get(source_id, 0) + 1
        blocking: list[str] = []
        if source is None:
            blocking.append("no_approved_compatible_source")
        if not state["eligible"]:
            blocking.append(str(state["reason"]))
        if request.max_credits is None:
            blocking.append("signed_spend_ceiling_missing")
        cost = float(policy["estimatedCreditsPerPassiveReel"])
        item_core = {
            "index": index,
            "creator": creator,
            "identityProfile": _CREATOR_SOUL_IDS[creator],
            "targetAccount": account,
            "accountState": state,
            "contentIntent": intent,
            "sourceAssetId": source.get("id") if source else None,
            "sourceCandidateIds": [str(row["id"]) for row in compatible],
            "sourceCooldown": {
                "scope": "current_plan",
                "selectionRule": "least_used_approved_compatible_source",
                "reuseCountAfterSelection": (
                    source_usage.get(str(source["id"]), 0) if source else 0
                ),
                "unavoidableReuse": bool(
                    source
                    and source_usage.get(str(source["id"]), 0) > 1
                    and len(plan_items) >= len(sources)
                ),
            },
            "referencePatternId": pattern.get("id") if pattern else None,
            "patternFamily": pattern.get("family") if pattern else "visual_first",
            "prompt": learned_prompt,
            "durationSeconds": float(policy["defaultDurationSeconds"]),
            "audioPolicy": "embedded_trending_required",
            "audioProfile": {
                "profile": policy["audioProfiles"][intent][
                    index % len(policy["audioProfiles"][intent])
                ],
                "resolveAt": "finishing",
                "trendSignal": "tiktok_primary",
                "internalPerformanceSignal": "soft_when_exact_linked",
                "creatorCooldownRequired": True,
                "accountCooldownRequired": True,
                "batchTrackUniquenessRequired": True,
                "batchSegmentUniquenessRequired": True,
            },
            "explorationClass": classes[index],
            "priority": count - index,
            "estimatedCost": {
                "credits": cost,
                "status": "estimate_not_quote",
                "evidence": policy["costEvidence"],
            },
            "learningDecision": learning,
            "blockingReasons": blocking,
            "executionState": "BLOCKED" if blocking else "DRAFT",
        }
        item_core["decisionFingerprint"] = _fingerprint(item_core)
        plan_items.append(item_core)

    estimated_credits = round(
        sum(float(item["estimatedCost"]["credits"]) for item in plan_items), 4
    )
    if request.max_credits is not None and estimated_credits > float(
        request.max_credits
    ):
        for item in plan_items:
            if (
                "estimated_plan_cost_exceeds_signed_ceiling"
                not in item["blockingReasons"]
            ):
                item["blockingReasons"].append(
                    "estimated_plan_cost_exceeds_signed_ceiling"
                )
                item["executionState"] = "BLOCKED"
    inputs = {
        "creator": creator,
        "identityProfile": _CREATOR_SOUL_IDS[creator],
        "horizonStart": request.start_date.isoformat(),
        "horizonEnd": horizon_end.isoformat(),
        "accounts": list(request.accounts),
        "objective": request.objective,
        "outputCount": count,
        "timezone": request.timezone,
        "autonomyMode": request.autonomy_mode,
        "maxCredits": request.max_credits,
        "policyFingerprint": _fingerprint(policy),
        "sourceFingerprints": [
            [source["id"], source["content_hash"]] for source in sources
        ],
        "patternFingerprints": [
            [pattern["id"], _fingerprint(pattern)] for pattern in patterns
        ],
        "items": [item["decisionFingerprint"] for item in plan_items],
    }
    input_fingerprint = _fingerprint(inputs)
    plan_id = f"plan_{input_fingerprint[:16]}"
    blocked = sum(bool(item["blockingReasons"]) for item in plan_items)
    receipt = {
        "schema": "creator_os.content_plan_decision.v1",
        "planId": plan_id,
        "inputFingerprint": input_fingerprint,
        "objective": {
            "id": request.objective,
            "weights": objective_policy,
            "effect": objective_policy["description"],
        },
        "learning": {
            "consulted": True,
            "appliedItems": [
                index
                for index, item in enumerate(plan_items)
                if item["learningDecision"]["learningApplied"]
            ],
            "changedItems": [
                index
                for index, item in enumerate(plan_items)
                if item["learningDecision"]["finalChoiceChanged"]
            ],
        },
        "resultingAllocation": {
            value: classes.count(value)
            for value in ("EXPLOIT", "CONTROLLED_VARIATION", "EXPLORE")
        },
        "blockedItems": blocked,
        "reason": "bounded deterministic planning from approved inventory",
    }
    return {
        "schema": "creator_os.content_plan.v1",
        "planId": plan_id,
        "version": 1,
        "creator": creator,
        "identityProfile": _CREATOR_SOUL_IDS[creator],
        "horizon": {
            "start": request.start_date.isoformat(),
            "end": horizon_end.isoformat(),
            "days": request.horizon_days,
        },
        "accounts": account_states,
        "timezone": request.timezone,
        "objective": request.objective,
        "requestedOutputCount": count,
        "contentMixPolicy": {
            "intents": intents,
            "actualCounts": {
                intent: sum(item["contentIntent"] == intent for item in plan_items)
                for intent in intents
            },
        },
        "explorationPolicy": objective_policy,
        "estimatedSpend": {
            "credits": estimated_credits,
            "status": "estimate_not_quote",
            "unknownCosts": ["provider_live_quote", "SocialCrawl_usage"],
        },
        "signedSpendCeiling": request.max_credits,
        "creationWindow": {
            "start": request.start_date.isoformat(),
            "end": horizon_end.isoformat(),
        },
        "publicationWindow": {
            "start": request.start_date.isoformat(),
            "end": horizon_end.isoformat(),
            "status": "proposal_pending_schedule_policy",
        },
        "autonomyMode": request.autonomy_mode,
        "status": "BLOCKED" if blocked else "DRAFT",
        "inputFingerprint": input_fingerprint,
        "previousPlanVersionId": None,
        "decisionReceipt": receipt,
        "items": plan_items,
        "applyWouldWrite": {
            "creativePlans": 1,
            "creativePlanVersions": 1,
            "creativePlanItems": len(plan_items),
            "providerCalls": 0,
            "exports": 0,
            "schedules": 0,
            "publications": 0,
        },
    }


def persist_plan(conn: sqlite3.Connection, plan: dict[str, Any]) -> dict[str, Any]:
    existing = conn.execute(
        "SELECT * FROM creative_plan_versions WHERE input_fingerprint = ?",
        (plan["inputFingerprint"],),
    ).fetchone()
    if existing is not None:
        return {
            **load_plan(conn, str(existing["id"])),
            "idempotent": True,
            "written": False,
        }
    creator = str(plan["creator"])
    root_name = f"{creator}_rolling_content_director"
    root = conn.execute(
        "SELECT id FROM creative_plans WHERE name = ?", (root_name,)
    ).fetchone()
    now = _now()
    if root is None:
        creative_plan_id = f"cplan_{_fingerprint(root_name)[:16]}"
        conn.execute(
            """
            INSERT INTO creative_plans (
              id, name, platform, goal, target_account, daily_base_video_target,
              style_lanes_json, model_profile, source_accounts_json, status,
              linked_campaign_slug, created_at, updated_at
            ) VALUES (?, ?, 'instagram', ?, ?, ?, '[]', ?, '[]', 'planned',
                      NULL, ?, ?)
            """,
            (
                creative_plan_id,
                root_name,
                plan["objective"].lower(),
                plan["accounts"][0]["handle"],
                max(1, round(plan["requestedOutputCount"] / plan["horizon"]["days"])),
                creator,
                now,
                now,
            ),
        )
    else:
        creative_plan_id = str(root["id"])
    previous = conn.execute(
        """
        SELECT id, version FROM creative_plan_versions
        WHERE creative_plan_id = ? ORDER BY version DESC LIMIT 1
        """,
        (creative_plan_id,),
    ).fetchone()
    version = int(previous["version"]) + 1 if previous else 1
    version_id = f"{plan['planId']}_v{version}"
    conn.execute(
        """
        INSERT INTO creative_plan_versions (
          id, creative_plan_id, version, creator, identity_profile,
          horizon_start, horizon_end, account_scope_json, timezone, objective,
          requested_output_count, content_mix_policy_json,
          exploration_policy_json, estimated_spend_json, signed_spend_ceiling,
          creation_window_json, publication_window_json, autonomy_mode, status,
          input_fingerprint, previous_plan_version_id, decision_receipt_json,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?)
        """,
        (
            version_id,
            creative_plan_id,
            version,
            plan["creator"],
            plan["identityProfile"],
            plan["horizon"]["start"],
            plan["horizon"]["end"],
            _json(plan["accounts"]),
            plan["timezone"],
            plan["objective"],
            plan["requestedOutputCount"],
            _json(plan["contentMixPolicy"]),
            _json(plan["explorationPolicy"]),
            _json(plan["estimatedSpend"]),
            plan["signedSpendCeiling"],
            _json(plan["creationWindow"]),
            _json(plan["publicationWindow"]),
            plan["autonomyMode"],
            plan["status"],
            plan["inputFingerprint"],
            previous["id"] if previous else None,
            _json(plan["decisionReceipt"]),
            now,
            now,
        ),
    )
    for index, item in enumerate(plan["items"]):
        item_id = f"pitem_{_fingerprint([version_id, index])[:16]}"
        conn.execute(
            """
            INSERT INTO creative_plan_items (
              id, plan_version_id, item_index, creator, identity_profile,
              target_account, content_intent, source_asset_id,
              source_candidate_ids_json, source_ranking_json,
              reference_pattern_id, pattern_family, pattern_ranking_json,
              prompt_text, desired_duration_seconds, audio_policy,
              audio_profile_json, proposed_window_json, experiment_id,
              experiment_variant, exploration_class, priority, dependencies_json,
              estimated_cost_json, execution_state, generation_identity_json,
              review_identity_json, export_identity_json, publication_identity_json,
              metric_cohort_identity_json, learning_outcome_identity_json,
              decision_receipt_json, blocking_reasons_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}',
                      NULL, NULL, ?, ?, '[]', ?, ?, '{}', '{}', '{}', '{}', '{}',
                      '{}', ?, ?, ?, ?)
            """,
            (
                item_id,
                version_id,
                index,
                item["creator"],
                item["identityProfile"],
                item["targetAccount"],
                item["contentIntent"],
                item["sourceAssetId"],
                _json(item["sourceCandidateIds"]),
                _json(
                    {
                        "baseCandidateIds": item["sourceCandidateIds"],
                        "selected": item["sourceAssetId"],
                        "learningDecision": item["learningDecision"],
                    }
                ),
                item["referencePatternId"],
                item["patternFamily"],
                _json(
                    {
                        "selected": item["referencePatternId"],
                        "learningDecision": item["learningDecision"],
                    }
                ),
                item["prompt"],
                item["durationSeconds"],
                item["audioPolicy"],
                _json(item["audioProfile"]),
                item["explorationClass"],
                item["priority"],
                _json(item["estimatedCost"]),
                item["executionState"],
                _json(item),
                _json(item["blockingReasons"]),
                now,
                now,
            ),
        )
    conn.commit()
    stored = load_plan(conn, version_id)
    return {**stored, "idempotent": False, "written": True}


def load_plan(conn: sqlite3.Connection, plan_id: str) -> dict[str, Any]:
    version = conn.execute(
        """
        SELECT * FROM creative_plan_versions
        WHERE id = ? OR input_fingerprint = ?
        ORDER BY version DESC LIMIT 1
        """,
        (plan_id, plan_id),
    ).fetchone()
    if version is None:
        root = conn.execute(
            "SELECT id FROM creative_plans WHERE id = ? OR name = ?",
            (plan_id, plan_id),
        ).fetchone()
        if root:
            version = conn.execute(
                """
                SELECT * FROM creative_plan_versions
                WHERE creative_plan_id = ? ORDER BY version DESC LIMIT 1
                """,
                (root["id"],),
            ).fetchone()
    if version is None:
        raise ValueError(f"content plan not found: {plan_id}")
    items = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM creative_plan_items
            WHERE plan_version_id = ? ORDER BY item_index
            """,
            (version["id"],),
        ).fetchall()
    ]
    return {
        "schema": "creator_os.persisted_content_plan.v1",
        "planId": version["id"],
        "creativePlanId": version["creative_plan_id"],
        "version": version["version"],
        "creator": version["creator"],
        "identityProfile": version["identity_profile"],
        "horizon": {
            "start": version["horizon_start"],
            "end": version["horizon_end"],
        },
        "accounts": json.loads(version["account_scope_json"]),
        "timezone": version["timezone"],
        "objective": version["objective"],
        "requestedOutputCount": version["requested_output_count"],
        "estimatedSpend": json.loads(version["estimated_spend_json"]),
        "signedSpendCeiling": version["signed_spend_ceiling"],
        "autonomyMode": version["autonomy_mode"],
        "status": version["status"],
        "inputFingerprint": version["input_fingerprint"],
        "previousPlanVersionId": version["previous_plan_version_id"],
        "decisionReceipt": json.loads(version["decision_receipt_json"]),
        "items": [
            {
                **item,
                "source_candidate_ids": json.loads(item["source_candidate_ids_json"]),
                "audio_profile": json.loads(item["audio_profile_json"]),
                "blocking_reasons": json.loads(item["blocking_reasons_json"]),
                "decision_receipt": json.loads(item["decision_receipt_json"]),
            }
            for item in items
        ],
    }


def transition_plan(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    to_state: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    if to_state not in PLAN_STATES:
        raise ValueError(f"invalid plan state: {to_state}")
    version = conn.execute(
        "SELECT * FROM creative_plan_versions WHERE id = ?", (plan_id,)
    ).fetchone()
    if version is None:
        raise ValueError(f"content plan not found: {plan_id}")
    current = str(version["status"])
    if to_state not in PLAN_TRANSITIONS[current]:
        raise ValueError(f"invalid plan transition: {current} -> {to_state}")
    if to_state == "APPROVED":
        blocked = conn.execute(
            """
            SELECT count(*) FROM creative_plan_items
            WHERE plan_version_id = ? AND json_array_length(blocking_reasons_json) > 0
            """,
            (plan_id,),
        ).fetchone()[0]
        if blocked:
            raise ValueError("blocked plan items prevent approval")
    now = _now()
    receipt = {
        "schema": "creator_os.plan_transition.v1",
        "planId": plan_id,
        "from": current,
        "to": to_state,
        "operator": operator,
        "reason": reason,
        "at": now,
    }
    conn.execute(
        "UPDATE creative_plan_versions SET status = ?, updated_at = ? WHERE id = ?",
        (to_state, now, plan_id),
    )
    conn.execute(
        """
        INSERT INTO creative_plan_events (
          id, creative_plan_id, event_type, status, message, metadata_json, created_at
        ) VALUES (?, ?, 'content_plan_transition', 'success', ?, ?, ?)
        """,
        (
            f"cpevt_{_fingerprint(receipt)[:16]}",
            version["creative_plan_id"],
            f"{current} -> {to_state}",
            _json(receipt),
            now,
        ),
    )
    conn.commit()
    return {**load_plan(conn, plan_id), "transitionReceipt": receipt}


def _horizon(value: str) -> int:
    normalized = value.strip().lower()
    if not normalized.endswith("d") or not normalized[:-1].isdigit():
        raise argparse.ArgumentTypeError("horizon must look like 7d")
    return int(normalized[:-1])


def _request(args: argparse.Namespace) -> PlanningRequest:
    accounts = tuple(
        item.strip() for item in str(args.accounts or "").split(",") if item.strip()
    )
    return PlanningRequest(
        creator=args.creator,
        horizon_days=args.horizon,
        accounts=accounts,
        objective=args.goal.upper(),
        output_count=args.count,
        timezone=args.timezone,
        autonomy_mode=args.mode.upper(),
        max_credits=args.max_credits,
        start_date=date.fromisoformat(args.start_date or date.today().isoformat()),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--creator", required=True)
    build.add_argument("--horizon", type=_horizon, default=7)
    build.add_argument("--accounts", required=True)
    build.add_argument(
        "--goal",
        choices=[key.lower() for key in _policy()["objectives"]],
        default="growth",
    )
    build.add_argument("--count", type=int)
    build.add_argument("--timezone", default=_policy()["defaultTimezone"])
    build.add_argument(
        "--mode",
        choices=[value.lower() for value in AUTONOMY_MODES],
        default=_policy()["defaultAutonomyMode"].lower(),
    )
    build.add_argument("--max-credits", type=float)
    build.add_argument("--start-date")
    mode = build.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("plan_id")
    listing = sub.add_parser("list")
    listing.add_argument("--creator")
    listing.add_argument("--limit", type=int, default=50)
    approve = sub.add_parser("approve")
    approve.add_argument("plan_id")
    approve.add_argument("--operator", default="authenticated_local_operator")
    approve.add_argument("--reason", default="operator_approved_plan")
    schedule = sub.add_parser("schedule-propose")
    schedule.add_argument("plan_id")
    schedule.add_argument("--blackout-date", action="append", default=[])
    schedule_mode = schedule.add_mutually_exclusive_group(required=True)
    schedule_mode.add_argument("--dry-run", action="store_true")
    schedule_mode.add_argument("--apply", action="store_true")
    experiment = sub.add_parser("experiment")
    experiment.add_argument("plan_id")
    experiment.add_argument("--variable", required=True)
    experiment.add_argument("--variant", action="append", required=True)
    experiment.add_argument("--hypothesis", required=True)
    experiment_mode = experiment.add_mutually_exclusive_group(required=True)
    experiment_mode.add_argument("--dry-run", action="store_true")
    experiment_mode.add_argument("--apply", action="store_true")
    execute = sub.add_parser("execute")
    execute.add_argument("plan_id")
    execute.add_argument("--max-credits", type=float)
    execute_mode = execute.add_mutually_exclusive_group(required=True)
    execute_mode.add_argument("--dry-run", action="store_true")
    execute_mode.add_argument("--apply", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("plan_id")
    review.add_argument("--item")
    review.add_argument("--action", dest="review_action")
    review.add_argument("--operator", default="authenticated_local_operator")
    review.add_argument("--reason")
    export = sub.add_parser("export")
    export.add_argument("plan_id")
    export.add_argument("--approved-only", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("plan_id")
    replan_parser = sub.add_parser("replan")
    replan_parser.add_argument("plan_id")
    replan_mode = replan_parser.add_mutually_exclusive_group(required=True)
    replan_mode.add_argument("--dry-run", action="store_true")
    replan_mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    writes = getattr(args, "apply", False) or args.action in {"approve", "review"}
    uri = f"file:{settings.db_path}?mode={'rw' if writes else 'ro'}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if args.action == "build":
            before = conn.total_changes
            plan = build_plan(conn, _request(args))
            result = (
                persist_plan(conn, plan)
                if args.apply
                else {
                    **plan,
                    "dryRun": True,
                    "persistentWrites": conn.total_changes - before,
                }
            )
        elif args.action == "show":
            result = load_plan(conn, args.plan_id)
        elif args.action == "list":
            from .content_director_operations import list_plans

            result = list_plans(conn, creator=args.creator, limit=args.limit)
        elif args.action == "approve":
            result = transition_plan(
                conn,
                plan_id=args.plan_id,
                to_state="APPROVED",
                operator=args.operator,
                reason=args.reason,
            )
        else:
            from .content_director_operations import (
                design_experiment,
                export_manifest_preview,
                plan_execution,
                plan_status,
                propose_schedule,
                replan,
                review_plan_item,
            )

            if args.action == "schedule-propose":
                result = propose_schedule(
                    conn,
                    args.plan_id,
                    apply=args.apply,
                    blackout_dates=frozenset(args.blackout_date),
                )
            elif args.action == "experiment":
                result = design_experiment(
                    conn,
                    plan_id=args.plan_id,
                    changed_variable=args.variable,
                    variants=tuple(args.variant),
                    hypothesis=args.hypothesis,
                    apply=args.apply,
                )
            elif args.action == "execute":
                from .core import CampaignFactory

                factory = CampaignFactory(settings)
                try:
                    result = plan_execution(
                        factory.conn,
                        factory,
                        plan_id=args.plan_id,
                        apply=args.apply,
                        signed_spend_credits=args.max_credits,
                    )
                finally:
                    factory.close()
            elif args.action == "review" and args.item and args.review_action:
                result = review_plan_item(
                    conn,
                    plan_item_id=args.item,
                    action=args.review_action,
                    operator=args.operator,
                    reason=args.reason or "operator_review",
                )
            elif args.action == "review":
                plan = load_plan(conn, args.plan_id)
                result = {
                    "schema": "creator_os.plan_review.v1",
                    "planId": plan["planId"],
                    "objective": plan["objective"],
                    "items": plan["items"],
                    "operatorVerdict": None,
                }
            elif args.action == "status":
                result = plan_status(conn, args.plan_id)
            elif args.action == "replan":
                result = replan(conn, plan_id=args.plan_id, apply=args.apply)
            else:
                result = export_manifest_preview(conn, args.plan_id)
    finally:
        conn.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
