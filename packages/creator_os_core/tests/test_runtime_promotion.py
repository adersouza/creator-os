from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from creator_os_core.runtime_promotion import (
    REQUIRED_CHECKS,
    RuntimePromotionError,
    promote_runtime,
)


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
        "approvedCommit": commit,
        "reviewedBy": "reviewer",
        "reviewedAt": "2026-07-22T12:00:00Z",
        "checks": [
            {
                "name": name,
                "status": "passed",
                "evidenceFingerprint": hashlib.sha256(name.encode()).hexdigest(),
            }
            for name in sorted(REQUIRED_CHECKS)
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
    (source / "value.txt").write_text("two", encoding="utf-8")
    _run("git", "add", "value.txt", cwd=source)
    _run("git", "commit", "-m", "second", cwd=source)
    _run("git", "push", "origin", "HEAD:main", cwd=source)
    second = _run("git", "rev-parse", "HEAD", cwd=source)
    approval = _approval(tmp_path / "approval.json", second)
    return source, runtime, first, second, approval, tmp_path / "state"


def _promote(repositories, *, verifier=None, health=None, dry_run=False):
    source, runtime, _first, second, approval, state = repositories
    return promote_runtime(
        source_root=source,
        runtime_root=runtime,
        approved_commit=second,
        approval_path=approval,
        state_root=state,
        operator="operator",
        dry_run=dry_run,
        verifier_command=verifier or (sys.executable, "-c", "raise SystemExit(0)"),
        health_command=health
        or (
            sys.executable,
            "-c",
            "import json; print(json.dumps([{'name':'runtime','status':'PASS'}]))",
        ),
    )


def test_promotion_creates_verified_backup_receipt_and_runtime(repositories) -> None:
    _source, runtime, first, second, _approval_path, _state = repositories
    receipt = _promote(repositories)
    assert receipt["status"] == "promoted"
    assert receipt["destinationCommitBefore"] == first
    assert receipt["destinationCommitAfter"] == second
    assert receipt["providerCalls"] == 0
    assert receipt["productionStateWrites"] == 0
    assert Path(receipt["backupManifestPath"]).is_file()
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == second


def test_dry_run_does_not_change_runtime_or_create_state(repositories) -> None:
    _source, runtime, first, _second, _approval_path, state = repositories
    plan = _promote(repositories, dry_run=True)
    assert plan["status"] == "planned"
    assert _run("git", "rev-parse", "HEAD", cwd=runtime) == first
    assert not state.exists()


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


def test_repeated_promotion_returns_same_verified_receipt(repositories) -> None:
    first = _promote(repositories)
    second = _promote(repositories)
    assert first == second


def test_receipt_tampering_is_rejected(repositories) -> None:
    receipt = _promote(repositories)
    receipt_path = next((repositories[-1] / "receipts").glob("*.json"))
    payload = json.loads(receipt_path.read_text())
    payload["operator"] = "attacker"
    receipt_path.write_text(json.dumps(payload))
    assert receipt["operator"] == "operator"
    with pytest.raises(RuntimePromotionError, match="receipt_tampered"):
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
