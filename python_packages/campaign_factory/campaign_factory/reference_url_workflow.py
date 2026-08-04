"""Campaign orchestration for reference URL intake and structural analysis."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from creator_os_core.provider_spend import (
    build_paid_action_quote,
    build_paid_action_spend_scope,
)
from reel_factory.worker_api import (
    canonicalize_reel_url,
    download_reel_url,
    gemini_motion_analysis_instruction,
)

from pipeline_contracts import validate_reference_video_motion_analysis

from .all_provider_cost import (
    begin_paid_action_attempt,
    budget_limits_from_env,
    issue_paid_action_authorization,
    reconcile_paid_action_cost,
)
from .production_source_selection import resolve_reference_analysis_governance
from .recreation_lifecycle import generate_recreation_anchor
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
    recreation_attempt_id: str | None = None,
    apply: bool,
) -> dict[str, Any]:
    if apply and not reference_authorized:
        raise ValueError("--apply reference intake requires --reference-authorized")
    if declared_talking and declared_non_talking:
        raise ValueError("reference cannot be both talking and non-talking")
    if bool(reference_url) == bool(reference_video_path):
        raise ValueError("provide exactly one of --reference-url or --reference-video")
    governance_context = resolve_reference_analysis_governance(factory, creator)
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
        persisted_path = (reference.get("source") or {}).get("path")
        reference_source = Path(str(persisted_path)) if persisted_path else source
        reference_source_sha256 = _sha256(reference_source)
        provider_rights = (
            _require_reference_provider_rights(
                db_path=factory.settings.reference_factory_db,
                reference_id=str(reference["referenceId"]),
                provider="gemini",
                operation="reference_analysis",
                source_sha256=reference_source_sha256,
            )
            if apply
            else None
        )
        recreation_provider_rights = (
            _require_reference_provider_rights(
                db_path=factory.settings.reference_factory_db,
                reference_id=str(reference["referenceId"]),
                provider="higgsfield",
                operation="recreation_generation",
                source_sha256=reference_source_sha256,
            )
            if apply and through != "analyze"
            else None
        )
        structural_analysis = _analyze_reference_structure(
            factory=factory,
            source=source,
            reference_id=str(reference["referenceId"]),
            overlay_inventory=dict(reference.get("overlayTextInventory") or {}),
            governance_context=governance_context,
            provider_rights=provider_rights,
            apply=apply,
        )
        reference["structuralMotionAnalysis"] = structural_analysis
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
        result: dict[str, Any] = {
            "ok": True,
            "schema": "campaign_factory.reference_url_analysis.v1",
            "creator": creator,
            "creatorGovernance": governance_context,
            "intent": "recreate_reel",
            "through": through or "plan",
            "apply": apply,
            "providerCalls": int(structural_analysis.get("providerCalls") or 0),
            "paidSpend": (structural_analysis.get("cost") or {}).get("actualUsd"),
            "paidSpendStatus": (structural_analysis.get("cost") or {}).get(
                "reconciliationState"
            ),
            "analysisProviderCalls": int(structural_analysis.get("providerCalls") or 0),
            "analysisCost": structural_analysis.get("cost"),
            "providerRights": provider_rights,
            "recreationProviderRights": recreation_provider_rights,
            "download": download_evidence,
            "reference": reference,
            "audio": audio,
            "proposedMutations": [
                *list(reference.get("proposedMutations") or []),
                *list(audio.get("proposedMutations") or []),
            ],
        }
        if through != "analyze":
            soul_identity = _active_soul_identity_binding(factory, creator)
            prompt_pack = build_openai_prompt_pack(
                creator=creator,
                intent="recreate_reel",
                reference_video=source,
                external_call_authorized=apply,
                cost_connection=factory.conn,
                campaign_id=str(governance_context["campaignId"]),
                run_id=f"reference_prompt:{reference_id}",
                governance_context=governance_context,
                soul_identity=soul_identity,
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
                creator_governance=governance_context,
                prompt_pack=prompt_pack,
                provider_rights=recreation_provider_rights,
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
                if through == "anchor":
                    anchor_generation = generate_recreation_anchor(
                        factory,
                        creator=creator,
                        prompt_pack_path=prompt_path,
                        attempt_id=recreation_attempt_id,
                        max_credits=float(max_credits or 0),
                        recreation_plan=result["recreation"],
                    )
                    result["anchorGeneration"] = anchor_generation
                    result["paidSpend"] = anchor_generation.get("campaignSpendReceipt")
                    result["applyStatus"] = (
                        "ANCHOR_GENERATED_DOWNLOADED_REGISTERED_REVIEW_REQUIRED"
                    )
                else:
                    result["applyStatus"] = "ANALYSIS_PERSISTED_ANCHOR_REVIEW_REQUIRED"
                result["paidExecutionBlocked"] = True
        return result


def _active_soul_identity_binding(factory: Any, creator: str) -> dict[str, Any]:
    identity = factory.domains.creator_governance.active_identity_profile(
        creator, provider="higgsfield"
    )
    core = {
        "schema": "campaign_factory.verified_soul_identity_binding.v1",
        "creatorSlug": str(identity.get("creator_slug") or "").strip().lower(),
        "provider": "higgsfield",
        "soulId": str(identity.get("provider_identity_id") or "").strip(),
        "identityProfileId": str(identity.get("id") or "").strip(),
        "identityProfileVersion": identity.get("version"),
        "identityProfileFingerprint": str(
            identity.get("profile_fingerprint") or ""
        ).strip(),
    }
    if (
        core["creatorSlug"] != str(creator).strip().lower()
        or not core["soulId"]
        or not core["identityProfileId"]
        or not isinstance(core["identityProfileVersion"], int)
        or core["identityProfileVersion"] < 1
        or len(core["identityProfileFingerprint"]) != 64
    ):
        raise PermissionError("active_higgsfield_soul_identity_invalid")
    return {
        **core,
        "bindingFingerprint": hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


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


def resolve_stored_reference(*, db_path: Path, reference_id: str) -> dict[str, Any]:
    """Resolve and byte-verify one stored URL-intake reference read-only."""

    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required for stored Reference Factory lookup")
    completed = subprocess.run(
        [
            uv,
            "run",
            "--package",
            "reference-factory",
            "python",
            "-m",
            "reference_factory.cli",
            "--db",
            str(db_path),
            "resolve-url-intake",
            "--reference-id",
            str(reference_id),
        ],
        capture_output=True,
        text=True,
        cwd=_source_root(),
        timeout=60,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ValueError(f"stored reference resolution failed: {detail[-1000:]}")
    try:
        resolved = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("stored reference resolution returned invalid JSON") from exc
    source = resolved.get("source") if isinstance(resolved, dict) else None
    if (
        not isinstance(source, dict)
        or resolved.get("referenceId") != reference_id
        or not source.get("path")
        or not source.get("sha256")
    ):
        raise ValueError("stored reference resolution is incomplete")
    candidate = Path(str(source["path"])).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("stored reference source is not a regular file")
    path = candidate.resolve()
    if _sha256(path) != str(source["sha256"]):
        raise ValueError("stored reference source SHA-256 mismatch")
    probe = resolved.get("videoProbe")
    if not isinstance(probe, dict) or int(probe.get("valid") or 0) != 1:
        raise ValueError("stored reference is missing a valid canonical video probe")
    return {**resolved, "resolvedPath": str(path), "exactBytesVerified": True}


def _analyze_reference_structure(
    *,
    factory: Any,
    source: Path,
    reference_id: str,
    overlay_inventory: dict[str, Any],
    governance_context: dict[str, Any],
    provider_rights: dict[str, Any] | None,
    apply: bool,
) -> dict[str, Any]:
    if not apply:
        return {
            "status": "planned",
            "reason": "external_analysis_requires_apply",
            "providerCalls": 0,
            "cost": {
                "quotedUsd": 0.0,
                "actualUsd": 0.0,
                "reconciliationState": "not_submitted",
            },
        }
    if provider_rights is None or provider_rights.get("eligible") is not True:
        raise PermissionError("reference_provider_rights_required")
    gemini = shutil.which("gemini")
    if not gemini:
        return {
            "status": "unavailable",
            "reason": "gemini_cli_unavailable",
            "providerCalls": 0,
            "cost": None,
        }
    instruction = gemini_motion_analysis_instruction(reference_id)
    source_sha256 = _sha256(source)
    rights_fingerprint = str(provider_rights["rightsEvidenceFingerprint"])
    paid_action = _authorize_gemini_structure_analysis(
        factory,
        reference_id=reference_id,
        source_sha256=source_sha256,
        rights_fingerprint=rights_fingerprint,
        instruction=instruction,
        governance_context=governance_context,
    )
    current_rights = _require_reference_provider_rights(
        db_path=factory.settings.reference_factory_db,
        reference_id=reference_id,
        provider="gemini",
        operation="reference_analysis",
        source_sha256=source_sha256,
    )
    if current_rights["rightsEvidenceFingerprint"] != rights_fingerprint:
        reconcile_paid_action_cost(
            factory.conn,
            event_id=str(paid_action["campaignLedgerEventId"]),
            actual_usd=None,
            unknown_reason="reference_rights_changed_after_authorization",
        )
        raise PermissionError("reference_rights_changed_after_authorization")
    prompt = f"@{{{source}}} {instruction}"
    try:
        completed = subprocess.run(
            [
                gemini,
                "--model",
                str(paid_action["model"]),
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
    except Exception:
        reconcile_paid_action_cost(
            factory.conn,
            event_id=str(paid_action["campaignLedgerEventId"]),
            actual_usd=None,
            unknown_reason="provider_outcome_ambiguous",
        )
        raise
    cost = reconcile_paid_action_cost(
        factory.conn,
        event_id=str(paid_action["campaignLedgerEventId"]),
        actual_usd=None,
        unknown_reason="provider_cost_not_exposed",
    )
    if completed.returncode != 0:
        return {
            "status": "unavailable",
            "reason": "gemini_cli_analysis_failed",
            "providerCalls": 1,
            "cost": cost,
            "paidAction": paid_action,
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
            "cost": cost,
            "paidAction": paid_action,
        }
    return {
        "status": "ready",
        "providerCalls": 1,
        "cost": cost,
        "paidAction": paid_action,
        "analysis": analysis,
        "overlayTextInventory": overlay_inventory,
        "overlayTextExcludedFromGenerationPrompt": True,
    }


def _require_reference_provider_rights(
    *,
    db_path: Path,
    reference_id: str,
    provider: str,
    operation: str,
    source_sha256: str,
) -> dict[str, Any]:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required for signed reference-rights verification")
    completed = subprocess.run(
        [
            uv,
            "run",
            "--package",
            "reference-factory",
            "reference-factory",
            "--db",
            str(db_path),
            "provider-rights-check",
            "--reference-id",
            reference_id,
            "--provider",
            provider,
            "--operation",
            operation,
            "--source-sha256",
            source_sha256,
        ],
        capture_output=True,
        text=True,
        cwd=_source_root(),
        timeout=60,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PermissionError("reference_provider_rights_ineligible:" + detail[-1000:])
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Reference Factory rights check returned invalid JSON"
        ) from exc
    if (
        receipt.get("eligible") is not True
        or receipt.get("referenceId") != reference_id
        or receipt.get("provider") != provider
        or receipt.get("operation") != operation
        or receipt.get("sourceSha256") != source_sha256
        or not receipt.get("rightsEvidenceFingerprint")
    ):
        raise PermissionError("reference_provider_rights_receipt_invalid")
    return receipt


def _authorize_gemini_structure_analysis(
    factory: Any,
    *,
    reference_id: str,
    source_sha256: str,
    rights_fingerprint: str,
    instruction: str,
    governance_context: dict[str, Any],
) -> dict[str, Any]:
    provider = "gemini"
    model = str(
        os.environ.get("CREATOR_OS_GEMINI_ANALYSIS_MODEL") or "gemini-2.5-flash"
    )
    quote_raw = str(os.environ.get("CREATOR_OS_GEMINI_ANALYSIS_QUOTE_USD") or "")
    try:
        quote_usd = float(quote_raw)
    except ValueError as exc:
        raise PermissionError("gemini_analysis_quote_usd_required") from exc
    if quote_usd <= 0:
        raise PermissionError("gemini_analysis_quote_usd_required")
    request_core = {
        "referenceId": reference_id,
        "sourceSha256": source_sha256,
        "rightsEvidenceFingerprint": rights_fingerprint,
        "instructionSha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "model": model,
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request_core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scope = build_paid_action_spend_scope(
        provider=provider,
        provider_model=model,
        action_type="reference_analysis",
        creator_id=str(governance_context["creatorId"]),
        campaign_id=str(governance_context["campaignId"]),
        run_id=f"gemini_structure:{reference_id}",
        input_fingerprints={
            "reference_request": request_fingerprint,
            "reference_source": source_sha256,
            "rights_evidence": rights_fingerprint,
        },
        parameters={
            "factory": "reference_factory",
            "referenceId": reference_id,
            "analysisKind": "motion_structure",
        },
    )
    quote = build_paid_action_quote(
        provider=provider,
        model=model,
        amount=quote_usd,
        source="operator_configured_upper_bound",
        pricing_version=str(
            os.environ.get("CREATOR_OS_GEMINI_ANALYSIS_PRICING_VERSION")
            or "gemini_cli.v1"
        ),
    )
    secret = str(os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET") or "")
    authorization = issue_paid_action_authorization(
        factory.conn,
        scope=scope,
        quote=quote,
        secret=secret,
        limits=budget_limits_from_env(provider=provider, run_cap_usd=quote_usd),
        governance_context=governance_context,
    )
    attempt_id = f"refattempt_{uuid.uuid4().hex}"
    event_id = begin_paid_action_attempt(
        factory.conn,
        authorization=authorization,
        secret=secret,
        attempt_id=attempt_id,
    )
    return {
        "schema": "campaign_factory.reference_paid_action_context.v1",
        "authorizationId": authorization["authorizationId"],
        "attemptId": attempt_id,
        "campaignLedgerEventId": event_id,
        "provider": provider,
        "model": model,
        "actionType": "reference_analysis",
        "referenceId": reference_id,
        "referenceSourceSha256": source_sha256,
        "rightsEvidenceFingerprint": rights_fingerprint,
        "requestFingerprint": request_fingerprint,
        "spendRequestFingerprint": scope["requestFingerprint"],
        "attemptPersistedBeforeExternalEffect": True,
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
