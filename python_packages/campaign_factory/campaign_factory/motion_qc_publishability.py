from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .persistence import json_load

MOTION_QC_POLICY_ID = "contentforge.motion_specific_qc"
MOTION_QC_POLICY_VERSION = "1.0.0"
MOTION_QC_CORE_REQUIREMENTS = (
    "motion",
    "temporal",
    "freeze",
    "anatomy",
    "identity",
)
MOTION_QC_BLOCKING_CODES = {
    "motion_specific_qc_required",
    "audio_video_alignment_qc_required",
    "lip_sync_qc_required",
}


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class MotionQcPublishabilityMixin:
    """Fail-closed generated-motion evidence boundary for Campaign Factory."""

    conn: sqlite3.Connection
    _utc_now: Callable[[], str]
    _sanitize_for_storage: Callable[[Any], Any]
    _verification_id: Callable[..., str]
    rendered_asset: Callable[[str], dict[str, Any]]
    record_event: Callable[..., dict[str, Any]]

    def motion_qc_requirements(self, asset: dict[str, Any]) -> dict[str, bool]:
        metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        publishability = metadata.get("publishability")
        publishability = publishability if isinstance(publishability, dict) else {}
        blocking_issues = {
            str(value)
            for value in publishability.get("blockingIssues") or []
            if isinstance(value, str)
        }
        generated_motion = bool(
            metadata.get("schema") == "campaign_factory.motion_generation_asset.v1"
            or str(asset.get("frame_type") or "") == "generated_motion"
            or blocking_issues & MOTION_QC_BLOCKING_CODES
        )
        embedded_audio = bool(
            metadata.get("audioBurned") is True
            or str(metadata.get("embeddedAudioMode") or "") in {"source", "generated"}
            or "audio_video_alignment_qc_required" in blocking_issues
        )
        lip_sync = bool(
            str(metadata.get("modelId") or "") == "local_longcat_avatar15_q4_mlx"
            or "lip_sync_qc_required" in blocking_issues
        )
        return {
            "motion": generated_motion,
            "audioAlignment": generated_motion and embedded_audio,
            "lipSync": generated_motion and lip_sync,
        }

    def generated_motion_identity_failures(self, asset: dict[str, Any]) -> list[str]:
        metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("schema") != "campaign_factory.motion_generation_asset.v1":
            return []
        publishability = metadata.get("publishability")
        publishability = publishability if isinstance(publishability, dict) else {}
        blocking_issues = {
            str(value)
            for value in publishability.get("blockingIssues") or []
            if isinstance(value, str)
        }
        text_only_unassigned = bool(
            metadata.get("identityRole") == "non_creator_broll"
            or metadata.get("sourceAssetRole") == "static_fallback_only"
            or "text_to_video_identity_assignment_forbidden" in blocking_issues
        )
        return (
            ["text_to_video_identity_assignment_forbidden"]
            if text_only_unassigned
            else []
        )

    def _motion_qc_receipt_validation(
        self,
        asset: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[list[str], dict[str, bool]]:
        requirements = self.motion_qc_requirements(asset)
        if not requirements["motion"]:
            return [], requirements
        failures: list[str] = []
        subject_sha256 = str(receipt.get("subjectSha256") or "")
        content_hash = str(asset.get("content_hash") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", subject_sha256):
            failures.append("motion_specific_qc_subject_invalid")
        if subject_sha256 != content_hash:
            failures.append("motion_specific_qc_subject_mismatch")
        policy = receipt.get("policy")
        policy = policy if isinstance(policy, dict) else {}
        if (
            policy.get("id") != MOTION_QC_POLICY_ID
            or policy.get("version") != MOTION_QC_POLICY_VERSION
        ):
            failures.append("motion_specific_qc_policy_mismatch")
        receipt_requirements = receipt.get("requirements")
        receipt_requirements = (
            receipt_requirements if isinstance(receipt_requirements, dict) else {}
        )
        evidence_sources = receipt.get("evidenceSources")
        evidence_sources = (
            evidence_sources if isinstance(evidence_sources, dict) else {}
        )
        required_evidence = list(MOTION_QC_CORE_REQUIREMENTS)
        if requirements["audioAlignment"]:
            required_evidence.append("audioAlignment")
        if requirements["lipSync"]:
            required_evidence.append("lipSync")
        for name in required_evidence:
            if receipt_requirements.get(name) is not True:
                failures.append(f"motion_specific_qc_requirement_missing:{name}")
                continue
            source = evidence_sources.get(name)
            source = source if isinstance(source, dict) else {}
            if (
                source.get("available") is not True
                or not str(source.get("analyzer") or "").strip()
                or source.get("subjectSha256") != content_hash
            ):
                failures.append(f"motion_specific_qc_evidence_invalid:{name}")
        if (
            receipt.get("passed") is not True
            or receipt.get("verdict") != "pass"
            or receipt.get("evidenceOnly") is not True
            or receipt.get("modelCalls") != 0
            or receipt.get("providerCalls") != 0
            or receipt.get("reasons") != []
        ):
            failures.append("motion_specific_qc_not_passed")
        return sorted(set(failures)), requirements

    def register_motion_qc_receipt(
        self,
        rendered_asset_id: str,
        *,
        receipt_path: str | Path,
        created_by: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Register one immutable ContentForge motion-QC result."""

        asset = self.rendered_asset(rendered_asset_id)
        requirements = self.motion_qc_requirements(asset)
        if not requirements["motion"]:
            raise ValueError("motion QC receipts only apply to generated motion assets")
        path = Path(receipt_path).expanduser().resolve()
        try:
            raw_receipt = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"motion QC receipt is unreadable: {path}") from exc
        try:
            receipt = json.loads(raw_receipt)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("motion QC receipt must be a JSON object") from exc
        if not isinstance(receipt, dict):
            raise ValueError("motion QC receipt must be a JSON object")
        failures, requirements = self._motion_qc_receipt_validation(asset, receipt)
        if failures:
            raise ValueError("invalid motion QC receipt: " + ", ".join(failures))
        media_path = Path(
            str(asset.get("campaign_path") or asset.get("output_path") or "")
        )
        try:
            media_sha256, media_size_bytes = _sha256_file(media_path)
        except OSError as exc:
            raise ValueError(
                f"generated motion media is unreadable: {media_path}"
            ) from exc
        if media_sha256 != str(asset.get("content_hash") or ""):
            raise ValueError(
                "generated motion media no longer matches its content hash"
            )
        canonical_receipt = json.dumps(
            self._sanitize_for_storage(receipt),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        receipt_sha256 = hashlib.sha256(canonical_receipt.encode("utf-8")).hexdigest()
        receipt_id = self._verification_id(
            "motionqc", rendered_asset_id, media_sha256, receipt_sha256
        )
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO motion_qc_receipts
            (id, campaign_id, rendered_asset_id, subject_sha256, policy_id,
             policy_version, receipt_path, receipt_sha256, receipt_json,
             requirements_json, media_size_bytes, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                asset["campaign_id"],
                rendered_asset_id,
                media_sha256,
                MOTION_QC_POLICY_ID,
                MOTION_QC_POLICY_VERSION,
                str(path),
                receipt_sha256,
                canonical_receipt,
                json.dumps(requirements, sort_keys=True),
                media_size_bytes,
                now,
                created_by,
            ),
        )
        row = self.conn.execute(
            "SELECT * FROM motion_qc_receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                """SELECT * FROM motion_qc_receipts
                WHERE rendered_asset_id = ? AND receipt_sha256 = ?""",
                (rendered_asset_id, receipt_sha256),
            ).fetchone()
        if row is None:
            raise RuntimeError("motion QC receipt registration failed")
        self.record_event(
            "motion_qc_receipt_registered",
            campaign_id=asset["campaign_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message="Immutable motion QC receipt registered",
            metadata={
                "receiptId": row["id"],
                "receiptSha256": receipt_sha256,
                "subjectSha256": media_sha256,
                "policyId": MOTION_QC_POLICY_ID,
                "policyVersion": MOTION_QC_POLICY_VERSION,
            },
            commit=False,
        )
        if commit:
            self.conn.commit()
        return self.motion_qc_receipt_payload(dict(row))

    def motion_qc_receipt_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "renderedAssetId": row["rendered_asset_id"],
            "subjectSha256": row["subject_sha256"],
            "policy": {
                "id": row["policy_id"],
                "version": row["policy_version"],
            },
            "receiptPath": row["receipt_path"],
            "receiptSha256": row["receipt_sha256"],
            "requirements": json_load(row["requirements_json"], {}),
            "mediaSizeBytes": row["media_size_bytes"],
            "createdAt": row["created_at"],
            "createdBy": row["created_by"],
        }

    def latest_motion_qc_receipt(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM motion_qc_receipts
            WHERE rendered_asset_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (rendered_asset_id,),
        ).fetchone()
        return dict(row) if row else None

    def motion_qc_gate(self, asset: dict[str, Any]) -> dict[str, Any]:
        requirements = self.motion_qc_requirements(asset)
        identity_failures = self.generated_motion_identity_failures(asset)
        receipt_payload = None
        failures: list[str] = []
        if requirements["motion"]:
            row = self.latest_motion_qc_receipt(str(asset["id"]))
            if row is None:
                failures.append("motion_specific_qc_required")
                if requirements["audioAlignment"]:
                    failures.append("audio_video_alignment_qc_required")
                if requirements["lipSync"]:
                    failures.append("lip_sync_qc_required")
            else:
                receipt = json_load(row.get("receipt_json"), {})
                if not isinstance(receipt, dict):
                    failures.append("motion_specific_qc_receipt_invalid")
                else:
                    canonical_receipt = json.dumps(
                        self._sanitize_for_storage(receipt),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    if hashlib.sha256(
                        canonical_receipt.encode("utf-8")
                    ).hexdigest() != row.get("receipt_sha256"):
                        failures.append("motion_specific_qc_receipt_invalid")
                    validation_failures, _ = self._motion_qc_receipt_validation(
                        asset, receipt
                    )
                    failures.extend(validation_failures)
                    if row.get("subject_sha256") != asset.get("content_hash"):
                        failures.append("motion_specific_qc_subject_mismatch")
                    media_path = Path(
                        str(
                            asset.get("campaign_path") or asset.get("output_path") or ""
                        )
                    )
                    try:
                        media_sha256, media_size_bytes = _sha256_file(media_path)
                    except OSError:
                        failures.append("motion_specific_qc_media_unreadable")
                    else:
                        if media_sha256 != asset.get("content_hash"):
                            failures.append("motion_specific_qc_media_hash_mismatch")
                        if media_size_bytes != row.get("media_size_bytes"):
                            failures.append("motion_specific_qc_media_size_mismatch")
                    receipt_payload = self.motion_qc_receipt_payload(row)
        failures.extend(identity_failures)
        failures = sorted(set(failures))
        motion_only_failures = [
            value
            for value in failures
            if value != "text_to_video_identity_assignment_forbidden"
        ]
        return {
            "failures": failures,
            "requirements": requirements,
            "receipt": receipt_payload,
            "checks": {
                "motion_specific_qc_passed": bool(
                    not requirements["motion"] or not motion_only_failures
                ),
                "audio_video_alignment_qc_passed": bool(
                    not requirements["audioAlignment"] or not motion_only_failures
                ),
                "lip_sync_qc_passed": bool(
                    not requirements["lipSync"] or not motion_only_failures
                ),
                "creator_identity_assignment_allowed": not bool(identity_failures),
            },
        }
