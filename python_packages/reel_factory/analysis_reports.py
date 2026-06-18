#!/usr/bin/env python3
"""Default-off report request and operator sidecar helpers for reel outputs."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_REPORTS = ("virality", "video_analysis")
REQUEST_SCHEMA = "reel_factory.analysis_report_requests.v1"
REPORT_SCHEMA = "reel_factory.analysis_reports.v1"


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sidecar_paths(output_path: Path) -> dict[str, Path]:
    return {
        "virality": output_path.with_suffix(output_path.suffix + ".virality_report.json"),
        "video_analysis": output_path.with_suffix(output_path.suffix + ".video_analysis.json"),
    }


def _valid_reports(reports: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for report in reports:
        if report not in DEFAULT_REPORTS:
            raise ValueError(f"report must be one of {sorted(DEFAULT_REPORTS)}")
        if report not in out:
            out.append(report)
    return tuple(out)


def _find_outputs(root: Path, *, clip: str | None = None, output_path: Path | None = None) -> list[Path]:
    if output_path is not None:
        output = output_path.expanduser()
        if not output.exists():
            raise FileNotFoundError(f"output file not found: {output}")
        return [output]

    proc = root / "02_processed"
    clip_dirs = [proc / clip] if clip else [path for path in sorted(proc.iterdir()) if path.is_dir() and not path.name.startswith("_")]
    outputs: list[Path] = []
    for clip_dir in clip_dirs:
        if not clip_dir.exists():
            continue
        outputs.extend(path for path in sorted(clip_dir.glob("*.mp4")) if "_audio_" not in path.stem)
    if not outputs:
        target = clip or "all clips"
        raise FileNotFoundError(f"no reel outputs found for {target} under {proc}")
    return outputs


def _manifest_path(output_path: Path) -> Path:
    return output_path.parent / "_analysis_report_requests.json"


def _report_record(output_path: Path, reports: Sequence[str], *, status: str) -> dict[str, Any]:
    sidecars = _sidecar_paths(output_path)
    return {
        "outputPath": str(output_path),
        "filename": output_path.name,
        "status": status,
        "requestedReports": list(reports),
        "sidecars": {report: str(sidecars[report]) for report in reports},
        "estimatedCostUsd": 0,
        "humanReviewRequired": True,
    }


def _write_request_manifest(records: list[dict[str, Any]], *, provider_calls: int) -> None:
    by_dir: dict[Path, list[dict[str, Any]]] = {}
    for record in records:
        by_dir.setdefault(Path(str(record["outputPath"])).parent, []).append(record)
    for directory, directory_records in by_dir.items():
        payload = {
            "schema": REQUEST_SCHEMA,
            "generatedAt": int(time.time()),
            "providerCalls": provider_calls,
            "estimatedCostUsd": 0,
            "records": directory_records,
        }
        _manifest_path(Path(str(directory_records[0]["outputPath"]))).write_text(_json_dumps(payload), encoding="utf-8")


def _normalize_virality_report(report: dict[str, Any], *, provider: str) -> dict[str, Any]:
    return {
        **report,
        "schema": "reel_factory.virality_report.v1",
        "provider": report.get("provider") or provider,
        "model": report.get("model") or "virality_predictor",
        "modelBacked": report.get("modelBacked", provider != "operator"),
        "reportId": report.get("reportId") or report.get("report_id") or f"virality_{time.time_ns()}",
    }


def _normalize_video_analysis_report(report: dict[str, Any], *, output_path: Path, provider: str) -> dict[str, Any]:
    features = report.get("winnerDnaFeatures")
    if not isinstance(features, dict):
        features = report.get("winner_dna_features") if isinstance(report.get("winner_dna_features"), dict) else {}
    scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    pattern_card = report.get("patternCard") if isinstance(report.get("patternCard"), dict) else {}
    pattern_card = {
        "schema": "reference_factory.pattern_card.v1",
        "id": pattern_card.get("id") or f"pattern_{output_path.stem}",
        "sourceReferenceId": pattern_card.get("sourceReferenceId") or output_path.stem,
        "platform": pattern_card.get("platform") or "instagram",
        "formatType": pattern_card.get("formatType") or features.get("camera") or "unknown",
        "hookType": pattern_card.get("hookType") or features.get("hook_type") or "unknown",
        **pattern_card,
    }
    return {
        **report,
        "schema": "reference_factory.video_analysis.v1",
        "id": report.get("id") or f"analysis_{output_path.stem}",
        "referenceId": report.get("referenceId") or output_path.stem,
        "provider": report.get("provider") or provider,
        "model": report.get("model") or "video_analysis",
        "status": report.get("status") or "pattern_ready",
        "media": report.get("media") if isinstance(report.get("media"), dict) else {"path": str(output_path)},
        "signals": report.get("signals") if isinstance(report.get("signals"), dict) else {"scores": scores},
        "scores": scores,
        "winnerDnaFeatures": features,
        "patternCard": pattern_card,
    }


def write_operator_reports(
    output_path: Path,
    *,
    virality: dict[str, Any] | None = None,
    video_analysis: dict[str, Any] | None = None,
    provider: str = "operator",
) -> dict[str, Any]:
    """Write operator/configured-provider reports in the sidecar format existing QC reads."""
    output = Path(output_path).expanduser()
    if not output.exists():
        raise FileNotFoundError(f"output file not found: {output}")

    sidecars = _sidecar_paths(output)
    written: list[str] = []
    if virality is not None:
        payload = _normalize_virality_report(virality, provider=provider)
        sidecars["virality"].write_text(_json_dumps(payload), encoding="utf-8")
        written.append("virality")
    if video_analysis is not None:
        payload = _normalize_video_analysis_report(video_analysis, output_path=output, provider=provider)
        sidecars["video_analysis"].write_text(_json_dumps(payload), encoding="utf-8")
        written.append("video_analysis")

    return {
        "schema": REPORT_SCHEMA,
        "outputPath": str(output),
        "writtenReports": written,
        "sidecars": {key: str(path) for key, path in sidecars.items() if key in written},
        "provider": provider,
        "providerCalls": 0,
        "estimatedCostUsd": 0,
    }


def _run_provider_command(
    provider_command: str,
    *,
    output_path: Path,
    report: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    cmd = [*shlex.split(provider_command), "--output", str(output_path), "--report", report]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"provider command failed for {output_path.name} {report}: {completed.stderr.strip()}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"provider command returned invalid JSON for {output_path.name} {report}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"provider command returned non-object JSON for {output_path.name} {report}")
    return payload


def request_analysis_reports(
    root: Path,
    *,
    clip: str | None = None,
    output_path: Path | None = None,
    reports: Sequence[str] = DEFAULT_REPORTS,
    provider_command: str | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Create zero-cost operator requests, or run an explicit configured provider command."""
    root = Path(root).expanduser().resolve()
    selected_reports = _valid_reports(reports)
    outputs = _find_outputs(root, clip=clip, output_path=output_path)
    records: list[dict[str, Any]] = []
    provider_calls = 0

    for output in outputs:
        if provider_command is None:
            records.append(_report_record(output, selected_reports, status="operator_input_required"))
            continue

        generated: dict[str, dict[str, Any]] = {}
        for report in selected_reports:
            provider_calls += 1
            generated[report] = _run_provider_command(
                provider_command,
                output_path=output,
                report=report,
                timeout_seconds=timeout_seconds,
            )
        write_operator_reports(
            output,
            virality=generated.get("virality"),
            video_analysis=generated.get("video_analysis"),
            provider="configured_provider_command",
        )
        records.append(_report_record(output, selected_reports, status="generated"))

    _write_request_manifest(records, provider_calls=provider_calls)
    return {
        "schema": REQUEST_SCHEMA,
        "generatedAt": int(time.time()),
        "providerCalls": provider_calls,
        "estimatedCostUsd": 0,
        "records": records,
    }


def _load_optional_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return _read_json(Path(path).expanduser())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Request or write default-off reel analysis report sidecars.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--clip")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="append", choices=DEFAULT_REPORTS)
    parser.add_argument("--provider-command")
    parser.add_argument("--operator-virality-json")
    parser.add_argument("--operator-video-analysis-json")
    args = parser.parse_args(argv)

    if args.operator_virality_json or args.operator_video_analysis_json:
        if not args.output:
            parser.error("--output is required when writing operator report JSON")
        result = write_operator_reports(
            args.output,
            virality=_load_optional_json(args.operator_virality_json),
            video_analysis=_load_optional_json(args.operator_video_analysis_json),
            provider="operator",
        )
    else:
        result = request_analysis_reports(
            args.root,
            clip=args.clip,
            output_path=args.output,
            reports=tuple(args.report or DEFAULT_REPORTS),
            provider_command=args.provider_command,
        )
    print(_json_dumps(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
