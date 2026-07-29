"""Result aggregation for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _motion_stage_result(generation_result: dict[str, Any]) -> dict[str, Any]:
    nested = generation_result.get("result")
    if isinstance(nested, dict) and (
        nested.get("schema") == "campaign_factory.motion_generation_stage_run.v1"
        or "registeredAsset" in nested
    ):
        return nested
    return generation_result


def probe_production_video(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe_missing")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("production_video_ffprobe_failed")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        video = next(
            stream
            for stream in streams
            if int(stream.get("width") or 0) > 0 and int(stream.get("height") or 0) > 0
        )
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
        raise RuntimeError("production_video_ffprobe_invalid") from exc
    return {
        "codec": str(video.get("codec_name") or ""),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "durationSeconds": round(duration, 3),
    }


def provider_execution(
    generation_result: Mapping[str, Any],
) -> dict[str, Any] | None:
    stage = _motion_stage_result(dict(generation_result))
    worker = stage.get("worker")
    worker = worker if isinstance(worker, dict) else {}
    execution = worker.get("result")
    if not isinstance(execution, dict) or not execution.get("predictionId"):
        return None
    return provider_receipt_summary(execution)


def provider_receipt_summary(
    execution: Mapping[str, Any], *, evidence_path: Path | None = None
) -> dict[str, Any]:
    return {
        "requestId": execution.get("predictionId"),
        "model": execution.get("providerModel"),
        "status": execution.get("status"),
        "submittedAt": execution.get("submittedAt"),
        "completedAt": execution.get("completedAt"),
        "outputUrl": execution.get("outputUrl"),
        "outputSha256": execution.get("outputSha256"),
        "outputRecords": execution.get("outputRecords") or [],
        "generationDurationSeconds": execution.get("generationDurationSeconds"),
        "providerInferenceMilliseconds": execution.get("providerInferenceMilliseconds"),
        "providerCostUsd": execution.get("providerCostUsd"),
        "requestFingerprint": execution.get("requestFingerprint"),
        "evidencePath": execution.get("evidencePath")
        or (str(evidence_path) if evidence_path is not None else None),
    }


def failed_provider_execution(
    factory: Any, job: Mapping[str, Any]
) -> dict[str, Any] | None:
    try:
        review_root_value = str(job.get("providerReviewRoot") or "").strip()
        if review_root_value:
            receipt_dir = Path(review_root_value).expanduser().resolve() / "receipts"
            higgsfield_matches: list[dict[str, Any]] = []
            for path in receipt_dir.glob("*.higgsfield_submission.json"):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    receipt = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(receipt, dict) and receipt.get(
                    "requestFingerprint"
                ) == job.get("providerPlanFingerprint"):
                    higgsfield_matches.append(receipt)
            if len(higgsfield_matches) == 1:
                receipt = higgsfield_matches[0]
                final = receipt.get("finalOutput")
                final = final if isinstance(final, dict) else {}
                return {
                    "requestId": receipt.get("generationId"),
                    "model": receipt.get("model"),
                    "status": receipt.get("status"),
                    "submittedAt": receipt.get("submittedAt"),
                    "completedAt": receipt.get("completedAt"),
                    "outputSha256": final.get("sha256"),
                    "generationDurationSeconds": receipt.get(
                        "generationDurationSeconds"
                    ),
                    "providerCostCredits": receipt.get("creditsConsumed"),
                    "requestFingerprint": receipt.get("requestFingerprint"),
                    "evidencePath": receipt.get("evidencePath"),
                }
        campaign = factory.domains.campaign_by_slug(str(job["campaign"]))
        model_slug = factory.domains.reel_execution.model_slug_for_campaign(
            campaign["id"]
        )
        evidence_dir = (
            factory.domains.campaign_dirs(model_slug, campaign["slug"])["audits"]
            / "motion_generation"
        )
        prompt_sha = hashlib.sha256(
            " ".join(str(job["prompt"]).split()).encode("utf-8")
        ).hexdigest()
        stages = list(job["productionRecipe"].get("stages") or [])
        expected_provider_model = (
            str(stages[0].get("providerModel") or "") if stages else ""
        )
        wavespeed_matches: list[tuple[dict[str, Any], Path]] = []
        for path in evidence_dir.glob("*.wavespeed_submission.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(receipt, dict):
                continue
            if (
                receipt.get("creator") == job.get("creator")
                and receipt.get("intent") == job.get("intent")
                and receipt.get("sourceSha256") == job.get("sourceSha256")
                and receipt.get("expandedPromptSha256") == prompt_sha
                and receipt.get("providerModel") == expected_provider_model
                and (
                    receipt.get("requestIdentitySeed") == job.get("seed")
                    or receipt.get("seed") == job.get("seed")
                )
                and receipt.get("predictionId")
            ):
                wavespeed_matches.append((receipt, path))
        if len(wavespeed_matches) != 1:
            return None
        receipt, path = wavespeed_matches[0]
        return provider_receipt_summary(receipt, evidence_path=path)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None


def run_production_hard_qc(
    *, job: Mapping[str, Any], generation_result: dict[str, Any]
) -> dict[str, Any]:
    blockers: list[str] = []
    source_path = Path(str(job["sourcePath"])).expanduser().resolve()
    if (
        source_path.is_symlink()
        or not source_path.is_file()
        or _sha256_file(source_path) != job["sourceSha256"]
    ):
        blockers.append("source_substitution")
    stage = _motion_stage_result(generation_result)
    registered = stage.get("registeredAsset")
    if not isinstance(registered, dict):
        blockers.append("unreadable_or_corrupt_media")
        return _hard_qc_receipt(job, blockers=blockers, output_sha256=None, probe=None)
    output = Path(str(registered.get("output_path") or "")).expanduser()
    output_sha: str | None = None
    probe: dict[str, Any] | None = None
    if output.is_symlink() or not output.resolve().is_file():
        blockers.append("unreadable_or_corrupt_media")
    else:
        output = output.resolve()
        try:
            output_sha = _sha256_file(output)
            if output_sha != str(registered.get("content_hash") or ""):
                blockers.append("source_substitution")
            probe = probe_production_video(output)
            if probe["durationSeconds"] <= 0 or probe["durationSeconds"] > 60:
                blockers.append("invalid_duration_or_codec")
            if probe["codec"] not in {"h264", "hevc", "av1", "vp9"}:
                blockers.append("invalid_duration_or_codec")
            ratio = probe["width"] / probe["height"]
            if not 0.50 <= ratio <= 0.65:
                blockers.append("invalid_duration_or_codec")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            blockers.append("unreadable_or_corrupt_media")
    provider = provider_execution(generation_result)
    if provider is not None:
        stages = list(job["productionRecipe"].get("stages") or [])
        expected_model = str(stages[-1].get("providerModel") or "") if stages else None
        if (
            provider.get("model") != expected_model
            or provider.get("outputSha256") != output_sha
            or provider.get("requestFingerprint") is None
        ):
            blockers.append("source_substitution")
    return _hard_qc_receipt(
        job, blockers=blockers, output_sha256=output_sha, probe=probe
    )


def _hard_qc_receipt(
    job: Mapping[str, Any],
    *,
    blockers: list[str],
    output_sha256: str | None,
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    unique_blockers = sorted(set(blockers))
    receipt = {
        "schema": "campaign_factory.production_hard_qc.v1",
        "jobId": job["jobId"],
        "sourceSha256": job["sourceSha256"],
        "outputSha256": output_sha256,
        "checks": {
            "sourceBinding": "failed"
            if "source_substitution" in unique_blockers
            else "passed",
            "mediaIntegrity": (
                "failed"
                if {
                    "unreadable_or_corrupt_media",
                    "invalid_duration_or_codec",
                }.intersection(unique_blockers)
                else "passed"
            ),
            "identityAndAnatomy": "not_reported_by_available_analyzers",
        },
        "probe": probe,
        "blockers": unique_blockers,
        "status": "blocked" if unique_blockers else "passed",
    }
    return {**receipt, "receiptFingerprint": _fingerprint(receipt)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def block_duplicate_provider_outputs(results: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for item in results:
        provider = item.get("provider")
        digest = (
            str(provider.get("outputSha256") or "")
            if isinstance(provider, dict)
            else ""
        )
        if not digest:
            continue
        if digest in seen:
            item["status"] = "blocked"
            item["error"] = "duplicate_provider_output"
            hard_qc = item.get("hardQc")
            if isinstance(hard_qc, dict):
                hard_qc["blockers"] = sorted(
                    set(hard_qc.get("blockers") or []).union({"duplicate_output"})
                )
                hard_qc["status"] = "blocked"
                unsigned = {
                    key: value
                    for key, value in hard_qc.items()
                    if key != "receiptFingerprint"
                }
                hard_qc["receiptFingerprint"] = _fingerprint(unsigned)
        else:
            seen.add(digest)


def finalize_production_batch(
    plan: dict[str, Any], results: list[dict[str, Any]], *, apply: bool
) -> dict[str, Any]:
    public_plan = {
        **plan,
        "jobs": [
            {key: value for key, value in job.items() if not str(key).startswith("_")}
            for job in plan["jobs"]
        ],
    }
    statuses = [str(item.get("status") or "") for item in results]
    final_provider_rows = [
        item["provider"] for item in results if isinstance(item.get("provider"), dict)
    ]
    provider_rows: list[dict[str, Any]] = []
    for item in results:
        item_providers = item.get("providers")
        if isinstance(item_providers, list):
            provider_rows.extend(
                provider for provider in item_providers if isinstance(provider, dict)
            )
        elif isinstance(item.get("provider"), dict):
            provider_rows.append(item["provider"])
    submitted_provider_rows = [
        provider for provider in provider_rows if provider.get("reconciled") is not True
    ]
    submitted_final_rows = [
        provider
        for provider in final_provider_rows
        if provider.get("reconciled") is not True
    ]
    raw_hashes = {
        str(provider.get("outputSha256"))
        for provider in final_provider_rows
        if provider.get("outputSha256")
    }
    final_hashes = {
        digest
        for item in results
        if item.get("status") == "completed"
        and (
            digest := str(
                ((item.get("result") or {}).get("audioFulfillment") or {}).get(
                    "finalVideoSha256"
                )
                or (
                    _motion_stage_result(item.get("result") or {}).get(
                        "registeredAsset"
                    )
                    or {}
                ).get("content_hash")
                or ""
            )
        )
    }
    costs = [provider.get("providerCostCredits") for provider in provider_rows]
    costs_reported = bool(provider_rows) and all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in costs
    )
    numeric_costs = [
        float(value)
        for value in costs
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    summary: dict[str, Any] = {
        "requested": plan["requested"],
        "created": len(results),
        "submitted": len(submitted_provider_rows),
        "jobsSubmitted": len(submitted_final_rows),
        "completed": statuses.count("completed"),
        "blocked": statuses.count("blocked"),
        "failed": statuses.count("failed"),
        "approved": statuses.count("completed"),
        "scheduled": 0,
        "published": 0,
        "uniqueOutputs": len(raw_hashes or final_hashes),
        "uniqueFinalOutputs": len(final_hashes),
        "totalProviderCredits": (
            round(sum(numeric_costs), 4) if costs_reported else None
        ),
        "providerCreditsReported": costs_reported,
        "quotedProviderCredits": plan["quotedProviderCredits"],
        "generationTimesSeconds": [
            provider.get("generationDurationSeconds") for provider in provider_rows
        ],
    }
    reconciled_count = sum(
        provider.get("reconciled") is True for provider in provider_rows
    )
    if reconciled_count:
        summary["reconciledCompletedRequests"] = reconciled_count
    return {
        **public_plan,
        "apply": apply,
        "results": results,
        "summary": summary,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
