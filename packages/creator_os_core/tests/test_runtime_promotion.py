from __future__ import annotations

import hashlib
import inspect
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
import yaml
from creator_os_core.runtime_promotion import (
    DIAGNOSTIC_TAIL_MAX_CHARS,
    PROMOTED_ENV_BLOCKLIST,
    PROMOTED_REQUIRED_EXECUTABLES,
    REQUIRED_CHECKS,
    REQUIRED_LIVE_HEALTH_CHECKS,
    TRUSTED_CHECK_APP_ID,
    TRUSTED_CHECK_APP_SLUG,
    TRUSTED_CHECK_WORKFLOWS,
    RuntimePromotionError,
    _promote_runtime,
    _promoted_subprocess_environment,
    _resolved_promoted_toolchain_evidence,
    _rollback_instructions,
    _runtime_lock_target,
    _validate_runtime_promotion_receipt_payload,
    _verify_github_approval_evidence,
    load_runtime_promotion_approval,
    promote_runtime,
)

from pipeline_contracts import (
    validate_runtime_promotion_approval,
    validate_runtime_promotion_receipt,
)

EVIDENCE_SECRET = "runtime-promotion-evidence-secret-longer-than-thirty-two-bytes"
ROOT = Path(__file__).resolve().parents[3]


def _health_script() -> str:
    rows = [
        {"name": name, "status": "PASS"} for name in sorted(REQUIRED_LIVE_HEALTH_CHECKS)
    ]
    return f"import json; print(json.dumps({rows!r}))"


