"""Result aggregation for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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
    return {
        **public_plan,
        "apply": apply,
        "results": results,
        "summary": {
            "requested": plan["requested"],
            "created": len(results),
            "submitted": len(provider_rows),
            "jobsSubmitted": len(final_provider_rows),
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
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }
