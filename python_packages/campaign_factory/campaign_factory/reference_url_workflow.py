"""Campaign orchestration for reference URL intake and structural analysis."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from reel_factory.worker_api import (
    canonicalize_reel_url,
    download_reel_url,
    gemini_motion_analysis_instruction,
)

from pipeline_contracts import validate_reference_video_motion_analysis

from .recreation_modes import plan_recreation
from .recreation_prompting import build_openai_prompt_pack
from .reference_audio_intake import (
    inspect_reference_audio,
    load_reference_audio_occurrence,
)


def run_reference_analysis(
    factory: Any,
    *,
    creator: str,
    reference_url: str | None,
    reference_video_path: Path | None,
    reference_platform: str | None,
    reference_authorized: bool,
    declared_talking: bool,
    declared_non_talking: bool = False,
    operator_classification: str | None = None,
    operator_warnings: list[str] | None = None,
    recreate_mode: str = "auto",
    through: str | None = "analyze",
    audio_policy: str = "auto",
    max_credits: float | None = None,
    creator_image_path: Path | None = None,
    apply: bool,
) -> dict[str, Any]:
    if apply and not reference_authorized:
        raise ValueError("--apply reference intake requires --reference-authorized")
    if declared_talking and declared_non_talking:
        raise ValueError("reference cannot be both talking and non-talking")
    if bool(reference_url) == bool(reference_video_path):
        raise ValueError("provide exactly one of --reference-url or --reference-video")
    with tempfile.TemporaryDirectory(prefix="creator-os-url-intake-") as raw_tmp:
        staging = Path(raw_tmp)
        os.chmod(staging, 0o700)
        if reference_url:
            identity = canonicalize_reel_url(reference_url)
            stem = _safe_stem(
                str(
                    identity.get("nativeMediaId")
                    or hashlib.sha256(reference_url.encode()).hexdigest()[:20]
                )
            )
            try:
                download = download_reel_url(reference_url, out_dir=staging, stem=stem)
            except Exception as exc:
                receipt_path = _record_failure(
                    factory.settings.reference_reels_root,
                    identity=identity,
                    error=exc,
                    apply=apply,
                )
                suffix = f"; sanitized receipt: {receipt_path}" if receipt_path else ""
                raise RuntimeError(
                    f"reference URL download failed; use --reference-video fallback{suffix}"
                ) from None
            source = Path(str(download["path"]))
            source_metrics = download.get("sourceMetrics")
            source_metrics = source_metrics if isinstance(source_metrics, dict) else {}
            metadata = {
                **identity,
                **source_metrics,
                "platform": download.get("platform") or identity["platform"],
                "nativeMediaId": download.get("nativeMediaId")
                or identity["nativeMediaId"],
                "originalUrl": download.get("originalUrl") or identity["originalUrl"],
                "canonicalUrl": download.get("canonicalUrl")
                or identity["canonicalUrl"],
                "extractor": download.get("extractor"),
                "extractorVersion": download.get("extractorVersion"),
                "redirectSummary": download.get("redirectSummary"),
                "cookieFallbackUsed": download.get("cookieFallbackUsed"),
                "downloadedSha256": download.get("downloadedSha256"),
            }
            metadata["caption"] = metadata.get("description")
            download_evidence = {
                "status": "downloaded",
                "authenticatedAccessUsed": bool(download.get("cookieFallbackUsed")),
                "command": download.get("command"),
                "downloadedSha256": download.get("downloadedSha256"),
                "metadata": _public_metadata(metadata),
            }
        else:
            source = Path(str(reference_video_path)).expanduser().resolve()
            if source.is_symlink() or not source.is_file():
                raise ValueError("--reference-video must be a regular local file")
            source_sha = _sha256(source)
            metadata = {
                "platform": reference_platform or "private_reference",
                "nativeMediaId": source_sha[:20],
                "originalUrl": None,
                "canonicalUrl": None,
                "extractor": "local_file",
                "extractorVersion": None,
                "downloadedSha256": source_sha,
            }
            download_evidence = {
                "status": "local_file",
                "authenticatedAccessUsed": False,
                "command": [],
                "downloadedSha256": source_sha,
                "metadata": _public_metadata(metadata),
            }
        metadata_path = staging / "reference_metadata.json"
        metadata["declaredTalking"] = bool(
            declared_talking or operator_classification in {"talking", "lip_sync"}
        )
        metadata["declaredNonTalking"] = bool(declared_non_talking)
        if operator_classification:
            metadata["operatorClassification"] = operator_classification
        if operator_warnings:
            metadata["operatorWarnings"] = sorted(set(operator_warnings))
        atomic_write_text(
            metadata_path, json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(metadata_path, 0o600)
        reference = _run_reference_factory(
            source=source,
            metadata_path=metadata_path,
            data_root=factory.settings.reference_reels_root,
            db_path=factory.settings.reference_factory_db,
            apply=apply,
        )
        structural_analysis = _analyze_reference_structure(
            source=source,
            reference_id=str(reference["referenceId"]),
            overlay_inventory=dict(reference.get("overlayTextInventory") or {}),
        )
        reference["structuralMotionAnalysis"] = structural_analysis
        persisted_path = (reference.get("source") or {}).get("path")
        audio_source = Path(str(persisted_path)) if persisted_path else source
        reference_id = str(reference["referenceId"])
        audio = (
            load_reference_audio_occurrence(factory.conn, reference_id)
            if str(reference.get("duplicateResult") or "").startswith("reused_")
            else None
        )
        if audio is None:
            audio = inspect_reference_audio(
                factory.conn,
                source_video=audio_source,
                reference_id=reference_id,
                metadata=metadata,
                artifact_root=factory.settings.campaigns_dir.parent,
                apply=apply,
                declared_talking=bool(metadata["declaredTalking"]),
                dance_or_synchronized=bool(
                    operator_classification == "dance"
                    or audio_policy == "reference_audio_required"
                ),
            )
        result = {
            "ok": True,
            "schema": "campaign_factory.reference_url_analysis.v1",
            "creator": creator,
            "intent": "recreate_reel",
            "through": through or "plan",
            "apply": apply,
            "providerCalls": int(structural_analysis.get("providerCalls") or 0),
            "paidSpend": 0,
            "analysisProviderCalls": int(structural_analysis.get("providerCalls") or 0),
            "analysisCost": structural_analysis.get("cost"),
            "download": download_evidence,
            "reference": reference,
            "audio": audio,
            "proposedMutations": [
                *list(reference.get("proposedMutations") or []),
                *list(audio.get("proposedMutations") or []),
            ],
        }
        if through != "analyze":
            if creator_image_path is None:
                raise ValueError(
                    "--creator-image is required for prompt-driven recreation"
                )
            prompt_pack = build_openai_prompt_pack(
                creator=creator,
                creator_image=creator_image_path,
                intent="recreate_reel",
                reference_video=source,
                external_call_authorized=apply,
            )
            prompt_cache = prompt_pack.get("cache") or {}
            prompt_call_made = prompt_cache.get("providerCallMade") is True
            prompt_planning = prompt_pack.get("promptPlanning") or {}
            prompt_cost = prompt_planning.get("cost") or {
                "status": "not_exposed",
                "usd": None,
            }
            if not prompt_call_made:
                prompt_cost = {"status": "cache_hit", "usd": 0.0}
            result["promptProviderCalls"] = int(prompt_call_made)
            result["providerCalls"] += int(prompt_call_made)
            result["promptPack"] = prompt_pack
            result["promptPlanning"] = prompt_planning
            result["promptSpend"] = prompt_cost
            result["recreation"] = plan_recreation(
                creator=creator,
                source_video=source,
                intake=result,
                requested_mode=recreate_mode,
                audio_policy=audio_policy,
                through=through,
                max_credits=max_credits,
                prompt_pack=prompt_pack,
            )
            result["providerQuoteCalls"] = int(
                _quote_provider_calls(result["recreation"])
            )
            result["providerCalls"] = int(
                structural_analysis.get("providerCalls") or 0
            ) + int(prompt_call_made)
            result["paidSpend"] = prompt_cost.get("usd")
            result["paidSpendStatus"] = prompt_cost.get("status")
            if apply:
                prompt_path = (
                    factory.settings.reference_reels_root
                    / "prompt_packs"
                    / f"{reference_id}.json"
                )
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(prompt_path.parent, 0o700)
                atomic_write_text(
                    prompt_path,
                    json.dumps(prompt_pack, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.chmod(prompt_path, 0o600)
                result["promptPackPath"] = str(prompt_path)
                result["applyStatus"] = "ANALYSIS_PERSISTED_ANCHOR_REVIEW_REQUIRED"
                result["paidExecutionBlocked"] = True
        return result


def _run_reference_factory(
    *,
    source: Path,
    metadata_path: Path,
    data_root: Path,
    db_path: Path,
    apply: bool,
) -> dict[str, Any]:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required for Reference Factory URL intake")
    cmd = [
        uv,
        "run",
        "--package",
        "reference-factory",
        "python",
        "-m",
        "reference_factory.url_intake",
        "--source",
        str(source),
        "--metadata",
        str(metadata_path),
        "--data-root",
        str(data_root),
        "--db",
        str(db_path),
    ]
    if apply:
        cmd.append("--apply")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=_source_root())
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout or "Reference Factory intake failed")[
                -3000:
            ]
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Reference Factory intake returned invalid JSON") from exc


def _analyze_reference_structure(
    *,
    source: Path,
    reference_id: str,
    overlay_inventory: dict[str, Any],
) -> dict[str, Any]:
    gemini = shutil.which("gemini")
    if not gemini:
        return {
            "status": "unavailable",
            "reason": "gemini_cli_unavailable",
            "providerCalls": 0,
            "cost": None,
        }
    instruction = gemini_motion_analysis_instruction(reference_id)
    prompt = f"@{{{source}}} {instruction}"
    completed = subprocess.run(
        [
            gemini,
            "--approval-mode",
            "plan",
            "--output-format",
            "json",
            "--include-directories",
            str(source.parent),
            "--prompt",
            prompt,
        ],
        capture_output=True,
        text=True,
        cwd=source.parent,
        timeout=300,
    )
    if completed.returncode != 0:
        return {
            "status": "unavailable",
            "reason": "gemini_cli_analysis_failed",
            "providerCalls": 1,
            "cost": "not_exposed_by_cli",
        }
    try:
        response = json.loads(completed.stdout)
        analysis = _json_object(str(response.get("response") or ""))
        validate_reference_video_motion_analysis(analysis)
        if analysis["referenceId"] != reference_id:
            raise ValueError("reference identity mismatch")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {
            "status": "unavailable",
            "reason": "gemini_cli_analysis_invalid",
            "providerCalls": 1,
            "cost": "not_exposed_by_cli",
        }
    return {
        "status": "ready",
        "providerCalls": 1,
        "cost": "not_exposed_by_cli",
        "analysis": analysis,
        "overlayTextInventory": overlay_inventory,
        "overlayTextExcludedFromGenerationPrompt": True,
    }


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Gemini analysis must be a JSON object")
    return value


def _source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_stem(value: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "._-")[:80]
    return cleaned or "reference"


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "platform",
        "nativeMediaId",
        "canonicalUrl",
        "extractor",
        "extractorVersion",
        "uploader",
        "uploader_id",
        "caption",
        "upload_date",
        "timestamp",
        "view_count",
        "like_count",
        "comment_count",
        "repost_count",
        "duration",
        "width",
        "height",
        "fps",
        "vcodec",
        "acodec",
        "redirectSummary",
        "operatorClassification",
        "operatorWarnings",
    }
    return {key: metadata[key] for key in sorted(keys) if metadata.get(key) is not None}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_failure(
    data_root: Path,
    *,
    identity: dict[str, Any],
    error: Exception,
    apply: bool,
) -> Path | None:
    if not apply:
        return None
    failure_id = hashlib.sha256(
        str(identity.get("canonicalUrl") or "").encode()
    ).hexdigest()[:20]
    root = data_root / "url_intake" / "failures"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = root / f"failure_{failure_id}.json"
    atomic_write_text(
        path,
        json.dumps(
            {
                "schema": "campaign_factory.reference_url_failure.v1",
                "platform": identity.get("platform"),
                "nativeMediaId": identity.get("nativeMediaId"),
                "canonicalUrl": identity.get("canonicalUrl"),
                "errorType": type(error).__name__,
                "credentialsIncluded": False,
                "partialMediaRetained": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


def _quote_provider_calls(recreation: Any) -> int:
    if not isinstance(recreation, dict):
        return 0
    quote = recreation.get("quote")
    return int(quote.get("quoteCalls") or 0) if isinstance(quote, dict) else 0
