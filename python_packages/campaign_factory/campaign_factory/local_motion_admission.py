"""Fail-closed Arena/Router admission for ordinary local motion generation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import payload_fingerprint
from reel_factory.worker_api import admit_local_motion

from pipeline_contracts import validate_local_model_router_decision

from .canonical_analyzer_registry import (
    CanonicalAnalyzerRegistryError,
)
from .canonical_analyzer_registry import (
    validate_canonical_analyzer_registry as _validate_canonical_analyzer_registry,
)
from .core import sha256_file
from .evidence_foundation import validate_compiled_thin_evidence_records


class LocalMotionAdmissionError(RuntimeError):
    """The requested local generation is not backed by valid promotion evidence."""


_PLACEHOLDER_REASONS = {"test", "manual", "because", "override", "n/a", "na"}


def _fingerprint(value: Mapping[str, Any]) -> str:
    return payload_fingerprint(value)


def validate_canonical_analyzer_registry(
    registry: Mapping[str, Any],
    *,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Require the exact registry emitted by ContentForge's canonical adapter."""

    try:
        return _validate_canonical_analyzer_registry(
            registry, contentforge_root=contentforge_root
        )
    except CanonicalAnalyzerRegistryError as exc:
        raise LocalMotionAdmissionError(f"local_motion_{exc}") from exc


