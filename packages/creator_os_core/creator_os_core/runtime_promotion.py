"""Guarded, local-only promotion of an exact Creator OS commit into runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .fileops import atomic_write_json, file_lock

SCHEMA: Final = "creator_os.runtime_promotion_receipt.v1"
APPROVAL_SCHEMA: Final = "creator_os.runtime_promotion_approval.v1"
REQUIRED_CHECKS: Final = frozenset(
    {
        "contracts",
        "architecture",
        "artifacts",
        "python",
        "javascript",
        "security",
        "full_verify",
        "ci",
        "pr_review",
    }
)


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


def _run(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
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
        "checkCount": len(names),
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


def load_runtime_promotion_approval(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise RuntimePromotionError("runtime_promotion_approval_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePromotionError("runtime_promotion_approval_invalid_json") from exc
    if not isinstance(payload, dict) or payload.get("schema") != APPROVAL_SCHEMA:
        raise RuntimePromotionError("runtime_promotion_approval_schema_mismatch")
    claimed = str(payload.get("approvalFingerprint") or "")
    core = dict(payload)
    core.pop("approvalFingerprint", None)
    if claimed != _fingerprint(core):
        raise RuntimePromotionError("runtime_promotion_approval_fingerprint_mismatch")
    if not str(payload.get("approvedCommit") or "").strip():
        raise RuntimePromotionError("runtime_promotion_approval_commit_missing")
    if not str(payload.get("reviewedBy") or "").strip():
        raise RuntimePromotionError("runtime_promotion_review_missing")
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
        evidence = str(check.get("evidenceFingerprint") or "")
        if len(evidence) != 64 or any(
            char not in "0123456789abcdef" for char in evidence
        ):
            raise RuntimePromotionError(
                f"runtime_promotion_check_evidence_invalid:{check.get('name')}"
            )
    return payload


def _existing_receipt(state_root: Path, approved_commit: str) -> dict[str, Any] | None:
    receipt_root = state_root / "receipts"
    if not receipt_root.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for path in receipt_root.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("sourceCommit") == approved_commit
            and payload.get("status") in {"promoted", "already_current"}
        ):
            claimed = payload.get("receiptFingerprint")
            core = dict(payload)
            core.pop("receiptFingerprint", None)
            if claimed != _fingerprint(core):
                raise RuntimePromotionError("runtime_promotion_receipt_tampered")
            matches.append(payload)
    if len(matches) > 1:
        raise RuntimePromotionError("runtime_promotion_duplicate_success_receipt")
    return matches[0] if matches else None


def promote_runtime(
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
) -> dict[str, Any]:
    """Promote one reviewed commit, with a verified bundle and automatic rollback."""

    source = source_root.expanduser().resolve()
    runtime = runtime_root.expanduser().resolve()
    state = state_root.expanduser().resolve()
    if not operator.strip():
        raise ValueError("runtime_promotion_operator_missing")
    if (
        source == runtime
        or state.is_relative_to(source)
        or state.is_relative_to(runtime)
    ):
        raise RuntimePromotionError("runtime_promotion_path_boundary_invalid")
    approval = load_runtime_promotion_approval(approval_path)
    if approval["approvedCommit"] != approved_commit:
        raise RuntimePromotionError("runtime_promotion_approval_commit_mismatch")
    _git(source, "fetch", "origin", code="source_fetch_failed")
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
    destination_commit = _clean_commit(runtime, label="runtime")
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
    plan_core = {
        "schema": "creator_os.runtime_promotion_plan.v1",
        "sourceRoot": str(source),
        "runtimeRoot": str(runtime),
        "sourceCommit": approved_commit,
        "destinationCommitBefore": destination_commit,
        "changedFiles": list(changed_files),
        "approvalFingerprint": approval["approvalFingerprint"],
        "operator": operator,
        "verifierCommand": list(verifier_command),
        "healthCommand": list(health_command),
        "productionStateWritesAllowed": False,
    }
    plan = {**plan_core, "planFingerprint": _fingerprint(plan_core)}
    if dry_run:
        return {**plan, "status": "planned", "dryRun": True}

    state.mkdir(parents=True, exist_ok=True)
    with file_lock(state / "runtime_promotion"):
        existing = _existing_receipt(state, approved_commit)
        if destination_commit == approved_commit and existing is not None:
            return existing
        promotion_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        backup_root = state / "backups" / promotion_id
        if backup_root.exists():
            raise RuntimePromotionError("runtime_promotion_backup_collision")
        backup_root.mkdir(parents=True, exist_ok=False)
        bundle_path = backup_root / "runtime.bundle"
        manifest_path = backup_root / "manifest.json"
        try:
            _git(
                runtime,
                "bundle",
                "create",
                str(bundle_path),
                "--all",
                code="runtime_backup_failed",
            )
            if not bundle_path.is_file() or bundle_path.is_symlink():
                raise RuntimePromotionError("runtime_backup_missing_or_unsafe")
            _checked(
                ("git", "bundle", "verify", str(bundle_path)),
                cwd=runtime,
                code="runtime_backup_verification_failed",
            )
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

        rolled_back = False
        verification: list[dict[str, Any]] = []
        try:
            _git(runtime, "fetch", "origin", code="runtime_fetch_failed")
            _git(
                runtime,
                "checkout",
                "--detach",
                approved_commit,
                code="runtime_checkout_failed",
            )
            if _clean_commit(runtime, label="runtime") != approved_commit:
                raise RuntimePromotionError("runtime_commit_verification_failed")
            for name, command in (
                ("full_verify", verifier_command),
                ("live_read_only_health", health_command),
            ):
                completed = _run(command, cwd=runtime)
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
                or _clean_commit(runtime, label="runtime") != destination_commit
            ):
                raise RuntimePromotionError(
                    f"runtime_promotion_failed_and_rollback_failed:{type(exc).__name__}:{exc}"
                ) from exc
            status = "rolled_back"
            failure = f"{type(exc).__name__}:{exc}"
        else:
            failure = None

        receipt_core = {
            "schema": SCHEMA,
            "promotionId": promotion_id,
            "createdAt": created_at,
            "operator": operator,
            "status": status,
            "sourceCommit": approved_commit,
            "destinationCommitBefore": destination_commit,
            "destinationCommitAfter": _clean_commit(runtime, label="runtime"),
            "approvalPath": str(approval_path.expanduser().resolve()),
            "approvalFingerprint": approval["approvalFingerprint"],
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
        receipt = {
            **receipt_core,
            "receiptFingerprint": _fingerprint(receipt_core),
        }
        receipt_path = state / "receipts" / f"{promotion_id}.json"
        atomic_write_json(receipt_path, receipt)
        decoded = json.loads(receipt_path.read_text(encoding="utf-8"))
        decoded_core = dict(decoded)
        claimed = decoded_core.pop("receiptFingerprint", None)
        if claimed != _fingerprint(decoded_core):
            raise RuntimePromotionError("runtime_promotion_receipt_verification_failed")
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
