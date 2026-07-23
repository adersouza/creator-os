"""Contract-validating CLI boundary for guarded Creator OS runtime promotion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from creator_os_core.runtime_promotion import (
    RUNTIME_VERIFIER_COMMAND,
    RuntimePromotionError,
    _promote_runtime,
    load_runtime_promotion_approval,
)

from pipeline_contracts import (
    validate_runtime_promotion_approval,
    validate_runtime_promotion_receipt,
)


def run_contract_validated_promotion(
    *,
    source_root: Path,
    runtime_root: Path,
    approved_commit: str,
    approval_path: Path,
    state_root: Path,
    operator: str,
    dry_run: bool,
) -> dict[str, Any]:
    approval = load_runtime_promotion_approval(approval_path)
    result = _promote_runtime(
        source_root=source_root,
        runtime_root=runtime_root,
        approved_commit=approved_commit,
        approval_path=approval_path,
        state_root=state_root,
        operator=operator,
        dry_run=dry_run,
        verifier_command=RUNTIME_VERIFIER_COMMAND,
        receipt_validator=validate_runtime_promotion_receipt,
        approval_payload=approval,
        approval_validator=validate_runtime_promotion_approval,
    )
    if result.get("schema") == "creator_os.runtime_promotion_receipt.v1":
        validate_runtime_promotion_receipt(result)
    elif not dry_run or result.get("schema") != "creator_os.runtime_promotion_plan.v1":
        raise RuntimePromotionError("runtime_promotion_result_contract_invalid")
    return result


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
        result = run_contract_validated_promotion(
            source_root=args.source_root,
            runtime_root=args.runtime_root,
            approved_commit=args.approved_commit,
            approval_path=args.approval,
            state_root=args.state_root,
            operator=args.operator,
            dry_run=args.dry_run,
        )
    except (RuntimePromotionError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
