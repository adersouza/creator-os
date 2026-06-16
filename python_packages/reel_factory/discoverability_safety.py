"""Discoverability-safe text checks for user-visible captions.

This module is intentionally small and dependency-free so it can run before
rendering, during CI, or as a local audit of caption banks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DISCOVERABILITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("url", re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)),
    ("dm", re.compile(r"\b(?:dm|dms|direct message|direct messages|message me|message you|send me|inbox me)\b", re.IGNORECASE)),
    ("link", re.compile(r"\b(?:link in bio|bio link|click (?:the )?link|tap (?:the )?link|check (?:the )?link|my link)\b", re.IGNORECASE)),
    ("onlyfans", re.compile(r"\b(?:onlyfans|only fans|fansly)\b", re.IGNORECASE)),
    ("of", re.compile(r"\bOF\b")),
    ("snapchat", re.compile(r"\b(?:snapchat|snap me|snap)\b", re.IGNORECASE)),
    ("telegram", re.compile(r"\btelegram\b", re.IGNORECASE)),
    ("whatsapp", re.compile(r"\bwhats ?app\b", re.IGNORECASE)),
    ("subscribe", re.compile(r"\b(?:subscribe here|join my page|join my private|premium page)\b", re.IGNORECASE)),
    ("linktree", re.compile(r"\b(?:linktree|beacons\.ai|beacons)\b", re.IGNORECASE)),
)

ACTIVE_CAPTION_GLOBS = (
    "01_captions/*.json",
    "caption_banks/banks.json",
)


@dataclass(frozen=True)
class DiscoverabilityFinding:
    source_file: str
    source_path: str
    source_index: str
    text: str
    blocked_terms: tuple[str, ...]
    blocked_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceFile": self.source_file,
            "sourcePath": self.source_path,
            "sourceIndex": self.source_index,
            "text": self.text,
            "blockedTerms": list(self.blocked_terms),
            "blockedReason": self.blocked_reason,
        }


def discoverability_safe_content_contract(*values: Any) -> dict[str, Any]:
    """Return the shared safety contract for any user-visible text values."""
    text = "\n".join(str(value) for value in values if value is not None).strip()
    blocked_terms: list[str] = []
    for label, pattern in DISCOVERABILITY_PATTERNS:
        if pattern.search(text):
            blocked_terms.append(label)
    blocked_terms = sorted(set(blocked_terms))
    return {
        "schema": "reel_factory.discoverability_safe_content_contract.v1",
        "discoverabilitySafe": not blocked_terms,
        "blockedTerms": blocked_terms,
        "blockedReason": (
            "unsafe_dm_link_or_off_platform_language"
            if blocked_terms else ""
        ),
        "wouldWrite": False,
    }


def audit_caption_sources(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    scanned_files = 0
    findings: list[DiscoverabilityFinding] = []

    for path in _active_caption_paths(root):
        scanned_files += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append(
                DiscoverabilityFinding(
                    source_file=str(path.relative_to(root)),
                    source_path="$",
                    source_index="parse_error",
                    text="",
                    blocked_terms=("invalid_json",),
                    blocked_reason=f"invalid_json: {exc}",
                )
            )
            continue
        for source_path, source_index, text in _iter_caption_texts(payload):
            contract = discoverability_safe_content_contract(text)
            if contract["discoverabilitySafe"]:
                continue
            findings.append(
                DiscoverabilityFinding(
                    source_file=str(path.relative_to(root)),
                    source_path=source_path,
                    source_index=source_index,
                    text=text,
                    blocked_terms=tuple(contract["blockedTerms"]),
                    blocked_reason=contract["blockedReason"],
                )
            )

    return {
        "schema": "reel_factory.caption_source_discoverability_audit.v1",
        "captionFilesScanned": scanned_files,
        "remainingRiskEntries": len(findings),
        "discoverabilitySafe": not findings,
        "findings": [finding.to_dict() for finding in findings],
        "wouldWrite": False,
    }


def _active_caption_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in ACTIVE_CAPTION_GLOBS:
        paths.extend(sorted(root.glob(pattern)))
    return [
        path
        for path in paths
        if path.is_file()
        and ".pre_discoverability_cleanup." not in path.name
        and not path.name.endswith(".bak")
    ]


def _iter_caption_texts(payload: Any) -> Iterable[tuple[str, str, str]]:
    if isinstance(payload, dict):
        hooks = payload.get("hooks")
        if isinstance(hooks, list):
            for index, hook in enumerate(hooks):
                text = _hook_text(hook)
                if text:
                    yield ("$.hooks", str(index), text)

        banks = payload.get("banks")
        if isinstance(banks, dict):
            for bank_name, entries in banks.items():
                if not isinstance(entries, list):
                    continue
                for index, entry in enumerate(entries):
                    text = _hook_text(entry)
                    if text:
                        yield (f"$.banks.{bank_name}", str(index), text)


def _hook_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        segments = value.get("segments")
        if isinstance(segments, list):
            return "\n".join(
                str(segment.get("text") or "").strip()
                for segment in segments
                if isinstance(segment, dict) and str(segment.get("text") or "").strip()
            ).strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Reel Factory caption sources for discoverability-unsafe text.")
    parser.add_argument("--root", default=".", help="Reel Factory repository root")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--fail-on-risk", action="store_true", help="Exit non-zero when risky entries are found")
    args = parser.parse_args()

    report = audit_caption_sources(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"captionFilesScanned={report['captionFilesScanned']} "
            f"remainingRiskEntries={report['remainingRiskEntries']} "
            f"discoverabilitySafe={str(report['discoverabilitySafe']).lower()}"
        )
        for finding in report["findings"]:
            print(
                f"- {finding['sourceFile']} {finding['sourcePath']}[{finding['sourceIndex']}]: "
                f"{', '.join(finding['blockedTerms'])}: {finding['text']}"
            )
    if args.fail_on_risk and not report["discoverabilitySafe"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
