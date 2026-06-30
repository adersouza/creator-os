"""Durable local review truth helpers for Reel Factory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from manifest import Manifest


def review_integrity_check(
    root: Path, *, deck_id: str | None = None, folder_root: Path | None = None
) -> dict:
    manifest = Manifest(root / "manifest.json")
    return manifest.review_integrity_check(deck_id=deck_id, folder_root=folder_root)


def regenerate_review_folders(
    root: Path, *, folder_root: Path, deck_id: str | None = None
) -> dict:
    manifest = Manifest(root / "manifest.json")
    return {
        "schema": "reel_factory.review_folder_regeneration.v1",
        "deckId": deck_id,
        "folderRoot": str(folder_root),
        "counts": manifest.regenerate_review_folders(folder_root, deck_id=deck_id),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reel Factory review source-of-truth tools"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("review-integrity-check")
    check.add_argument("--root", default=".")
    check.add_argument("--deck")
    check.add_argument("--folder-root")
    regen = sub.add_parser("review-regenerate-folders")
    regen.add_argument("--root", default=".")
    regen.add_argument("--deck")
    regen.add_argument("--folder-root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "review-integrity-check":
        result = review_integrity_check(
            root,
            deck_id=args.deck,
            folder_root=Path(args.folder_root).resolve() if args.folder_root else None,
        )
    else:
        result = regenerate_review_folders(
            root,
            deck_id=args.deck,
            folder_root=Path(args.folder_root).resolve(),
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
