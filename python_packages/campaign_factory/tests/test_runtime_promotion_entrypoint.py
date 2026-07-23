from __future__ import annotations

from pathlib import Path

from campaign_factory import runtime_promotion_entrypoint as entrypoint


def test_runtime_promotion_entrypoint_validates_approval_and_receipt(
    monkeypatch,
) -> None:
    approval = {"schema": "creator_os.runtime_promotion_approval.v1"}
    receipt = {"schema": "creator_os.runtime_promotion_receipt.v1"}
    observed: list[tuple[str, object]] = []
    monkeypatch.setattr(
        entrypoint,
        "load_runtime_promotion_approval",
        lambda _path: approval,
    )
    monkeypatch.setattr(
        entrypoint,
        "validate_runtime_promotion_approval",
        lambda payload: observed.append(("approval", payload)),
    )

    def promote(**kwargs):
        assert kwargs["approval_payload"] is approval
        assert kwargs["verifier_command"] == ("make", "runtime-verify")
        kwargs["approval_validator"](kwargs["approval_payload"])
        kwargs["receipt_validator"](receipt)
        return receipt

    monkeypatch.setattr(entrypoint, "_promote_runtime", promote)
    monkeypatch.setattr(
        entrypoint,
        "validate_runtime_promotion_receipt",
        lambda payload: observed.append(("receipt", payload)),
    )

    result = entrypoint.run_contract_validated_promotion(
        source_root=Path("/source"),
        runtime_root=Path("/runtime"),
        approved_commit="a" * 40,
        approval_path=Path("/approval.json"),
        state_root=Path("/state"),
        operator="operator",
        dry_run=False,
    )

    assert result is receipt
    assert observed == [
        ("approval", approval),
        ("receipt", receipt),
        ("receipt", receipt),
    ]
