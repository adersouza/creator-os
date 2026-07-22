from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from campaign_factory.creative_approval import (
    CreativeApprovalError,
    CreativeApprovalStore,
    load_creative_approval,
    validate_creative_approval,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _approval(tmp_path: Path) -> dict:
    source = tmp_path / "source.jpg"
    output = tmp_path / "output.mp4"
    receipt = tmp_path / "qc.json"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    receipt.write_text("{}")
    core = {
        "schema": "campaign_factory.creative_approval.v1",
        "approvalId": "approval-1",
        "approvedBy": "operator",
        "approvedAt": "2026-07-22T12:00:00Z",
        "creatorIdentity": {"id": "stacey", "fingerprint": "a" * 64},
        "contentIntent": {"id": "intent-1", "fingerprint": "b" * 64},
        "benchmarkRecipe": {"id": "recipe-1", "fingerprint": "c" * 64},
        "model": {"id": "local-model", "fingerprint": "d" * 64},
        "input": {"path": str(source), "sha256": _sha(source)},
        "output": {"path": str(output), "sha256": _sha(output)},
        "qcEvidence": [
            {
                "checkId": "contentforge.motion_specific_qc",
                "receiptPath": str(receipt),
                "receiptSha256": _sha(receipt),
                "subjectSha256": _sha(output),
                "passed": True,
            }
        ],
        "exportPayload": {
            "schema": "campaign_draft_payload.v2",
            "fingerprint": "e" * 64,
        },
        "contentSemantics": {
            "burnedOverlayText": None,
            "instagramPostCaption": "caption",
            "generatedAudio": None,
            "sourceAudio": None,
            "nativeInstagramAudio": {"status": "needs_operator_selection"},
        },
    }
    return {**core, "approvalFingerprint": _fingerprint(core)}


def test_creative_approval_binds_every_exact_artifact(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    assert validate_creative_approval(payload) == payload
    store = CreativeApprovalStore(tmp_path / "approvals")
    path = store.record(payload)
    assert load_creative_approval(path) == payload
    assert store.record(payload) == path


def test_creative_approval_rejects_output_substitution(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    Path(payload["output"]["path"]).write_bytes(b"substituted")
    with pytest.raises(CreativeApprovalError, match="output_missing_or_substituted"):
        validate_creative_approval(payload)


def test_creative_approval_rejects_failed_qc(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    payload["qcEvidence"][0]["passed"] = False
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    with pytest.raises(CreativeApprovalError, match="qc_blocked"):
        validate_creative_approval(payload)


def test_creative_approval_rejects_semantic_conflation(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    payload["contentSemantics"].pop("nativeInstagramAudio")
    core = dict(payload)
    core.pop("approvalFingerprint")
    payload["approvalFingerprint"] = _fingerprint(core)
    with pytest.raises(CreativeApprovalError, match="content_semantics_invalid"):
        validate_creative_approval(payload)


def test_creative_approval_rejects_identity_collision(tmp_path: Path) -> None:
    payload = _approval(tmp_path)
    store = CreativeApprovalStore(tmp_path / "approvals")
    path = store.record(payload)
    decoded = json.loads(path.read_text())
    decoded["approvedBy"] = "attacker"
    path.write_text(json.dumps(decoded))
    with pytest.raises(CreativeApprovalError, match="identity_collision"):
        store.record(payload)