def test_required_promotion_checks_match_canonical_workflow_provenance() -> None:
    monorepo = yaml.safe_load(
        (ROOT / ".github/workflows/monorepo-ci.yml").read_text(encoding="utf-8")
    )
    security = yaml.safe_load(
        (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    )

    for check in {"contracts", "hygiene", "architecture", "python", "javascript"}:
        assert check in monorepo["jobs"]
        assert TRUSTED_CHECK_WORKFLOWS[check] == (
            monorepo["name"],
            ".github/workflows/monorepo-ci.yml",
        )
    assert security["jobs"]["secrets"]["name"] == "Secret scan"
    assert security["jobs"]["trivy"]["name"] == "Trivy filesystem scan"
    assert security["jobs"]["codeql"]["name"] == "CodeQL (${{ matrix.language }})"
    for check in {
        "Secret scan",
        "CodeQL (javascript-typescript)",
        "CodeQL (python)",
        "Trivy filesystem scan",
    }:
        assert TRUSTED_CHECK_WORKFLOWS[check] == (
            security["name"],
            ".github/workflows/security.yml",
        )
    assert set(TRUSTED_CHECK_WORKFLOWS) == REQUIRED_CHECKS


def test_rollback_instructions_are_shell_safe_and_restore_bundle_before_checkout(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime with spaces"
    bundle = tmp_path / "backup with spaces.bundle"
    commit = "a" * 40

    instructions = _rollback_instructions(
        runtime=runtime,
        bundle_path=bundle,
        destination_commit=commit,
    )

    assert [shlex.split(command) for command in instructions] == [
        ["git", "-C", str(runtime), "status", "--porcelain"],
        ["git", "-C", str(runtime), "bundle", "verify", str(bundle)],
        ["git", "-C", str(runtime), "fetch", str(bundle)],
        ["git", "-C", str(runtime), "checkout", "--detach", commit],
        [
            str(runtime / "scripts" / "creator-os"),
            "status",
            "--live-read-only",
            "--json",
        ],
    ]


@pytest.fixture(autouse=True)
def evidence_secret(monkeypatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)


def _run(*command: str, cwd: Path) -> str:
    completed = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _approval(path: Path, commit: str) -> Path:
    core = {
        "schema": "creator_os.runtime_promotion_approval.v1",
        "repository": "example/creator-os",
        "pullRequestNumber": 1,
        "approvedCommit": commit,
        "reviewedCommit": commit,
        "reviewedBy": "reviewer",
        "reviewedAt": "2020-01-01T01:00:00Z",
        "review": {
            "reviewId": 42,
            "reviewer": "reviewer",
            "state": "APPROVED",
            "submittedAt": "2020-01-01T00:30:00Z",
            "commitId": commit,
        },
        "checks": [
            {
                "name": name,
                "status": "passed",
                "checkRunId": index + 1,
                "detailsUrl": (
                    f"https://github.com/example/creator-os/actions/runs/"
                    f"{100 + index}/job/{index + 1}"
                ),
                "completedAt": "2020-01-01T00:15:00Z",
                "headSha": commit,
                "appId": TRUSTED_CHECK_APP_ID,
                "appSlug": TRUSTED_CHECK_APP_SLUG,
                "workflowRunId": 100 + index,
                "workflowName": (
                    "Security"
                    if name
                    in {
                        "Secret scan",
                        "CodeQL (javascript-typescript)",
                        "CodeQL (python)",
                        "Trivy filesystem scan",
                    }
                    else "Creator OS Monorepo CI"
                ),
                "workflowPath": (
                    ".github/workflows/security.yml"
                    if name
                    in {
                        "Secret scan",
                        "CodeQL (javascript-typescript)",
                        "CodeQL (python)",
                        "Trivy filesystem scan",
                    }
                    else ".github/workflows/monorepo-ci.yml"
                ),
            }
            for index, name in enumerate(sorted(REQUIRED_CHECKS))
        ],
    }
    path.write_text(
        json.dumps({**core, "approvalFingerprint": _fingerprint(core)}),
        encoding="utf-8",
    )
    return path


def _single_owner_approval(path: Path, commit: str) -> Path:
    legacy_path = _approval(path, commit)
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    for field in ("reviewedBy", "reviewedAt", "review"):
        payload.pop(field)
    payload.update(
        {
            "approvalMode": "single_owner_ci",
            "operator": "owner",
            "attestedAt": "2020-01-01T01:00:00Z",
            "attestationReason": "Exact merged commit and required CI verified",
            "branchProtection": {
                "strictStatusChecks": True,
                "requiredStatusChecks": sorted(REQUIRED_CHECKS),
                "requiredApprovingReviewCount": 0,
                "requiredConversationResolution": True,
                "enforceAdmins": True,
            },
        }
    )
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def repositories(tmp_path: Path):
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", str(origin), cwd=tmp_path)
    source = tmp_path / "source"
    _run("git", "clone", str(origin), str(source), cwd=tmp_path)
    _run("git", "config", "user.email", "test@example.com", cwd=source)
    _run("git", "config", "user.name", "Test", cwd=source)
    (source / "package.json").write_text(
        json.dumps({"engines": {"node": ">=1"}}),
        encoding="utf-8",
    )
    (source / "value.txt").write_text("one", encoding="utf-8")
    scripts = source / "scripts"
    scripts.mkdir()
    health_script = scripts / "creator-os"
    health_script.write_text(
        "#!/usr/bin/env python3\n" + _health_script() + "\n",
        encoding="utf-8",
    )
    health_script.chmod(0o755)
    _run("git", "add", "package.json", "value.txt", "scripts/creator-os", cwd=source)
    _run("git", "commit", "-m", "first", cwd=source)
    _run("git", "push", "origin", "HEAD:main", cwd=source)
    first = _run("git", "rev-parse", "HEAD", cwd=source)
    runtime = tmp_path / "runtime"
    _run("git", "clone", "--branch", "main", str(origin), str(runtime), cwd=tmp_path)
    _run("git", "checkout", "--detach", cwd=runtime)
    (source / "value.txt").write_text("two", encoding="utf-8")
    _run("git", "add", "value.txt", cwd=source)
    _run("git", "commit", "-m", "second", cwd=source)
    _run("git", "push", "origin", "HEAD:main", cwd=source)
    second = _run("git", "rev-parse", "HEAD", cwd=source)
    approval = _approval(tmp_path / "approval.json", second)
    return source, runtime, first, second, approval, tmp_path / "state"


def _promote(
    repositories,
    *,
    verifier=None,
    health=None,
    dry_run=False,
    receipt_validator=None,
    state_override=None,
    approval_evidence_verifier=None,
    approval_payload=None,
    operator="operator",
):
    source, runtime, _first, second, approval, state = repositories

    def verified_evidence(_source, exact):
        core = {
            "repository": exact["repository"],
            "pullRequestNumber": exact["pullRequestNumber"],
            "approvedCommit": exact["approvedCommit"],
            "reviewedCommit": exact["reviewedCommit"],
            "reviewId": exact["review"]["reviewId"],
            "reviewerPermission": "write",
            "trustedCheckApp": "github-actions:15368",
            "checkRunIds": sorted(item["checkRunId"] for item in exact["checks"]),
            "workflowRunIds": sorted(
                {item["workflowRunId"] for item in exact["checks"]}
            ),
        }
        return {**core, "evidenceFingerprint": _fingerprint(core)}

    return _promote_runtime(
        source_root=source,
        runtime_root=runtime,
        approved_commit=second,
        approval_path=approval,
        state_root=state_override or state,
        operator=operator,
        dry_run=dry_run,
        verifier_command=verifier or (sys.executable, "-c", "raise SystemExit(0)"),
        health_command=health
        or (
            sys.executable,
            "-c",
            _health_script(),
        ),
        approval_evidence_verifier=approval_evidence_verifier or verified_evidence,
        receipt_validator=receipt_validator,
        approval_payload=approval_payload,
    )


def _seed_incomplete_transaction(
    *,
    state: Path,
    runtime: Path,
    before: str,
    approved: str,
    status: str = "runtime_mutated",
) -> tuple[Path, str]:
    import creator_os_core.runtime_promotion as promotion

    promotion_id = str(uuid.uuid4())
    created_at = "2020-01-01T00:00:00Z"
    backup_root = state / "backups" / promotion_id
    backup_root.mkdir(parents=True)
    bundle_path = backup_root / "runtime.bundle"
    _run("git", "bundle", "create", str(bundle_path), "--all", "HEAD", cwd=runtime)
    manifest_core = {
        "schema": "creator_os.runtime_promotion_backup.v1",
        "promotionId": promotion_id,
        "createdAt": created_at,
        "runtimeRoot": str(runtime.resolve()),
        "runtimeCommit": before,
        "sourceCommit": approved,
        "bundlePath": str(bundle_path),
        "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "changedFiles": [],
    }
    manifest = {
        **manifest_core,
        "manifestFingerprint": _fingerprint(manifest_core),
    }
    manifest_path = backup_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    transaction_path = state / "transactions" / f"{promotion_id}.json"
    promotion._write_transaction_journal(
        transaction_path,
        {
            "schema": promotion.TRANSACTION_SCHEMA,
            "promotionId": promotion_id,
            "createdAt": created_at,
            "updatedAt": created_at,
            "status": status,
            "runtimeRoot": str(runtime.resolve()),
            "sourceCommit": approved,
            "destinationCommitBefore": before,
            "backupManifestPath": str(manifest_path),
            "backupManifestFingerprint": manifest["manifestFingerprint"],
            "receiptFingerprint": None,
            "failure": None,
        },
    )
    return transaction_path, promotion_id


def test_promotion_creates_verified_backup_receipt_and_runtime(repositories) -> None:
    _source, runtime, first, second, _approval_path, _state = repositories
    receipt = _promote(repositories)
    assert receipt["status"] == "promoted"
    assert receipt["destinationCommitBefore"] == first
    assert receipt["destinationCommitAfter"] == second
    assert receipt["providerCalls"] == 0
    assert receipt["productionStateWrites"] == 0
    assert receipt["producerAttestation"]["issuer"] == "creator_os.runtime_promotion"
    toolchain = receipt["verification"][0]
    assert toolchain["name"] == "toolchain_preflight"
    assert toolchain["passed"] is True
    assert toolchain["toolchainEvidence"]["schema"] == (
        "creator_os.runtime_toolchain_evidence.v1"
    )
    assert Path(receipt["backupManifestPath"]).is_file()
    validate_runtime_promotion_receipt(receipt)
    assert _validate_runtime_promotion_receipt_payload(receipt) == receipt
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == second


def test_receipt_rollback_instructions_execute_and_finish_with_live_health(
    repositories,
) -> None:
    _source, runtime, first, *_rest = repositories
    receipt = _promote(repositories)
    outputs: list[subprocess.CompletedProcess[str]] = []

    for instruction in receipt["rollbackInstructions"]:
        outputs.append(
            subprocess.run(
                shlex.split(instruction),
                cwd=runtime.parent,
                capture_output=True,
                check=True,
                text=True,
            )
        )

    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    report = json.loads(outputs[-1].stdout)
    assert {item["name"] for item in report} == REQUIRED_LIVE_HEALTH_CHECKS
    assert {item["status"] for item in report} == {"PASS"}


def test_core_approval_validation_matches_canonical_contract(repositories) -> None:
    approval = load_runtime_promotion_approval(repositories[4])

    validate_runtime_promotion_approval(approval)

    approval["untrustedField"] = "not canonical"
    core = dict(approval)
    core.pop("approvalFingerprint")
    approval["approvalFingerprint"] = _fingerprint(core)
    repositories[4].write_text(json.dumps(approval), encoding="utf-8")
    with pytest.raises(RuntimePromotionError, match="approval_shape_invalid"):
        load_runtime_promotion_approval(repositories[4])
    with pytest.raises(ValueError):
        validate_runtime_promotion_approval(approval)


def test_core_receipt_validation_rejects_noncanonical_extra_field(repositories) -> None:
    receipt = _promote(repositories)
    receipt["untrustedField"] = "not canonical"

    with pytest.raises(RuntimePromotionError, match="receipt_shape_invalid"):
        _validate_runtime_promotion_receipt_payload(receipt)
    with pytest.raises(ValueError):
        validate_runtime_promotion_receipt(receipt)


def test_dry_run_does_not_change_runtime_or_create_state(repositories) -> None:
    source, runtime, first, _second, _approval_path, state = repositories
    refs_before = _run("git", "show-ref", cwd=source)
    plan = _promote(repositories, dry_run=True)
    assert plan["status"] == "planned"
    assert plan["toolchainEvidence"]["schema"] == (
        "creator_os.runtime_toolchain_evidence.v1"
    )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not state.exists()
    assert _run("git", "show-ref", cwd=source) == refs_before


def test_dry_run_never_fetches_or_mutates_git_refs(repositories, monkeypatch) -> None:
    import creator_os_core.runtime_promotion as promotion

    source, runtime, *_rest = repositories
    source_refs = _run("git", "show-ref", cwd=source)
    runtime_refs = _run("git", "show-ref", cwd=runtime)
    commands: list[tuple[str, ...]] = []
    original = promotion._run

    def record(command, *, cwd, environment=None):
        commands.append(tuple(command))
        return original(command, cwd=cwd, environment=environment)

    monkeypatch.setattr(promotion, "_run", record)
    _promote(repositories, dry_run=True)

    assert not any("fetch" in command or "pull" in command for command in commands)
    assert _run("git", "show-ref", cwd=source) == source_refs
    assert _run("git", "show-ref", cwd=runtime) == runtime_refs
    assert not repositories[-1].exists()


def test_approval_rejects_duplicate_check_run_identity(repositories) -> None:
    approval_path = repositories[4]
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["checks"][1]["checkRunId"] = approval["checks"][0]["checkRunId"]
    core = dict(approval)
    core.pop("approvalFingerprint")
    approval["approvalFingerprint"] = _fingerprint(core)
    approval_path.write_text(json.dumps(approval), encoding="utf-8")

    with pytest.raises(RuntimePromotionError, match="check_run_identity_invalid"):
        load_runtime_promotion_approval(approval_path)


def test_exact_approval_payload_handoff_does_not_reread_path(
    repositories, monkeypatch
) -> None:
    import creator_os_core.runtime_promotion as promotion

    approval = load_runtime_promotion_approval(repositories[4])
    monkeypatch.setattr(
        promotion,
        "load_runtime_promotion_approval",
        lambda _path: (_ for _ in ()).throw(AssertionError("approval reread")),
    )
    plan = _promote(repositories, dry_run=True, approval_payload=approval)
    assert plan["approvalFingerprint"] == approval["approvalFingerprint"]


def test_public_promotion_path_has_no_injectable_safety_overrides() -> None:
    parameters = set(inspect.signature(promote_runtime).parameters)
    assert "verifier_command" not in parameters
    assert "health_command" not in parameters
    assert "approval_evidence_verifier" not in parameters


@pytest.mark.parametrize(
    "nested", ["source_in_runtime", "runtime_in_source", "state_parent"]
)
def test_promotion_rejects_every_nested_root_alias(repositories, nested: str) -> None:
    source, runtime, _first, second, approval, state = repositories
    if nested == "source_in_runtime":
        source = runtime / "nested-source"
    elif nested == "runtime_in_source":
        runtime = source / "nested-runtime"
    else:
        state = source.parent
    with pytest.raises(RuntimePromotionError, match="path_boundary_invalid"):
        _promote_runtime(
            source_root=source,
            runtime_root=runtime,
            approved_commit=second,
            approval_path=approval,
            state_root=state,
            operator="operator",
            dry_run=True,
            verifier_command=(sys.executable, "-c", "raise SystemExit(0)"),
            health_command=(sys.executable, "-c", "raise SystemExit(0)"),
            approval_evidence_verifier=lambda _source, _approval: {
                "evidenceFingerprint": "e" * 64
            },
        )


def test_unmerged_commit_is_rejected_even_when_locally_present(repositories) -> None:
    source, runtime, _first, _second, _approval_path, state = repositories
    (source / "value.txt").write_text("unmerged", encoding="utf-8")
    _run("git", "add", "value.txt", cwd=source)
    _run("git", "commit", "-m", "unmerged", cwd=source)
    unmerged = _run("git", "rev-parse", "HEAD", cwd=source)
    approval = _approval(state.parent / "unmerged-approval.json", unmerged)

    with pytest.raises(RuntimePromotionError, match="approved_commit_not_origin_main"):
        _promote_runtime(
            source_root=source,
            runtime_root=runtime,
            approved_commit=unmerged,
            approval_path=approval,
            state_root=state,
            operator="operator",
            dry_run=True,
            approval_evidence_verifier=lambda _source, _approval: {
                "evidenceFingerprint": "e" * 64
            },
            verifier_command=(sys.executable, "-c", "raise SystemExit(0)"),
            health_command=(sys.executable, "-c", "raise SystemExit(0)"),
        )


def test_live_github_evidence_binds_merge_review_and_checks(
    repositories, monkeypatch
) -> None:
    source, _runtime, _first, second, approval_path, _state = repositories
    approval = load_runtime_promotion_approval(approval_path)
    checks = [
        {
            "id": item["checkRunId"],
            "name": item["name"],
            "status": "completed",
            "conclusion": "success",
            "details_url": item["detailsUrl"],
            "completed_at": item["completedAt"],
            "head_sha": second,
            "app": {"id": item["appId"], "slug": item["appSlug"]},
        }
        for item in approval["checks"]
    ]
    permission = {"value": "write"}
    workflow_path_override = {"value": None}

    def api(_source, endpoint):
        if endpoint.endswith("/collaborators/reviewer/permission"):
            return {"permission": permission["value"]}
        if endpoint.endswith("/reviews?per_page=100"):
            return [
                {
                    "id": 42,
                    "state": "APPROVED",
                    "user": {"login": "reviewer"},
                    "submitted_at": "2020-01-01T00:30:00Z",
                    "commit_id": second,
                }
            ]
        if endpoint.endswith("/check-runs?per_page=100"):
            return {"check_runs": checks}
        if "/actions/runs/" in endpoint:
            run_id = int(endpoint.rsplit("/", 1)[-1])
            expected = next(
                item for item in approval["checks"] if item["workflowRunId"] == run_id
            )
            return {
                "id": run_id,
                "name": expected["workflowName"],
                "path": workflow_path_override["value"] or expected["workflowPath"],
                "head_sha": second,
                "status": "completed",
                "conclusion": "success",
                "repository": {"full_name": "example/creator-os"},
                "head_repository": {"full_name": "example/creator-os"},
            }
        return {
            "merged_at": "2020-01-01T00:45:00Z",
            "merge_commit_sha": second,
            "head": {"sha": second},
            "user": {"login": "author"},
        }

    monkeypatch.setattr("creator_os_core.runtime_promotion._github_api_json", api)
    evidence = _verify_github_approval_evidence(source, approval)
    assert evidence["approvedCommit"] == second
    assert len(evidence["checkRunIds"]) == len(REQUIRED_CHECKS)
    assert evidence["reviewerPermission"] == "write"

    permission["value"] = "read"
    with pytest.raises(RuntimePromotionError, match="reviewer_permission_insufficient"):
        _verify_github_approval_evidence(source, approval)
    permission["value"] = "write"
    checks[0]["app"] = {"id": 1, "slug": "lookalike-actions"}
    with pytest.raises(RuntimePromotionError, match="check_not_live_verified"):
        _verify_github_approval_evidence(source, approval)
    checks[0]["app"] = {
        "id": TRUSTED_CHECK_APP_ID,
        "slug": TRUSTED_CHECK_APP_SLUG,
    }
    workflow_path_override["value"] = ".github/workflows/lookalike.yml"
    with pytest.raises(RuntimePromotionError, match="workflow_not_live_verified"):
        _verify_github_approval_evidence(source, approval)
    workflow_path_override["value"] = None
    approval["checks"][0]["checkRunId"] = 999_999
    with pytest.raises(RuntimePromotionError, match="check_not_live_verified"):
        _verify_github_approval_evidence(source, approval)
    approval["checks"][0]["checkRunId"] = checks[0]["id"]
    approval["review"]["reviewId"] = 999_999
    with pytest.raises(
        RuntimePromotionError, match="review_not_independent_or_current"
    ):
        _verify_github_approval_evidence(source, approval)


def test_live_github_evidence_rejects_self_review(repositories, monkeypatch) -> None:
    source, _runtime, _first, second, approval_path, _state = repositories
    approval = load_runtime_promotion_approval(approval_path)

    def api(_source, endpoint):
        if endpoint.endswith("/collaborators/reviewer/permission"):
            return {"permission": "write"}
        if endpoint.endswith("/reviews?per_page=100"):
            return [
                {
                    "id": 42,
                    "state": "APPROVED",
                    "user": {"login": "reviewer"},
                    "submitted_at": "2020-01-01T00:30:00Z",
                    "commit_id": second,
                }
            ]
        if endpoint.endswith("/check-runs?per_page=100"):
            return {"check_runs": []}
        return {
            "merged_at": "2020-01-01T00:45:00Z",
            "merge_commit_sha": second,
            "head": {"sha": second},
            "user": {"login": "reviewer"},
        }

    monkeypatch.setattr("creator_os_core.runtime_promotion._github_api_json", api)
    with pytest.raises(
        RuntimePromotionError, match="review_not_independent_or_current"
    ):
        _verify_github_approval_evidence(source, approval)


def test_single_owner_ci_evidence_binds_actor_policy_merge_and_checks(
    repositories,
    monkeypatch,
) -> None:
    source, _runtime, _first, second, approval_path, _state = repositories
    approval = load_runtime_promotion_approval(
        _single_owner_approval(approval_path, second)
    )
    validate_runtime_promotion_approval(approval)
    checks = [
        {
            "id": item["checkRunId"],
            "name": item["name"],
            "status": "completed",
            "conclusion": "success",
            "details_url": item["detailsUrl"],
            "completed_at": item["completedAt"],
            "head_sha": second,
            "app": {"id": item["appId"], "slug": item["appSlug"]},
        }
        for item in approval["checks"]
    ]
    actor = {"login": "owner"}
    review_count = {"value": 0}

    def api(_source, endpoint):
        if endpoint == "user":
            return actor
        if endpoint.endswith("/collaborators/owner/permission"):
            return {"permission": "admin"}
        if endpoint.endswith("/branches/main/protection"):
            return {
                "required_status_checks": {
                    "strict": True,
                    "checks": [
                        {"context": name}
                        for name in approval["branchProtection"]["requiredStatusChecks"]
                    ],
                },
                "required_pull_request_reviews": {
                    "required_approving_review_count": review_count["value"]
                },
                "required_conversation_resolution": {"enabled": True},
                "enforce_admins": {"enabled": True},
            }
        if endpoint.endswith("/check-runs?per_page=100"):
            return {"check_runs": checks}
        if "/actions/runs/" in endpoint:
            run_id = int(endpoint.rsplit("/", 1)[-1])
            expected = next(
                item for item in approval["checks"] if item["workflowRunId"] == run_id
            )
            return {
                "id": run_id,
                "name": expected["workflowName"],
                "path": expected["workflowPath"],
                "head_sha": second,
                "status": "completed",
                "conclusion": "success",
                "repository": {"full_name": "example/creator-os"},
                "head_repository": {"full_name": "example/creator-os"},
            }
        return {
            "merged_at": "2020-01-01T00:45:00Z",
            "merge_commit_sha": second,
            "head": {"sha": second},
            "user": {"login": "owner"},
        }

    monkeypatch.setattr("creator_os_core.runtime_promotion._github_api_json", api)
    evidence = _verify_github_approval_evidence(source, approval)
    assert evidence["approvalMode"] == "single_owner_ci"
    assert evidence["operator"] == "owner"
    assert evidence["operatorPermission"] == "admin"
    assert evidence["branchProtection"] == approval["branchProtection"]

    actor["login"] = "different-user"
    with pytest.raises(RuntimePromotionError, match="operator_identity_mismatch"):
        _verify_github_approval_evidence(source, approval)
    actor["login"] = "owner"
    review_count["value"] = 1
    with pytest.raises(RuntimePromotionError, match="branch_protection"):
        _verify_github_approval_evidence(source, approval)


def test_single_owner_ci_rejects_weakened_declared_policy_and_operator_mismatch(
    repositories,
) -> None:
    source, runtime, _first, second, approval_path, state = repositories
    approval_path = _single_owner_approval(approval_path, second)
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    payload["branchProtection"]["requiredStatusChecks"].remove("CodeQL (python)")
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimePromotionError, match="branch_protection_missing_checks"):
        load_runtime_promotion_approval(approval_path)

    approval_path = _single_owner_approval(approval_path, second)
    with pytest.raises(RuntimePromotionError, match="operator_identity_mismatch"):
        _promote_runtime(
            source_root=source,
            runtime_root=runtime,
            approved_commit=second,
            approval_path=approval_path,
            state_root=state,
            operator="someone-else",
            dry_run=True,
            verifier_command=(sys.executable, "-c", "raise SystemExit(0)"),
            health_command=(sys.executable, "-c", "raise SystemExit(0)"),
            approval_evidence_verifier=lambda _source, _approval: {
                "evidenceFingerprint": "e" * 64
            },
        )


def test_single_owner_ci_receipt_remains_contract_valid(repositories) -> None:
    _source, _runtime, _first, second, approval_path, _state = repositories
    approval = load_runtime_promotion_approval(
        _single_owner_approval(approval_path, second)
    )
    evidence_core = {
        "approvalMode": "single_owner_ci",
        "repository": approval["repository"],
        "pullRequestNumber": approval["pullRequestNumber"],
        "approvedCommit": approval["approvedCommit"],
        "reviewedCommit": approval["reviewedCommit"],
        "operator": approval["operator"],
        "operatorPermission": "admin",
        "branchProtection": approval["branchProtection"],
        "trustedCheckApp": "github-actions:15368",
        "checkRunIds": sorted(item["checkRunId"] for item in approval["checks"]),
        "workflowRunIds": sorted(
            {item["workflowRunId"] for item in approval["checks"]}
        ),
    }
    evidence = {
        **evidence_core,
        "evidenceFingerprint": _fingerprint(evidence_core),
    }
    receipt = _promote(
        repositories,
        approval_evidence_verifier=lambda _source, _approval: evidence,
        approval_payload=approval,
        operator="owner",
    )
    validate_runtime_promotion_receipt(receipt)
    assert receipt["approvalEvidence"]["approvalMode"] == "single_owner_ci"
    assert _validate_runtime_promotion_receipt_payload(receipt) == receipt


def test_dirty_source_is_rejected(repositories) -> None:
    source, _runtime, *_rest = repositories
    (source / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(RuntimePromotionError, match="source_dirty"):
        _promote(repositories)


def test_wrong_approved_commit_is_rejected(repositories) -> None:
    source, runtime, _first, second, approval, state = repositories
    payload = json.loads(approval.read_text())
    payload["approvedCommit"] = "0" * 40
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    approval.write_text(json.dumps(payload))
    with pytest.raises(RuntimePromotionError, match="approval_commit_mismatch"):
        promote_runtime(
            source_root=source,
            runtime_root=runtime,
            approved_commit=second,
            approval_path=approval,
            state_root=state,
            operator="operator",
            dry_run=False,
        )


def test_failed_verifier_rolls_back_and_preserves_receipt(repositories) -> None:
    _source, runtime, first, _second, _approval_path, state = repositories
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            verifier=(sys.executable, "-c", "raise SystemExit(7)"),
        )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    receipts = list((state / "receipts").glob("*.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["status"] == "rolled_back"
    transactions = list((state / "transactions").glob("*.json"))
    assert len(transactions) == 1
    assert json.loads(transactions[0].read_text())["status"] == "rolled_back"


def test_failed_verifier_receipt_has_only_bounded_redacted_diagnostics(
    repositories,
    monkeypatch,
) -> None:
    _source, _runtime, _first, _second, _approval_path, state = repositories
    secret = "unit-test-secret-value-that-must-not-survive"
    monkeypatch.setenv("UNIT_TEST_API_TOKEN", secret)
    verifier = state.parent / "failing-verifier.py"
    verifier.write_text(
        "import sys\n"
        "print('x' * 5000)\n"
        f"print({secret!r})\n"
        f"print('Authorization: Bearer {secret}', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            verifier=(sys.executable, str(verifier)),
        )

    receipt = json.loads(next((state / "receipts").glob("*.json")).read_text())
    validate_runtime_promotion_receipt(receipt)
    full_verify = next(
        item for item in receipt["verification"] if item["name"] == "full_verify"
    )
    assert full_verify["returnCode"] == 7
    assert full_verify["passed"] is False
    assert full_verify["diagnosticTailLimit"] == DIAGNOSTIC_TAIL_MAX_CHARS
    assert len(full_verify["stdoutTail"]) <= DIAGNOSTIC_TAIL_MAX_CHARS
    assert len(full_verify["stderrTail"]) <= DIAGNOSTIC_TAIL_MAX_CHARS
    assert secret not in full_verify["stdoutTail"]
    assert secret not in full_verify["stderrTail"]
    assert "<redacted>" in full_verify["stdoutTail"]
    assert "<redacted>" in full_verify["stderrTail"]


def test_legacy_committed_journal_with_rolled_back_receipt_is_recovered(
    repositories,
) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, _second, _approval_path, state = repositories
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            verifier=(sys.executable, "-c", "raise SystemExit(7)"),
        )
    transaction_path = next((state / "transactions").glob("*.json"))
    transaction = promotion._load_transaction_journal(transaction_path)
    promotion._transaction_update(
        transaction_path,
        transaction,
        status="committed",
        receipt_fingerprint=str(transaction["receiptFingerprint"]),
    )

    receipt = _promote(repositories)

    recovered = promotion._load_transaction_journal(transaction_path)
    assert recovered["status"] == "rolled_back"
    assert recovered["failure"] == (
        "RuntimePromotionError:runtime_post_promotion_full_verify_failed"
    )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == receipt["sourceCommit"]
    assert receipt["destinationCommitBefore"] == first


def test_failed_health_rolls_back(repositories) -> None:
    _source, runtime, first, *_rest = repositories
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            health=(sys.executable, "-c", "raise SystemExit(8)"),
        )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_exit_zero_with_nonpassing_health_report_rolls_back(repositories) -> None:
    _source, runtime, first, *_rest = repositories
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            health=(
                sys.executable,
                "-c",
                "import json; print(json.dumps([{'name':'runtime','status':'WARN'}]))",
            ),
        )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_incomplete_all_pass_health_inventory_rolls_back(repositories) -> None:
    _source, runtime, first, *_rest = repositories
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            health=(
                sys.executable,
                "-c",
                "import json; print(json.dumps([{'name':'runtime','status':'PASS'}]))",
            ),
        )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_promoted_commands_receive_only_allowlisted_environment(
    repositories, monkeypatch
) -> None:
    source, _runtime, *_rest = repositories
    source_venv_bin = source / ".venv" / "bin"
    source_venv_bin.mkdir(parents=True)
    inherited_path = os.environ["PATH"]
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(source_venv_bin), inherited_path)),
    )
    monkeypatch.setenv("SHOULD_NOT_REACH_PROMOTED_CODE_TOKEN", "sensitive")
    monkeypatch.setenv("VIRTUAL_ENV", str(source / ".venv"))
    verifier = (
        sys.executable,
        "-c",
        (
            "import os, shutil; "
            "blocked={'CREATOR_OS_EVIDENCE_AUTH_SECRET',"
            "'SHOULD_NOT_REACH_PROMOTED_CODE_TOKEN','VIRTUAL_ENV'}; "
            "raise SystemExit(0 if blocked.isdisjoint(os.environ) "
            f"and {str(source_venv_bin)!r} not in os.environ.get('PATH','') "
            "and all(shutil.which(tool) for tool in "
            f"{PROMOTED_REQUIRED_EXECUTABLES!r}) else 9)"
        ),
    )
    receipt = _promote(repositories, verifier=verifier)
    assert receipt["status"] == "promoted"


