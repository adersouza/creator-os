from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_tribev2_remains_research_only() -> None:
    production_paths = [
        ROOT / "python_packages" / "campaign_factory" / "campaign_factory",
        ROOT / "python_packages" / "reel_factory",
        ROOT / "apps" / "dashboard" / "api",
    ]
    forbidden_terms = ("tribev2", "tribe_v2", "TRIBE")
    allowed_fragments = (
        "_spikes/tribev2",
        "tribev2_reel_analysis",
        "tribev2_reel_review",
        "tribev2_holdout_pilot_review",
    )
    hits: list[str] = []
    for base in production_paths:
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js"}:
                continue
            rel = str(path.relative_to(ROOT))
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(term in text for term in forbidden_terms) and not any(fragment in rel or fragment in text for fragment in allowed_fragments):
                hits.append(rel)

    assert hits == []
