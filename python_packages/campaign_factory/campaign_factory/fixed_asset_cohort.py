"""Truthful fixed-asset learning cohorts within the supervised Content Director."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .content_director import (
    _account_state,
    _creator_planning_context,
    _fingerprint,
    _json,
    _now,
    load_plan,
)
from .existing_media import attach_existing_to_plan
from .learning_consumption import apply_learning_to_production_plan

COHORT_OBJECTIVE = "LEARNING_COHORT"
COHORT_PURPOSE = "MECHANICAL_LEARNING_PROOF"
COHORT_REASON = "replanned_for_truthful_existing_asset_cohort"
OBSERVATION_COHORTS = ("1h", "24h", "72h")
OBSERVATION_OFFSETS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "72h": timedelta(hours=72),
}


@dataclass(frozen=True)
class FixedAssetCohortRequest:
    creator: str
    account: str
    intent: str
    asset_ids: tuple[str, ...]
    observation_cohorts: tuple[str, ...]
    autonomy_mode: str
    timezone: str
    start_date: date


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _published(conn: sqlite3.Connection, asset_id: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1 FROM proof_runs
            WHERE rendered_asset_id = ? AND threadsdash_post_id IS NOT NULL
            UNION ALL
            SELECT 1 FROM variant_account_usage
            WHERE rendered_asset_id = ? AND published_at IS NOT NULL
            LIMIT 1
            """,
            (asset_id, asset_id),
        ).fetchone()
        is not None
    )


def _fixture_evidence(receipt: dict[str, Any]) -> bool:
    classifications = {
        _text(receipt.get("evidenceClass")).lower(),
        _text(receipt.get("provenanceClass")).lower(),
        _text(receipt.get("sourceClass")).lower(),
    }
    return bool(
        receipt.get("fixture") is True
        or receipt.get("isFixture") is True
        or classifications & {"fixture", "fallback", "synthetic_fixture"}
        or _text(receipt.get("campaign")).lower().startswith(("fixture", "test_"))
    )


def _latest_rolling_plan(
    conn: sqlite3.Connection, *, creator: str, account: str
) -> str | None:
    row = conn.execute(
        """
        SELECT pv.id
        FROM creative_plan_versions pv
        JOIN creative_plans cp ON cp.id = pv.creative_plan_id
        WHERE pv.creator = ?
          AND cp.name = ?
          AND EXISTS (
            SELECT 1 FROM creative_plan_items pi
            WHERE pi.plan_version_id = pv.id AND pi.target_account = ?
          )
        ORDER BY pv.version DESC, pv.created_at DESC
        LIMIT 1
        """,
        (creator, f"{creator}_rolling_content_director", account),
    ).fetchone()
    return str(row["id"]) if row else None


def _proposed_window(*, request: FixedAssetCohortRequest, index: int) -> dict[str, Any]:
    zone = ZoneInfo(request.timezone)
    start = datetime.combine(
        request.start_date + timedelta(days=index),
        time(hour=18, minute=30),
        tzinfo=zone,
    )
    return {
        "schema": "creator_os.schedule_proposal.v1",
        "targetAccount": request.account,
        "timezone": request.timezone,
        "windowStart": start.isoformat(),
        "windowEnd": (start + timedelta(minutes=30)).isoformat(),
        "sourceLayer": "explicit_fixed_asset_cohort",
        "learnedTiming": False,
        "threadsdashboardFinalAuthority": True,
        "status": "PROPOSED_NOT_SCHEDULED",
    }


def _outcome_learning_diagnostics(
    conn: sqlite3.Connection,
    *,
    creator: str,
    account: str,
    intent: str,
) -> list[str]:
    observed = conn.execute(
        """
        SELECT count(*)
        FROM creative_plan_metric_cohorts mc
        JOIN creative_plan_items pi ON pi.id = mc.plan_item_id
        WHERE pi.creator = ? AND pi.target_account = ? AND pi.content_intent = ?
          AND mc.observation_bucket IN ('24h', '72h')
          AND mc.observation_state = 'OBSERVED'
          AND mc.learning_eligible = 1
        """,
        (creator, account, intent),
    ).fetchone()[0]
    return (
        ["fewer_than_three_eligible_24h_or_72h_outcomes"] if int(observed) < 3 else []
    )


