from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from .core import new_id, utc_now
from .creation_modes import run_creation_batch
from .derived_stills import validate_static_source_assets

ALGORITHM_VERSION: Final = "creator_round_robin_v1"
STALE_CLAIM_MINUTES: Final = 30


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _candidates(
    factory: Any,
    *,
    run_key: str,
    now: str,
    per_creator_cap: int,
    per_campaign_cap: int,
) -> list[dict[str, Any]]:
    cutoff = (_parse_time(now) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    rows = factory.conn.execute(
        """
        SELECT c.id AS campaign_id, c.slug AS campaign_slug,
               m.id AS creator_id, m.slug AS creator_slug,
               cg.production_priority, cp.daily_base_video_target,
               cp.style_lanes_json, s.id AS source_asset_id,
               s.stored_path AS source_path, s.content_hash AS source_sha256,
               (
                 SELECT ra.id FROM rendered_assets ra
                 WHERE ra.source_asset_id = s.id
                   AND ra.review_state = 'approved'
                   AND NOT EXISTS (
                     SELECT 1 FROM asset_inventory_reservations reservation
                     WHERE reservation.asset_id = ra.id
                       AND reservation.status IN ('pending', 'committed')
                   )
                 ORDER BY ra.updated_at DESC, ra.id
                 LIMIT 1
               ) AS reusable_asset_id,
               COALESCE((
                 SELECT AVG(CASE WHEN ra.review_state = 'approved' THEN 1.0 ELSE 0.0 END)
                 FROM rendered_assets ra
                 WHERE ra.campaign_id = c.id
               ), 1.0) AS quality_yield,
               COALESCE((
                 SELECT COUNT(*) FROM daily_orchestrator_items prior
                 WHERE prior.creator_id = m.id
                   AND datetime(prior.created_at) >= datetime(?)
                   AND prior.state IN ('selected', 'running', 'completed')
               ), 0) AS creator_recent,
               COALESCE((
                 SELECT COUNT(*) FROM daily_orchestrator_items prior
                 WHERE prior.campaign_id = c.id
                   AND datetime(prior.created_at) >= datetime(?)
                   AND prior.state IN ('selected', 'running', 'completed')
               ), 0) AS campaign_recent,
               (
                 SELECT MAX(prior.created_at) FROM daily_orchestrator_items prior
                 WHERE prior.creator_id = m.id
               ) AS creator_last_served,
               (
                 SELECT MAX(prior.next_attempt_at)
                 FROM daily_orchestrator_items prior
                 WHERE prior.campaign_id = c.id
                   AND prior.state = 'blocked'
               ) AS blocked_until
        FROM campaign_governance cg
        JOIN campaigns c ON c.id = cg.campaign_id
        JOIN models m ON m.id = cg.model_id
        JOIN creator_lifecycle_state cls ON cls.model_id = m.id
        LEFT JOIN creative_plans cp ON cp.linked_campaign_slug = c.slug
          AND cp.status IN ('planned', 'active')
        JOIN source_assets s ON s.campaign_id = c.id
          AND s.model_id = m.id
          AND s.media_type = 'image'
          AND lower(COALESCE(s.status, '')) = 'approved'
        WHERE cls.status = 'active'
          AND cg.lifecycle_status IN ('production_ready', 'producing')
          AND COALESCE(cg.blocker_codes_json, '[]') = '[]'
          AND NOT EXISTS (
            SELECT 1 FROM daily_orchestrator_items exhausted
            WHERE exhausted.campaign_id = c.id
              AND exhausted.source_asset_id = s.id
              AND exhausted.state = 'exhausted'
          )
        ORDER BY m.id, c.id, s.updated_at DESC, s.id
        """,
        (cutoff, cutoff),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    current = _parse_time(now)
    for row in rows:
        item = dict(row)
        blocked_until = item.get("blocked_until")
        if blocked_until and _parse_time(str(blocked_until)) > current:
            continue
        target = max(1, int(item.get("daily_base_video_target") or 1))
        recent = int(item.get("campaign_recent") or 0)
        creator_remaining = per_creator_cap - int(item.get("creator_recent") or 0)
        campaign_remaining = min(target, per_campaign_cap) - recent
        if creator_remaining <= 0 or campaign_remaining <= 0:
            continue
        source = Path(str(item.get("source_path") or "")).expanduser()
        if source.is_symlink() or not source.is_file():
            continue
        with source.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != item.get(
                "source_sha256"
            ):
                continue
        mode = _planned_mode(item.get("style_lanes_json"))
        if mode == "static_reel":
            try:
                validate_static_source_assets(
                    factory,
                    (str(item["source_asset_id"]),),
                )
            except (PermissionError, ValueError):
                continue
        provider = "internal" if mode == "static_reel" else "higgsfield"
        try:
            governance = factory.domains.creator_governance.resolve_operation(
                creator=str(item["creator_id"]),
                campaign=str(item["campaign_id"]),
                operation="generation",
                provider=provider,
                source_asset_id=str(item["source_asset_id"]),
                at=now,
            )
        except PermissionError:
            continue
        item["target"] = target
        item["remainingTarget"] = target - recent
        item["creatorRemainingCap"] = creator_remaining
        item["campaignRemainingCap"] = campaign_remaining
        item["mode"] = mode
        item["provider"] = provider
        item["requiresProvider"] = provider != "internal"
        item["governance"] = governance
        item["completionRatio"] = recent / target
        item["stableTieBreak"] = _fingerprint(
            [run_key, item["creator_id"], item["campaign_id"]]
        )
        candidates.append(item)
    return candidates


def _planned_mode(style_lanes_json: Any) -> str:
    try:
        lanes = json.loads(str(style_lanes_json or "[]"))
    except json.JSONDecodeError:
        return "static_reel"
    for lane in lanes if isinstance(lanes, list) else []:
        candidate = lane.get("mode") if isinstance(lane, dict) else lane
        if candidate in {"static_reel", "calm_animation"}:
            return str(candidate)
    return "static_reel"


def _recent_provider_count(factory: Any, *, now: str) -> int:
    cutoff = (_parse_time(now) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    return int(
        factory.conn.execute(
            """
            SELECT COUNT(*) FROM daily_orchestrator_items
            WHERE datetime(created_at) >= datetime(?)
              AND mode != 'static_reel'
              AND state IN ('selected', 'running', 'completed')
            """,
            (cutoff,),
        ).fetchone()[0]
    )


def _filter_cross_run_capacity(
    factory: Any,
    selected: list[dict[str, Any]],
    *,
    now: str,
    per_creator_cap: int,
    per_campaign_cap: int,
    provider_cap: int,
) -> list[dict[str, Any]]:
    """Recheck daily limits while the caller owns an IMMEDIATE transaction."""

    cutoff = (_parse_time(now) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    creator_counts = {
        str(row[0]): int(row[1])
        for row in factory.conn.execute(
            """
            SELECT creator_id, COUNT(*) FROM daily_orchestrator_items
            WHERE datetime(created_at) >= datetime(?)
              AND state IN ('selected', 'running', 'completed')
            GROUP BY creator_id
            """,
            (cutoff,),
        ).fetchall()
    }
    campaign_counts = {
        str(row[0]): int(row[1])
        for row in factory.conn.execute(
            """
            SELECT campaign_id, COUNT(*) FROM daily_orchestrator_items
            WHERE datetime(created_at) >= datetime(?)
              AND state IN ('selected', 'running', 'completed')
            GROUP BY campaign_id
            """,
            (cutoff,),
        ).fetchall()
    }
    provider_count = _recent_provider_count(factory, now=now)
    accepted: list[dict[str, Any]] = []
    for item in selected:
        creator_id = str(item["creator_id"])
        campaign_id = str(item["campaign_id"])
        requires_provider = item["mode"] != "static_reel"
        if (
            creator_counts.get(creator_id, 0) >= per_creator_cap
            or campaign_counts.get(campaign_id, 0) >= per_campaign_cap
            or (requires_provider and provider_count >= provider_cap)
        ):
            continue
        accepted.append(item)
        creator_counts[creator_id] = creator_counts.get(creator_id, 0) + 1
        campaign_counts[campaign_id] = campaign_counts.get(campaign_id, 0) + 1
        if requires_provider:
            provider_count += 1
    return accepted


def _fair_order(
    candidates: list[dict[str, Any]],
    *,
    max_items: int,
    per_creator_cap: int,
    per_campaign_cap: int,
    provider_cap: int,
) -> list[dict[str, Any]]:
    by_creator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_creator[str(candidate["creator_id"])].append(candidate)
    for creator_candidates in by_creator.values():
        creator_candidates.sort(
            key=lambda item: (
                item["completionRatio"],
                -int(item.get("production_priority") or 0),
                int(item.get("campaign_recent") or 0),
                -float(item.get("quality_yield") or 0),
                str(item["stableTieBreak"]),
            )
        )
    creator_order = sorted(
        by_creator,
        key=lambda creator_id: (
            min(
                int(item.get("creator_recent") or 0) for item in by_creator[creator_id]
            ),
            min(
                str(item.get("creator_last_served") or "")
                for item in by_creator[creator_id]
            ),
            creator_id,
        ),
    )
    selected: list[dict[str, Any]] = []
    creator_counts: dict[str, int] = defaultdict(int)
    campaign_counts: dict[str, int] = defaultdict(int)
    provider_count = 0
    while len(selected) < max_items:
        progressed = False
        for creator_id in creator_order:
            creator_budget = min(
                per_creator_cap,
                min(
                    int(item.get("creatorRemainingCap") or 0)
                    for item in by_creator[creator_id]
                ),
            )
            if creator_counts[creator_id] >= creator_budget:
                continue
            eligible = next(
                (
                    item
                    for item in by_creator[creator_id]
                    if campaign_counts[str(item["campaign_id"])]
                    < min(
                        per_campaign_cap,
                        int(item.get("campaignRemainingCap") or 0),
                    )
                    and (
                        not item.get("requiresProvider")
                        or provider_count < provider_cap
                    )
                    and item not in selected
                ),
                None,
            )
            if eligible is None:
                continue
            selected.append(eligible)
            creator_counts[creator_id] += 1
            campaign_counts[str(eligible["campaign_id"])] += 1
            if eligible.get("requiresProvider"):
                provider_count += 1
            progressed = True
            if len(selected) >= max_items:
                break
        if not progressed:
            break
    return selected


def _batch_succeeded(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    summary = result.get("summary")
    results = result.get("results")
    if not isinstance(summary, dict) or not isinstance(results, list) or not results:
        return False
    integer_fields = ("requested", "completed", "failed")
    if any(
        isinstance(summary.get(field), bool)
        or not isinstance(summary.get(field), int)
        or int(summary[field]) < 0
        for field in integer_fields
    ):
        return False
    requested = int(summary["requested"])
    if requested <= 0 or summary["failed"] != 0 or len(results) != requested:
        return False
    statuses: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            return False
        status = item.get("status")
        if not isinstance(status, str) or status not in {"completed", "reused"}:
            return False
        statuses.append(status)
    if summary["completed"] < requested:
        return False
    if "reused" in summary and (
        isinstance(summary["reused"], bool)
        or not isinstance(summary["reused"], int)
        or summary["reused"] < 0
        or summary["reused"] != statuses.count("reused")
    ):
        return False
    return True


def _stop_reason(
    *,
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    max_items: int,
    provider_cap: int,
) -> str:
    if len(selected) == max_items:
        return "requested_capacity_filled"
    selected_provider = sum(bool(item.get("requiresProvider")) for item in selected)
    if (
        any(
            item.get("requiresProvider") and item not in selected for item in candidates
        )
        and selected_provider >= provider_cap
    ):
        return "provider_capacity_exhausted"
    if candidates:
        return "creator_or_campaign_capacity_exhausted"
    return "eligible_inventory_exhausted"


def orchestrate_daily(
    factory: Any,
    *,
    run_key: str,
    max_items: int,
    per_creator_cap: int = 2,
    per_campaign_cap: int = 1,
    provider_cap: int = 0,
    max_attempts: int = 3,
    apply: bool = False,
    execute: bool = False,
    runner: Callable[..., dict[str, Any]] = run_creation_batch,
    now: str | None = None,
) -> dict[str, Any]:
    """Plan fairly across creators, then optionally persist and execute creation only."""
    if not run_key.strip():
        raise ValueError("run_key is required")
    if not 1 <= max_items <= 100:
        raise ValueError("max_items must be between 1 and 100")
    if min(per_creator_cap, per_campaign_cap, max_attempts) < 1 or provider_cap < 0:
        raise ValueError("caps and max_attempts must be positive")
    if execute and not apply:
        raise ValueError("execute requires apply")
    timestamp = now or utc_now()
    limits = {
        "maxItems": max_items,
        "perCreator": per_creator_cap,
        "perCampaign": per_campaign_cap,
        "provider": provider_cap,
        "maxAttempts": max_attempts,
    }
    policy_fingerprint = _fingerprint(
        {"algorithm": ALGORITHM_VERSION, "limits": limits}
    )
    if apply:
        factory.domains.inventory_reservations.expire_inventory_reservations()
    prior_run = factory.conn.execute(
        "SELECT * FROM daily_orchestrator_runs WHERE run_key = ?", (run_key,)
    ).fetchone()
    if prior_run is not None:
        if str(prior_run["policy_fingerprint"]) != policy_fingerprint:
            raise ValueError("daily_orchestrator_run_key_policy_mismatch")
        selected = [
            dict(row)
            for row in factory.conn.execute(
                """
                SELECT * FROM daily_orchestrator_items
                WHERE run_id = ? ORDER BY ordinal
                """,
                (prior_run["id"],),
            ).fetchall()
        ]
        run_id = str(prior_run["id"])
    else:
        candidates = _candidates(
            factory,
            run_key=run_key,
            now=timestamp,
            per_creator_cap=per_creator_cap,
            per_campaign_cap=per_campaign_cap,
        )
        provider_remaining = max(
            0,
            provider_cap - _recent_provider_count(factory, now=timestamp),
        )
        ranked = _fair_order(
            candidates,
            max_items=max_items,
            per_creator_cap=per_creator_cap,
            per_campaign_cap=per_campaign_cap,
            provider_cap=provider_remaining,
        )
        stop_reason = _stop_reason(
            selected=ranked,
            candidates=candidates,
            max_items=max_items,
            provider_cap=provider_remaining,
        )
        run_id = new_id("orun")
        selected = []
        for ordinal, candidate in enumerate(ranked):
            reason = {
                "creator": "least_recently_served_round_robin",
                "campaign": "lowest_target_completion_then_priority",
                "source": "latest_exact_approved_campaign_image",
                "reuse": (
                    "exact_approved_unreserved_asset_available"
                    if candidate.get("reusable_asset_id")
                    else "generate_from_exact_approved_source"
                ),
                "spend": (
                    "provider_slot_reserved_subject_to_atomic_quote_authorization"
                    if candidate["requiresProvider"]
                    else "local_static_no_provider_spend"
                ),
                "provider": candidate["provider"],
                "governanceFingerprint": candidate["governance"][
                    "governanceFingerprint"
                ],
                "score": {
                    "completionRatio": candidate["completionRatio"],
                    "creatorRecent": int(candidate.get("creator_recent") or 0),
                    "campaignRecent": int(candidate.get("campaign_recent") or 0),
                    "priority": int(candidate.get("production_priority") or 0),
                    "qualityYield": float(candidate.get("quality_yield") or 0),
                },
            }
            decision = {
                "runKey": run_key,
                "ordinal": ordinal,
                "creatorId": candidate["creator_id"],
                "campaignId": candidate["campaign_id"],
                "sourceAssetId": candidate["source_asset_id"],
                "reason": reason,
            }
            selected.append(
                {
                    "id": new_id("oitem"),
                    "run_id": run_id,
                    "ordinal": ordinal,
                    "creator_id": candidate["creator_id"],
                    "creator_slug": candidate["creator_slug"],
                    "campaign_id": candidate["campaign_id"],
                    "campaign_slug": candidate["campaign_slug"],
                    "source_asset_id": candidate["source_asset_id"],
                    "mode": candidate["mode"],
                    "intent": "passive_selfie",
                    "state": "selected",
                    "attempt_count": 0,
                    "max_attempts": max_attempts,
                    "next_attempt_at": None,
                    "selection_reason_json": json.dumps(reason, sort_keys=True),
                    "decision_fingerprint": _fingerprint(decision),
                    "result_json": None,
                    "error_code": None,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
        if apply:
            factory.conn.execute("BEGIN IMMEDIATE")
            try:
                filtered = _filter_cross_run_capacity(
                    factory,
                    selected,
                    now=timestamp,
                    per_creator_cap=per_creator_cap,
                    per_campaign_cap=per_campaign_cap,
                    provider_cap=provider_cap,
                )
                if len(filtered) != len(selected):
                    stop_reason = "cross_run_capacity_exhausted"
                selected = filtered
                factory.conn.execute(
                    """
                    INSERT INTO daily_orchestrator_runs
                    (id, run_key, status, algorithm_version, policy_fingerprint,
                     requested_items, selected_items, limits_json, stop_reason,
                     next_run_reason, created_at, updated_at)
                    VALUES (?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        run_key,
                        ALGORITHM_VERSION,
                        policy_fingerprint,
                        max_items,
                        len(selected),
                        json.dumps(limits, sort_keys=True),
                        stop_reason,
                        "retry blocked work after bounded backoff; otherwise next daily target",
                        timestamp,
                        timestamp,
                    ),
                )
                for item in selected:
                    factory.conn.execute(
                        """
                        INSERT INTO daily_orchestrator_items
                        (id, run_id, ordinal, creator_id, campaign_id,
                         source_asset_id, mode, intent, state, attempt_count,
                         max_attempts, next_attempt_at, selection_reason_json,
                         decision_fingerprint, result_json, error_code,
                         created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        tuple(
                            item[key]
                            for key in (
                                "id",
                                "run_id",
                                "ordinal",
                                "creator_id",
                                "campaign_id",
                                "source_asset_id",
                                "mode",
                                "intent",
                                "state",
                                "attempt_count",
                                "max_attempts",
                                "next_attempt_at",
                                "selection_reason_json",
                                "decision_fingerprint",
                                "result_json",
                                "error_code",
                                "created_at",
                                "updated_at",
                            )
                        ),
                    )
                factory.conn.commit()
            except Exception:
                factory.conn.rollback()
                raise
    if execute:
        factory.conn.execute(
            "UPDATE daily_orchestrator_runs SET status = 'running', updated_at = ? WHERE id = ?",
            (timestamp, run_id),
        )
        factory.conn.commit()
        for item in selected:
            if item["state"] == "completed":
                continue
            stale_cutoff = (
                (_parse_time(timestamp) - timedelta(minutes=STALE_CLAIM_MINUTES))
                .isoformat()
                .replace("+00:00", "Z")
            )
            reason = json.loads(item["selection_reason_json"])
            provider = str(reason.get("provider") or "internal")
            try:
                factory.domains.creator_governance.resolve_operation(
                    creator=str(item["creator_id"]),
                    campaign=str(item["campaign_id"]),
                    operation="generation",
                    provider=provider,
                    source_asset_id=str(item["source_asset_id"]),
                    at=timestamp,
                )
            except PermissionError as exc:
                factory.conn.execute(
                    """
                    UPDATE daily_orchestrator_items
                    SET state = 'exhausted', error_code = ?, updated_at = ?
                    WHERE id = ? AND state != 'completed'
                    """,
                    (f"governance_changed:{exc}"[:500], timestamp, item["id"]),
                )
                factory.conn.commit()
                continue
            attempts = int(item["attempt_count"]) + 1
            claim = factory.conn.execute(
                """
                UPDATE daily_orchestrator_items
                SET state = 'running', attempt_count = ?, updated_at = ?
                WHERE id = ?
                  AND attempt_count < max_attempts
                  AND (
                    state = 'selected'
                    OR (
                      state = 'blocked'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    )
                    OR (
                      state = 'running'
                      AND updated_at <= ?
                    )
                  )
                """,
                (attempts, timestamp, item["id"], timestamp, stale_cutoff),
            )
            factory.conn.commit()
            if claim.rowcount != 1:
                continue
            try:
                result = runner(
                    factory,
                    creator=item.get("creator_slug")
                    or factory.conn.execute(
                        "SELECT slug FROM models WHERE id = ?", (item["creator_id"],)
                    ).fetchone()["slug"],
                    campaign=item.get("campaign_slug")
                    or factory.conn.execute(
                        "SELECT slug FROM campaigns WHERE id = ?",
                        (item["campaign_id"],),
                    ).fetchone()["slug"],
                    mode=item["mode"],
                    style=item["intent"],
                    count=1,
                    execution="cloud",
                    accounts=None,
                    audio_preference="embedded_trending_required",
                    apply=True,
                    source_asset_ids=(str(item["source_asset_id"]),),
                )
                if not _batch_succeeded(result):
                    raise RuntimeError("production_batch_incomplete_or_failed")
            except Exception as exc:
                exhausted = attempts >= int(item["max_attempts"])
                delay = min(24, 2 ** max(0, attempts - 1))
                retry_at = _parse_time(timestamp) + timedelta(hours=delay)
                factory.conn.execute(
                    """
                    UPDATE daily_orchestrator_items
                    SET state = ?, next_attempt_at = ?, error_code = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "exhausted" if exhausted else "blocked",
                        retry_at.isoformat().replace("+00:00", "Z"),
                        f"{type(exc).__name__}:{exc}"[:500],
                        timestamp,
                        item["id"],
                    ),
                )
            else:
                factory.conn.execute(
                    """
                    UPDATE daily_orchestrator_items
                    SET state = 'completed', result_json = ?, error_code = NULL,
                        next_attempt_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (json.dumps(result, sort_keys=True), timestamp, item["id"]),
                )
            factory.conn.commit()
        incomplete = factory.conn.execute(
            """
            SELECT COUNT(*) FROM daily_orchestrator_items
            WHERE run_id = ? AND state != 'completed'
            """,
            (run_id,),
        ).fetchone()[0]
        factory.conn.execute(
            """
            UPDATE daily_orchestrator_runs
            SET status = ?, updated_at = ? WHERE id = ?
            """,
            ("blocked" if incomplete else "completed", timestamp, run_id),
        )
        factory.conn.commit()
    items = (
        [
            dict(row)
            for row in factory.conn.execute(
                "SELECT * FROM daily_orchestrator_items WHERE run_id = ? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
        ]
        if apply
        else selected
    )
    return {
        "schema": "campaign_factory.daily_orchestrator.v1",
        "runId": run_id if apply else None,
        "runKey": run_key,
        "algorithmVersion": ALGORITHM_VERSION,
        "policyFingerprint": policy_fingerprint,
        "apply": apply,
        "execute": execute,
        "limits": limits,
        "selected": len(items),
        "items": items,
        "stopReason": (
            str(prior_run["stop_reason"]) if prior_run is not None else stop_reason
        ),
        "nextRun": "retry bounded blockers, then recompute fair order",
        "publishingAuthority": False,
    }
