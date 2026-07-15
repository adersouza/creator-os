from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REEL_PACKAGE = ROOT / "python_packages" / "reel_factory" / "reel_factory"
# These legacy modules are being removed by the parallel outcome-ledger slice.
LEGACY_PENDING_DELETION = {
    "intelligence_store.py",
    "metrics_store.py",
    "orchestrator.py",
    "pipeline_run.py",
    "winner_dna.py",
}


def test_active_reel_worker_has_no_campaign_spend_state_access() -> None:
    forbidden_text = (
        "CAMPAIGN_FACTORY_DB",
        "campaign_factory.sqlite",
        "higgsfield_spend_reservations",
        "ai_cost_events",
    )
    violations = []
    for path in REEL_PACKAGE.glob("*.py"):
        if path.name in LEGACY_PENDING_DELETION:
            continue
        text = path.read_text(encoding="utf-8")
        if any(term in text for term in forbidden_text):
            violations.append(path.name)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] == "campaign_factory":
                    violations.append(path.name)
            elif isinstance(node, ast.Import):
                if any(
                    alias.name.split(".", 1)[0] == "campaign_factory"
                    for alias in node.names
                ):
                    violations.append(path.name)
    assert sorted(set(violations)) == []
    assert not (REEL_PACKAGE / "higgsfield_cost_preflight.py").exists()
