from __future__ import annotations

import hashlib
import json
import os
from argparse import ArgumentParser, Namespace, _SubParsersAction
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Final

from creator_os_core.evidence_attestation import (
    evidence_key_id,
    load_evidence_secret,
    payload_fingerprint,
)
from creator_os_core.local_api_auth import LocalApiAuthContext
from fastapi import HTTPException, Request

from .core import new_id, utc_now

READ = "read_local"
MUTATE = "local_mutation"
PAID = "paid_external_effect"
HANDOFF = "external_handoff"
RUNTIME = "runtime_operation"
DESTRUCTIVE = "destructive_mutation"

_HANDOFF_COMMANDS: Final = {
    "export-threadsdash",
    "bridge",
    "closed-loop-proof",
    "reddit-handoff",
}
_PAID_COMMANDS: Final = {
    "create",
    "stills",
    "orchestrate-daily",
    "reddit-weekly-generate",
}
_RUNTIME_COMMANDS: Final = {"serve", "runtime-promotion"}
_DESTRUCTIVE_WORDS: Final = {"delete", "remove", "purge", "revoke", "cancel"}
_LEGACY_MUTATIONS: Final = {
    "init",
    "prepare-reel",
    "sync-reel",
    "approve",
    "review-decision",
    "import-folder",
    "import-reference-bank",
    "import-audio-catalog",
    "import-audio-memory",
    "make-batch",
    "intake-finished-video",
    "create-creative-plan",
    "update-creative-plan-status",
    "sync-creative-plan-progress",
    "sync-performance",
    "sync-threadsdash-assignments",
    "reddit-assign",
    "reddit-weekly",
    "reddit-library-archive",
}
_READ_ONLY_COMMANDS: Final = {
    "account-tiers",
    "campaign-readiness",
    "caption-quality-repair-plan",
    "creative-knowledge-base",
    "daily-plan",
    "draft-inventory-gap",
    "fresh-schedule-safe-production-plan",
    "lifecycle-dashboard",
    "multi-surface-inventory-audit",
    "operator-review-minimum-certification-path",
    "operational-observability",
    "parent-factory-53-parent-trial",
    "parent-factory-discoverability-loss-analysis",
    "parent-factory-post-gate-fresh-batch-proof",
    "recommended-inventory-request-plan",
    "reddit-schedule",
    "reddit-library",
    "account-plan",
    "assignment-eligibility",
    "export-readiness",
    "performance-summary",
    "operator-status",
}
_READ_ONLY_MARKERS: Final = (
    "report",
    "summary",
    "status",
    "explain",
    "readiness",
    "eligibility",
    "list",
    "show",
    "preflight",
)
_READ_ONLY_POST_ROUTES: Final = {
    "/api/campaign-readiness",
    "/api/export-readiness",
    "/api/threadsdash-usage",
    "/api/supabase-preflight",
}
_HANDOFF_ROUTES: Final = {"/api/export-threadsdash"}
AUTHORITY_CLAIM_STALE_MINUTES: Final = 30


@dataclass(frozen=True)
class AuthorityDecision:
    operation_id: str
    effect_class: str
    role: str
    actor_fingerprint: str
    request_fingerprint: str
    idempotency_key: str
    allowed: bool
    reason: str
    preview: bool
    apply_requested: bool
    idempotency_required: bool
    receipt_required: bool
    rollback_owner: str
    reconciliation_owner: str


def _command_id(args: Namespace) -> str:
    parts = [str(getattr(args, "cmd", "") or "")]
    for key in sorted(vars(args)):
        if key.endswith("_cmd") and getattr(args, key, None):
            parts.append(str(getattr(args, key)))
    return "cli:" + "/".join(parts)