def _asset_rows(
    conn: sqlite3.Connection,
    *,
    request: FixedAssetCohortRequest,
    identity_profile: str,
    eligible_campaign_ids: frozenset[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for asset_id in request.asset_ids:
        row = conn.execute(
            """
            SELECT ra.id, ra.campaign_id, ra.source_asset_id,
                   ra.content_hash AS final_sha256,
                   ra.output_path, ra.review_state, ra.audit_status,
                   ra.metadata_json, sa.content_hash AS source_sha256,
                   sa.stored_path AS source_path, sa.status AS source_status,
                   m.slug AS creator
            FROM rendered_assets ra
            JOIN source_assets sa ON sa.id = ra.source_asset_id
            JOIN models m ON m.id = sa.model_id
            WHERE ra.id = ?
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            result.append({"id": asset_id, "blockers": ["asset_not_found"]})
            continue
        value = dict(row)
        intake = conn.execute(
            """
            SELECT id, receipt_json
            FROM existing_media_intakes
            WHERE rendered_asset_id = ? AND final_sha256 = ?
            ORDER BY updated_at DESC, id DESC LIMIT 1
            """,
            (asset_id, value["final_sha256"]),
        ).fetchone()
        receipt = (
            _record(json.loads(intake["receipt_json"]))
            if intake is not None
            else _record(json.loads(value["metadata_json"] or "{}"))
        )
        review = conn.execute(
            """
            SELECT * FROM existing_media_asset_reviews
            WHERE rendered_asset_id = ? AND final_sha256 = ?
              AND verdict = 'WOULD_POST'
            ORDER BY created_at DESC LIMIT 1
            """,
            (asset_id, value["final_sha256"]),
        ).fetchone()
        approval = conn.execute(
            """
            SELECT id, metadata_json, created_at
            FROM activity_events
            WHERE event_type = 'source_approval_decided'
              AND source_asset_id = ? AND status = 'success'
            ORDER BY created_at DESC LIMIT 1
            """,
            (value["source_asset_id"],),
        ).fetchone()
        approval_metadata = (
            _record(json.loads(approval["metadata_json"])) if approval else {}
        )
        final_path = Path(_text(value["output_path"])).expanduser().resolve()
        source_path = Path(_text(value["source_path"])).expanduser().resolve()
        blockers: list[str] = []
        if _text(value["creator"]).lower() != request.creator:
            blockers.append("wrong_creator")
        if _text(receipt.get("creator")).lower() != request.creator:
            blockers.append("wrong_creator")
        if _text(receipt.get("intendedAccount")) != request.account:
            blockers.append("wrong_account_scope")
        if _text(receipt.get("contentIntent")) != request.intent:
            blockers.append("mixed_or_wrong_content_intent")
        if value.get("campaign_id") not in eligible_campaign_ids:
            blockers.append("campaign_state_blocks_fixed_asset_cohort")
        if _text(receipt.get("identityProfile")) != identity_profile:
            blockers.append("identity_profile_mismatch")
        if _text(value["source_status"]).lower() != "approved":
            blockers.append("missing_source_approval")
        if (
            approval is None
            or _text(approval_metadata.get("decision")).lower() != "approved"
            or _text(approval_metadata.get("sourceAssetId")) != value["source_asset_id"]
            or _text(approval_metadata.get("sha256")).lower()
            != _text(value["source_sha256"]).lower()
        ):
            blockers.append("missing_source_approval_receipt")
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or _sha256(source_path) != _text(value["source_sha256"]).lower()
        ):
            blockers.append("source_lineage_invalid")
        if (
            not final_path.is_file()
            or final_path.is_symlink()
            or _sha256(final_path) != _text(value["final_sha256"]).lower()
        ):
            blockers.append("final_media_invalid")
        if _record(receipt.get("technicalQc")).get("status") != "passed":
            blockers.append("missing_technical_qc")
        if value["review_state"] != "approved" or review is None:
            blockers.append("missing_would_post_review")
        audio = _record(receipt.get("audio"))
        audio_receipt_path = (
            Path(_text(audio.get("receiptPath"))).expanduser().resolve()
        )
        audio_receipt_sha = _text(audio.get("receiptSha256")).lower()
        audio_receipt: dict[str, Any] = {}
        if (
            audio_receipt_path.is_file()
            and not audio_receipt_path.is_symlink()
            and audio_receipt_sha
            and _sha256(audio_receipt_path) == audio_receipt_sha
        ):
            try:
                audio_receipt = _record(
                    json.loads(audio_receipt_path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                audio_receipt = {}
        final_audio_binding = _record(audio_receipt.get("finalVideo"))
        if (
            _text(audio.get("fulfillmentStatus")).lower() != "verified"
            or _text(audio.get("proofType")) != "embedded_output_audio_stream"
            or _text(audio.get("fulfillmentOutputSha256")).lower()
            != _text(value["final_sha256"]).lower()
            or not _text(audio.get("musicId"))
            or not _text(audio.get("sourceTrackSha256"))
            or not _text(audio.get("acousticFingerprint"))
            or not _text(audio.get("processedSegmentSha256"))
            or audio.get("segmentStartSeconds") is None
            or audio.get("segmentDurationSeconds") is None
            or not audio_receipt
            or _text(final_audio_binding.get("sha256")).lower()
            != _text(value["final_sha256"]).lower()
        ):
            blockers.append("audio_lineage_invalid")
        if _published(conn, asset_id):
            blockers.append("previously_published_asset")
        if _fixture_evidence(receipt):
            blockers.append("fixture_evidence")
        result.append(
            {
                **value,
                "id": asset_id,
                "receipt": receipt,
                "review": dict(review) if review else None,
                "sourceApproval": {
                    "eventId": approval["id"] if approval else None,
                    "metadata": approval_metadata,
                },
                "audio": audio,
                "audioReceipt": audio_receipt,
                "finalPath": str(final_path),
                "sourcePath": str(source_path),
                "blockers": list(dict.fromkeys(blockers)),
            }
        )
    return result


def build_fixed_asset_cohort(
    conn: sqlite3.Connection, request: FixedAssetCohortRequest
) -> dict[str, Any]:
    """Build one explicit fixed cohort without mutating the database or media."""

    before = conn.total_changes
    governance = _creator_planning_context(
        conn,
        request.creator,
        allowed_campaign_states=frozenset(
            {"production_ready", "producing", "reviewing", "approved"}
        ),
    )
    creator = str(governance["creatorSlug"])
    identity_profile = str(governance["providerIdentityId"])
    eligible_campaign_ids = frozenset(
        str(row["campaignId"]) for row in governance["campaigns"]
    )
    if request.autonomy_mode != "SUPERVISED":
        raise ValueError("fixed-asset cohorts require supervised mode")
    if len(request.asset_ids) < 2 or len(request.asset_ids) > 100:
        raise ValueError("fixed-asset cohorts require between 2 and 100 assets")
    if len(set(request.asset_ids)) != len(request.asset_ids):
        raise ValueError("fixed-asset cohort asset IDs must be distinct")
    if tuple(request.observation_cohorts) != OBSERVATION_COHORTS:
        raise ValueError("observation cohorts must be exactly 1h,24h,72h")
    if not request.account.strip():
        raise ValueError("fixed-asset cohort account is required")
    request = FixedAssetCohortRequest(
        creator=creator,
        account=request.account.strip().lstrip("@"),
        intent=request.intent.strip().lower(),
        asset_ids=request.asset_ids,
        observation_cohorts=request.observation_cohorts,
        autonomy_mode=request.autonomy_mode,
        timezone=request.timezone,
        start_date=request.start_date,
    )
    account_state = _account_state(
        conn,
        request.account,
        expected_model_id=str(governance["creatorId"]),
    )
    account_creator = conn.execute(
        """
        SELECT m.slug
        FROM accounts a JOIN models m ON m.id = a.model_id
        WHERE lower(a.handle) = lower(?) AND a.platform = 'instagram'
        """,
        (request.account,),
    ).fetchone()
    assets = _asset_rows(
        conn,
        request=request,
        identity_profile=identity_profile,
        eligible_campaign_ids=eligible_campaign_ids,
    )
    if account_creator is None or _text(account_creator["slug"]).lower() != creator:
        for asset in assets:
            asset["blockers"].append("account_creator_mismatch")
    final_shas = [
        _text(asset.get("final_sha256")).lower()
        for asset in assets
        if _text(asset.get("final_sha256"))
    ]
    if len(set(final_shas)) != len(final_shas):
        for asset in assets:
            asset["blockers"].append("duplicate_final_sha")
    audio_cohorts = {
        (
            _text(asset.get("audio", {}).get("fulfillmentStatus")).lower(),
            _text(asset.get("audio", {}).get("proofType")),
            _text(asset.get("receipt", {}).get("contractVersion")),
            _text(asset.get("receipt", {}).get("derivationKind")),
            _text(asset.get("audioReceipt", {}).get("schema")),
        )
        for asset in assets
        if not asset.get("blockers")
    }
    if len(audio_cohorts) > 1:
        for asset in assets:
            asset["blockers"].append("mixed_audio_cohorts")

    replan_provenance_plan = _latest_rolling_plan(
        conn, creator=request.creator, account=request.account
    )
    creative_plan_id = (
        f"cplan_{_fingerprint(['fixed_asset_cohort', creator, request.account])[:16]}"
    )
    latest_fixed = conn.execute(
        """
        SELECT id, version FROM creative_plan_versions
        WHERE creative_plan_id = ? ORDER BY version DESC LIMIT 1
        """,
        (creative_plan_id,),
    ).fetchone()
    previous_plan = str(latest_fixed["id"]) if latest_fixed else replan_provenance_plan
    inputs = {
        "mode": "FIXED_ASSET_COHORT",
        "purpose": COHORT_PURPOSE,
        "creator": request.creator,
        "identityProfile": identity_profile,
        "creatorGovernanceFingerprint": governance["governanceFingerprint"],
        "account": request.account,
        "intent": request.intent,
        "assetIds": list(request.asset_ids),
        "finalSha256": final_shas,
        "observationCohorts": list(request.observation_cohorts),
        "autonomyMode": request.autonomy_mode,
        "timezone": request.timezone,
    }
    input_fingerprint = _fingerprint(inputs)
    plan_id = f"plan_{input_fingerprint[:16]}"
    existing = conn.execute(
        "SELECT id FROM creative_plan_versions WHERE input_fingerprint = ?",
        (input_fingerprint,),
    ).fetchone()
    existing_plan_id = str(existing["id"]) if existing else None
    conflicts = conn.execute(
        """
        SELECT pi.plan_version_id,
               json_extract(pi.generation_identity_json, '$.renderedAssetId') AS asset_id
        FROM creative_plan_items pi
        WHERE json_extract(pi.generation_identity_json, '$.renderedAssetId') IN (
          SELECT value FROM json_each(?)
        )
        """,
        (_json(list(request.asset_ids)),),
    ).fetchall()
    for conflict in conflicts:
        if existing_plan_id and conflict["plan_version_id"] == existing_plan_id:
            continue
        for asset in assets:
            if asset["id"] == conflict["asset_id"]:
                asset["blockers"].append("asset_already_attached_to_competing_item")

    secondary = _outcome_learning_diagnostics(
        conn,
        creator=request.creator,
        account=request.account,
        intent=request.intent,
    )
    items: list[dict[str, Any]] = []
    variables: dict[str, list[Any]] = {
        "sourceImage": [],
        "visualPrompt": [],
        "motionDetails": [],
        "tiktokTrack": [],
        "audioSegment": [],
        "captionOrHook": [],
        "proposedPostingTime": [],
    }
    for index, asset in enumerate(assets):
        receipt = _record(asset.get("receipt"))
        generation = _record(receipt.get("generation"))
        audio = _record(receipt.get("audio"))
        source = {
            "id": asset.get("source_asset_id"),
            "content_hash": asset.get("source_sha256"),
        }
        _, _, learning = apply_learning_to_production_plan(
            conn,
            creator=request.creator,
            creator_identity_profile=identity_profile,
            account=request.account,
            intent=request.intent,
            sources=[source],
            base_prompt=_text(generation.get("prompt")),
        )
        learning["learningApplied"] = False
        learning["learningInfluenced"] = False
        learning["finalChoiceChanged"] = False
        learning["reason"] = "operator_fixed_asset_cohort"
        learning["packPresent"] = bool(learning.get("knowledgePackId"))
        learning["primaryFallback"] = learning.get("fallbackReason")
        window = _proposed_window(request=request, index=index)
        item = {
            "index": index,
            "creator": request.creator,
            "identityProfile": identity_profile,
            "targetAccount": request.account,
            "contentIntent": request.intent,
            "renderedAssetId": asset["id"],
            "finalSha256": asset.get("final_sha256"),
            "sourceAssetId": asset.get("source_asset_id"),
            "sourceSha256": asset.get("source_sha256"),
            "sourceApproval": asset.get("source_status"),
            "sourceApprovalReceipt": asset.get("sourceApproval"),
            "technicalQc": _record(receipt.get("technicalQc")),
            "creativeReview": asset.get("review"),
            "generation": generation,
            "prompt": _text(generation.get("prompt")),
            "audioIdentity": audio,
            "attachmentMethod": "existing_canonical_asset",
            "generatedDuringPlan": False,
            "attachmentCost": {"credits": 0, "providerCalls": 0},
            "originalGenerationCost": _record(generation.get("originalCost")),
            "proposedWindow": window,
            "observationCohorts": list(request.observation_cohorts),
            "experimentClass": ("CONTROL" if index == 0 else "CONTROLLED_VARIATION"),
            "experimentVariant": f"asset_{index + 1}",
            "learningDecision": learning,
            "publicationHistoryEmpty": not _published(conn, asset["id"]),
            "blockingReasons": list(dict.fromkeys(asset.get("blockers", []))),
            "executionState": ("BLOCKED" if asset.get("blockers") else "DRAFT"),
        }
        item["decisionFingerprint"] = _fingerprint(item)
        items.append(item)
        variables["sourceImage"].append(asset.get("source_asset_id"))
        variables["visualPrompt"].append(_text(generation.get("prompt")))
        variables["motionDetails"].append(generation.get("recipe"))
        variables["tiktokTrack"].append(audio.get("musicId"))
        variables["audioSegment"].append(
            [audio.get("segmentStartSeconds"), audio.get("segmentDurationSeconds")]
        )
        variables["captionOrHook"].append(receipt.get("caption"))
        variables["proposedPostingTime"].append(window["windowStart"])

    supervised_active = any(
        bool(item["learningDecision"].get("learningEligible")) for item in items
    )
    if not supervised_active:
        secondary.append("no_supervised_active_recommendation")
    for item in items:
        item["learningDecision"]["secondaryDiagnostics"] = secondary

    if not account_state["eligible"]:
        for item in items:
            item["blockingReasons"].append(str(account_state["reason"]))
            item["executionState"] = "BLOCKED"
    all_blockers = list(
        dict.fromkeys(blocker for item in items for blocker in item["blockingReasons"])
    )
    plan_version = (
        int(
            conn.execute(
                """
                SELECT coalesce(max(version), 0) + 1
                FROM creative_plan_versions WHERE creative_plan_id = ?
                """,
                (creative_plan_id,),
            ).fetchone()[0]
        )
        if existing_plan_id is None
        else int(
            conn.execute(
                "SELECT version FROM creative_plan_versions WHERE id = ?",
                (existing_plan_id,),
            ).fetchone()[0]
        )
    )
    plan_version_id = existing_plan_id or f"{plan_id}_v{plan_version}"
    experiment = {
        "schema": "creator_os.fixed_asset_cohort_experiment.v1",
        "purpose": COHORT_PURPOSE,
        "classification": COHORT_PURPOSE,
        "causalClaim": False,
        "hypothesis": "mechanically prove publication-to-learning lineage only",
        "controlledVariables": [
            "creator",
            "identity_profile",
            "account",
            "content_intent",
            "observation_cohorts",
        ],
        "variablesDiffering": [
            key
            for key, values in variables.items()
            if len({_json(value) for value in values}) > 1
        ],
        "variableValues": variables,
        "warning": "multiple variables differ; no source, audio, prompt, timing, or creative causal conclusion is supported",
    }
    decision = {
        "schema": "creator_os.fixed_asset_cohort_decision.v1",
        "mode": "FIXED_ASSET_COHORT",
        "purpose": COHORT_PURPOSE,
        "reason": COHORT_REASON,
        "explicitOperatorAssets": list(request.asset_ids),
        "learning": {
            "consulted": True,
            "packPresent": any(
                item["learningDecision"]["packPresent"] for item in items
            ),
            "eligible": supervised_active,
            "applied": False,
            "rankingChanged": False,
            "finalChoiceChanged": False,
            "primaryFallback": (
                items[0]["learningDecision"].get("primaryFallback") if items else None
            ),
            "secondaryDiagnostics": secondary,
        },
        "experiment": experiment,
    }
    result = {
        "schema": "creator_os.fixed_asset_cohort.v1",
        "mode": "FIXED_ASSET_COHORT",
        "purpose": COHORT_PURPOSE,
        "creativePlanId": creative_plan_id,
        "planId": plan_version_id,
        "version": plan_version,
        "creator": request.creator,
        "identityProfile": identity_profile,
        "creatorGovernance": governance,
        "account": account_state,
        "contentIntent": request.intent,
        "assetIds": list(request.asset_ids),
        "finalSha256": final_shas,
        "observationCohorts": list(request.observation_cohorts),
        "autonomyMode": request.autonomy_mode,
        "timezone": request.timezone,
        "horizon": {
            "start": request.start_date.isoformat(),
            "end": (
                request.start_date + timedelta(days=len(request.asset_ids) - 1)
            ).isoformat(),
        },
        "status": "BLOCKED" if all_blockers else "DRAFT",
        "inputFingerprint": input_fingerprint,
        "previousPlanVersionId": previous_plan,
        "replanProvenancePlanId": replan_provenance_plan,
        "replanReason": COHORT_REASON,
        "decisionReceipt": decision,
        "experiment": experiment,
        "items": items,
        "blockers": all_blockers,
        "dryRun": True,
        "persistentWrites": conn.total_changes - before,
        "applyWouldWrite": {
            "creativePlans": 0
            if conn.execute(
                "SELECT 1 FROM creative_plans WHERE id = ?", (creative_plan_id,)
            ).fetchone()
            else 1,
            "creativePlanVersions": 0 if existing_plan_id else 1,
            "creativePlanItems": 0 if existing_plan_id else len(items),
            "experimentReceipts": 0 if existing_plan_id else 1,
            "metricCohorts": 0,
            "metricCohortExpectations": 0 if existing_plan_id else len(items) * 3,
            "existingAssetAttachments": 0 if existing_plan_id else len(items),
            "providerCalls": 0,
            "mediaWrites": 0,
            "exports": 0,
            "schedules": 0,
            "publications": 0,
        },
        "idempotent": existing_plan_id is not None,
        "proposedStateTransitions": [
            {
                "planItemIndex": item["index"],
                "states": [
                    "DRAFT",
                    "APPROVED",
                    "EXISTING_ASSET_READY",
                    "CREATIVE_APPROVED",
                ],
            }
            for item in items
        ],
    }
    if result["persistentWrites"] != 0:
        raise AssertionError("fixed cohort dry-run mutated the database")
    return result


def _insert_item_events(conn: sqlite3.Connection, *, item_id: str, now: str) -> None:
    for from_state, to_state in (
        ("DRAFT", "APPROVED"),
        ("APPROVED", "EXISTING_ASSET_READY"),
    ):
        receipt = {
            "schema": "creator_os.fixed_asset_cohort_item_transition.v1",
            "planItemId": item_id,
            "from": from_state,
            "to": to_state,
            "reason": COHORT_REASON,
        }
        conn.execute(
            """
            INSERT INTO creative_plan_item_events (
              id, plan_item_id, from_state, to_state, event_type, actor,
              reason, receipt_json, created_at
            ) VALUES (?, ?, ?, ?, 'fixed_asset_cohort_transition',
                      'authenticated_local_operator', ?, ?, ?)
            """,
            (
                f"pitevt_{_fingerprint(receipt)[:16]}",
                item_id,
                from_state,
                to_state,
                COHORT_REASON,
                _json(receipt),
                now,
            ),
        )


def apply_fixed_asset_cohort(
    conn: sqlite3.Connection, preview: dict[str, Any]
) -> dict[str, Any]:
    """Persist, approve, and attach an already validated exact cohort."""

    if preview.get("blockers"):
        raise ValueError("fixed-asset cohort blocked: " + ",".join(preview["blockers"]))
    conn.execute("BEGIN IMMEDIATE")
    try:
        refreshed = build_fixed_asset_cohort(
            conn,
            FixedAssetCohortRequest(
                creator=preview["creator"],
                account=preview["account"]["handle"],
                intent=preview["contentIntent"],
                asset_ids=tuple(preview["assetIds"]),
                observation_cohorts=tuple(preview["observationCohorts"]),
                autonomy_mode=preview["autonomyMode"],
                timezone=preview["timezone"],
                start_date=date.fromisoformat(preview["horizon"]["start"]),
            ),
        )
        if refreshed["inputFingerprint"] != preview["inputFingerprint"]:
            raise ValueError("fixed-asset cohort inputs changed before apply")
        if refreshed.get("blockers"):
            raise ValueError(
                "fixed-asset cohort blocked: " + ",".join(refreshed["blockers"])
            )
        preview = refreshed
        existing = conn.execute(
            "SELECT id FROM creative_plan_versions WHERE input_fingerprint = ?",
            (preview["inputFingerprint"],),
        ).fetchone()
        if existing is not None:
            plan = load_plan(conn, str(existing["id"]))
            pending: list[tuple[dict[str, Any], str]] = []
            for item in plan["items"]:
                generation = _record(json.loads(item["generation_identity_json"]))
                ranking = _record(json.loads(item["source_ranking_json"]))
                rendered_asset_id = _text(
                    generation.get("renderedAssetId") or ranking.get("renderedAssetId")
                )
                if not rendered_asset_id:
                    raise ValueError(
                        "fixed cohort item missing rendered asset identity: "
                        f"{item['id']}"
                    )
                check = attach_existing_to_plan(
                    conn,
                    plan_id=plan["planId"],
                    plan_item_id=item["id"],
                    rendered_asset_id=rendered_asset_id,
                    apply=False,
                    learning_decision=json.loads(item["decision_receipt_json"]),
                    commit=False,
                )
                if check["blockers"]:
                    raise ValueError(
                        "fixed cohort attachment blocked: "
                        + ",".join(check["blockers"])
                    )
                pending.append((item, rendered_asset_id))
            attachments = [
                attach_existing_to_plan(
                    conn,
                    plan_id=plan["planId"],
                    plan_item_id=item["id"],
                    rendered_asset_id=rendered_asset_id,
                    apply=True,
                    learning_decision=json.loads(item["decision_receipt_json"]),
                    commit=False,
                )
                for item, rendered_asset_id in pending
            ]
            conn.commit()
            persisted = load_plan(conn, plan["planId"])
            return {
                **preview,
                "status": persisted["status"],
                "dryRun": False,
                "written": False,
                "idempotent": True,
                "persistedPlan": persisted,
                "attachments": attachments,
            }

        now = _now()
        plan_id = preview["planId"]
        creative_plan_id = preview["creativePlanId"]
        account = preview["account"]["handle"]
        conn.execute(
            """
        INSERT OR IGNORE INTO creative_plans (
          id, name, platform, goal, target_account, daily_base_video_target,
          style_lanes_json, model_profile, source_accounts_json, status,
          linked_campaign_slug, created_at, updated_at
        ) VALUES (?, ?, 'instagram', 'mechanical_learning_proof', ?, 1, '[]', ?,
                  '[]', 'planned', NULL, ?, ?)
        """,
            (
                creative_plan_id,
                f"{preview['creator']}_{account}_fixed_asset_learning_cohort",
                account,
                preview["creator"],
                now,
                now,
            ),
        )
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?,
                  'DRAFT', ?, ?, ?, ?, ?)
        """,
            (
                plan_id,
                creative_plan_id,
                preview["version"],
                preview["creator"],
                preview["identityProfile"],
                preview["horizon"]["start"],
                preview["horizon"]["end"],
                _json([preview["account"]]),
                preview["timezone"],
                COHORT_OBJECTIVE,
                len(preview["items"]),
                _json(
                    {
                        "mode": "FIXED_ASSET_COHORT",
                        "intent": preview["contentIntent"],
                        "duplicateIntentsExplicitlyAuthorized": True,
                    }
                ),
                _json({"classification": COHORT_PURPOSE, "causalClaim": False}),
                _json(
                    {
                        "attachmentCredits": 0,
                        "providerCalls": 0,
                        "originalGenerationCostsRetained": [
                            item["originalGenerationCost"] for item in preview["items"]
                        ],
                    }
                ),
                _json(preview["horizon"]),
                _json(
                    {
                        "status": "PROPOSED_NOT_SCHEDULED",
                        "windows": [
                            item["proposedWindow"] for item in preview["items"]
                        ],
                    }
                ),
                preview["autonomyMode"],
                preview["inputFingerprint"],
                preview["previousPlanVersionId"],
                _json(preview["decisionReceipt"]),
                now,
                now,
            ),
        )
        experiment_id = f"pexp_{_fingerprint([plan_id, COHORT_PURPOSE])[:16]}"
        item_ids: list[str] = []
        for item in preview["items"]:
            item_id = f"pitem_{_fingerprint([plan_id, item['index']])[:16]}"
            item_ids.append(item_id)
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'retained_actual_prompt',
                      '{}', ?, ?, 'embedded_trending_required', ?, ?, ?, ?, ?, ?,
                      '[]', ?, 'DRAFT', '{}', '{}', '{}', '{}', '{}', '{}', ?,
                      '[]', ?, ?)
            """,
                (
                    item_id,
                    plan_id,
                    item["index"],
                    item["creator"],
                    item["identityProfile"],
                    item["targetAccount"],
                    item["contentIntent"],
                    item["sourceAssetId"],
                    _json([item["sourceAssetId"]]),
                    _json(
                        {
                            "mode": "explicit_fixed_asset",
                            "renderedAssetId": item["renderedAssetId"],
                            "finalSha256": item["finalSha256"],
                        }
                    ),
                    item["prompt"],
                    float(item["audioIdentity"].get("segmentDurationSeconds") or 5),
                    _json(item["audioIdentity"]),
                    _json(item["proposedWindow"]),
                    experiment_id,
                    item["experimentVariant"],
                    item["experimentClass"],
                    len(preview["items"]) - item["index"],
                    _json(
                        {
                            "attachmentCredits": 0,
                            "providerCalls": 0,
                            "originalGenerationCost": item["originalGenerationCost"],
                        }
                    ),
                    _json(item["learningDecision"]),
                    now,
                    now,
                ),
            )
        experiment = preview["experiment"]
        conn.execute(
            """
        INSERT INTO creative_plan_experiments (
          id, plan_version_id, creator, account_scope_json, content_intent,
          hypothesis, controlled_variables_json, changed_variable,
          variants_json, assignment_method, deterministic_seed,
          publication_windows_json, required_observation_cohort,
          minimum_sample_warning, status, outcome_links_json,
          interpretation_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'multiple_uncontrolled_variables', ?,
                  'explicit_operator_fixed_cohort', ?, ?, '24h', ?, 'PROPOSED',
                  '[]', ?, ?, ?)
        """,
            (
                experiment_id,
                plan_id,
                preview["creator"],
                _json([account]),
                preview["contentIntent"],
                experiment["hypothesis"],
                _json(experiment["controlledVariables"]),
                _json(
                    [
                        {
                            "name": item["experimentVariant"],
                            "renderedAssetId": item["renderedAssetId"],
                        }
                        for item in preview["items"]
                    ]
                ),
                int(_fingerprint([plan_id, "cohort"])[:8], 16),
                _json([item["proposedWindow"] for item in preview["items"]]),
                experiment["warning"],
                _json(experiment),
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE creative_plan_versions SET status='APPROVED', updated_at=? WHERE id=?",
            (now, plan_id),
        )
        plan_event = {
            "schema": "creator_os.plan_transition.v1",
            "planId": plan_id,
            "from": "DRAFT",
            "to": "APPROVED",
            "operator": "authenticated_local_operator",
            "reason": COHORT_REASON,
            "at": now,
        }
        conn.execute(
            """
        INSERT INTO creative_plan_events (
          id, creative_plan_id, event_type, status, message, metadata_json, created_at
        ) VALUES (?, ?, 'content_plan_transition', 'success', ?, ?, ?)
        """,
            (
                f"cpevt_{_fingerprint(plan_event)[:16]}",
                creative_plan_id,
                "DRAFT -> APPROVED",
                _json(plan_event),
                now,
            ),
        )
        for item_id, item in zip(item_ids, preview["items"], strict=True):
            _insert_item_events(conn, item_id=item_id, now=now)
            conn.execute(
                """
            UPDATE creative_plan_items
            SET execution_state='EXISTING_ASSET_READY', updated_at=? WHERE id=?
            """,
                (now, item_id),
            )
            conn.execute(
                """
            UPDATE creative_plan_items
            SET metric_cohort_identity_json=?, updated_at=? WHERE id=?
            """,
                (
                    _json(
                        {
                            "schema": "creator_os.metric_cohort_expectations.v1",
                            "observationBuckets": list(OBSERVATION_COHORTS),
                            "offsetsFromActualPublication": {
                                bucket: int(OBSERVATION_OFFSETS[bucket].total_seconds())
                                for bucket in OBSERVATION_COHORTS
                            },
                            "publicationRequiredBeforeMaterialization": True,
                            "materializedCohortIds": [],
                        }
                    ),
                    now,
                    item_id,
                ),
            )

        preflight = [
            attach_existing_to_plan(
                conn,
                plan_id=plan_id,
                plan_item_id=item_id,
                rendered_asset_id=item["renderedAssetId"],
                apply=False,
                learning_decision=item["learningDecision"],
                commit=False,
            )
            for item_id, item in zip(item_ids, preview["items"], strict=True)
        ]
        attachment_blockers = [
            blocker for receipt in preflight for blocker in receipt["blockers"]
        ]
        if attachment_blockers:
            raise ValueError(
                "fixed cohort attachment blocked: "
                + ",".join(dict.fromkeys(attachment_blockers))
            )
        attachments = [
            attach_existing_to_plan(
                conn,
                plan_id=plan_id,
                plan_item_id=item_id,
                rendered_asset_id=item["renderedAssetId"],
                apply=True,
                learning_decision=item["learningDecision"],
                commit=False,
            )
            for item_id, item in zip(item_ids, preview["items"], strict=True)
        ]
        conn.commit()
        persisted = load_plan(conn, plan_id)
        return {
            **preview,
            "status": persisted["status"],
            "dryRun": False,
            "written": True,
            "idempotent": False,
            "persistedPlan": persisted,
            "attachments": attachments,
            "providerCalls": 0,
            "mediaWrites": 0,
            "exports": 0,
            "schedules": 0,
            "publications": 0,
        }
    except Exception:
        conn.rollback()
        raise
