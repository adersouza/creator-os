#!/usr/bin/env python3
"""Default-off post-render virality evidence checks for Reel Factory outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIN_VIRALITY_SCORE = 70.0
MIN_HOOK_SCORE = 60.0
MAX_RETENTION_RISK = 65.0


def _coerce_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    score = float(value)
    if 0.0 <= score <= 1.0:
        score *= 100.0
    if score < 0.0 or score > 100.0:
        return None
    return round(score, 3)


def _first_score(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        score = _coerce_score(payload.get(key))
        if score is not None:
            return score
    for parent in ("prediction", "metrics", "scores", "analysis"):
        nested = payload.get(parent)
        if isinstance(nested, dict):
            score = _first_score(nested, keys)
            if score is not None:
                return score
    return None


def _report_body(report: dict[str, Any]) -> dict[str, Any]:
    nested = report.get("virality")
    if isinstance(nested, dict):
        return nested
    return report


def evaluate_virality_report(
    report: dict[str, Any] | None, *, required: bool = False
) -> dict[str, Any]:
    """Evaluate a supplied Higgsfield/operator virality report without making provider calls."""
    if not isinstance(report, dict):
        return {
            "schema": "reel_factory.virality_qc.v1",
            "status": "failed" if required else "unavailable",
            "required": bool(required),
            "reportPresent": False,
            "provider": None,
            "model": None,
            "modelBacked": None,
            "reportId": None,
            "score": None,
            "hookScore": None,
            "retentionRisk": None,
            "thresholds": thresholds(),
            "warnings": ["virality_report_missing"] if required else [],
        }

    body = _report_body(report)
    score = _first_score(
        body, ("score", "viralityScore", "overallScore", "predictionScore")
    )
    hook_score = _first_score(
        body, ("hookScore", "hookViralityScore", "firstThreeSecondsScore")
    )
    retention_risk = _first_score(
        body, ("retentionRisk", "retentionRiskScore", "dropoffRisk")
    )
    warnings: list[str] = []
    if score is None:
        warnings.append("virality_score_missing")
    elif score < MIN_VIRALITY_SCORE:
        warnings.append("virality_score_low")
    if hook_score is not None and hook_score < MIN_HOOK_SCORE:
        warnings.append("virality_hook_score_low")
    if retention_risk is not None and retention_risk > MAX_RETENTION_RISK:
        warnings.append("virality_retention_risk_high")
    status = "failed" if required and warnings else ("warn" if warnings else "passed")
    return {
        "schema": "reel_factory.virality_qc.v1",
        "status": status,
        "required": bool(required),
        "reportPresent": True,
        "provider": body.get("provider") or report.get("provider"),
        "model": body.get("model") or report.get("model"),
        "modelBacked": body.get("modelBacked")
        if "modelBacked" in body
        else report.get("modelBacked"),
        "reportId": body.get("reportId")
        or body.get("report_id")
        or report.get("reportId")
        or report.get("report_id"),
        "score": score,
        "hookScore": hook_score,
        "retentionRisk": retention_risk,
        "thresholds": thresholds(),
        "warnings": warnings,
    }


def thresholds() -> dict[str, float]:
    return {
        "minViralityScore": MIN_VIRALITY_SCORE,
        "minHookScore": MIN_HOOK_SCORE,
        "maxRetentionRisk": MAX_RETENTION_RISK,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_virality_report(output_path: Path) -> dict[str, Any] | None:
    candidates = (
        output_path.with_suffix(output_path.suffix + ".virality_report.json"),
        output_path.with_suffix(output_path.suffix + ".virality.json"),
        output_path.with_suffix(".virality_report.json"),
        output_path.with_suffix(".virality.json"),
        output_path.parent / f"{output_path.stem}.virality_report.json",
        output_path.parent / f"{output_path.stem}.virality.json",
    )
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload is not None:
            return payload

    aggregate = _read_json(output_path.parent / "_virality_qc.json")
    if not aggregate:
        return None
    for row in aggregate.get("records") or []:
        if isinstance(row, dict) and row.get("filename") == output_path.name:
            return row
    return None


def evaluate_output_virality(
    output_path: Path, *, required: bool = False
) -> dict[str, Any] | None:
    report = load_virality_report(output_path)
    if report is None and not required:
        return None
    return evaluate_virality_report(report, required=required)