def _load_json_object(path: Path, *, field: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise LocalMotionAdmissionError(f"local_motion_{field}_missing_or_unsafe")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalMotionAdmissionError(f"local_motion_{field}_invalid_json") from exc
    if not isinstance(value, dict):
        raise LocalMotionAdmissionError(f"local_motion_{field}_must_be_object")
    return value


def _normalized_override(
    *,
    model_id: str | None,
    operator: str | None,
    reason: str | None,
) -> tuple[str | None, str | None, str | None]:
    supplied = (model_id, operator, reason)
    if any(value is not None for value in supplied) and not all(
        value is not None and str(value).strip() for value in supplied
    ):
        raise LocalMotionAdmissionError(
            "local_motion_router_override_evidence_must_be_complete"
        )
    if model_id is None:
        return None, None, None
    normalized_reason = " ".join(str(reason).split())
    words = [
        word for word in normalized_reason.split(" ") if any(c.isalnum() for c in word)
    ]
    if (
        len(normalized_reason) < 20
        or len(words) < 3
        or normalized_reason.lower().strip(" .!?") in _PLACEHOLDER_REASONS
    ):
        raise LocalMotionAdmissionError(
            "local_motion_router_override_reason_not_substantive"
        )
    return str(model_id).strip(), str(operator).strip(), normalized_reason


def build_local_motion_admission(
    *,
    evidence_bundle_path: Path | None,
    evidence_bundle: Mapping[str, Any] | None = None,
    arena_summary_path: Path,
    accepted_still_path: Path,
    audio_path: Path | None,
    campaign_creator: str,
    task_kind: str,
    override_model_id: str | None = None,
    override_operator: str | None = None,
    override_reason: str | None = None,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Return one exact Router decision bound to this Campaign request."""

    if (evidence_bundle_path is None) == (evidence_bundle is None):
        raise LocalMotionAdmissionError(
            "local_motion_evidence_bundle_requires_one_transport"
        )
    raw_records = (
        _load_json_object(evidence_bundle_path, field="evidence_bundle")
        if evidence_bundle_path is not None
        else dict(evidence_bundle or {})
    )
    records = validate_compiled_thin_evidence_records(raw_records)
    validate_canonical_analyzer_registry(
        records["analyzerRegistry"], contentforge_root=contentforge_root
    )
    summary = _load_json_object(arena_summary_path, field="arena_summary")
    identity = records["creatorIdentityProfile"]
    intent = records["contentIntent"]
    recipe = records["benchmarkRecipe"]
    normalized_creator = str(campaign_creator or "").strip().lower()
    evidence_creator = str(identity.get("creatorKey") or "").strip().lower()
    if not normalized_creator or evidence_creator != normalized_creator:
        raise LocalMotionAdmissionError("local_motion_campaign_creator_mismatch")

    still = accepted_still_path.expanduser().resolve()
    if not still.is_file() or still.is_symlink():
        raise LocalMotionAdmissionError("local_motion_accepted_still_missing_or_unsafe")
    input_fingerprints = [sha256_file(still)]
    if audio_path is not None:
        audio = audio_path.expanduser().resolve()
        if not audio.is_file() or audio.is_symlink():
            raise LocalMotionAdmissionError("local_motion_audio_missing_or_unsafe")
        input_fingerprints.append(sha256_file(audio))
    if list(intent.get("sourceAssetFingerprints") or []) != input_fingerprints:
        raise LocalMotionAdmissionError("local_motion_content_intent_input_mismatch")
    if list(recipe.get("inputFingerprints") or []) != input_fingerprints:
        raise LocalMotionAdmissionError("local_motion_benchmark_input_mismatch")
    if recipe.get("taskKind") != task_kind:
        raise LocalMotionAdmissionError("local_motion_benchmark_task_mismatch")

    profile_id = str(identity.get("profileId") or "")
    profile_fingerprint = _fingerprint(identity)
    intent_id = str(intent.get("intentId") or "")
    intent_fingerprint = _fingerprint(intent)
    selected_model, operator, reason = _normalized_override(
        model_id=override_model_id,
        operator=override_operator,
        reason=override_reason,
    )
    try:
        admission = admit_local_motion(
            arena_summary=summary,
            evidence_records=records,
            input_fingerprints=input_fingerprints,
            creator_id=normalized_creator,
            identity_profile_id=profile_id,
            identity_profile_fingerprint=profile_fingerprint,
            content_intent_id=intent_id,
            content_intent_fingerprint=intent_fingerprint,
            task_kind=task_kind,
            override_model_id=selected_model,
            override_operator=operator,
            override_reason=reason,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise LocalMotionAdmissionError(
            f"local_motion_router_admission_failed:{exc}"
        ) from exc
    if not isinstance(admission, dict):
        raise LocalMotionAdmissionError("local_motion_router_admission_invalid")
    return admission


def revalidate_local_motion_admission(
    admission: Mapping[str, Any] | None,
    *,
    arena_summary_path: Path | None,
    accepted_still_path: Path,
    audio_path: Path | None,
    campaign_creator: str,
    task_kind: str,
    model_id: str,
    benchmark_recipe: Mapping[str, Any] | None,
    analyzer_registry: Mapping[str, Any] | None,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Re-admit immediately before execution and reject stale/replayed evidence."""

    if not isinstance(admission, Mapping):
        raise LocalMotionAdmissionError("local_motion_execution_admission_missing")
    original = dict(admission)
    expected_keys = {
        "schema",
        "routerDecision",
        "arenaSummary",
        "evidenceRecords",
        "inputFingerprints",
        "resourceSnapshot",
        "admissionFingerprint",
    }
    if set(original) != expected_keys or original.get("schema") != (
        "campaign_factory.local_motion_admission.v1"
    ):
        raise LocalMotionAdmissionError("local_motion_execution_admission_invalid")
    original_core = dict(original)
    claimed_admission = str(original_core.pop("admissionFingerprint") or "")
    if _fingerprint(original_core) != claimed_admission:
        raise LocalMotionAdmissionError(
            "local_motion_execution_admission_fingerprint_mismatch"
        )
    raw_decision = original.get("routerDecision")
    if not isinstance(raw_decision, Mapping):
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_missing"
        )
    decision = dict(raw_decision)
    try:
        validate_local_model_router_decision(decision)
    except ValueError as exc:
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_invalid"
        ) from exc
    decision_core = dict(decision)
    claimed_decision = str(decision_core.pop("decisionFingerprint") or "")
    if _fingerprint(decision_core) != claimed_decision:
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_decision_fingerprint_mismatch"
        )
    if decision.get("selectedModelId") != model_id:
        raise LocalMotionAdmissionError(
            "local_motion_execution_selected_model_mismatch"
        )
    if (
        decision.get("paidProviderFallbackAllowed") is not False
        or decision.get("legacyLocalMotionFallbackAllowed") is not False
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_router_fallback_not_closed"
        )

    records_raw = original.get("evidenceRecords")
    if not isinstance(records_raw, Mapping):
        raise LocalMotionAdmissionError("local_motion_execution_evidence_missing")
    records = validate_compiled_thin_evidence_records(records_raw)
    recipe = records["benchmarkRecipe"]
    registry = records["analyzerRegistry"]
    if benchmark_recipe is None or dict(benchmark_recipe) != recipe:
        raise LocalMotionAdmissionError(
            "local_motion_execution_benchmark_recipe_mismatch"
        )
    if analyzer_registry is None or dict(analyzer_registry) != registry:
        raise LocalMotionAdmissionError(
            "local_motion_execution_analyzer_registry_mismatch"
        )
    validate_canonical_analyzer_registry(registry, contentforge_root=contentforge_root)

    identity = records["creatorIdentityProfile"]
    intent = records["contentIntent"]
    normalized_creator = str(campaign_creator or "").strip().lower()
    if str(identity.get("creatorKey") or "").strip().lower() != normalized_creator:
        raise LocalMotionAdmissionError(
            "local_motion_execution_campaign_creator_mismatch"
        )
    still = accepted_still_path.expanduser().resolve()
    if not still.is_file() or still.is_symlink():
        raise LocalMotionAdmissionError(
            "local_motion_execution_accepted_still_missing_or_unsafe"
        )
    input_fingerprints = [sha256_file(still)]
    if audio_path is not None:
        audio = audio_path.expanduser().resolve()
        if not audio.is_file() or audio.is_symlink():
            raise LocalMotionAdmissionError(
                "local_motion_execution_audio_missing_or_unsafe"
            )
        input_fingerprints.append(sha256_file(audio))
    if (
        original.get("inputFingerprints") != input_fingerprints
        or list(intent.get("sourceAssetFingerprints") or []) != input_fingerprints
        or list(recipe.get("inputFingerprints") or []) != input_fingerprints
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_input_fingerprint_mismatch"
        )
    if (
        recipe.get("taskKind") != task_kind
        or decision.get("request", {}).get("taskKind") != task_kind
    ):
        raise LocalMotionAdmissionError("local_motion_execution_task_mismatch")

    if arena_summary_path is None:
        raise LocalMotionAdmissionError(
            "local_motion_execution_arena_summary_path_missing"
        )
    summary = _load_json_object(arena_summary_path, field="arena_summary")
    summary_binding = {
        "summaryId": summary.get("summaryId"),
        "summaryFingerprint": summary.get("summaryFingerprint"),
        "planId": summary.get("planId"),
        "planFingerprint": summary.get("planFingerprint"),
        "purpose": summary.get("purpose"),
    }
    if original.get("arenaSummary") != summary_binding:
        raise LocalMotionAdmissionError("local_motion_execution_arena_summary_mismatch")

    override = decision.get("operatorOverride")
    override = override if isinstance(override, Mapping) else {}
    try:
        current = admit_local_motion(
            arena_summary=summary,
            evidence_records=records,
            input_fingerprints=input_fingerprints,
            creator_id=normalized_creator,
            identity_profile_id=str(identity.get("profileId") or ""),
            identity_profile_fingerprint=_fingerprint(identity),
            content_intent_id=str(intent.get("intentId") or ""),
            content_intent_fingerprint=_fingerprint(intent),
            task_kind=task_kind,
            override_model_id=(str(override.get("modelId")) if override else None),
            override_operator=(str(override.get("operator")) if override else None),
            override_reason=(str(override.get("reason")) if override else None),
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise LocalMotionAdmissionError(
            f"local_motion_execution_readmission_failed:{exc}"
        ) from exc
    if not isinstance(current, dict):
        raise LocalMotionAdmissionError("local_motion_execution_readmission_invalid")
    current_decision = current.get("routerDecision")
    if not isinstance(current_decision, Mapping):
        raise LocalMotionAdmissionError(
            "local_motion_execution_readmission_decision_missing"
        )
    for field in (
        "selectedModelId",
        "selectedModelFingerprint",
        "operatorOverride",
        "paidProviderFallbackAllowed",
        "legacyLocalMotionFallbackAllowed",
    ):
        if current_decision.get(field) != decision.get(field):
            raise LocalMotionAdmissionError(
                f"local_motion_execution_router_drift:{field}"
            )
    original_winning = decision.get("winningEvidence")
    current_winning = current_decision.get("winningEvidence")
    if not isinstance(original_winning, Mapping) or not isinstance(
        current_winning, Mapping
    ):
        raise LocalMotionAdmissionError(
            "local_motion_execution_winning_evidence_missing"
        )
    for field in (
        "arenaSummaryFingerprint",
        "benchmarkIds",
        "cohortKey",
        "matchedArenaSampleIds",
        "validArenaSampleIds",
        "promotionApproval",
    ):
        if current_winning.get(field) != original_winning.get(field):
            raise LocalMotionAdmissionError(
                f"local_motion_execution_winning_evidence_drift:{field}"
            )
    return original
