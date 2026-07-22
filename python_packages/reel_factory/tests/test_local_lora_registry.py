from __future__ import annotations

import json
from pathlib import Path

import pytest
from reel_factory.local_lora_registry import (
    lora_receipt_path,
    register_local_lora,
    verify_local_lora,
)


def _register(path: Path, *, apply: bool = True) -> dict[str, object]:
    return register_local_lora(
        path,
        lora_id="stacey_motion_v1",
        compatible_model_ids=["local_wan22_ti2v_5b_mlx"],
        license_id="operator-owned",
        source_repository="local/creator-os",
        source_revision="training-run-2026-07-21",
        apply=apply,
    )


def test_registration_is_explicit_revision_and_hash_bound(tmp_path: Path) -> None:
    path = tmp_path / "creator.safetensors"
    path.write_bytes(b"adapter")
    planned = _register(path, apply=False)
    assert planned["status"] == "planned"
    assert not lora_receipt_path(path).exists()
    registered = _register(path)
    assert registered["status"] == "registered"
    verified = verify_local_lora(path, model_id="local_wan22_ti2v_5b_mlx")
    assert verified["verified"] is True
    assert verified["sha256"] == registered["sha256"]


def test_substitution_and_base_model_mismatch_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "creator.safetensors"
    path.write_bytes(b"adapter")
    _register(path)
    path.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="mismatch:sha256"):
        verify_local_lora(path, model_id="local_wan22_ti2v_5b_mlx")

    path.write_bytes(b"adapter")
    receipt = lora_receipt_path(path)
    payload = json.loads(receipt.read_text())
    payload["compatibleModels"] = {"local_wan22_ti2v_5b_mlx": "different-base-revision"}
    receipt.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="base_model_revision_mismatch"):
        verify_local_lora(path, model_id="local_wan22_ti2v_5b_mlx")


def test_cross_family_registration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "creator.safetensors"
    path.write_bytes(b"adapter")
    with pytest.raises(ValueError, match="cannot span Wan and LTX"):
        register_local_lora(
            path,
            lora_id="mixed_family",
            compatible_model_ids=[
                "local_wan22_ti2v_5b_mlx",
                "local_ltx23_distilled_mlx",
            ],
            license_id="operator-owned",
            source_repository="local/test",
            source_revision="v1",
            apply=False,
        )
