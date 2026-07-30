#!/usr/bin/env python3
"""Classify a change and reject release claims that its evidence cannot support."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / ".github/release-gate-matrix.json"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class GateError(ValueError):
    """A release declaration is incomplete or unsupported."""


def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "creator_os.release_gate_matrix.v1":
        raise GateError("unsupported release-gate matrix schema")
    if not data.get("releaseClasses"):
        raise GateError("release-gate matrix has no release classes")
    return data


def _documentation_only(path: str) -> bool:
    return (
        path.endswith(".md")
        or path.startswith("docs/")
        or path in {"LICENSE", "NOTICE"}
    )


def infer_release_classes(paths: list[str], matrix: dict[str, Any]) -> list[str]:
    if not paths:
        raise GateError("no changed files were found")
    if all(_documentation_only(path) for path in paths):
        return ["documentation_only"]

    classes = {"local_logic"}
    for name, definition in matrix["releaseClasses"].items():
        if name in {"documentation_only", "local_logic"}:
            continue
        patterns = definition.get("patterns", [])
        if any(
            fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in patterns
        ):
            classes.add(name)
    return sorted(classes)


def _declaration(body: str, label: str) -> list[str]:
    match = re.search(
        rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$",
        body,
    )
    if not match:
        raise GateError(f"missing `{label}: ...` declaration")
    return sorted(
        {
            token.strip().strip("`")
            for token in match.group(1).split(",")
            if token.strip()
        }
    )


def parse_declarations(body: str) -> tuple[list[str], list[str]]:
    return (
        _declaration(body, "Release classes"),
        _declaration(body, "Evidence claims"),
    )


def validate_declarations(
    *,
    inferred: list[str],
    declared: list[str],
    claims: list[str],
    matrix: dict[str, Any],
) -> None:
    known_classes = set(matrix["releaseClasses"])
    unknown_classes = sorted(set(declared) - known_classes)
    if unknown_classes:
        raise GateError(f"unknown release classes: {', '.join(unknown_classes)}")
    missing_classes = sorted(set(inferred) - set(declared))
    if missing_classes:
        raise GateError(
            "PR understates its release classes: " + ", ".join(missing_classes)
        )

    known_claims = set(matrix["claims"])
    unknown_claims = sorted(set(claims) - known_claims)
    if unknown_claims:
        raise GateError(f"unknown evidence claims: {', '.join(unknown_claims)}")
    forbidden = sorted(set(claims) & set(matrix["pullRequestForbiddenClaims"]))
    if forbidden:
        raise GateError(
            "a pull request cannot claim post-merge/runtime proof: "
            + ", ".join(forbidden)
        )


def required_gates(classes: list[str], matrix: dict[str, Any]) -> dict[str, list[str]]:
    stages = ("pull_request", "main", "promotion", "controlled_live")
    return {
        stage: sorted(
            {
                gate
                for name in classes
                for gate in matrix["releaseClasses"][name]["mandatoryGates"][stage]
            }
        )
        for stage in stages
    }


def build_receipt(
    *,
    base_sha: str,
    head_sha: str,
    paths: list[str],
    declared: list[str],
    inferred: list[str],
    claims: list[str],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "creator_os.release_gate_receipt.v1",
        "baseSha": base_sha,
        "headSha": head_sha,
        "changedFiles": sorted(paths),
        "declaredReleaseClasses": declared,
        "inferredReleaseClasses": inferred,
        "evidenceClaims": claims,
        "requiredGates": required_gates(inferred, matrix),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _commit(value: str, label: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", f"{value}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    resolved = completed.stdout.strip()
    if completed.returncode or not SHA_RE.fullmatch(resolved):
        raise GateError(f"{label} does not resolve to an exact commit")
    return resolved


def _changed_paths(base_sha: str, head_sha: str) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRTD",
            f"{base_sha}...{head_sha}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise GateError(completed.stderr.strip() or "git diff failed")
    return sorted(set(completed.stdout.splitlines()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate-pr"])
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--body-env", default="PR_BODY")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        matrix = load_matrix(args.matrix)
        base_sha = _commit(args.base, "base")
        head_sha = _commit(args.head, "head")
        paths = _changed_paths(base_sha, head_sha)
        inferred = infer_release_classes(paths, matrix)
        declared, claims = parse_declarations(os.environ.get(args.body_env, ""))
        validate_declarations(
            inferred=inferred,
            declared=declared,
            claims=claims,
            matrix=matrix,
        )
        receipt = build_receipt(
            base_sha=base_sha,
            head_sha=head_sha,
            paths=paths,
            declared=declared,
            inferred=inferred,
            claims=claims,
            matrix=matrix,
        )
    except GateError as exc:
        print(f"release gate failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
