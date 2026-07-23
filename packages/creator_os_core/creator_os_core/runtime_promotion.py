"""Guarded, local-only promotion of an exact Creator OS commit into runtime."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    sign_evidence_attestation,
    verify_evidence_attestation,
)
from .fileops import atomic_write_json, file_lock

SCHEMA: Final = "creator_os.runtime_promotion_receipt.v1"
APPROVAL_SCHEMA: Final = "creator_os.runtime_promotion_approval.v1"
TRANSACTION_SCHEMA: Final = "creator_os.runtime_promotion_transaction.v1"
TRANSACTION_ISSUER: Final = "creator_os.runtime_promotion_transaction"
LIVE_HEALTH_POLICY: Final = "creator_os.runtime_live_read_only_health.v1"
REQUIRED_LIVE_HEALTH_CHECKS: Final = frozenset(
    {
        "repository",
        "venv-entrypoints",
        "contracts",
        "local-config",
        "canonical-roots",
        "runtime",
        "campaign-database",
        "provider-readiness",
        "threadsdashboard-handshake",
    }
)
TRUSTED_CHECK_APP_ID: Final = 15368
TRUSTED_CHECK_APP_SLUG: Final = "github-actions"
WRITE_PERMISSIONS: Final = frozenset({"admin", "maintain", "write"})
TRUSTED_CHECK_WORKFLOWS: Final = {
    "contracts": ("Creator OS Monorepo CI", ".github/workflows/monorepo-ci.yml"),
    "hygiene": ("Creator OS Monorepo CI", ".github/workflows/monorepo-ci.yml"),
    "architecture": ("Creator OS Monorepo CI", ".github/workflows/monorepo-ci.yml"),
    "python": ("Creator OS Monorepo CI", ".github/workflows/monorepo-ci.yml"),
    "javascript": ("Creator OS Monorepo CI", ".github/workflows/monorepo-ci.yml"),
    "Secret scan": ("Security", ".github/workflows/security.yml"),
    "CodeQL (javascript-typescript)": ("Security", ".github/workflows/security.yml"),
    "CodeQL (python)": ("Security", ".github/workflows/security.yml"),
    "Trivy filesystem scan": ("Security", ".github/workflows/security.yml"),
}
PROMOTED_ENV_ALLOWLIST: Final = frozenset(
    {
        "CI",
        "COLORTERM",
        "FORCE_COLOR",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "NO_COLOR",
        "NPM_CONFIG_CACHE",
        "PATH",
        "PNPM_HOME",
        "SHELL",
        "TERM",
        "TERM_PROGRAM",
        "TMP",
        "TMPDIR",
        "TEMP",
        "USER",
        "UV_CACHE_DIR",
        "VIRTUAL_ENV",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)
REQUIRED_CHECKS: Final = frozenset(
    {
        "contracts",
        "hygiene",
        "architecture",
        "python",
        "javascript",
        "Secret scan",
        "CodeQL (javascript-typescript)",
        "CodeQL (python)",
        "Trivy filesystem scan",
    }
)
ApprovalEvidenceVerifier = Callable[[Path, dict[str, Any]], dict[str, Any]]
ReceiptValidator = Callable[[dict[str, Any]], None]
ApprovalValidator = Callable[[dict[str, Any]], None]


class RuntimePromotionError(RuntimeError):
    """A guarded runtime promotion precondition or validation failed."""


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
        env=dict(environment) if environment is not None else None,
        text=True,
        timeout=7200,
    )


def _checked(command: Sequence[str], *, cwd: Path, code: str) -> str:
    completed = _run(command, cwd=cwd)
    if completed.returncode != 0:
        raise RuntimePromotionError(
            f"{code}:" + (completed.stderr[-2000:] or completed.stdout[-2000:])
        )
    return completed.stdout.strip()


def _promoted_subprocess_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    environment = {
        key: value for key, value in source.items() if key in PROMOTED_ENV_ALLOWLIST
    }
    environment.update(
        {
            "CREATOR_OS_RUNTIME_PROMOTION_ISOLATED": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return environment


def _git(repo: Path, *args: str, code: str) -> str:
    return _checked(("git", "-C", str(repo), *args), cwd=repo, code=code)


def _validate_live_read_only_health(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimePromotionError(
            "runtime_live_read_only_health_invalid_json"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimePromotionError("runtime_live_read_only_health_report_missing")
    statuses: list[str] = []
    names: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimePromotionError("runtime_live_read_only_health_item_invalid")
        name = str(item.get("name") or "").strip()
        status = str(item.get("status") or "").strip()
        if not name or not status:
            raise RuntimePromotionError("runtime_live_read_only_health_item_invalid")
        names.append(name)
        statuses.append(status)
    if len(names) != len(set(names)):
        raise RuntimePromotionError("runtime_live_read_only_health_duplicate_check")
    actual_names = frozenset(names)
    if actual_names != REQUIRED_LIVE_HEALTH_CHECKS:
        missing = sorted(REQUIRED_LIVE_HEALTH_CHECKS.difference(actual_names))
        unexpected = sorted(actual_names.difference(REQUIRED_LIVE_HEALTH_CHECKS))
        raise RuntimePromotionError(
            "runtime_live_read_only_health_inventory_mismatch:"
            f"missing={','.join(missing)};unexpected={','.join(unexpected)}"
        )
    nonpassing = [
        f"{name}:{status}"
        for name, status in zip(names, statuses, strict=True)
        if status != "PASS"
    ]
    if nonpassing:
        raise RuntimePromotionError(
            "runtime_live_read_only_health_not_all_passed:" + ",".join(nonpassing)
        )
    return {
        "policy": LIVE_HEALTH_POLICY,
        "checkCount": len(names),
        "checkNames": sorted(names),
        "statusCounts": dict(sorted(Counter(statuses).items())),
        "reportFingerprint": _fingerprint({"checks": payload}),
    }


def _clean_commit(repo: Path, *, label: str) -> str:
    if not repo.is_dir() or not (repo / ".git").exists():
        # Worktrees use a .git file.
        if not repo.is_dir() or not (repo / ".git").is_file():
            raise RuntimePromotionError(f"runtime_promotion_{label}_not_git_checkout")
    status = _git(repo, "status", "--porcelain", code=f"{label}_status_failed")
    if status:
        raise RuntimePromotionError(f"runtime_promotion_{label}_dirty")
    return _git(repo, "rev-parse", "HEAD", code=f"{label}_head_failed")


def _clean_detached_runtime_commit(runtime: Path) -> str:
    commit = _clean_commit(runtime, label="runtime")
    symbolic = _run(
        ("git", "-C", str(runtime), "symbolic-ref", "-q", "HEAD"),
        cwd=runtime,
    )
    if symbolic.returncode == 0:
        raise RuntimePromotionError("runtime_promotion_runtime_not_detached")
    if symbolic.returncode != 1:
        raise RuntimePromotionError("runtime_promotion_runtime_head_state_unreadable")
    return commit


def load_runtime_promotion_approval(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise RuntimePromotionError("runtime_promotion_approval_missing_or_unsafe")
    resolved = expanded.resolve()
    if not resolved.is_file():
        raise RuntimePromotionError("runtime_promotion_approval_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePromotionError("runtime_promotion_approval_invalid_json") from exc
    return _validate_runtime_promotion_approval_payload(payload)


def _validate_runtime_promotion_approval_payload(
    candidate: Any,
) -> dict[str, Any]:
    payload = copy.deepcopy(candidate)
    if not isinstance(payload, dict) or payload.get("schema") != APPROVAL_SCHEMA:
        raise RuntimePromotionError("runtime_promotion_approval_schema_mismatch")
    claimed = str(payload.get("approvalFingerprint") or "")
    core = dict(payload)
    core.pop("approvalFingerprint", None)
    if claimed != _fingerprint(core):
        raise RuntimePromotionError("runtime_promotion_approval_fingerprint_mismatch")
    for field in ("approvedCommit", "reviewedCommit"):
        commit = str(payload.get(field) or "")
        if len(commit) != 40 or any(
            character not in "0123456789abcdef" for character in commit
        ):
            raise RuntimePromotionError(f"runtime_promotion_approval_{field}_invalid")
    repository = str(payload.get("repository") or "")
    if repository.count("/") != 1 or any(
        not part.strip() for part in repository.split("/")
    ):
        raise RuntimePromotionError("runtime_promotion_repository_invalid")
    pull_request = payload.get("pullRequestNumber")
    if (
        isinstance(pull_request, bool)
        or not isinstance(pull_request, int)
        or pull_request <= 0
    ):
        raise RuntimePromotionError("runtime_promotion_pull_request_invalid")
    if not str(payload.get("reviewedBy") or "").strip():
        raise RuntimePromotionError("runtime_promotion_review_missing")
    try:
        reviewed_at = datetime.fromisoformat(
            str(payload.get("reviewedAt") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RuntimePromotionError("runtime_promotion_reviewed_at_invalid") from exc
    if reviewed_at.tzinfo is None or reviewed_at > datetime.now(UTC):
        raise RuntimePromotionError("runtime_promotion_reviewed_at_invalid")
    review = payload.get("review")
    if not isinstance(review, dict) or set(review) != {
        "reviewId",
        "reviewer",
        "state",
        "submittedAt",
        "commitId",
    }:
        raise RuntimePromotionError("runtime_promotion_review_evidence_invalid")
    if (
        isinstance(review.get("reviewId"), bool)
        or not isinstance(review.get("reviewId"), int)
        or int(review["reviewId"]) <= 0
        or review.get("state") != "APPROVED"
        or review.get("reviewer") != payload.get("reviewedBy")
        or review.get("commitId") != payload.get("reviewedCommit")
    ):
        raise RuntimePromotionError("runtime_promotion_review_evidence_invalid")
    try:
        submitted_at = datetime.fromisoformat(
            str(review.get("submittedAt") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RuntimePromotionError(
            "runtime_promotion_review_evidence_invalid"
        ) from exc
    if submitted_at.tzinfo is None or submitted_at > reviewed_at:
        raise RuntimePromotionError("runtime_promotion_review_evidence_invalid")
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise RuntimePromotionError("runtime_promotion_checks_missing")
    identities = [
        str(item.get("name") or "") for item in checks if isinstance(item, dict)
    ]
    if len(identities) != len(checks) or len(identities) != len(set(identities)):
        raise RuntimePromotionError("runtime_promotion_checks_duplicate_or_invalid")
    missing = REQUIRED_CHECKS.difference(identities)
    if missing:
        raise RuntimePromotionError(
            "runtime_promotion_required_checks_missing:" + ",".join(sorted(missing))
        )
    for check in checks:
        if check.get("status") != "passed":
            raise RuntimePromotionError(
                f"runtime_promotion_check_not_passed:{check.get('name')}"
            )
        if set(check) != {
            "name",
            "status",
            "checkRunId",
            "detailsUrl",
            "completedAt",
            "headSha",
            "appId",
            "appSlug",
            "workflowRunId",
            "workflowName",
            "workflowPath",
        }:
            raise RuntimePromotionError(
                f"runtime_promotion_check_evidence_invalid:{check.get('name')}"
            )
        if (
            isinstance(check.get("checkRunId"), bool)
            or not isinstance(check.get("checkRunId"), int)
            or int(check["checkRunId"]) <= 0
            or not str(check.get("detailsUrl") or "").startswith("https://")
            or check.get("headSha") != payload.get("reviewedCommit")
            or check.get("appId") != TRUSTED_CHECK_APP_ID
            or check.get("appSlug") != TRUSTED_CHECK_APP_SLUG
            or isinstance(check.get("workflowRunId"), bool)
            or not isinstance(check.get("workflowRunId"), int)
            or int(check["workflowRunId"]) <= 0
            or not str(check.get("workflowName") or "").strip()
            or not str(check.get("workflowPath") or "").startswith(".github/workflows/")
            or f"/actions/runs/{check.get('workflowRunId')}/"
            not in str(check.get("detailsUrl") or "")
            or (
                str(check.get("workflowName")),
                str(check.get("workflowPath")),
            )
            != TRUSTED_CHECK_WORKFLOWS.get(str(check.get("name") or ""))
        ):
            raise RuntimePromotionError(
                f"runtime_promotion_check_evidence_invalid:{check.get('name')}"
            )
        try:
            completed_at = datetime.fromisoformat(
                str(check.get("completedAt") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise RuntimePromotionError(
                f"runtime_promotion_check_evidence_invalid:{check.get('name')}"
            ) from exc
        if completed_at.tzinfo is None or completed_at > reviewed_at:
            raise RuntimePromotionError(
                f"runtime_promotion_check_evidence_invalid:{check.get('name')}"
            )
    return payload


def _github_api_json(source: Path, endpoint: str) -> Any:
    raw = _checked(("gh", "api", endpoint), cwd=source, code="github_evidence_failed")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimePromotionError("github_evidence_invalid_json") from exc


def _verify_github_approval_evidence(
    source: Path, approval: dict[str, Any]
) -> dict[str, Any]:
    repository = str(approval["repository"])
    pull_request_number = int(approval["pullRequestNumber"])
    pull_request = _github_api_json(
        source, f"repos/{repository}/pulls/{pull_request_number}"
    )
    if not isinstance(pull_request, dict):
        raise RuntimePromotionError("runtime_promotion_pull_request_evidence_invalid")
    if (
        pull_request.get("merged_at") is None
        or pull_request.get("merge_commit_sha") != approval["approvedCommit"]
        or pull_request.get("head", {}).get("sha") != approval["reviewedCommit"]
    ):
        raise RuntimePromotionError("runtime_promotion_pull_request_not_exactly_merged")
    author = str(pull_request.get("user", {}).get("login") or "")
    reviews = _github_api_json(
        source, f"repos/{repository}/pulls/{pull_request_number}/reviews?per_page=100"
    )
    if not isinstance(reviews, list):
        raise RuntimePromotionError("runtime_promotion_review_evidence_invalid")
    expected_review = approval["review"]
    matched_reviews = [
        review
        for review in reviews
        if isinstance(review, dict)
        and review.get("id") == expected_review["reviewId"]
        and review.get("state") == "APPROVED"
        and review.get("user", {}).get("login") == expected_review["reviewer"]
        and review.get("submitted_at") == expected_review["submittedAt"]
        and review.get("commit_id") == approval["reviewedCommit"]
    ]
    if len(matched_reviews) != 1 or expected_review["reviewer"] == author:
        raise RuntimePromotionError(
            "runtime_promotion_review_not_independent_or_current"
        )
    permission_payload = _github_api_json(
        source,
        f"repos/{repository}/collaborators/{expected_review['reviewer']}/permission",
    )
    reviewer_permission = (
        str(permission_payload.get("permission") or "")
        if isinstance(permission_payload, dict)
        else ""
    )
    if reviewer_permission not in WRITE_PERMISSIONS:
        raise RuntimePromotionError(
            "runtime_promotion_reviewer_permission_insufficient"
        )
    check_payload = _github_api_json(
        source,
        f"repos/{repository}/commits/{approval['reviewedCommit']}/check-runs?per_page=100",
    )
    if not isinstance(check_payload, dict) or not isinstance(
        check_payload.get("check_runs"), list
    ):
        raise RuntimePromotionError("runtime_promotion_check_evidence_invalid")
    check_runs = check_payload["check_runs"]
    verified_workflow_runs: dict[int, dict[str, Any]] = {}
    for expected in approval["checks"]:
        matches = [
            run
            for run in check_runs
            if isinstance(run, dict)
            and run.get("id") == expected["checkRunId"]
            and run.get("name") == expected["name"]
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("details_url") == expected["detailsUrl"]
            and run.get("completed_at") == expected["completedAt"]
            and run.get("head_sha") == approval["reviewedCommit"]
            and run.get("app", {}).get("id") == TRUSTED_CHECK_APP_ID
            and run.get("app", {}).get("slug") == TRUSTED_CHECK_APP_SLUG
        ]
        if len(matches) != 1:
            raise RuntimePromotionError(
                f"runtime_promotion_check_not_live_verified:{expected['name']}"
            )
        workflow_run_id = int(expected["workflowRunId"])
        if workflow_run_id not in verified_workflow_runs:
            workflow_run = _github_api_json(
                source,
                f"repos/{repository}/actions/runs/{workflow_run_id}",
            )
            if not isinstance(workflow_run, dict):
                raise RuntimePromotionError(
                    f"runtime_promotion_workflow_not_live_verified:{expected['name']}"
                )
            verified_workflow_runs[workflow_run_id] = workflow_run
        workflow_run = verified_workflow_runs[workflow_run_id]
        if (
            workflow_run.get("id") != workflow_run_id
            or workflow_run.get("name") != expected["workflowName"]
            or workflow_run.get("path") != expected["workflowPath"]
            or workflow_run.get("head_sha") != approval["reviewedCommit"]
            or workflow_run.get("status") != "completed"
            or workflow_run.get("conclusion") != "success"
            or workflow_run.get("repository", {}).get("full_name") != repository
            or workflow_run.get("head_repository", {}).get("full_name") != repository
        ):
            raise RuntimePromotionError(
                f"runtime_promotion_workflow_not_live_verified:{expected['name']}"
            )
    evidence_core = {
        "repository": repository,
        "pullRequestNumber": pull_request_number,
        "approvedCommit": approval["approvedCommit"],
        "reviewedCommit": approval["reviewedCommit"],
        "reviewId": expected_review["reviewId"],
        "reviewerPermission": reviewer_permission,
        "trustedCheckApp": f"{TRUSTED_CHECK_APP_SLUG}:{TRUSTED_CHECK_APP_ID}",
        "checkRunIds": sorted(check["checkRunId"] for check in approval["checks"]),
        "workflowRunIds": sorted(verified_workflow_runs),
    }
    return {**evidence_core, "evidenceFingerprint": _fingerprint(evidence_core)}


def _remote_main_commit(source: Path) -> str:
    raw = _checked(
        ("git", "ls-remote", "--exit-code", "origin", "refs/heads/main"),
        cwd=source,
        code="source_remote_main_lookup_failed",
    )
    rows = [line.split() for line in raw.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
        raise RuntimePromotionError("source_remote_main_not_exactly_once")
    return rows[0][0]


def _runtime_lock_target(runtime: Path) -> Path:
    return runtime.parent / f".{runtime.name}.creator-os-runtime-promotion"


def _assert_runtime_lock_path_safe(target: Path, runtime: Path) -> None:
    lock_path = target.with_name(target.name + ".lock")
    if (
        lock_path.is_symlink()
        or (lock_path.exists() and not lock_path.is_file())
        or lock_path.parent.resolve() != runtime.parent.resolve()
    ):
        raise RuntimePromotionError("runtime_promotion_lock_path_unsafe")


def _owned_subroot(
    state_root: Path,
    name: str,
    *,
    create: bool,
) -> Path | None:
    if name not in {"backups", "receipts", "transactions"}:
        raise RuntimePromotionError("runtime_promotion_state_subroot_invalid")
    path = state_root / name
    if path.is_symlink():
        raise RuntimePromotionError(f"runtime_promotion_{name}_path_unsafe")
    if path.exists() and not path.is_dir():
        raise RuntimePromotionError(f"runtime_promotion_{name}_path_unsafe")
    if not path.exists():
        if not create:
            return None
        path.mkdir(parents=False, exist_ok=False)
    resolved = path.resolve()
    if not resolved.is_relative_to(state_root) or resolved == state_root:
        raise RuntimePromotionError(f"runtime_promotion_{name}_path_unsafe")
    return resolved


def _validate_receipt_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.suffix != ".json":
        raise RuntimePromotionError("runtime_promotion_receipt_path_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePromotionError("runtime_promotion_receipt_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise RuntimePromotionError("runtime_promotion_receipt_shape_invalid")
    promotion_id = str(payload.get("promotionId") or "")
    try:
        parsed_id = uuid.UUID(promotion_id)
    except ValueError as exc:
        raise RuntimePromotionError(
            "runtime_promotion_receipt_identity_invalid"
        ) from exc
    if str(parsed_id) != promotion_id or path.name != f"{promotion_id}.json":
        raise RuntimePromotionError("runtime_promotion_receipt_identity_invalid")
    attestation = payload.get("producerAttestation")
    claimed = payload.get("receiptFingerprint")
    core = dict(payload)
    core.pop("producerAttestation", None)
    core.pop("receiptFingerprint", None)
    if claimed != _fingerprint(core):
        raise RuntimePromotionError("runtime_promotion_receipt_tampered")
    try:
        verify_evidence_attestation(
            dict(attestation) if isinstance(attestation, dict) else {},
            {**core, "receiptFingerprint": claimed},
            secret=load_evidence_secret(),
            expected_issuer="creator_os.runtime_promotion",
        )
    except EvidenceAttestationError as exc:
        raise RuntimePromotionError(
            "runtime_promotion_receipt_attestation_invalid"
        ) from exc
    return payload


def _load_all_receipts(state_root: Path) -> list[dict[str, Any]]:
    receipt_root = _owned_subroot(state_root, "receipts", create=False)
    if receipt_root is None:
        return []
    receipts = [_validate_receipt_file(path) for path in sorted(receipt_root.iterdir())]
    promotion_ids = [str(item["promotionId"]) for item in receipts]
    if len(promotion_ids) != len(set(promotion_ids)):
        raise RuntimePromotionError("runtime_promotion_duplicate_receipt_identity")
    return receipts


def _existing_receipt(state_root: Path, approved_commit: str) -> dict[str, Any] | None:
    matches = [
        payload
        for payload in _load_all_receipts(state_root)
        if payload.get("sourceCommit") == approved_commit
        and payload.get("status") in {"promoted", "already_current"}
    ]
    return max(matches, key=lambda item: str(item.get("createdAt") or ""), default=None)


def _write_transaction_journal(
    path: Path,
    core: dict[str, Any],
) -> dict[str, Any]:
    payload = {**core, "transactionFingerprint": _fingerprint(core)}
    record = {
        **payload,
        "producerAttestation": sign_evidence_attestation(
            payload,
            issuer=TRANSACTION_ISSUER,
            issued_at=str(core["updatedAt"]),
            secret=load_evidence_secret(),
        ),
    }
    atomic_write_json(path, record)
    return record


def _load_transaction_journal(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimePromotionError("runtime_promotion_transaction_path_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePromotionError("runtime_promotion_transaction_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != TRANSACTION_SCHEMA:
        raise RuntimePromotionError("runtime_promotion_transaction_shape_invalid")
    promotion_id = str(payload.get("promotionId") or "")
    try:
        parsed_id = uuid.UUID(promotion_id)
    except ValueError as exc:
        raise RuntimePromotionError(
            "runtime_promotion_transaction_identity_invalid"
        ) from exc
    if str(parsed_id) != promotion_id or path.name != f"{promotion_id}.json":
        raise RuntimePromotionError("runtime_promotion_transaction_identity_invalid")
    core = dict(payload)
    attestation = core.pop("producerAttestation", None)
    claimed = core.pop("transactionFingerprint", None)
    if claimed != _fingerprint(core):
        raise RuntimePromotionError("runtime_promotion_transaction_tampered")
    try:
        verify_evidence_attestation(
            dict(attestation) if isinstance(attestation, dict) else {},
            {**core, "transactionFingerprint": claimed},
            secret=load_evidence_secret(),
            expected_issuer=TRANSACTION_ISSUER,
        )
    except EvidenceAttestationError as exc:
        raise RuntimePromotionError(
            "runtime_promotion_transaction_attestation_invalid"
        ) from exc
    return payload


def _load_verified_backup(
    state_root: Path,
    runtime: Path,
    record: dict[str, Any],
) -> Path:
    promotion_id = str(record.get("promotionId") or "")
    backup_root = _owned_subroot(state_root, "backups", create=False)
    if backup_root is None:
        raise RuntimePromotionError("runtime_promotion_recovery_backup_missing")
    promotion_root = backup_root / promotion_id
    if (
        promotion_root.is_symlink()
        or not promotion_root.is_dir()
        or not promotion_root.resolve().is_relative_to(backup_root)
    ):
        raise RuntimePromotionError("runtime_promotion_recovery_backup_unsafe")
    manifest_path = promotion_root / "manifest.json"
    bundle_path = promotion_root / "runtime.bundle"
    if (
        manifest_path.is_symlink()
        or bundle_path.is_symlink()
        or not manifest_path.is_file()
        or not bundle_path.is_file()
        or str(manifest_path.resolve()) != str(record.get("backupManifestPath") or "")
    ):
        raise RuntimePromotionError("runtime_promotion_recovery_backup_unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePromotionError(
            "runtime_promotion_recovery_manifest_unreadable"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimePromotionError("runtime_promotion_recovery_manifest_invalid")
    manifest_core = dict(manifest)
    claimed = manifest_core.pop("manifestFingerprint", None)
    if (
        claimed != record.get("backupManifestFingerprint")
        or claimed != _fingerprint(manifest_core)
        or manifest.get("promotionId") != promotion_id
        or manifest.get("runtimeRoot") != str(runtime)
        or manifest.get("runtimeCommit") != record.get("destinationCommitBefore")
        or manifest.get("sourceCommit") != record.get("sourceCommit")
        or manifest.get("bundlePath") != str(bundle_path)
        or manifest.get("bundleSha256") != _sha256_file(bundle_path)
    ):
        raise RuntimePromotionError("runtime_promotion_recovery_manifest_invalid")
    _checked(
        ("git", "bundle", "verify", str(bundle_path)),
        cwd=runtime,
        code="runtime_promotion_recovery_bundle_invalid",
    )
    bundle_heads = _checked(
        ("git", "bundle", "list-heads", str(bundle_path)),
        cwd=runtime,
        code="runtime_promotion_recovery_bundle_heads_invalid",
    )
    if str(record.get("destinationCommitBefore") or "") not in {
        line.split()[0] for line in bundle_heads.splitlines() if line.split()
    }:
        raise RuntimePromotionError("runtime_promotion_recovery_commit_not_bundled")
    return bundle_path


def _commit_exists(repo: Path, commit: str) -> bool:
    result = _run(
        ("git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"),
        cwd=repo,
    )
    return result.returncode == 0


def _restore_commit_from_bundle(runtime: Path, commit: str, bundle_path: Path) -> None:
    if not _commit_exists(runtime, commit):
        _git(
            runtime,
            "fetch",
            str(bundle_path),
            code="runtime_promotion_recovery_bundle_fetch_failed",
        )
    if not _commit_exists(runtime, commit):
        raise RuntimePromotionError("runtime_promotion_recovery_commit_unavailable")


def _transaction_update(
    path: Path,
    record: dict[str, Any],
    *,
    status: str,
    failure: str | None = None,
    receipt_fingerprint: str | None = None,
) -> dict[str, Any]:
    core = {
        key: value
        for key, value in record.items()
        if key not in {"transactionFingerprint", "producerAttestation"}
    }
    core["status"] = status
    core["updatedAt"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    core["failure"] = failure
    if receipt_fingerprint is not None:
        core["receiptFingerprint"] = receipt_fingerprint
    return _write_transaction_journal(path, core)


def _recover_incomplete_transactions(state_root: Path, runtime: Path) -> None:
    transaction_root = _owned_subroot(state_root, "transactions", create=False)
    if transaction_root is None:
        return
    terminal = {"committed", "rolled_back", "recovered_committed", "recovered_rollback"}
    for path in sorted(transaction_root.iterdir()):
        record = _load_transaction_journal(path)
        if record.get("runtimeRoot") != str(runtime):
            raise RuntimePromotionError(
                "runtime_promotion_transaction_runtime_mismatch"
            )
        status = str(record.get("status") or "")
        if status in {"committed", "recovered_committed"}:
            receipt_root = _owned_subroot(state_root, "receipts", create=False)
            receipt_path = (
                receipt_root / f"{record.get('promotionId')}.json"
                if receipt_root is not None
                else state_root / "receipts" / f"{record.get('promotionId')}.json"
            )
            if not receipt_path.exists() and not receipt_path.is_symlink():
                raise RuntimePromotionError(
                    "runtime_promotion_committed_receipt_missing"
                )
            receipt = _validate_receipt_file(receipt_path)
            if (
                receipt.get("receiptFingerprint") != record.get("receiptFingerprint")
                or receipt.get("promotionId") != record.get("promotionId")
                or receipt.get("sourceCommit") != record.get("sourceCommit")
                or receipt.get("status") not in {"promoted", "already_current"}
            ):
                raise RuntimePromotionError(
                    "runtime_promotion_committed_receipt_mismatch"
                )
            continue
        if status in terminal:
            continue
        before = str(record.get("destinationCommitBefore") or "")
        approved = str(record.get("sourceCommit") or "")
        promotion_id = str(record.get("promotionId") or "")
        if not before or not approved or not promotion_id:
            raise RuntimePromotionError("runtime_promotion_transaction_shape_invalid")
        bundle_path = _load_verified_backup(state_root, runtime, record)
        current = _clean_detached_runtime_commit(runtime)
        receipt_root = _owned_subroot(state_root, "receipts", create=False)
        receipt_path = (
            receipt_root / f"{promotion_id}.json"
            if receipt_root is not None
            else state_root / "receipts" / f"{promotion_id}.json"
        )
        if receipt_path.exists() or receipt_path.is_symlink():
            receipt = _validate_receipt_file(receipt_path)
            if (
                receipt.get("promotionId") == promotion_id
                and receipt.get("sourceCommit") == approved
                and receipt.get("status") in {"promoted", "already_current"}
                and current == approved
            ):
                _transaction_update(
                    path,
                    record,
                    status="recovered_committed",
                    receipt_fingerprint=str(receipt["receiptFingerprint"]),
                )
                continue
        if current == approved and before != approved:
            _restore_commit_from_bundle(runtime, before, bundle_path)
            _git(
                runtime,
                "checkout",
                "--detach",
                before,
                code="runtime_promotion_recovery_checkout_failed",
            )
            current = _clean_detached_runtime_commit(runtime)
        if current != before:
            raise RuntimePromotionError("runtime_promotion_recovery_state_ambiguous")
        _transaction_update(
            path,
            record,
            status="recovered_rollback",
            failure="incomplete_promotion_recovered_before_new_attempt",
        )


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second or first.is_relative_to(second) or second.is_relative_to(first)
    )


def _verify_promotion_authority(
    source: Path,
    approved_commit: str,
    approval: dict[str, Any],
    approval_evidence_verifier: ApprovalEvidenceVerifier,
) -> dict[str, Any]:
    resolved_commit = _git(
        source,
        "rev-parse",
        f"{approved_commit}^{{commit}}",
        code="approved_commit_not_found",
    )
    if resolved_commit != approved_commit:
        raise RuntimePromotionError("runtime_promotion_commit_not_exact")
    source_commit = _clean_commit(source, label="source")
    if source_commit != approved_commit:
        raise RuntimePromotionError("runtime_promotion_source_not_at_approved_commit")
    if _remote_main_commit(source) != approved_commit:
        raise RuntimePromotionError("runtime_promotion_approved_commit_not_origin_main")
    evidence = approval_evidence_verifier(source, approval)
    if not isinstance(evidence, dict) or not str(
        evidence.get("evidenceFingerprint") or ""
    ):
        raise RuntimePromotionError("runtime_promotion_live_evidence_missing")
    evidence_core = dict(evidence)
    evidence_fingerprint = evidence_core.pop("evidenceFingerprint", None)
    if evidence_fingerprint != _fingerprint(evidence_core):
        raise RuntimePromotionError(
            "runtime_promotion_live_evidence_fingerprint_mismatch"
        )
    return evidence


def _promotion_plan(
    *,
    source: Path,
    runtime: Path,
    approved_commit: str,
    destination_commit: str,
    approval: dict[str, Any],
    approval_evidence: dict[str, Any],
    operator: str,
    verifier_command: Sequence[str],
    health_command: Sequence[str],
) -> dict[str, Any]:
    changed_files = tuple(
        line
        for line in _git(
            source,
            "diff",
            "--name-only",
            destination_commit,
            approved_commit,
            code="promotion_diff_failed",
        ).splitlines()
        if line.strip()
    )
    core = {
        "schema": "creator_os.runtime_promotion_plan.v1",
        "sourceRoot": str(source),
        "runtimeRoot": str(runtime),
        "sourceCommit": approved_commit,
        "destinationCommitBefore": destination_commit,
        "changedFiles": list(changed_files),
        "approvalFingerprint": approval["approvalFingerprint"],
        "approvalEvidenceFingerprint": approval_evidence["evidenceFingerprint"],
        "operator": operator,
        "verifierCommand": list(verifier_command),
        "healthCommand": list(health_command),
        "healthPolicy": LIVE_HEALTH_POLICY,
        "productionStateWritesAllowed": False,
    }
    return {**core, "planFingerprint": _fingerprint(core)}


def promote_runtime(
    *,
    source_root: Path,
    runtime_root: Path,
    approved_commit: str,
    approval_path: Path,
    state_root: Path,
    operator: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the production promotion path without injectable safety overrides."""

    return _promote_runtime(
        source_root=source_root,
        runtime_root=runtime_root,
        approved_commit=approved_commit,
        approval_path=approval_path,
        state_root=state_root,
        operator=operator,
        dry_run=dry_run,
        verifier_command=("make", "verify"),
        health_command=(
            "scripts/creator-os",
            "status",
            "--live-read-only",
            "--json",
        ),
        approval_evidence_verifier=_verify_github_approval_evidence,
    )