def test_promoted_environment_preserves_unrelated_node_and_system_paths(
    tmp_path: Path,
) -> None:
    def executable(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    source = tmp_path / "source"
    source_venv_bin = source / ".venv" / "bin"
    source_venv_bin.mkdir(parents=True)
    source_venv_alias = tmp_path / "source-venv-alias"
    source_venv_alias.symlink_to(source_venv_bin, target_is_directory=True)
    source_named_venv_bin = source / "venv" / "bin"
    source_tools_bin = source / "tools" / "bin"
    activated_venv_bin = tmp_path / "activated-source-venv" / "bin"
    node_24_bin = tmp_path / "node-24" / "bin"
    node_modules_bin = tmp_path / "node_modules" / ".bin"
    unrelated_bin = tmp_path / "unrelated-tools" / "bin"
    system_bin = tmp_path / "system" / "bin"
    for name in ("node", "pnpm"):
        executable(node_24_bin / name)
    for name in ("git", "make", "python3", "uv"):
        executable(system_bin / name)
    original_path = os.pathsep.join(
        (
            str(source_venv_bin),
            str(source_venv_alias),
            str(source_named_venv_bin),
            str(source_tools_bin),
            str(node_24_bin),
            str(activated_venv_bin),
            str(node_modules_bin),
            "relative/bin",
            str(unrelated_bin),
            str(node_24_bin),
            str(system_bin),
        )
    )

    environment = _promoted_subprocess_environment(
        source_root=source,
        environ={
            "CONDA_PREFIX": str(tmp_path / "conda"),
            "PATH": original_path,
            "PIPENV_ACTIVE": "1",
            "PYTHONHOME": str(source / ".venv"),
            "PYTHONPATH": str(source),
            "UV_PROJECT_ENVIRONMENT": str(tmp_path / "uv-environment"),
            "VIRTUAL_ENV": str(activated_venv_bin.parent),
        },
    )

    assert PROMOTED_ENV_BLOCKLIST.isdisjoint(environment)
    assert environment["PATH"].split(os.pathsep) == [
        str(node_24_bin),
        str(unrelated_bin),
        str(system_bin),
    ]
    assert all(
        shutil.which(executable_name, path=environment["PATH"])
        for executable_name in PROMOTED_REQUIRED_EXECUTABLES
    )


def _fake_toolchain(
    tmp_path: Path,
    *,
    node_version: str,
) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "package.json").write_text(
        json.dumps({"engines": {"node": "22.x || 24.x || >=26"}}),
        encoding="utf-8",
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    versions = {
        "git": "git version 2.50.0",
        "make": "GNU Make 3.81",
        "node": node_version,
        "pnpm": "11.6.0",
        "python3": "Python 3.12.11",
        "uv": "uv 0.11.7",
    }
    for name, version in versions.items():
        path = tools / name
        path.write_text(
            f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(version)}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
    return source, {"PATH": str(tools)}


def test_promoted_toolchain_accepts_supported_node_24_path(
    tmp_path: Path,
) -> None:
    source, environment = _fake_toolchain(tmp_path, node_version="v24.14.0")

    evidence = _resolved_promoted_toolchain_evidence(
        source_root=source,
        environment=environment,
    )

    assert evidence["nodeEngine"] == "22.x || 24.x || >=26"
    assert evidence["nodeMajor"] == 24
    assert {tool["name"] for tool in evidence["tools"]} == set(
        PROMOTED_REQUIRED_EXECUTABLES
    )
    assert len(evidence["evidenceFingerprint"]) == 64


def test_promoted_toolchain_rejects_node_25(tmp_path: Path) -> None:
    source, environment = _fake_toolchain(tmp_path, node_version="v25.9.0")

    with pytest.raises(
        RuntimePromotionError,
        match=r"node_version_unsupported:v25\.9\.0",
    ):
        _resolved_promoted_toolchain_evidence(
            source_root=source,
            environment=environment,
        )


def test_promoted_environment_fails_closed_when_required_tool_is_missing(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    for name in set(PROMOTED_REQUIRED_EXECUTABLES) - {"pnpm"}:
        path = tools / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    with pytest.raises(
        RuntimePromotionError,
        match="runtime_promotion_required_executable_missing:pnpm",
    ):
        _promoted_subprocess_environment(
            source_root=tmp_path / "source",
            environ={"PATH": str(tools)},
        )


def test_promoted_environment_rejects_required_tool_symlinked_into_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source_tools = source / "tools" / "bin"
    clean_tools = tmp_path / "clean-tools"
    source_tools.mkdir(parents=True)
    clean_tools.mkdir()
    for name in PROMOTED_REQUIRED_EXECUTABLES:
        path = source_tools / name if name == "node" else clean_tools / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    (clean_tools / "node").symlink_to(source_tools / "node")

    with pytest.raises(
        RuntimePromotionError,
        match="runtime_promotion_required_executable_unsafe:node",
    ):
        _promoted_subprocess_environment(
            source_root=source,
            environ={"PATH": str(clean_tools)},
        )


def test_promoted_environment_is_validated_before_runtime_mutation(
    repositories, monkeypatch
) -> None:
    _source, runtime, first, *_rest = repositories

    def reject_environment(*, source_root, environ=None):
        raise RuntimePromotionError("runtime_promotion_required_executable_missing:uv")

    monkeypatch.setattr(
        "creator_os_core.runtime_promotion._promoted_subprocess_environment",
        reject_environment,
    )

    with pytest.raises(
        RuntimePromotionError,
        match="runtime_promotion_required_executable_missing:uv",
    ):
        _promote(repositories)

    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_promoted_toolchain_is_validated_before_runtime_mutation(
    repositories, monkeypatch
) -> None:
    _source, runtime, first, *_rest = repositories

    def reject_toolchain(*, source_root, environment):
        raise RuntimePromotionError(
            "runtime_promotion_node_version_unsupported:v25.9.0:"
            "required=22.x || 24.x || >=26"
        )

    monkeypatch.setattr(
        "creator_os_core.runtime_promotion._resolved_promoted_toolchain_evidence",
        reject_toolchain,
    )

    with pytest.raises(
        RuntimePromotionError,
        match="runtime_promotion_node_version_unsupported",
    ):
        _promote(repositories)

    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_runtime_must_start_detached(repositories) -> None:
    _source, runtime, _first, *_rest = repositories
    _run("git", "checkout", "main", cwd=runtime)
    with pytest.raises(RuntimePromotionError, match="runtime_not_detached"):
        _promote(repositories, dry_run=True)


def test_runtime_scoped_lock_blocks_different_state_roots(repositories) -> None:
    from creator_os_core.fileops import file_lock

    _source, runtime, *_rest = repositories
    alternate_state = repositories[-1].parent / "alternate-state"
    outcome: list[object] = []

    def run() -> None:
        try:
            outcome.append(_promote(repositories, state_override=alternate_state))
        except BaseException as exc:  # pragma: no cover - asserted below
            outcome.append(exc)

    with file_lock(_runtime_lock_target(runtime.resolve())):
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(0.2)
        assert worker.is_alive()
        assert not outcome
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert outcome and isinstance(outcome[0], dict)


def test_runtime_lock_symlink_is_rejected(repositories, tmp_path: Path) -> None:
    _source, runtime, *_rest = repositories
    target = _runtime_lock_target(runtime.resolve())
    lock_path = target.with_name(target.name + ".lock")
    outside = tmp_path / "outside-lock"
    outside.write_text("unchanged", encoding="utf-8")
    lock_path.symlink_to(outside)
    with pytest.raises(RuntimePromotionError, match="lock_path_unsafe"):
        _promote(repositories)
    assert outside.read_text(encoding="utf-8") == "unchanged"


def test_authority_is_refreshed_under_lock_before_mutation(repositories) -> None:
    calls = 0

    def evidence(_source, exact):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimePromotionError("review_was_dismissed")
        core = {
            "repository": exact["repository"],
            "pullRequestNumber": exact["pullRequestNumber"],
            "approvedCommit": exact["approvedCommit"],
            "reviewedCommit": exact["reviewedCommit"],
            "reviewId": exact["review"]["reviewId"],
            "reviewerPermission": "write",
            "trustedCheckApp": "github-actions:15368",
            "checkRunIds": sorted(item["checkRunId"] for item in exact["checks"]),
            "workflowRunIds": sorted(
                {item["workflowRunId"] for item in exact["checks"]}
            ),
        }
        return {**core, "evidenceFingerprint": _fingerprint(core)}

    _source, runtime, first, *_rest = repositories
    with pytest.raises(RuntimePromotionError, match="review_was_dismissed"):
        _promote(repositories, approval_evidence_verifier=evidence)
    assert calls == 2
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


@pytest.mark.parametrize("subroot", ["backups", "transactions", "receipts"])
def test_state_subroot_symlink_is_rejected_before_write(
    repositories, tmp_path: Path, subroot: str
) -> None:
    state = repositories[-1]
    state.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (state / subroot).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimePromotionError, match=rf"{subroot}_path_unsafe"):
        _promote(repositories)
    assert not list(outside.iterdir())


def test_state_root_symlink_is_rejected(repositories, tmp_path: Path) -> None:
    outside = tmp_path / "outside-state"
    outside.mkdir()
    alias = tmp_path / "state-alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimePromotionError, match="state_root_unsafe"):
        _promote(repositories, state_override=alias)


def test_repeated_promotion_runs_fresh_verification_and_writes_new_receipt(
    repositories, tmp_path: Path
) -> None:
    marker = tmp_path / "health-calls.txt"
    rows = [
        {"name": name, "status": "PASS"} for name in sorted(REQUIRED_LIVE_HEALTH_CHECKS)
    ]
    health = (
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import json; "
            f"p=Path({str(marker)!r}); "
            "p.write_text((p.read_text() if p.exists() else '') + 'x'); "
            f"print(json.dumps({rows!r}))"
        ),
    )
    first = _promote(repositories, health=health)
    second = _promote(repositories, health=health)
    assert first["promotionId"] != second["promotionId"]
    assert second["status"] == "already_current"
    assert marker.read_text() == "xx"
    assert len(list((repositories[-1] / "receipts").glob("*.json"))) == 2