def _safe_request(args: Namespace) -> dict[str, Any]:
    def normalize(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Enum):
            return normalize(value.value)
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [normalize(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    return {
        key: normalize(
            "[redacted]"
            if any(
                word in key.lower()
                for word in ("secret", "token", "password", "authorization")
            )
            else value
        )
        for key, value in vars(args).items()
    }


def classify_cli_operation(args: Namespace) -> tuple[str, bool]:
    command = str(getattr(args, "cmd", "") or "")
    operation_id = _command_id(args)
    apply = bool(getattr(args, "apply", False))
    execute = bool(getattr(args, "execute", False))
    return _classify_command(
        command,
        operation_id,
        apply=apply,
        execute=execute,
        supports_apply=hasattr(args, "apply"),
    )


def _classify_command(
    command: str,
    operation_id: str,
    *,
    apply: bool,
    execute: bool,
    supports_apply: bool,
) -> tuple[str, bool]:
    tokens = operation_id.replace(":", "/").replace("-", "_").split("/")
    preview = not apply and not execute
    if command in _RUNTIME_COMMANDS:
        return RUNTIME, False
    if command in _HANDOFF_COMMANDS:
        return HANDOFF, False
    if any(word in token for token in tokens for word in _DESTRUCTIVE_WORDS):
        return DESTRUCTIVE, False
    if command in _PAID_COMMANDS and (apply or execute):
        return PAID, False
    if apply or command in _LEGACY_MUTATIONS:
        return MUTATE, preview and command not in _LEGACY_MUTATIONS
    if supports_apply or command in _PAID_COMMANDS:
        return READ, True
    if command in _READ_ONLY_COMMANDS or any(
        marker in operation_id for marker in _READ_ONLY_MARKERS
    ):
        return READ, True
    # Unknown legacy leaves fail closed as mutations until explicitly classified.
    return MUTATE, False


def build_cli_authority_registry(parser: ArgumentParser) -> list[dict[str, Any]]:
    """Inventory every argparse leaf; adding a command changes this registry."""

    records: list[dict[str, Any]] = []

    def walk(current: ArgumentParser, path: list[str]) -> None:
        subparsers = next(
            (
                action
                for action in current._actions
                if isinstance(action, _SubParsersAction)
            ),
            None,
        )
        if subparsers is not None:
            for name, child in sorted(subparsers.choices.items()):
                walk(child, [*path, name])
            return
        options = {
            option
            for action in current._actions
            for option in getattr(action, "option_strings", ())
        }
        operation_id = "cli:" + "/".join(path)
        effect_class, preview = _classify_command(
            path[0],
            operation_id,
            apply="--apply" in options,
            execute="--execute" in options,
            supports_apply="--apply" in options,
        )
        records.append(
            {
                "operationId": operation_id,
                "effectClass": effect_class,
                "previewSupported": preview or "--apply" in options,
                "applyFlag": "--apply" in options,
                "allowedRoles": ["reader", "operator"]
                if effect_class == READ
                else ["operator"],
                "idempotencyRequired": effect_class != READ,
                "receiptRequired": effect_class != READ,
            }
        )

    walk(parser, [])
    return records


def authorize_cli_operation(args: Namespace) -> AuthorityDecision:
    effect_class, preview = classify_cli_operation(args)
    request = _safe_request(args)
    if effect_class == READ or preview:
        actor = f"uid:{os.getuid()}" if hasattr(os, "getuid") else "local-user"
        role = "reader"
    elif str(getattr(args, "cmd", "") or "") == "init":
        actor = f"bootstrap:uid:{os.getuid()}" if hasattr(os, "getuid") else "bootstrap"
        role = "operator"
    else:
        secret = load_evidence_secret()
        actor = f"{evidence_key_id(secret)}:" + (
            f"uid:{os.getuid()}" if hasattr(os, "getuid") else "local-user"
        )
        role = "operator"
    operation_id = _command_id(args)
    request_fingerprint = payload_fingerprint(request)
    explicit_idempotency_key = getattr(args, "idempotency_key", None) or os.environ.get(
        "CREATOR_OS_IDEMPOTENCY_KEY"
    )
    idempotency_key = str(
        explicit_idempotency_key
        or (
            f"runtime:{new_id('invocation')}"
            if effect_class == RUNTIME
            else request_fingerprint
        )
    )
    return AuthorityDecision(
        operation_id=operation_id,
        effect_class=effect_class,
        role=role,
        actor_fingerprint=hashlib.sha256(actor.encode()).hexdigest(),
        request_fingerprint=request_fingerprint,
        idempotency_key=idempotency_key,
        allowed=True,
        reason="authenticated_operator" if role == "operator" else "read_only_preview",
        preview=preview,
        apply_requested=bool(
            getattr(args, "apply", False) or getattr(args, "execute", False)
        ),
        idempotency_required=effect_class != READ,
        receipt_required=effect_class != READ,
        rollback_owner=(
            "runtime_promotion"
            if effect_class == RUNTIME
            else "threadsdashboard"
            if effect_class == HANDOFF
            else "campaign_factory"
        ),
        reconciliation_owner=(
            "threadsdashboard"
            if effect_class == HANDOFF
            else "provider_spend"
            if effect_class == PAID
            else "campaign_factory"
        ),
    )


def claim_cli_authority_event(conn: Any, decision: AuthorityDecision) -> dict[str, Any]:
    if decision.effect_class == READ or decision.preview:
        return {"status": "read_only", "outcome": None}
    return _claim_authority_event(
        conn,
        operation_id=decision.operation_id,
        effect_class=decision.effect_class,
        actor_fingerprint=decision.actor_fingerprint,
        role=decision.role,
        request_fingerprint=decision.request_fingerprint,
        reason=decision.reason,
        idempotency_key=decision.idempotency_key,
        preview=decision.preview,
        apply_requested=decision.apply_requested,
        rollback_owner=decision.rollback_owner,
        reconciliation_owner=decision.reconciliation_owner,
    )


def complete_cli_authority_event(
    conn: Any,
    decision: AuthorityDecision,
    *,
    succeeded: bool,
    exit_code: int | None = None,
    retryable: bool = False,
    error: str | None = None,
) -> None:
    if decision.effect_class == READ or decision.preview:
        return
    _complete_authority_event(
        conn,
        operation_id=decision.operation_id,
        idempotency_key=decision.idempotency_key,
        succeeded=succeeded,
        outcome={"exitCode": int(exit_code or 0)} if exit_code is not None else None,
        retryable=retryable,
        error=error,
    )


def record_authority_event(conn: Any, decision: AuthorityDecision) -> str:
    """Compatibility wrapper around the claim phase."""

    status = claim_cli_authority_event(conn, decision)["status"]
    return {
        "claimed": "recorded",
        "replay": "replay_suppressed",
    }.get(str(status), str(status))


def api_operation(request: Request) -> dict[str, Any]:
    route = request.scope.get("route")
    path = str(getattr(route, "path", request.url.path))
    return api_authority_for(method=request.method.upper(), path=path)


def api_authority_for(
    *,
    method: str,
    path: str,
    context: LocalApiAuthContext | None = None,
    request_fingerprint: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    operation_id = f"api:{method}:{path}"
    effect_class = _classify_api(method, path)
    allowed_roles = (
        ["reader", "operator", "admin"]
        if effect_class == READ
        else ["operator", "admin"]
    )
    authority = {
        "operationId": operation_id,
        "effectClass": effect_class,
        "allowedRoles": allowed_roles,
        "preview": effect_class == READ,
        "idempotencyRequired": effect_class != READ,
        "receiptRequired": effect_class != READ,
        "rollbackOwner": (
            "threadsdashboard" if effect_class == HANDOFF else "campaign_factory"
        ),
        "reconciliationOwner": (
            "threadsdashboard" if effect_class == HANDOFF else "campaign_factory"
        ),
    }
    if context is not None:
        if context.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="operator_authority_required")
        if effect_class != READ and not str(idempotency_key or "").strip():
            raise HTTPException(status_code=428, detail="idempotency_key_required")
        authority.update(
            {
                "actorFingerprint": context.actor_fingerprint,
                "role": context.role,
                "requestFingerprint": request_fingerprint
                or payload_fingerprint(
                    {
                        "operationId": operation_id,
                        "actorFingerprint": context.actor_fingerprint,
                    }
                ),
                "idempotencyKey": str(idempotency_key or "").strip() or None,
            }
        )
    return authority


def _classify_api(method: str, path: str) -> str:
    if method == "GET" or (method == "POST" and path in _READ_ONLY_POST_ROUTES):
        return READ
    if path in _HANDOFF_ROUTES:
        return HANDOFF
    return MUTATE


def build_api_authority_registry(app: Any) -> list[dict[str, Any]]:
    records = []
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        for method in sorted(getattr(route, "methods", set()) or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            effect_class = _classify_api(method, path)
            records.append(
                {
                    "operationId": f"api:{method}:{path}",
                    "effectClass": effect_class,
                    "allowedRoles": ["reader", "operator", "admin"]
                    if effect_class == READ
                    else ["operator", "admin"],
                    "idempotencyRequired": effect_class != READ,
                    "receiptRequired": effect_class != READ,
                    "previewSupported": effect_class == READ,
                    "applyRequired": effect_class != READ,
                    "rollbackOwner": (
                        "threadsdashboard"
                        if effect_class == HANDOFF
                        else "campaign_factory"
                    ),
                    "reconciliationOwner": (
                        "threadsdashboard"
                        if effect_class == HANDOFF
                        else "campaign_factory"
                    ),
                }
            )
    return sorted(records, key=lambda item: item["operationId"])


def authorize_api_operation(request: Request, context: LocalApiAuthContext) -> None:
    request.state.operator_authority = api_authority_for(
        method=request.method.upper(),
        path=str(getattr(request.scope.get("route"), "path", request.url.path)),
        context=context,
        request_fingerprint=getattr(
            request.state, "operator_request_fingerprint", None
        ),
        idempotency_key=request.headers.get("idempotency-key"),
    )


def claim_api_authority_event(conn: Any, authority: dict[str, Any]) -> dict[str, Any]:
    if authority.get("effectClass") == READ:
        return {"status": "read_only", "outcome": None}
    try:
        return _claim_authority_event(
            conn,
            operation_id=str(authority["operationId"]),
            effect_class=str(authority["effectClass"]),
            actor_fingerprint=str(authority["actorFingerprint"]),
            role=str(authority["role"]),
            request_fingerprint=str(authority["requestFingerprint"]),
            reason="authenticated_api_operator",
            idempotency_key=str(authority["idempotencyKey"]),
            preview=False,
            apply_requested=True,
            rollback_owner=str(authority["rollbackOwner"]),
            reconciliation_owner=str(authority["reconciliationOwner"]),
        )
    except RuntimeError as exc:
        if str(exc) == "operator_idempotency_key_conflict":
            raise HTTPException(
                status_code=409, detail="idempotency_key_conflict"
            ) from exc
        raise


def complete_api_authority_event(
    conn: Any,
    authority: dict[str, Any],
    *,
    succeeded: bool,
    outcome: dict[str, Any] | None,
    retryable: bool,
    error: str | None = None,
) -> None:
    if authority.get("effectClass") == READ:
        return
    _complete_authority_event(
        conn,
        operation_id=str(authority["operationId"]),
        idempotency_key=str(authority["idempotencyKey"]),
        succeeded=succeeded,
        outcome=outcome,
        retryable=retryable,
        error=error,
    )


def record_api_authority_event(conn: Any, authority: dict[str, Any]) -> str:
    """Compatibility wrapper around the API claim phase."""

    status = claim_api_authority_event(conn, authority)["status"]
    return {
        "claimed": "recorded",
        "replay": "replay_suppressed",
    }.get(str(status), str(status))


def _claim_authority_event(
    conn: Any,
    *,
    operation_id: str,
    effect_class: str,
    actor_fingerprint: str,
    role: str,
    request_fingerprint: str,
    reason: str,
    idempotency_key: str,
    preview: bool,
    apply_requested: bool,
    rollback_owner: str,
    reconciliation_owner: str,
) -> dict[str, Any]:
    if conn.in_transaction:
        raise RuntimeError("operator_authority_claim_requires_clean_transaction")
    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            """
            SELECT * FROM operator_authority_events
            WHERE operation_id = ? AND idempotency_key = ?
            """,
            (operation_id, idempotency_key),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO operator_authority_events
                (id, operation_id, effect_class, decision, actor_fingerprint, role,
                 request_fingerprint, reason, created_at, idempotency_key, preview,
                 apply_requested, rollback_owner, reconciliation_owner,
                 execution_state, attempt_count, claim_updated_at, completed_at,
                 outcome_json, error_json, retryable)
                VALUES (?, ?, ?, 'allowed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'claimed', 1, ?, NULL, NULL, NULL, 0)
                """,
                (
                    new_id("authority"),
                    operation_id,
                    effect_class,
                    actor_fingerprint,
                    role,
                    request_fingerprint,
                    reason,
                    now,
                    idempotency_key,
                    int(preview),
                    int(apply_requested),
                    rollback_owner,
                    reconciliation_owner,
                    now,
                ),
            )
            conn.commit()
            return {"status": "claimed", "outcome": None, "attemptCount": 1}
        row = dict(existing)
        if row["request_fingerprint"] != request_fingerprint:
            raise RuntimeError("operator_idempotency_key_conflict")
        state = str(row.get("execution_state") or "claimed")
        retryable = bool(row.get("retryable"))
        if state == "succeeded" or (state == "failed" and not retryable):
            conn.commit()
            return {
                "status": "replay",
                "outcome": _json_object(row.get("outcome_json")),
                "executionState": state,
                "attemptCount": int(row.get("attempt_count") or 1),
            }
        if state == "claimed" and not _claim_is_stale(row, now=now):
            conn.commit()
            return {
                "status": "in_progress",
                "outcome": None,
                "attemptCount": int(row.get("attempt_count") or 1),
            }
        if state == "claimed":
            conn.commit()
            return {
                "status": "reconciliation_required",
                "outcome": None,
                "executionState": state,
                "attemptCount": int(row.get("attempt_count") or 1),
                "reconciliationOwner": row.get("reconciliation_owner"),
            }
        attempt_count = int(row.get("attempt_count") or 1) + 1
        updated = conn.execute(
            """
            UPDATE operator_authority_events
            SET execution_state = 'claimed', attempt_count = ?,
                claim_updated_at = ?, completed_at = NULL, outcome_json = NULL,
                error_json = NULL, retryable = 0
            WHERE operation_id = ? AND idempotency_key = ?
              AND request_fingerprint = ?
              AND execution_state = 'failed' AND retryable = 1
            """,
            (
                attempt_count,
                now,
                operation_id,
                idempotency_key,
                request_fingerprint,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("operator_authority_claim_race")
        conn.commit()
        return {
            "status": "claimed",
            "outcome": None,
            "attemptCount": attempt_count,
        }
    except Exception:
        conn.rollback()
        raise


def _complete_authority_event(
    conn: Any,
    *,
    operation_id: str,
    idempotency_key: str,
    succeeded: bool,
    outcome: dict[str, Any] | None,
    retryable: bool,
    error: str | None,
) -> None:
    if conn.in_transaction:
        raise RuntimeError("operator_authority_complete_requires_clean_transaction")
    completed_at = utc_now()
    state = "succeeded" if succeeded else "failed"
    if succeeded and outcome is None:
        raise ValueError("successful authority completion requires an outcome")
    conn.execute("BEGIN IMMEDIATE")
    try:
        updated = conn.execute(
            """
            UPDATE operator_authority_events
            SET execution_state = ?, completed_at = ?, outcome_json = ?,
                error_json = ?, retryable = ?
            WHERE operation_id = ? AND idempotency_key = ?
              AND execution_state = 'claimed'
            """,
            (
                state,
                completed_at,
                json.dumps(outcome, sort_keys=True) if outcome is not None else None,
                json.dumps({"error": error}, sort_keys=True) if error else None,
                int(bool(retryable and not succeeded)),
                operation_id,
                idempotency_key,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("operator_authority_completion_not_claimed")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _claim_is_stale(row: dict[str, Any], *, now: str) -> bool:
    raw = str(row.get("claim_updated_at") or row.get("created_at") or "")
    if not raw:
        return True
    claimed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=UTC)
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current - claimed >= timedelta(minutes=AUTHORITY_CLAIM_STALE_MINUTES)


def _json_object(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def decision_json(decision: AuthorityDecision) -> dict[str, Any]:
    return asdict(decision)
