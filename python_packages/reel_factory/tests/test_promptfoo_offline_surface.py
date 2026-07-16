from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evals.prompt_regressions.prompts import render_prompt


def test_soul_reference_prompt_surface_is_captured_offline() -> None:
    rendered = render_prompt(
        {
            "vars": {
                "surface": "soul_reference_still",
                "creative_direction": "preserve the exact seated pose",
            }
        }
    )

    assert "exactly one standalone image" in rendered
    assert "preserve the exact seated pose" in rendered
    assert '"image_prompt"' in rendered
