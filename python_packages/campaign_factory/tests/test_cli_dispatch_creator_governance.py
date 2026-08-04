from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import campaign_factory.cli_dispatch_creator_governance as subject
from campaign_factory.cli_dispatch_operations import dispatch_operations_commands


def test_identity_enrollment_dispatch_preserves_preview_evidence_binding(
    tmp_path, monkeypatch
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema": "identity.v1"}), encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"reviewed": True}), encoding="utf-8")
    calls = []
    outputs = []

    def enroll(creator, **kwargs):
        calls.append((creator, kwargs))
        return {"creator": creator, "validated": kwargs.get("validate_only", False)}

    cf = SimpleNamespace(
        domains=SimpleNamespace(
            creator_governance=SimpleNamespace(enroll_identity_profile=enroll)
        ),
        conn=None,
    )
    args = SimpleNamespace(
        cmd="creator-identity-enroll",
        creator="stacey",
        provider="higgsfield",
        provider_identity_id="soul-stacey",
        profile_json=str(profile),
        provider_identity_evidence=str(evidence),
        canonical_source_asset_id=None,
        operator="operator@test",
        apply=False,
    )
    monkeypatch.setattr(subject, "print_json", outputs.append)

    assert dispatch_operations_commands(args, cf, None) == 0
    assert outputs == [{"creator": "stacey", "validated": True}]
    assert len(calls) == 1
    creator, enrollment = calls[0]
    assert creator == "stacey"
    assert enrollment["profile"] == {"schema": "identity.v1"}
    assert (
        enrollment["identity_manifest_sha256"]
        == hashlib.sha256(profile.read_bytes()).hexdigest()
    )
    assert (
        enrollment["provider_identity_evidence_sha256"]
        == hashlib.sha256(evidence.read_bytes()).hexdigest()
    )
    assert enrollment["canonical_evidence_type"] == "provider_identity_attestation"
    assert enrollment["validate_only"] is True