def test_receipt_validation_failure_rolls_runtime_back(repositories) -> None:
    _source, runtime, first, *_rest = repositories

    def reject(_receipt) -> None:
        raise ValueError("schema rejected")

    with pytest.raises(RuntimePromotionError, match="receipt_failed_and_rolled_back"):
        _promote(repositories, receipt_validator=reject)
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not list((repositories[-1] / "receipts").glob("*.json"))


def test_repeated_promotion_does_not_hide_new_health_failure(repositories) -> None:
    _source, runtime, _first, approved, *_rest = repositories
    _promote(repositories)
    with pytest.raises(RuntimePromotionError, match="runtime_promotion_rolled_back"):
        _promote(
            repositories,
            health=(sys.executable, "-c", "raise SystemExit(9)"),
        )
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == approved


def test_receipt_write_failure_rolls_runtime_back(repositories, monkeypatch) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, *_rest = repositories
    original = promotion.atomic_write_json

    def fail_receipt(path, payload):
        if Path(path).parent.name == "receipts":
            raise OSError("disk unavailable")
        return original(path, payload)

    monkeypatch.setattr(promotion, "atomic_write_json", fail_receipt)
    with pytest.raises(RuntimePromotionError, match="receipt_failed_and_rolled_back"):
        _promote(repositories)
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first


