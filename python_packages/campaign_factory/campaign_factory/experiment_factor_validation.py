from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .observed_experiment_reporting import EXPERIMENT_FACTORS


def validate_factor_values(
    *,
    changed_variable: str,
    variants: list[Any],
    factor_values: tuple[dict[str, Any], dict[str, Any]] | None,
    assets: dict[str, dict[str, Any]],
    source_family_block_id: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    if changed_variable not in EXPERIMENT_FACTORS:
        raise ValueError(f"unsupported blocked experiment factor: {changed_variable}")
    if factor_values is None or len(factor_values) != 2:
        raise ValueError("blocked experiment requires factor values for both arms")
    normalized = {
        "control": dict(factor_values[0]),
        "treatment": dict(factor_values[1]),
    }
    for role, values in normalized.items():
        if set(values) != set(EXPERIMENT_FACTORS):
            missing = sorted(set(EXPERIMENT_FACTORS) - set(values))
            extra = sorted(set(values) - set(EXPERIMENT_FACTORS))
            raise ValueError(
                f"{role} factor values are incomplete: missing={missing} extra={extra}"
            )
        if any(
            not isinstance(value, str) or not value.strip() for value in values.values()
        ):
            raise ValueError(f"{role} factor values must be non-empty strings")
    differing = {
        factor
        for factor in EXPERIMENT_FACTORS
        if normalized["control"][factor] != normalized["treatment"][factor]
    }
    if differing != {changed_variable}:
        raise ValueError(
            "experiment arms must differ only on the declared factor: "
            f"declared={changed_variable} differing={sorted(differing)}"
        )
    if len(variants) != 2:
        raise ValueError("blocked experiment requires exactly two variants")
    control_value = normalized["control"][changed_variable]
    treatment_value = normalized["treatment"][changed_variable]
    if treatment_value != variants[1]:
        raise ValueError("treatment factor value does not match experiment variant")
    if not (
        control_value == variants[0]
        or (changed_variable == "observed_profile" and variants[0] == "control")
    ):
        raise ValueError("control factor value does not match experiment variant")

    actual_families = {
        role: asset_source_family(asset) for role, asset in assets.items()
    }
    if changed_variable == "source_family":
        if len(set(actual_families.values())) != 2:
            raise ValueError("source-family experiment requires two source families")
    elif set(actual_families.values()) != {source_family_block_id}:
        raise ValueError("experiment assets do not match the source-family block")
    for role, actual in actual_families.items():
        if normalized[role]["source_family"] != actual:
            raise ValueError(f"{role} source-family factor does not match asset")

    if changed_variable == "audio_track":
        for role, asset in assets.items():
            actual_track = asset_audio_track(asset)
            if not actual_track:
                raise ValueError(f"{role} exact audio track evidence is missing")
            if normalized[role]["audio_track"] != actual_track:
                raise ValueError(f"{role} audio-track factor does not match asset")

    controls = {
        key: normalized["control"][key]
        for key in sorted(EXPERIMENT_FACTORS - {changed_variable})
    }
    fingerprint = hashlib.sha256(
        json.dumps(controls, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return normalized, fingerprint


def validate_audio_experiment_exception(receipt: dict[str, Any] | None) -> None:
    required = {"exceptionId", "authorizedBy", "reason", "scope"}
    if not isinstance(receipt, dict) or not required.issubset(receipt):
        raise PermissionError(
            "exact-track experiment requires an operator reuse-policy exception"
        )
    if receipt.get("scope") != "exact_track_controlled_experiment" or any(
        not str(receipt.get(key) or "").strip() for key in required
    ):
        raise PermissionError("audio reuse-policy exception is invalid")


def asset_source_family(asset: dict[str, Any]) -> str:
    metadata = json.loads(asset.get("metadata_json") or "{}")
    return str(
        metadata.get("sourceFamilyId")
        or asset.get("parent_asset_id")
        or asset.get("id")
    )


def asset_audio_track(asset: dict[str, Any]) -> str:
    metadata = json.loads(asset.get("metadata_json") or "{}")
    receipt = metadata.get("audioEmbeddingReceipt")
    selected = receipt.get("selectedTrack") if isinstance(receipt, dict) else None
    if not isinstance(selected, dict):
        return ""
    return str(
        selected.get("canonicalTrackId")
        or selected.get("musicId")
        or selected.get("trackId")
        or ""
    )


def candidate_source_family(source: Mapping[str, Any]) -> str:
    raw_notes = source.get("notes")
    if isinstance(raw_notes, Mapping):
        notes = dict(raw_notes)
    elif raw_notes is not None:
        try:
            decoded = json.loads(str(raw_notes))
            notes = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            notes = {}
    else:
        notes = {}
    return str(
        source.get("sourceFamilyId")
        or source.get("source_family_id")
        or notes.get("sourceFamilyId")
        or notes.get("source_family_id")
        or ""
    ).strip()
