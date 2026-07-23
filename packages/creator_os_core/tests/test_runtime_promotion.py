from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from creator_os_core.runtime_promotion import (
    REQUIRED_CHECKS,
    REQUIRED_LIVE_HEALTH_CHECKS,
    TRUSTED_CHECK_APP_ID,
    TRUSTED_CHECK_APP_SLUG,
    RuntimePromotionError,
    _promote_runtime,
    _runtime_lock_target,
    _verify_github_approval_evidence,
    load_runtime_promotion_approval,
    promote_runtime,
)

EVIDENCE_SECRET = "runtime-promotion-evidence-secret-longer-than-thirty-two-bytes"


def _health_script() -> str:
    rows = [
        {"name": name, "status": "PASS"} for name in sorted(REQUIRED_LIVE_HEALTH_CHECKS)
    ]
    return f"import json; print(json.dumps({rows!r}))"


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


@pytest.fixture
def repositories(tmp_path: Path):
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", str(origin), cwd=tmp_path)
    source = tmp_path / "source"
    _run("git", "clone", str(origin), str(source), cwd=tmp_path)
    _run("git", "config", "user.email", "test@example.com", cwd=source)
    _run("git", "config", "user.name", "Test", cwd=source)
    (source / "value.txt").write_text("one", encoding="utf-8")
    _run("git", "add", "value.txt", cwd=source)
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
        operator="operator",
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
    assert Path(receipt["backupManifestPath"]).is_file()
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == second


def test_dry_run_does_not_change_runtime_or_create_state(repositories) -> None:
    source, runtime, first, _second, _approval_path, state = repositories
    refs_before = _run("git", "show-ref", cwd=source)
    plan = _promote(repositories, dry_run=True)
    assert plan["status"] == "planned"
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not state.exists()
    assert _run("git", "show-ref", cwd=source) == refs_before


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
    monkeypatch.setenv("SHOULD_NOT_REACH_PROMOTED_CODE_TOKEN", "sensitive")
    verifier = (
        sys.executable,
        "-c",
        (
            "import os; "
            "blocked={'CREATOR_OS_EVIDENCE_AUTH_SECRET',"
            "'SHOULD_NOT_REACH_PROMOTED_CODE_TOKEN'}; "
            "raise SystemExit(0 if blocked.isdisjoint(os.environ) "
            "and os.environ.get('PATH') else 9)"
        ),
    )
    receipt = _promote(repositories, verifier=verifier)
    assert receipt["status"] == "promoted"


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