def test_terminal_journal_failure_after_receipt_write_rolls_back_and_cleans_receipt(
    repositories, monkeypatch
) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, *_rest, state = repositories
    original = promotion._transaction_update
    failed = {"committed": False}

    def fail_committed(path, record, *, status, failure=None, receipt_fingerprint=None):
        if status == "committed" and not failed["committed"]:
            failed["committed"] = True
            raise OSError("transaction journal disk unavailable")
        return original(
            path,
            record,
            status=status,
            failure=failure,
            receipt_fingerprint=receipt_fingerprint,
        )

    monkeypatch.setattr(promotion, "_transaction_update", fail_committed)
    with pytest.raises(RuntimePromotionError, match="receipt_failed_and_rolled_back"):
        _promote(repositories)

    assert failed["committed"] is True
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not list((state / "receipts").glob("*.json"))
    transactions = list((state / "transactions").glob("*.json"))
    assert len(transactions) == 1
    assert promotion._load_transaction_journal(transactions[0])["status"] == (
        "rolled_back"
    )


def test_receipt_construction_failure_after_checkout_rolls_runtime_back(
    repositories, monkeypatch
) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, *_rest, state = repositories
    original = promotion.sign_evidence_attestation

    def fail_receipt(payload, *, issuer, issued_at, secret):
        if issuer == "creator_os.runtime_promotion":
            raise OSError("receipt signer unavailable")
        return original(
            payload,
            issuer=issuer,
            issued_at=issued_at,
            secret=secret,
        )

    monkeypatch.setattr(promotion, "sign_evidence_attestation", fail_receipt)
    with pytest.raises(RuntimePromotionError, match="receipt_failed_and_rolled_back"):
        _promote(repositories)

    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not list((state / "receipts").glob("*.json"))
    transaction_path = next((state / "transactions").glob("*.json"))
    assert promotion._load_transaction_journal(transaction_path)["status"] == (
        "rolled_back"
    )