def _promote_runtime(
    *,
    source_root: Path,
    runtime_root: Path,
    approved_commit: str,
    approval_path: Path,
    state_root: Path,
    operator: str,
    dry_run: bool,
    verifier_command: Sequence[str] = ("make", "verify"),
    health_command: Sequence[str] = (
        "scripts/creator-os",
        "status",
        "--live-read-only",
        "--json",
    ),
    approval_evidence_verifier: ApprovalEvidenceVerifier = _verify_github_approval_evidence,
    receipt_validator: ReceiptValidator | None = None,
    approval_payload: dict[str, Any] | None = None,
    approval_validator: ApprovalValidator | None = None,
) -> dict[str, Any]:
    """Promote one reviewed commit, with a verified bundle and automatic rollback."""

    source = source_root.expanduser().resolve()
    runtime = runtime_root.expanduser().resolve()
    state_input = state_root.expanduser()
    if state_input.is_symlink():
        raise RuntimePromotionError("runtime_promotion_state_root_unsafe")
    state = state_input.resolve()
    if not operator.strip():
        raise ValueError("runtime_promotion_operator_missing")
    if any(
        _paths_overlap(first, second)
        for first, second in (
            (source, runtime),
            (source, state),
            (runtime, state),
        )
    ):
        raise RuntimePromotionError("runtime_promotion_path_boundary_invalid")
    approval = (
        load_runtime_promotion_approval(approval_path)
        if approval_payload is None
        else _validate_runtime_promotion_approval_payload(approval_payload)
    )
    if approval_validator is not None:
        approval_validator(copy.deepcopy(approval))
    if approval["approvedCommit"] != approved_commit:
        raise RuntimePromotionError("runtime_promotion_approval_commit_mismatch")
    if dry_run:
        verified_approval_evidence = _verify_promotion_authority(
            source,
            approved_commit,
            approval,
            approval_evidence_verifier,
        )
        destination_commit = _clean_detached_runtime_commit(runtime)
        plan = _promotion_plan(
            source=source,
            runtime=runtime,
            approved_commit=approved_commit,
            destination_commit=destination_commit,
            approval=approval,
            approval_evidence=verified_approval_evidence,
            operator=operator,
            verifier_command=verifier_command,
            health_command=health_command,
        )
        return {**plan, "status": "planned", "dryRun": True}

    runtime_lock_target = _runtime_lock_target(runtime)
    _assert_runtime_lock_path_safe(runtime_lock_target, runtime)
    with file_lock(runtime_lock_target):
        verified_approval_evidence = _verify_promotion_authority(
            source,
            approved_commit,
            approval,
            approval_evidence_verifier,
        )
        if state.exists() and (state.is_symlink() or not state.is_dir()):
            raise RuntimePromotionError("runtime_promotion_state_root_unsafe")
        state.mkdir(parents=True, exist_ok=True)
        state = state.resolve()
        if any(_paths_overlap(state, checkout) for checkout in (source, runtime)):
            raise RuntimePromotionError("runtime_promotion_path_boundary_invalid")
        for subroot in ("backups", "receipts", "transactions"):
            _owned_subroot(state, subroot, create=True)
        _recover_incomplete_transactions(state, runtime)
        destination_commit = _clean_detached_runtime_commit(runtime)
        plan = _promotion_plan(
            source=source,
            runtime=runtime,
            approved_commit=approved_commit,
            destination_commit=destination_commit,
            approval=approval,
            approval_evidence=verified_approval_evidence,
            operator=operator,
            verifier_command=verifier_command,
            health_command=health_command,
        )
        changed_files = tuple(plan["changedFiles"])
        # Validate every prior success receipt before starting another attempt. A
        # current checkout still receives fresh verification; an old receipt is
        # historical evidence, not a health cache.
        _existing_receipt(state, approved_commit)
        promotion_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        backups_root = _owned_subroot(state, "backups", create=True)
        if backups_root is None:  # pragma: no cover - create=True is total
            raise RuntimePromotionError("runtime_promotion_backups_path_unsafe")
        backup_root = backups_root / promotion_id
        if backup_root.exists():
            raise RuntimePromotionError("runtime_promotion_backup_collision")
        backup_root.mkdir(parents=False, exist_ok=False)
        if backup_root.is_symlink() or not backup_root.resolve().is_relative_to(
            backups_root
        ):
            raise RuntimePromotionError("runtime_promotion_backup_path_unsafe")
        bundle_path = backup_root / "runtime.bundle"
        manifest_path = backup_root / "manifest.json"
        try:
            _git(
                runtime,
                "bundle",
                "create",
                str(bundle_path),
                "--all",
                "HEAD",
                code="runtime_backup_failed",
            )
            if not bundle_path.is_file() or bundle_path.is_symlink():
                raise RuntimePromotionError("runtime_backup_missing_or_unsafe")
            _checked(
                ("git", "bundle", "verify", str(bundle_path)),
                cwd=runtime,
                code="runtime_backup_verification_failed",
            )
            bundle_heads = _checked(
                ("git", "bundle", "list-heads", str(bundle_path)),
                cwd=runtime,
                code="runtime_backup_verification_failed",
            )
            if destination_commit not in {
                line.split()[0] for line in bundle_heads.splitlines() if line.split()
            }:
                raise RuntimePromotionError("runtime_backup_commit_not_bundled")
            backup_manifest_core = {
                "schema": "creator_os.runtime_promotion_backup.v1",
                "promotionId": promotion_id,
                "createdAt": created_at,
                "runtimeRoot": str(runtime),
                "runtimeCommit": destination_commit,
                "sourceCommit": approved_commit,
                "bundlePath": str(bundle_path),
                "bundleSha256": _sha256_file(bundle_path),
                "changedFiles": list(changed_files),
            }
            backup_manifest = {
                **backup_manifest_core,
                "manifestFingerprint": _fingerprint(backup_manifest_core),
            }
            atomic_write_json(manifest_path, backup_manifest)
            verified_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_core = dict(verified_manifest)
            claimed_manifest = manifest_core.pop("manifestFingerprint", None)
            if (
                claimed_manifest != _fingerprint(manifest_core)
                or _sha256_file(bundle_path) != verified_manifest["bundleSha256"]
            ):
                raise RuntimePromotionError(
                    "runtime_backup_manifest_verification_failed"
                )
        except BaseException:
            # The runtime was not changed before the backup became verifiable.
            raise

        # Authorization can change while a large backup is being created. Re-read
        # every mutable source immediately before journaling the mutation.
        verified_approval_evidence = _verify_promotion_authority(
            source,
            approved_commit,
            approval,
            approval_evidence_verifier,
        )
        plan = _promotion_plan(
            source=source,
            runtime=runtime,
            approved_commit=approved_commit,
            destination_commit=destination_commit,
            approval=approval,
            approval_evidence=verified_approval_evidence,
            operator=operator,
            verifier_command=verifier_command,
            health_command=health_command,
        )

        transaction_root = _owned_subroot(state, "transactions", create=True)
        if transaction_root is None:  # pragma: no cover - create=True is total
            raise RuntimePromotionError("runtime_promotion_transactions_path_unsafe")
        transaction_path = transaction_root / f"{promotion_id}.json"
        transaction_core = {
            "schema": TRANSACTION_SCHEMA,
            "promotionId": promotion_id,
            "createdAt": created_at,
            "updatedAt": created_at,
            "status": "prepared",
            "runtimeRoot": str(runtime),
            "sourceCommit": approved_commit,
            "destinationCommitBefore": destination_commit,
            "backupManifestPath": str(manifest_path),
            "backupManifestFingerprint": backup_manifest["manifestFingerprint"],
            "receiptFingerprint": None,
            "failure": None,
        }
        transaction = _write_transaction_journal(
            transaction_path,
            transaction_core,
        )

        rolled_back = False
        verification: list[dict[str, Any]] = []
        failure: str | None = None
        try:
            _git(runtime, "fetch", "origin", code="runtime_fetch_failed")
            _git(
                runtime,
                "checkout",
                "--detach",
                approved_commit,
                code="runtime_checkout_failed",
            )
            if _clean_detached_runtime_commit(runtime) != approved_commit:
                raise RuntimePromotionError("runtime_commit_verification_failed")
            transaction = _transaction_update(
                transaction_path,
                transaction,
                status="runtime_mutated",
            )
            for name, command in (
                ("full_verify", verifier_command),
                ("live_read_only_health", health_command),
            ):
                completed = _run(
                    command,
                    cwd=runtime,
                    environment=_promoted_subprocess_environment(),
                )
                passed = completed.returncode == 0
                report_summary = None
                report_error = None
                if name == "live_read_only_health" and passed:
                    try:
                        report_summary = _validate_live_read_only_health(
                            completed.stdout
                        )
                    except RuntimePromotionError as exc:
                        passed = False
                        report_error = str(exc)
                record = {
                    "name": name,
                    "command": list(command),
                    "returnCode": completed.returncode,
                    "stdoutSha256": hashlib.sha256(
                        completed.stdout.encode()
                    ).hexdigest(),
                    "stderrSha256": hashlib.sha256(
                        completed.stderr.encode()
                    ).hexdigest(),
                    "passed": passed,
                    "reportSummary": report_summary,
                    "reportError": report_error,
                }
                verification.append(record)
                if not passed:
                    raise RuntimePromotionError(f"runtime_post_promotion_{name}_failed")
            transaction = _transaction_update(
                transaction_path,
                transaction,
                status="receipt_pending",
            )
            status = (
                "promoted"
                if destination_commit != approved_commit
                else "already_current"
            )
        except BaseException as exc:
            rollback = _run(
                ("git", "-C", str(runtime), "checkout", "--detach", destination_commit),
                cwd=runtime,
            )
            rolled_back = rollback.returncode == 0
            if (
                not rolled_back
                or _clean_detached_runtime_commit(runtime) != destination_commit
            ):
                raise RuntimePromotionError(
                    f"runtime_promotion_failed_and_rollback_failed:{type(exc).__name__}:{exc}"
                ) from exc
            status = "rolled_back"
            failure = f"{type(exc).__name__}:{exc}"
            transaction = _transaction_update(
                transaction_path,
                transaction,
                status="rolled_back",
                failure=failure,
            )
        receipt_core = {
            "schema": SCHEMA,
            "promotionId": promotion_id,
            "createdAt": created_at,
            "operator": operator,
            "status": status,
            "sourceCommit": approved_commit,
            "destinationCommitBefore": destination_commit,
            "destinationCommitAfter": _clean_detached_runtime_commit(runtime),
            "approvalPath": str(approval_path.expanduser().resolve()),
            "approvalFingerprint": approval["approvalFingerprint"],
            "approvalEvidence": verified_approval_evidence,
            "planFingerprint": plan["planFingerprint"],
            "backupManifestPath": str(manifest_path),
            "backupManifestFingerprint": backup_manifest["manifestFingerprint"],
            "verification": verification,
            "rolledBack": rolled_back,
            "failure": failure,
            "rollbackInstructions": [
                f"git -C {runtime} status --porcelain",
                f"git -C {runtime} checkout --detach {destination_commit}",
                f"git bundle verify {bundle_path}",
            ],
            "productionStateWrites": 0,
            "providerCalls": 0,
        }
        receipt_payload = {
            **receipt_core,
            "receiptFingerprint": _fingerprint(receipt_core),
        }
        receipt = {
            **receipt_payload,
            "producerAttestation": sign_evidence_attestation(
                receipt_payload,
                issuer="creator_os.runtime_promotion",
                issued_at=created_at,
                secret=load_evidence_secret(),
            ),
        }
        receipt_root = _owned_subroot(state, "receipts", create=True)
        if receipt_root is None:  # pragma: no cover - create=True is total
            raise RuntimePromotionError("runtime_promotion_receipts_path_unsafe")
        receipt_path = receipt_root / f"{promotion_id}.json"
        try:
            if receipt_validator is not None:
                receipt_validator(receipt)
            atomic_write_json(receipt_path, receipt)
            decoded = json.loads(receipt_path.read_text(encoding="utf-8"))
            decoded_core = dict(decoded)
            decoded_attestation = decoded_core.pop("producerAttestation", None)
            claimed = decoded_core.pop("receiptFingerprint", None)
            if claimed != _fingerprint(decoded_core):
                raise RuntimePromotionError(
                    "runtime_promotion_receipt_verification_failed"
                )
            verify_evidence_attestation(
                dict(decoded_attestation)
                if isinstance(decoded_attestation, dict)
                else {},
                {**decoded_core, "receiptFingerprint": claimed},
                secret=load_evidence_secret(),
                expected_issuer="creator_os.runtime_promotion",
            )
            if receipt_validator is not None:
                receipt_validator(decoded)
            transaction = _transaction_update(
                transaction_path,
                transaction,
                status="committed",
                receipt_fingerprint=str(decoded["receiptFingerprint"]),
            )
        except BaseException as exc:
            if status not in {"promoted", "already_current"}:
                if isinstance(exc, EvidenceAttestationError):
                    raise RuntimePromotionError(
                        "runtime_promotion_receipt_attestation_invalid"
                    ) from exc
                raise
            rollback = _run(
                ("git", "-C", str(runtime), "checkout", "--detach", destination_commit),
                cwd=runtime,
            )
            rollback_verified = (
                rollback.returncode == 0
                and _clean_detached_runtime_commit(runtime) == destination_commit
            )
            try:
                receipt_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                raise RuntimePromotionError(
                    "runtime_promotion_receipt_failed_rollback_succeeded_cleanup_failed"
                ) from cleanup_exc
            if not rollback_verified:
                raise RuntimePromotionError(
                    "runtime_promotion_receipt_failed_and_rollback_failed"
                ) from exc
            try:
                _transaction_update(
                    transaction_path,
                    transaction,
                    status="rolled_back",
                    failure=f"{type(exc).__name__}:{exc}",
                )
            except BaseException as journal_exc:
                raise RuntimePromotionError(
                    "runtime_promotion_receipt_failed_rollback_succeeded_journal_failed"
                ) from journal_exc
            raise RuntimePromotionError(
                "runtime_promotion_receipt_failed_and_rolled_back"
            ) from exc
        if status == "rolled_back":
            raise RuntimePromotionError(
                f"runtime_promotion_rolled_back:{failure}:receipt={receipt_path}"
            )
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--approved-commit", required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = promote_runtime(
            source_root=args.source_root,
            runtime_root=args.runtime_root,
            approved_commit=args.approved_commit,
            approval_path=args.approval,
            state_root=args.state_root,
            operator=args.operator,
            dry_run=args.dry_run,
        )
    except (RuntimePromotionError, OSError, ValueError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
