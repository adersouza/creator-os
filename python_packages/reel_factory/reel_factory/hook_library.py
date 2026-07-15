#!/usr/bin/env python3
"""Manage the local reusable hook library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .embedding_provider import DEFAULT_EMBEDDING_MODEL
from .hook_tools import reindex_hook_library


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--library", default=None)
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    library = (
        Path(args.library)
        if args.library
        else root / "project_data" / "hook_library.json"
    )
    if args.reindex:
        print(
            json.dumps(
                reindex_hook_library(library, embedding_model=args.embedding_model),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(json.dumps({"library": str(library), "exists": library.exists()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