def test_incomplete_transaction_is_recovered_before_new_promotion(
    repositories, monkeypatch
) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, approved, _approval_path, state = repositories
    transaction_path, _promotion_id = _seed_incomplete_transaction(
        state=state,
        runtime=runtime,
        before=first,
        approved=approved,
    )
    _run("git", "fetch", "origin", cwd=runtime)
    _run("git", "checkout", "--detach", approved, cwd=runtime)
    real_commit_exists = promotion._commit_exists
    forced_missing = {"done": False}

    def commit_exists(repo, commit):
        if commit == first and not forced_missing["done"]:
            forced_missing["done"] = True
            return False
        return real_commit_exists(repo, commit)

    monkeypatch.setattr(promotion, "_commit_exists", commit_exists)

    receipt = _promote(repositories)

    recovered = promotion._load_transaction_journal(transaction_path)
    assert recovered["status"] == "recovered_rollback"
    assert forced_missing["done"] is True
    assert receipt["destinationCommitBefore"] == first
    assert receipt["destinationCommitAfter"] == approved


def test_receipt_wins_recovery_if_crash_preceded_terminal_journal(repositories) -> None:
    import creator_os_core.runtime_promotion as promotion

    first_receipt = _promote(repositories)
    state = repositories[-1]
    transaction_path = state / "transactions" / f"{first_receipt['promotionId']}.json"
    transaction = promotion._load_transaction_journal(transaction_path)
    promotion._transaction_update(
        transaction_path,
        transaction,
        status="receipt_pending",
    )

    second_receipt = _promote(repositories)

    recovered = promotion._load_transaction_journal(transaction_path)
    assert recovered["status"] == "recovered_committed"
    assert second_receipt["status"] == "already_current"


