"""Command-line adapter for recording exact-byte creative approvals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .creative_approval import (
    CreativeApprovalError,
    CreativeApprovalStore,
    load_creative_approval,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        approval = load_creative_approval(args.approval)
        if args.root is None:
            from .config import get_settings

            root = get_settings().creative_approvals_dir
        else:
            root = args.root
        path = CreativeApprovalStore(root).record(approval)
    except (CreativeApprovalError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": "campaign_factory.creative_approval_recorded.v1",
                "approvalId": approval["approvalId"],
                "approvalFingerprint": approval["approvalFingerprint"],
                "path": str(path),
                "productionWrites": 0,
                "providerCalls": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0
