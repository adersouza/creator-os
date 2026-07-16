from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from campaign_factory.contentforge_cli import run_contentforge
from campaign_factory.contracts import load_example


def _contentforge_root(tmp_path: Path) -> Path:
    root = tmp_path / "contentforge"
    root.mkdir()
    (root / "cli.mjs").write_text("", encoding="utf-8")
    return root


def test_campaign_profile_validates_full_node_response_at_subprocess_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = load_example("contentforge_campaign_audit_response")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(response), stderr=""
        ),
    )

    assert (
        run_contentforge(
            _contentforge_root(tmp_path),
            "similarity",
            {"auditProfile": "campaign_factory_v1"},
        )
        == response
    )


def test_campaign_profile_rejects_drifted_node_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = load_example("contentforge_campaign_audit_response")
    del response["readinessSummary"]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(response), stderr=""
        ),
    )

    with pytest.raises(
        RuntimeError, match="response contract violation.*readinessSummary"
    ):
        run_contentforge(
            _contentforge_root(tmp_path),
            "similarity",
            {"auditProfile": "campaign_factory_v1"},
        )