def test_receipt_tampering_is_rejected(repositories) -> None:
    receipt = _promote(repositories)
    receipt_path = next((repositories[-1] / "receipts").glob("*.json"))
    payload = json.loads(receipt_path.read_text())
    payload["operator"] = "attacker"
    receipt_path.write_text(json.dumps(payload))
    assert receipt["operator"] == "operator"
    with pytest.raises(RuntimePromotionError, match="receipt_tampered"):
        _promote(repositories)


def test_receipt_recomputed_checksum_cannot_forge_attestation(repositories) -> None:
    _promote(repositories)
    receipt_path = next((repositories[-1] / "receipts").glob("*.json"))
    payload = json.loads(receipt_path.read_text())
    payload["operator"] = "attacker"
    semantic = dict(payload)
    semantic.pop("producerAttestation")
    semantic.pop("receiptFingerprint")
    payload["receiptFingerprint"] = _fingerprint(semantic)
    receipt_path.write_text(json.dumps(payload))
    with pytest.raises(RuntimePromotionError, match="attestation_invalid"):
        _promote(repositories)


def test_malformed_receipt_cannot_be_hidden_from_global_scan(repositories) -> None:
    _promote(repositories)
    receipt_path = next((repositories[-1] / "receipts").iterdir())
    receipt_path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimePromotionError, match="receipt_unreadable"):
        _promote(repositories)


