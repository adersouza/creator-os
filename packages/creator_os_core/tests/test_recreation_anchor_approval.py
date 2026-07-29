from __future__ import annotations

import hashlib
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
