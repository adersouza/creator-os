from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from reel_factory.worker_api import toolchain_receipt

from pipeline_contracts import (
    validate_experiment_assignment_receipt,
    validate_renderer_equivalence_receipt,
)

from .account_eligibility import enforce_account_eligibility
from .assignment_eligibility import (
    AssignmentEligibilityError,
    evaluate_assignment_eligibility,
    persist_assignment_origin,
)
from .observed_experiment_reporting import OBSERVED_MEASUREMENT_PLAN

DEFAULT_REUSE_COOLDOWN_DAYS = 14


class InventoryReservationRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        utc_now: Callable[[], str],
        normalize_content_surface: Callable[[str | None], str],
        rendered_asset: Callable[[str], dict[str, Any]],
        ensure_rendered_asset_perceptual_metadata: Callable[..., dict[str, Any]],
        asset_uniqueness_values: Callable[..., dict[str, str]],
        default_reservation_ttl_days: int,
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._utc_now = utc_now
        self._normalize_content_surface = normalize_content_surface
        self._rendered_asset = rendered_asset
        self._ensure_rendered_asset_perceptual_metadata = (
            ensure_rendered_asset_perceptual_metadata
        )
        self._asset_uniqueness_values = asset_uniqueness_values
        self._default_reservation_ttl_days = default_reservation_ttl_days

    def reserve_inventory_asset(
        self,
        asset_id: str,
        *,
        account_id: str | None = None,
        surface: str | None = None,
        reserved_by: str = "campaign_factory",
        expires_at: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        reuse_cooldown_days: int = DEFAULT_REUSE_COOLDOWN_DAYS,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        now = self._utc_now()
        expires_at = (
            expires_at
            or (
                datetime.fromisoformat(now)
                + timedelta(days=self._default_reservation_ttl_days)
            ).isoformat()
        )
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "within a transaction" not in str(exc).lower():
                raise
        try:
            row = self._reserve_inventory_asset(
                asset_id,
                account_id=account_id,
                surface=surface,
                reserved_by=reserved_by,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                metadata=metadata,
                reuse_cooldown_days=reuse_cooldown_days,
                override_reason=override_reason,
                now=now,
            )
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()
        return row

    def _reserve_inventory_asset(
        self,
        asset_id: str,
        *,
        account_id: str | None,
        surface: str | None,
        reserved_by: str,
        expires_at: str,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        reuse_cooldown_days: int,
        override_reason: str | None,
        now: str,
        paired_asset_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert one reservation inside the caller's transaction."""

        asset = self._ensure_rendered_asset_perceptual_metadata(asset_id)
        if asset.get("review_state") == "rejected":
            raise ValueError(f"operator-rejected asset cannot be reserved: {asset_id}")
        normalized_surface = self._normalize_content_surface(
            surface or asset.get("content_surface") or "reel"
        )
        uniqueness = self._asset_uniqueness_values(asset, metadata=metadata)
        self.expire_inventory_reservations(now=now, commit=False)
        if idempotency_key:
            existing = self.conn.execute(
                """
                SELECT * FROM asset_inventory_reservations
                WHERE idempotency_key = ? AND status IN ('pending', 'committed')
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict(existing)
        if (
            account_id
            and not self.conn.execute(
                "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        ):
            raise ValueError(f"account not found: {account_id}")
        account_eligibility = enforce_account_eligibility(
            self.conn,
            account_id=account_id,
            surface=normalized_surface,
            planned_at=now,
        )
        eligibility = evaluate_assignment_eligibility(
            self.conn,
            rendered_asset_id=asset_id,
            account_id=account_id,
            planned_at=now,
            surface=normalized_surface,
            reuse_window_days=reuse_cooldown_days,
        )
        if paired_asset_id:
            eligibility = self._pair_scoped_eligibility(
                eligibility, paired_asset_id=paired_asset_id
            )
        if not eligibility["allowed"]:
            raise AssignmentEligibilityError(eligibility)
        active = self.conn.execute(
            """
            SELECT 1 FROM asset_inventory_reservations
            WHERE asset_id = ? AND status IN ('pending', 'committed')
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if active:
            raise ValueError(f"asset already has an active reservation: {asset_id}")
        conflicts = self.inventory_uniqueness_conflicts(
            asset,
            uniqueness=uniqueness,
            surface=normalized_surface,
            cooldown_days=reuse_cooldown_days,
            account_id=account_id,
        )
        if paired_asset_id:
            conflicts = [
                item for item in conflicts if item["assetId"] != paired_asset_id
            ]
        if conflicts and (
            not override_reason or override_reason == "controlled_experiment_pair"
        ):
            raise ValueError(
                "cross-account source/perceptual reuse cooldown conflict: "
                + ",".join(item["assetId"] for item in conflicts[:5])
            )
        reservation_id = self._new_id("invres")
        row_id = self._new_id("invresrow")
        self.conn.execute(
            """
            INSERT INTO asset_inventory_reservations
            (id, asset_id, campaign_id, account_id, surface, reservation_id, reserved_by,
             reserved_at, expires_at, status, idempotency_key, source_family_id,
             perceptual_fingerprint, perceptual_cluster_id, account_group_id,
             reuse_cooldown_days, override_reason, account_eligibility_json,
             assignment_eligibility_json, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                asset_id,
                asset["campaign_id"],
                account_id,
                normalized_surface,
                reservation_id,
                reserved_by,
                now,
                expires_at,
                idempotency_key,
                uniqueness["sourceFamilyId"],
                uniqueness["perceptualFingerprint"],
                uniqueness["perceptualClusterId"],
                uniqueness["accountGroupId"],
                reuse_cooldown_days,
                override_reason,
                json.dumps(account_eligibility, ensure_ascii=False, sort_keys=True),
                json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        persist_assignment_origin(self.conn, eligibility)
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row_id,)
            ).fetchone()
        )

    @staticmethod
    def _pair_scoped_eligibility(
        decision: dict[str, Any], *, paired_asset_id: str
    ) -> dict[str, Any]:
        allowed_reasons = {
            "source_family_reuse_window",
            "perceptual_reuse_window",
        }
        blocking_matches = [
            match
            for match in decision.get("matches") or []
            if not (
                match.get("renderedAssetId") == paired_asset_id
                and match.get("reason") in allowed_reasons
            )
        ]
        reasons = list(
            dict.fromkeys(str(match["reason"]) for match in blocking_matches)
        )
        return {
            **decision,
            "allowed": not reasons,
            "reasonCodes": reasons,
            "variantCooldownCheck": reasons[0] if reasons else "clear",
        }

    def reserve_experiment_pair(
        self,
        *,
        experiment_id: str,
        parent_family_id: str,
        pair_index: int,
        control_asset_id: str,
        treatment_asset_id: str,
        account_ids: tuple[str, str],
        eligible_slots: tuple[dict[str, str], dict[str, str]],
        plan_item_ids: tuple[str, str],
        treatment_profile: str,
        reserved_by: str = "authenticated_local_operator",
        reuse_cooldown_days: int = DEFAULT_REUSE_COOLDOWN_DAYS,
    ) -> dict[str, Any]:
        """Atomically reserve and immutably assign one cross-account pair."""

        if len(set(account_ids)) != 2:
            raise ValueError("experiment pair requires two distinct accounts")
        if len(set(plan_item_ids)) != 2:
            raise ValueError("experiment pair requires two distinct plan items")
        experiment = self.conn.execute(
            "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        if not experiment:
            raise ValueError(f"experiment not found: {experiment_id}")
        if str(experiment["assignment_method"]) != "cross_account_blocked_rotation.v1":
            raise ValueError(
                "experiment assignment method is not cross-account rotation"
            )
        variants = json.loads(experiment["variants_json"] or "[]")
        if variants != ["control", treatment_profile]:
            raise ValueError("experiment must contain one control and one profile")
        measurement_plan = json.loads(experiment["interpretation_json"] or "{}").get(
            "measurementPlan"
        )
        if measurement_plan != OBSERVED_MEASUREMENT_PLAN:
            raise ValueError("observed-profile measurement plan was not predeclared")
        if set(json.loads(experiment["account_scope_json"] or "[]")) != set(
            account_ids
        ):
            raise ValueError("experiment pair accounts do not match experiment scope")
        assets = {
            "control": self._approved_experiment_asset(control_asset_id),
            "treatment": self._approved_experiment_asset(treatment_asset_id),
        }
        if assets["control"]["campaign_id"] != assets["treatment"]["campaign_id"]:
            raise ValueError("experiment assets belong to different campaigns")
        self._validate_renderer_qualification(assets["control"])
        self._validate_treatment_lineage(
            assets["control"],
            assets["treatment"],
            treatment_profile=treatment_profile,
        )
        self._validate_parent_family(
            assets["control"], assets["treatment"], parent_family_id
        )
        self._validate_audio_equivalence(assets["control"], assets["treatment"])
        self._validate_audio_cooldown(
            assets,
            now=self._utc_now(),
            cooldown_days=reuse_cooldown_days,
        )
        items = [
            self.conn.execute(
                "SELECT * FROM creative_plan_items WHERE id = ?", (item_id,)
            ).fetchone()
            for item_id in plan_item_ids
        ]
        if any(item is None for item in items):
            raise ValueError("experiment plan item not found")
        if any(
            item["plan_version_id"] != experiment["plan_version_id"] for item in items
        ):
            raise ValueError("experiment plan item belongs to another plan version")
        if any(
            item["experiment_id"] not in {None, "", experiment_id} for item in items
        ):
            raise ValueError("experiment plan item is already assigned elsewhere")
        if any(item["creator"] != experiment["creator"] for item in items):
            raise ValueError("experiment plan item creator does not match experiment")
        if any(
            item["content_intent"] != experiment["content_intent"] for item in items
        ):
            raise ValueError(
                "experiment plan item content intent does not match experiment"
            )
        for account_id, slot, item in zip(
            account_ids, eligible_slots, items, strict=True
        ):
            self._validate_experiment_slot(slot)
            if str(item["target_account"]) != account_id:
                raise ValueError("plan item target account does not match pair account")
            if json.loads(item["export_identity_json"] or "{}") or json.loads(
                item["publication_identity_json"] or "{}"
            ):
                raise ValueError(
                    "experiment plan item is already exported or published"
                )
            prior = self.conn.execute(
                """
                SELECT 1 FROM creative_plan_metric_cohorts
                WHERE plan_item_id = ? AND observation_state != 'MISSING'
                LIMIT 1
                """,
                (item["id"],),
            ).fetchone()
            if prior:
                raise ValueError("plan item observation window has already started")
        if (
            eligible_slots[0]["windowStart"] != eligible_slots[1]["windowStart"]
            or eligible_slots[0]["windowEnd"] != eligible_slots[1]["windowEnd"]
        ):
            raise ValueError("experiment pair slots must use equivalent windows")
        fingerprint_input = {
            "experimentId": experiment_id,
            "parentFamilyId": parent_family_id,
            "accountIds": list(account_ids),
            "eligibleWindows": list(eligible_slots),
            "pairIndex": int(pair_index),
        }
        assignment_fingerprint = self._canonical_sha256(fingerprint_input)
        pair_id = f"expair_{assignment_fingerprint[:20]}"
        existing = self.conn.execute(
            """
            SELECT receipt_json FROM creative_plan_item_events
            WHERE event_type = 'experiment_assignment'
              AND json_extract(receipt_json, '$.pairId') = ?
            ORDER BY plan_item_id
            """,
            (pair_id,),
        ).fetchall()
        if existing:
            receipts = [json.loads(row["receipt_json"]) for row in existing]
            if len(receipts) != 2:
                raise ValueError("experiment pair has incomplete immutable assignment")
            return {
                "schema": "creator_os.experiment_pair_assignment.v1",
                "pairId": pair_id,
                "idempotent": True,
                "assignments": receipts,
            }
        base_rotation = int(
            self._canonical_sha256(
                {"experimentId": experiment_id, "accountIds": sorted(account_ids)}
            )[:8],
            16,
        )
        control_account_index = (base_rotation + int(pair_index)) % 2
        role_for_index = [
            "control" if index == control_account_index else "treatment"
            for index in range(2)
        ]
        now = self._utc_now()
        expires_at = (
            max(
                datetime.fromisoformat(now)
                + timedelta(days=self._default_reservation_ttl_days),
                max(
                    datetime.fromisoformat(slot["windowEnd"].replace("Z", "+00:00"))
                    for slot in eligible_slots
                )
                + timedelta(hours=72),
            )
        ).isoformat()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "within a transaction" not in str(exc).lower():
                raise
        try:
            reservations: list[dict[str, Any]] = []
            receipts: list[dict[str, Any]] = []
            first_asset_id: str | None = None
            for index, role in enumerate(role_for_index):
                asset = assets[role]
                reservation = self._reserve_inventory_asset(
                    str(asset["id"]),
                    account_id=account_ids[index],
                    surface=str(asset.get("content_surface") or "reel"),
                    reserved_by=reserved_by,
                    expires_at=expires_at,
                    idempotency_key=f"{pair_id}:{role}",
                    metadata={
                        "controlledExperimentPair": pair_id,
                        "experimentId": experiment_id,
                        "role": role,
                        "cooldownException": {
                            "reason": "controlled_experiment_pair",
                            "scope": "pair_only",
                            "thirdReuseAllowed": False,
                        },
                    },
                    reuse_cooldown_days=reuse_cooldown_days,
                    override_reason="controlled_experiment_pair",
                    now=now,
                    paired_asset_id=first_asset_id,
                )
                reservations.append(reservation)
                first_asset_id = first_asset_id or str(asset["id"])
                retention = self._experiment_retention(assets, pair_id=pair_id)
                receipt = {
                    "schema": "creator_os.experiment_assignment_receipt.v1",
                    "experimentId": experiment_id,
                    "pairId": pair_id,
                    "armId": role
                    if role == "control"
                    else f"treatment:{treatment_profile}",
                    "role": role,
                    "accountId": account_ids[index],
                    "eligibleSlot": {
                        "slotId": eligible_slots[index]["slotId"],
                        "windowStart": eligible_slots[index]["windowStart"],
                        "windowEnd": eligible_slots[index]["windowEnd"],
                    },
                    "parentFamilyId": parent_family_id,
                    "observationCohorts": ["1h", "24h", "72h"],
                    "assignmentAlgorithmVersion": "cross_account_blocked_rotation.v1",
                    "assignmentFingerprint": assignment_fingerprint,
                    "reservationId": reservation["reservation_id"],
                    "assignedAssetId": str(asset["id"]),
                    "assignedAssetSha256": str(asset["content_hash"]),
                    "retention": retention,
                    "cooldownException": {
                        "reason": "controlled_experiment_pair",
                        "scope": "pair_only",
                        "relationships": [
                            "source_family",
                            "perceptual_sibling",
                            "audio",
                        ],
                        "thirdReuseAllowed": False,
                    },
                    "assignedAt": now,
                }
                validate_experiment_assignment_receipt(receipt)
                item = items[index]
                prior_generation = json.loads(item["generation_identity_json"] or "{}")
                if prior_generation and (
                    prior_generation.get("renderedAssetId") != asset["id"]
                    or prior_generation.get("finalSha256") != asset["content_hash"]
                ):
                    raise ValueError("experiment plan item has a conflicting asset")
                generation_identity = {
                    "schema": "creator_os.existing_video_plan_attachment.v1",
                    "renderedAssetId": asset["id"],
                    "finalSha256": asset["content_hash"],
                    "method": "existing_canonical_asset",
                    "generatedDuringPlan": False,
                    "attachmentCost": {"credits": 0, "providerCalls": 0},
                    "experimentAssignmentFingerprint": assignment_fingerprint,
                }
                self.conn.execute(
                    """
                    UPDATE creative_plan_items
                    SET experiment_id = ?, experiment_variant = ?,
                        exploration_class = ?, decision_receipt_json = ?,
                        source_asset_id = ?, generation_identity_json = ?,
                        execution_state = 'CREATIVE_APPROVED', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        experiment_id,
                        receipt["armId"],
                        "CONTROL" if role == "control" else "CONTROLLED_VARIATION",
                        json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                        asset["source_asset_id"],
                        json.dumps(
                            generation_identity, ensure_ascii=False, sort_keys=True
                        ),
                        now,
                        item["id"],
                    ),
                )
                event_id = f"pitevt_assignment_{self._canonical_sha256(receipt)[:20]}"
                self.conn.execute(
                    """
                    INSERT INTO creative_plan_item_events
                    (id, plan_item_id, from_state, to_state, event_type, actor,
                     reason, receipt_json, created_at)
                    VALUES (?, ?, ?, ?, 'experiment_assignment', ?,
                            'controlled_experiment_pair', ?, ?)
                    """,
                    (
                        event_id,
                        item["id"],
                        item["execution_state"],
                        item["execution_state"],
                        reserved_by,
                        json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                self._insert_experiment_cohorts(
                    str(item["id"]),
                    window_start=eligible_slots[index]["windowStart"],
                    now=now,
                )
                receipts.append(receipt)
            for asset in assets.values():
                metadata = json.loads(asset.get("metadata_json") or "{}")
                holds = metadata.setdefault("experimentRetention", [])
                if pair_id not in {
                    str(hold.get("pairId")) for hold in holds if isinstance(hold, dict)
                }:
                    holds.append(
                        {
                            "pairId": pair_id,
                            "class": "experiment_evidence",
                            "protectedThroughDecision": True,
                            "evidenceSha256": receipts[0]["retention"][
                                "evidenceSha256"
                            ],
                        }
                    )
                self.conn.execute(
                    "UPDATE rendered_assets SET metadata_json = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        now,
                        asset["id"],
                    ),
                )
            self.conn.execute(
                """
                UPDATE creative_plan_experiments
                SET status = 'RUNNING', updated_at = ?
                WHERE id = ?
                """,
                (now, experiment_id),
            )
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()
        return {
            "schema": "creator_os.experiment_pair_assignment.v1",
            "pairId": pair_id,
            "idempotent": False,
            "assignments": receipts,
            "reservations": reservations,
        }

    def _approved_experiment_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self._rendered_asset(asset_id)
        if asset.get("review_state") != "approved":
            raise ValueError(f"experiment asset is not approved: {asset_id}")
        path = str(asset.get("campaign_path") or asset.get("output_path") or "")
        file_path = Path(path).expanduser()
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError(f"experiment asset file is missing: {asset_id}")
        with file_path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != asset.get("content_hash"):
            raise ValueError(f"experiment asset SHA mismatch: {asset_id}")
        return asset

    @staticmethod
    def _validate_parent_family(
        control: dict[str, Any],
        treatment: dict[str, Any],
        parent_family_id: str,
    ) -> None:
        control_family = str(control.get("parent_asset_id") or control["id"])
        treatment_family = str(treatment.get("parent_asset_id") or treatment["id"])
        if (
            str(control["id"]) != parent_family_id
            and control_family != parent_family_id
        ) or treatment_family != parent_family_id:
            raise ValueError("control and treatment do not share the parent family")

    @staticmethod
    def _validate_renderer_qualification(control: dict[str, Any]) -> None:
        metadata = json.loads(control.get("metadata_json") or "{}")
        binding = metadata.get("rendererEquivalenceReceipt")
        if not isinstance(binding, dict):
            raise ValueError("control renderer equivalence qualification is missing")
        path = Path(str(binding.get("path") or "")).expanduser()
        if path.is_symlink() or not path.is_file():
            raise ValueError("control renderer equivalence receipt is missing")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != binding.get("sha256"):
            raise ValueError("control renderer equivalence receipt SHA mismatch")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        validate_renderer_equivalence_receipt(receipt)
        if receipt.get("status") != "qualified":
            raise ValueError("control renderer equivalence qualification failed")
        if receipt.get("sourceSha256") != control.get("content_hash"):
            raise ValueError("control renderer qualification source SHA mismatch")
        audio_embedder = Path(__file__).with_name("audio_radar") / "embedding.py"
        with audio_embedder.open("rb") as handle:
            audio_embedder_sha = hashlib.file_digest(handle, "sha256").hexdigest()
        current = toolchain_receipt(audio_embedder_sha256=audio_embedder_sha)[
            "fingerprint"
        ]
        if receipt.get("toolchainFingerprint") != current:
            raise ValueError("control renderer qualification expired")

    @classmethod
    def _validate_audio_equivalence(
        cls, control: dict[str, Any], treatment: dict[str, Any]
    ) -> None:
        for asset in (control, treatment):
            metadata = json.loads(asset.get("metadata_json") or "{}")
            receipt = metadata.get("audioEmbeddingReceipt")
            if not isinstance(receipt, dict):
                continue
            verification = receipt.get("verification")
            ffmpeg = receipt.get("ffmpeg")
            final = receipt.get("finalVideo")
            if (
                not isinstance(verification, dict)
                or verification.get("status") != "verified"
                or verification.get("audioPresent") is not True
                or verification.get("audioStreamCount") != 1
                or verification.get("audioCodec") != "aac"
                or not isinstance(ffmpeg, dict)
                or ffmpeg.get("audioCodec") != "aac"
                or not isinstance(final, dict)
                or final.get("sha256") != asset.get("content_hash")
                or not final.get("audioFingerprint")
            ):
                raise ValueError("experiment asset AAC evidence is incomplete")
        if cls._audio_fingerprint(control) != cls._audio_fingerprint(treatment):
            raise ValueError("control and treatment audio selection/segment/mix differ")

    def _validate_audio_cooldown(
        self,
        assets: dict[str, dict[str, Any]],
        *,
        now: str,
        cooldown_days: int,
    ) -> None:
        fingerprint = self._audio_fingerprint(assets["control"])
        if not fingerprint:
            return
        excluded = {str(asset["id"]) for asset in assets.values()}
        cutoff = (
            datetime.fromisoformat(now) - timedelta(days=max(0, cooldown_days))
        ).isoformat()
        campaign_id = str(assets["control"]["campaign_id"])
        queries = (
            """
            SELECT asset_id FROM asset_inventory_reservations
            WHERE campaign_id = ? AND status IN ('pending', 'committed')
              AND reserved_at >= ?
            """,
            """
            SELECT rendered_asset_id AS asset_id FROM asset_account_assignments
            WHERE campaign_id = ? AND created_at >= ?
            """,
            """
            SELECT rendered_asset_id AS asset_id FROM distribution_plans
            WHERE campaign_id = ?
              AND COALESCE(planned_window_start, created_at) >= ?
            """,
        )
        for query in queries:
            for row in self.conn.execute(query, (campaign_id, cutoff)).fetchall():
                asset_id = str(row["asset_id"])
                if asset_id in excluded:
                    continue
                prior = self._rendered_asset(asset_id)
                if self._audio_fingerprint(prior) == fingerprint:
                    raise ValueError(
                        f"pre-existing audio reuse cooldown conflict: {asset_id}"
                    )

    @classmethod
    def _validate_treatment_lineage(
        cls,
        control: dict[str, Any],
        treatment: dict[str, Any],
        *,
        treatment_profile: str,
    ) -> None:
        control_metadata = json.loads(control.get("metadata_json") or "{}")
        treatment_metadata = json.loads(treatment.get("metadata_json") or "{}")
        visual = treatment_metadata.get("visualDerivativeReceipt")
        control_audio = control_metadata.get("audioEmbeddingReceipt")
        treatment_audio = treatment_metadata.get("audioEmbeddingReceipt")
        if not isinstance(visual, dict):
            raise ValueError("treatment visual derivative receipt is missing")
        if treatment_metadata.get("observedProfile") != treatment_profile:
            raise ValueError("treatment observed profile does not match experiment")
        receipt_path = Path(str(visual.get("path") or "")).expanduser()
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("treatment visual derivative receipt file is missing")
        with receipt_path.open("rb") as handle:
            receipt_sha = hashlib.file_digest(handle, "sha256").hexdigest()
        if receipt_sha != visual.get("sha256"):
            raise ValueError("treatment visual derivative receipt SHA mismatch")
        if isinstance(treatment_audio, dict):
            original = treatment_audio.get("originalVideo")
            final = treatment_audio.get("finalVideo")
            if not isinstance(original, dict) or original.get("sha256") != visual.get(
                "outputSha256"
            ):
                raise ValueError("treatment pre-audio visual SHA mismatch")
            if not isinstance(final, dict) or final.get("sha256") != treatment.get(
                "content_hash"
            ):
                raise ValueError("treatment final audio SHA mismatch")
        elif visual.get("outputSha256") != treatment.get("content_hash"):
            raise ValueError("treatment visual SHA does not match final asset")
        if isinstance(control_audio, dict):
            original = control_audio.get("originalVideo")
            if not isinstance(original, dict) or original.get("sha256") != visual.get(
                "sourceSha256"
            ):
                raise ValueError("treatment source does not match control visual")
        elif visual.get("sourceSha256") != control.get("content_hash"):
            raise ValueError("treatment source does not match control asset")

    @classmethod
    def _audio_fingerprint(cls, asset: dict[str, Any]) -> str:
        metadata = json.loads(asset.get("metadata_json") or "{}")
        receipt = metadata.get("audioEmbeddingReceipt")
        if not isinstance(receipt, dict):
            return ""
        return cls._canonical_sha256(
            {
                "selectedTrack": receipt.get("selectedTrack"),
                "selectedSegment": receipt.get("selectedSegment"),
                "mixSettings": receipt.get("mixSettings"),
            }
        )

    @staticmethod
    def _validate_experiment_slot(slot: dict[str, str]) -> None:
        required = {"slotId", "windowStart", "windowEnd"}
        if not required.issubset(slot) or any(not str(slot[key]) for key in required):
            raise ValueError("experiment slot is incomplete")
        start = datetime.fromisoformat(slot["windowStart"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(slot["windowEnd"].replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("experiment slot window is invalid")

    @classmethod
    def _experiment_retention(
        cls, assets: dict[str, dict[str, Any]], *, pair_id: str
    ) -> dict[str, Any]:
        evidence: set[str] = {str(asset["content_hash"]) for asset in assets.values()}
        for asset in assets.values():
            metadata = json.loads(asset.get("metadata_json") or "{}")
            for binding_name in (
                "visualDerivativeReceipt",
                "audioEmbeddingReceipt",
                "rendererEquivalenceReceipt",
            ):
                binding = metadata.get(binding_name)
                if isinstance(binding, dict):
                    cls._collect_sha256(binding, evidence)
        evidence.add(cls._canonical_sha256({"pairId": pair_id}))
        return {
            "class": "experiment_evidence",
            "protectedThroughDecision": True,
            "evidenceSha256": sorted(evidence),
        }

    @classmethod
    def _collect_sha256(cls, value: Any, output: set[str]) -> None:
        if isinstance(value, dict):
            for child in value.values():
                cls._collect_sha256(child, output)
        elif isinstance(value, list):
            for child in value:
                cls._collect_sha256(child, output)
        elif isinstance(value, str) and len(value) == 64:
            try:
                int(value, 16)
            except ValueError:
                return
            output.add(value.lower())

    def _insert_experiment_cohorts(
        self, plan_item_id: str, *, window_start: str, now: str
    ) -> None:
        start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        for bucket, hours in (("1h", 1), ("24h", 24), ("72h", 72)):
            self.conn.execute(
                """
                INSERT INTO creative_plan_metric_cohorts
                (id, plan_item_id, observation_bucket, expected_earliest_at,
                 observation_state, learning_eligible, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'MISSING', 0, ?, ?)
                ON CONFLICT(plan_item_id, observation_bucket) DO NOTHING
                """,
                (
                    f"pmc_{self._canonical_sha256([plan_item_id, bucket])[:20]}",
                    plan_item_id,
                    bucket,
                    (start + timedelta(hours=hours)).isoformat(),
                    now,
                    now,
                ),
            )

    @staticmethod
    def _canonical_sha256(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def expire_inventory_reservations(
        self, *, now: str | None = None, commit: bool = True
    ) -> int:
        current = now or self._utc_now()
        cursor = self.conn.execute(
            """
            UPDATE asset_inventory_reservations
            SET status = 'expired', updated_at = ?
            WHERE status IN ('pending', 'committed')
              AND expires_at IS NOT NULL
              AND expires_at != ''
              AND expires_at <= ?
            """,
            (current, current),
        )
        if commit and cursor.rowcount:
            self.conn.commit()
        return int(cursor.rowcount or 0)

    def release_inventory_reservation(
        self,
        reservation_id: str,
        *,
        status: str = "released",
        pending_only: bool = False,
    ) -> dict[str, Any]:
        if status not in {"released", "expired", "cancelled"}:
            raise ValueError("status must be released, expired, or cancelled")
        row = self.conn.execute(
            "SELECT * FROM asset_inventory_reservations WHERE reservation_id = ? OR id = ?",
            (reservation_id, reservation_id),
        ).fetchone()
        if not row:
            raise ValueError(f"reservation not found: {reservation_id}")
        if pending_only and row["status"] != "pending":
            return dict(row)
        if row["status"] == status:
            return dict(row)
        if row["status"] not in {"pending", "committed"}:
            raise ValueError(
                f"reservation cannot transition from terminal state: "
                f"{reservation_id} ({row['status']})"
            )
        now = self._utc_now()
        self.conn.execute(
            "UPDATE asset_inventory_reservations SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, row["id"]),
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def commit_inventory_reservation(self, reservation_id: str) -> dict[str, Any]:
        row = self._reservation_row(reservation_id)
        if not row:
            raise ValueError(f"reservation not found: {reservation_id}")
        if row["status"] == "committed":
            return dict(row)
        if row["status"] != "pending":
            raise ValueError(
                f"reservation is not pending: {reservation_id} ({row['status']})"
            )
        now = self._utc_now()
        self.conn.execute(
            "UPDATE asset_inventory_reservations SET status = 'committed', updated_at = ? WHERE id = ? AND status = 'pending'",
            (now, row["id"]),
        )
        self._record_reservation_event(
            row,
            event_type="draft_ingest_accepted",
            occurred_at=now,
            evidence={
                "reservationId": row["reservation_id"],
                "assetId": row["asset_id"],
                "status": "committed",
            },
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def cancel_inventory_reservation(
        self,
        reservation_id: str,
        *,
        post_id: str,
        reason: str,
        cancelled_at: str | None = None,
    ) -> dict[str, Any]:
        """Terminalize a draft reservation from a durable cancellation event."""

        row = self._reservation_row(reservation_id)
        if not row:
            raise ValueError(f"reservation not found: {reservation_id}")
        post_id = self._required(post_id, "post_id")
        reason = self._required(reason, "reason")
        if row["status"] == "cancelled":
            return dict(row)
        if row["status"] not in {"pending", "committed"}:
            raise ValueError(
                f"reservation cannot be cancelled: {reservation_id} ({row['status']})"
            )
        now = cancelled_at or self._utc_now()
        self.conn.execute(
            """
            UPDATE asset_inventory_reservations
            SET status = 'cancelled', updated_at = ?
            WHERE id = ? AND status IN ('pending', 'committed')
            """,
            (now, row["id"]),
        )
        self._record_reservation_event(
            row,
            event_type="draft_cancelled",
            post_id=post_id,
            occurred_at=now,
            evidence={
                "reservationId": row["reservation_id"],
                "assetId": row["asset_id"],
                "postId": post_id,
                "reason": reason,
                "status": "cancelled",
            },
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def publish_inventory_reservation(
        self,
        reservation_id: str,
        *,
        post_id: str,
        instagram_media_id: str,
        published_at: str,
        instagram_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Terminalize a committed reservation and record its publication assignment."""

        row = self._reservation_row(reservation_id)
        if not row:
            raise ValueError(f"reservation not found: {reservation_id}")
        post_id = self._required(post_id, "post_id")
        instagram_media_id = self._required(instagram_media_id, "instagram_media_id")
        published_at = self._required(published_at, "published_at")
        if row["status"] == "published":
            event = self.conn.execute(
                """
                SELECT instagram_media_id
                FROM asset_inventory_reservation_events
                WHERE reservation_row_id = ? AND event_type = 'publication_confirmed'
                """,
                (row["id"],),
            ).fetchone()
            if event and event["instagram_media_id"] == instagram_media_id:
                return dict(row)
            raise ValueError(
                f"reservation already published to another media id: {reservation_id}"
            )
        if row["status"] != "committed":
            raise ValueError(
                f"reservation is not committed: {reservation_id} ({row['status']})"
            )
        asset = self._rendered_asset(str(row["asset_id"]))
        assignment_id = (
            "assign_"
            + self._canonical_sha256(
                {
                    "reservationId": row["reservation_id"],
                    "instagramMediaId": instagram_media_id,
                }
            )[:24]
        )
        self.conn.execute(
            """
            INSERT INTO asset_account_assignments
            (id, campaign_id, rendered_asset_id, account_id, instagram_account_id,
             source_family_id, perceptual_fingerprint, perceptual_cluster_id,
             account_group_id, account_eligibility_json, assignment_eligibility_json,
             notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                assignment_id,
                row["campaign_id"],
                row["asset_id"],
                row["account_id"],
                instagram_account_id,
                row["source_family_id"],
                row["perceptual_fingerprint"],
                row["perceptual_cluster_id"],
                row["account_group_id"],
                row["account_eligibility_json"],
                row["assignment_eligibility_json"],
                f"publication:{post_id}:{instagram_media_id}",
                published_at,
                published_at,
            ),
        )
        self.conn.execute(
            """
            UPDATE asset_inventory_reservations
            SET status = 'published', updated_at = ?
            WHERE id = ? AND status = 'committed'
            """,
            (published_at, row["id"]),
        )
        self._record_reservation_event(
            row,
            event_type="publication_confirmed",
            post_id=post_id,
            instagram_media_id=instagram_media_id,
            occurred_at=published_at,
            evidence={
                "reservationId": row["reservation_id"],
                "assetId": row["asset_id"],
                "assignmentId": assignment_id,
                "postId": post_id,
                "instagramMediaId": instagram_media_id,
                "instagramAccountId": instagram_account_id,
                "finalMediaSha256": asset.get("content_hash"),
                "status": "published",
            },
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM asset_inventory_reservations WHERE id = ?", (row["id"],)
            ).fetchone()
        )

    def _reservation_row(self, reservation_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM asset_inventory_reservations
            WHERE reservation_id = ? OR id = ?
            """,
            (reservation_id, reservation_id),
        ).fetchone()

    def _record_reservation_event(
        self,
        row: sqlite3.Row,
        *,
        event_type: str,
        occurred_at: str,
        evidence: dict[str, Any],
        post_id: str | None = None,
        instagram_media_id: str | None = None,
    ) -> None:
        evidence_json = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        evidence_sha256 = hashlib.sha256(evidence_json.encode()).hexdigest()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO asset_inventory_reservation_events
            (id, reservation_row_id, reservation_id, event_type, post_id,
             instagram_media_id, occurred_at, evidence_json, evidence_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"invresevt_{evidence_sha256[:24]}",
                row["id"],
                row["reservation_id"],
                event_type,
                post_id,
                instagram_media_id,
                occurred_at,
                evidence_json,
                evidence_sha256,
            ),
        )

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized

    def reservation_reconciliation_report(
        self, *, now: str | None = None, apply: bool = False
    ) -> dict[str, Any]:
        current = now or self._utc_now()
        stranded = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT *
                FROM asset_inventory_reservations
                WHERE status IN ('pending', 'committed')
                  AND expires_at IS NOT NULL
                  AND expires_at != ''
                  AND expires_at <= ?
                ORDER BY expires_at, reservation_id
                """,
                (current,),
            ).fetchall()
        ]
        expired_count = self.expire_inventory_reservations(now=current) if apply else 0
        expired = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT *
                FROM asset_inventory_reservations
                WHERE status = 'expired'
                ORDER BY updated_at DESC, reservation_id
                """
            ).fetchall()
        ]
        return {
            "schema": "campaign_factory.inventory_reservation_reconciliation.v1",
            "generatedAt": current,
            "applied": apply,
            "expiredNow": expired_count,
            "strandedCount": len(stranded),
            "strandedReservations": stranded,
            "expiredReservations": expired,
        }

    def inventory_uniqueness_conflicts(
        self,
        asset: dict[str, Any],
        *,
        uniqueness: dict[str, str],
        surface: str,
        cooldown_days: int,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        keys = {
            "sourceFamilyId": uniqueness.get("sourceFamilyId") or "",
            "perceptualClusterId": uniqueness.get("perceptualClusterId") or "",
        }
        if not any(keys.values()):
            return []
        now = datetime.fromisoformat(self._utc_now())
        cutoff = (now - timedelta(days=max(0, int(cooldown_days or 0)))).isoformat()
        conflicts: list[dict[str, Any]] = []
        for key_name, value in keys.items():
            if not value:
                continue
            column = (
                "source_family_id"
                if key_name == "sourceFamilyId"
                else "perceptual_cluster_id"
            )
            rows = self.conn.execute(
                f"""
                SELECT asset_id, account_id, reserved_at, status
                FROM asset_inventory_reservations
                WHERE campaign_id = ? AND surface = ? AND {column} = ?
                  AND status IN ('pending', 'committed')
                  AND asset_id <> ?
                  AND reserved_at >= ?
                """,
                (asset["campaign_id"], surface, value, asset["id"], cutoff),
            ).fetchall()
            for row in rows:
                if account_id and row["account_id"] == account_id:
                    continue
                conflicts.append(
                    {
                        "assetId": row["asset_id"],
                        "reason": f"active_reservation_{column}",
                        "status": row["status"],
                    }
                )
            assigned = self.conn.execute(
                """
                SELECT a.rendered_asset_id, a.account_id, a.created_at
                FROM asset_account_assignments a
                JOIN rendered_assets r ON r.id = a.rendered_asset_id
                WHERE a.campaign_id = ? AND r.content_surface = ? AND r.id <> ?
                  AND a.created_at >= ?
                """,
                (asset["campaign_id"], surface, asset["id"], cutoff),
            ).fetchall()
            for row in assigned:
                other = self._rendered_asset(row["rendered_asset_id"])
                other_values = self._asset_uniqueness_values(other)
                if other_values.get(key_name) != value:
                    continue
                if account_id and row["account_id"] == account_id:
                    continue
                conflicts.append(
                    {
                        "assetId": row["rendered_asset_id"],
                        "reason": f"assigned_{column}",
                        "status": "assigned",
                    }
                )
        return conflicts

    def reservation_adjusted_inventory(
        self,
        readiness_rows: list[dict[str, Any]],
        *,
        content_surface: str | None = None,
        reconcile_expired: bool = True,
        ensure_metadata: bool = True,
    ) -> dict[str, int]:
        if reconcile_expired:
            self.expire_inventory_reservations()
        active_asset_ids = [
            str(row.get("assetId"))
            for row in readiness_rows
            if row.get("canHandoff")
            and row.get("assetId")
            and (
                content_surface is None or row.get("contentSurface") == content_surface
            )
        ]
        if not active_asset_ids:
            return {
                "grossInventory": 0,
                "reservedInventory": 0,
                "assignedInventory": 0,
                "usedInventory": 0,
                "cooldownBlockedInventory": 0,
                "netInventory": 0,
            }
        placeholders = ",".join("?" for _ in active_asset_ids)
        params = sorted(active_asset_ids)
        reserved_rows = self.conn.execute(
            f"""
            SELECT DISTINCT asset_id
            FROM asset_inventory_reservations
            WHERE asset_id IN ({placeholders})
              AND status IN ('pending', 'committed')
            """,
            params,
        ).fetchall()
        assignment_rows = self.conn.execute(
            f"""
            SELECT DISTINCT rendered_asset_id
            FROM asset_account_assignments
            WHERE rendered_asset_id IN ({placeholders})
            """,
            params,
        ).fetchall()
        reserved = {str(row["asset_id"]) for row in reserved_rows}
        used = {str(row["rendered_asset_id"]) for row in assignment_rows}
        reserved_or_used = reserved | used
        assets_by_id = {
            str(row["id"]): dict(row)
            for row in self.conn.execute(
                f"SELECT * FROM rendered_assets WHERE id IN ({placeholders})",
                params,
            ).fetchall()
        }
        blocked_keys: set[tuple[str, str]] = set()
        for asset_id in reserved_or_used:
            asset = assets_by_id.get(asset_id)
            if not asset:
                continue
            asset = (
                self._ensure_rendered_asset_perceptual_metadata(asset_id)
                if ensure_metadata
                else asset
            )
            assets_by_id[asset_id] = asset
            values = self._asset_uniqueness_values(asset)
            for key_name in ("sourceFamilyId", "perceptualClusterId"):
                value = values.get(key_name) or ""
                if value:
                    blocked_keys.add((key_name, value))
        cooldown_blocked: set[str] = set()
        for asset_id, asset in assets_by_id.items():
            if asset_id in reserved_or_used:
                continue
            asset = (
                self._ensure_rendered_asset_perceptual_metadata(asset_id)
                if ensure_metadata
                else asset
            )
            assets_by_id[asset_id] = asset
            values = self._asset_uniqueness_values(asset)
            if any(
                (key_name, values.get(key_name) or "") in blocked_keys
                for key_name in ("sourceFamilyId", "perceptualClusterId")
            ):
                cooldown_blocked.add(asset_id)
        unavailable = reserved | used
        unavailable |= cooldown_blocked
        return {
            "grossInventory": len(active_asset_ids),
            "reservedInventory": len(reserved),
            "assignedInventory": len(used),
            "usedInventory": len(used),
            "cooldownBlockedInventory": len(cooldown_blocked),
            "netInventory": max(0, len(active_asset_ids) - len(unavailable)),
        }