def test_committed_journal_cannot_outlive_its_receipt(repositories) -> None:
    _promote(repositories)
    receipt_path = next((repositories[-1] / "receipts").iterdir())
    receipt_path.unlink()
    with pytest.raises(RuntimePromotionError, match="committed_receipt_missing"):
        _promote(repositories)


def test_renamed_or_symlinked_receipt_is_rejected(repositories) -> None:
    _promote(repositories)
    receipt_root = repositories[-1] / "receipts"
    receipt_path = next(receipt_root.iterdir())
    renamed = receipt_root / f"{uuid.uuid4()}.json"
    receipt_path.rename(renamed)
    with pytest.raises(RuntimePromotionError, match="committed_receipt_missing"):
        _promote(repositories)

    renamed.unlink()
    receipt_path.symlink_to(repositories[4])
    with pytest.raises(RuntimePromotionError, match="receipt_path_unsafe"):
        _promote(repositories)


def test_failed_backup_halts_before_runtime_change(repositories, monkeypatch) -> None:
    import creator_os_core.runtime_promotion as promotion

    _source, runtime, first, *_rest = repositories
    original = promotion._git

    def fail_bundle(repo, *args, code):
        if args[:2] == ("bundle", "create"):
            raise RuntimePromotionError("runtime_backup_failed")
        return original(repo, *args, code=code)

    monkeypatch.setattr(promotion, "_git", fail_bundle)
    with pytest.raises(RuntimePromotionError, match="runtime_backup_failed"):
        _promote(repositories)
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
