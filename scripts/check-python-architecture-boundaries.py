#!/usr/bin/env python3
"""Repo-local Python import boundary checks.

import-linter validates installed package graphs. This script complements it by
scanning the working tree directly, so newly added files are caught before they
are installed or included in package metadata.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BOUNDARIES: tuple[
    tuple[Path, str, tuple[str, ...], dict[str, tuple[Path, ...]]], ...
] = (
    (
        ROOT / "python_packages/reel_factory",
        "reel_factory",
        ("campaign_factory", "reference_factory", "repurposer"),
        {},
    ),
    (
        ROOT / "packages/pipeline_contracts/pipeline_contracts",
        "pipeline_contracts",
        ("campaign_factory", "reference_factory", "repurposer"),
        {},
    ),
    (
        ROOT / "python_packages/reference_factory/reference_factory",
        "reference_factory",
        ("campaign_factory", "reel_factory", "repurposer"),
        {},
    ),
    (
        ROOT / "python_packages/campaign_factory/campaign_factory",
        "campaign_factory",
        ("reference_factory", "repurposer"),
        {
            "repurposer": (
                ROOT
                / "python_packages/campaign_factory/campaign_factory/variation_stage.py",
            ),
        },
    ),
)


def main() -> int:
    violations: list[str] = []
    for root, source_name, forbidden, allowlist in BOUNDARIES:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                violations.append(
                    f"{path.relative_to(ROOT)}:{exc.lineno}: syntax error blocks boundary scan"
                )
                continue
            for line, imported in _imports(tree):
                if imported in forbidden and path not in allowlist.get(imported, ()):
                    rel = path.relative_to(ROOT)
                    violations.append(
                        f"{rel}:{line}: {source_name} must not import {imported}"
                    )

    if violations:
        print("Python architecture boundary violations:")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    return 0


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                (node.lineno, alias.name.split(".", 1)[0]) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module.split(".", 1)[0]))
    return found


if __name__ == "__main__":
    raise SystemExit(main())
