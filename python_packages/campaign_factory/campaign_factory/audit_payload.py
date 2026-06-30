from __future__ import annotations

from pathlib import Path
from typing import Any

from .persistence import json_load


def audit_report(self, audit_report_id: str) -> dict[str, Any]:
    row = self.conn.execute(
        "SELECT * FROM audit_reports WHERE id = ?", (audit_report_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"audit report not found: {audit_report_id}")
    row_dict = dict(row)
    report = self._audit_report_payload(row_dict)
    report["id"] = audit_report_id
    path = Path(row_dict["report_path"])
    if path.exists():
        raw = json_load(path.read_text(encoding="utf-8"), {})
        if isinstance(raw, dict):
            raw["id"] = audit_report_id
            raw["database"] = report
            return raw
    return report


def _audit_report_payload(self, row: dict[str, Any]) -> dict[str, Any]:
    report = {
        "id": row["id"],
        "contentForgeRunId": row["contentforge_run_id"],
        "reportPath": row["report_path"],
        "score": row["score"],
        "status": row["status"],
        "layers": json_load(row["layers_json"], {}),
        "verdicts": json_load(row["verdicts_json"], {}),
        "overallVerdict": row["overall_verdict"],
        "filesAnalyzed": row["files_analyzed"],
        "failedChecks": json_load(row["failed_checks_json"], []),
        "warnings": json_load(row["warnings_json"], []),
        "createdAt": row["created_at"],
        "readinessSummary": None,
    }
    path = Path(row["report_path"])
    if path.exists():
        payload = json_load(path.read_text(encoding="utf-8"), {})
        if isinstance(payload, dict):
            report["readinessSummary"] = payload.get("readinessSummary")
            report["contractVersion"] = payload.get("contractVersion")
            report["auditProfile"] = payload.get("auditProfile")
            report["targetFile"] = payload.get("targetFile")
            report["verdictCodes"] = payload.get("verdictCodes") or {}
            report["ocr"] = payload.get("ocr")
            report["captionBoxes"] = payload.get("captionBoxes") or []
            report["safeZoneScore"] = payload.get("safeZoneScore")
            report["readabilityScore"] = payload.get("readabilityScore")
            report["hookVisibilityScore"] = payload.get("hookVisibilityScore")
            report["safeZone"] = payload.get("safeZone")
            report["readability"] = payload.get("readability")
            report["hookVisibility"] = payload.get("hookVisibility")
            report["creativeQuality"] = payload.get("creativeQuality")
            report["timings"] = payload.get("timings")
            report["error"] = payload.get("error")
    return report
