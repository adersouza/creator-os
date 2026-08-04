from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from creator_os_core.recreation_anchor_approval import (
    load_recreation_anchor_approval,
    write_recreation_anchor_approval,
)


def test_anchor_approval_binds_exact_bytes_and_request_lineage(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "anchor.png"
    anchor.write_bytes(b"approved anchor")
    receipt = write_recreation_anchor_approval(
        output_dir=tmp_path / "approvals",
        creator="stacey",
        soul_id="soul-1",
        anchor_generation_id="generation-1",
        anchor_file=anchor,
        prompt_pack_id="prompt-pack-1",
        prompt_pack_fingerprint="a" * 64,
        anchor_prompt_fingerprint="b" * 64,
        creator_image_sha256="c" * 64,
        reference_video_sha256="d" * 64,
        selected_composition_frame_sha256="e" * 64,
        approved_by="operator@test",
        approved_at="2026-07-29T12:00:00Z",
    )

    loaded = load_recreation_anchor_approval(
        Path(receipt["receiptPath"]),
        expected_creator="stacey",
        expected_soul_id="soul-1",
        expected_creator_image_sha256="c" * 64,
        expected_reference_video_sha256="d" * 64,
        expected_prompt_pack_fingerprint="a" * 64,
        expected_anchor_file=Path(receipt["anchorFilePath"]),
    )
    assert loaded["anchorFileSha256"] == hashlib.sha256(anchor.read_bytes()).hexdigest()
    assert Path(loaded["anchorFilePath"]) != anchor

    anchor.write_bytes(b"changed anchor")
    load_recreation_anchor_approval(
        Path(receipt["receiptPath"]),
        expected_creator="stacey",
        expected_soul_id="soul-1",
        expected_creator_image_sha256="c" * 64,
        expected_reference_video_sha256="d" * 64,
        expected_prompt_pack_fingerprint="a" * 64,
    )
    Path(receipt["anchorFilePath"]).write_bytes(b"changed retained anchor")
    with pytest.raises(PermissionError, match="sha_mismatch"):
        load_recreation_anchor_approval(
            Path(receipt["receiptPath"]),
            expected_creator="stacey",
            expected_soul_id="soul-1",
            expected_creator_image_sha256="c" * 64,
            expected_reference_video_sha256="d" * 64,
            expected_prompt_pack_fingerprint="a" * 64,
        )


def test_soul_bound_anchor_approval_requires_no_creator_image(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "anchor.png"
    anchor.write_bytes(b"soul-bound anchor")
    soul_core = {
        "schema": "campaign_factory.verified_soul_identity_binding.v1",
        "creatorSlug": "stacey",
        "provider": "higgsfield",
        "soulId": "soul-1",
        "identityProfileId": "identity-1",
        "identityProfileVersion": 2,
        "identityProfileFingerprint": "f" * 64,
    }
    soul = {
        **soul_core,
        "bindingFingerprint": hashlib.sha256(
            json.dumps(soul_core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    rights = {
        "schema": "reference_factory.provider_rights_eligibility.v1",
        "eligible": True,
        "referenceId": "reference-1",
        "provider": "higgsfield",
        "operation": "recreation_generation",
        "sourceSha256": "d" * 64,
        "rightsEventId": "rights-1",
        "rightsEvidenceFingerprint": "9" * 64,
        "rightsExpiresAt": "2026-08-04T00:00:00Z",
    }
    receipt = write_recreation_anchor_approval(
        output_dir=tmp_path / "approvals",
        creator="stacey",
        soul_id="soul-1",
        anchor_generation_id="generation-1",
        anchor_file=anchor,
        prompt_pack_id="prompt-pack-1",
        prompt_pack_fingerprint="a" * 64,
        anchor_prompt_fingerprint="b" * 64,
        creator_image_sha256=None,
        reference_video_sha256="d" * 64,
        selected_composition_frame_sha256="e" * 64,
        approved_by="operator@test",
        reference_id="reference-1",
        recreation_plan_fingerprint="8" * 64,
        selected_recreation_mode="structural",
        reference_classification="simple_pose_motion",
        reference_provider_rights=rights,
        soul_identity=soul,
    )

    loaded = load_recreation_anchor_approval(
        Path(receipt["receiptPath"]),
        expected_creator="stacey",
        expected_soul_id="soul-1",
        expected_creator_image_sha256=None,
        expected_reference_video_sha256="d" * 64,
        expected_prompt_pack_fingerprint="a" * 64,
        expected_recreation_plan_fingerprint="8" * 64,
        expected_selected_recreation_mode="structural",
        expected_reference_classification="simple_pose_motion",
        expected_reference_provider_rights_fingerprint="9" * 64,
        expected_soul_identity_fingerprint=soul["bindingFingerprint"],
    )
    assert loaded["schema"] == "creator_os.recreation_anchor_approval.v3"
    assert loaded["creatorImageSha256"] is None
    assert loaded["soulIdentity"] == soul
