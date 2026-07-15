from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MONOREPO_ROOT = PACKAGE_ROOT.parents[1]
PYTHONPATH = os.pathsep.join(
    [
        str(PACKAGE_ROOT),
        str(MONOREPO_ROOT / "packages" / "creator_os_core"),
        str(MONOREPO_ROOT / "packages" / "pipeline_contracts"),
    ]
)


def _settings_paths(env: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from campaign_factory.config import get_settings; "
                "s = get_settings(); "
                "print(json.dumps({'campaigns': str(s.campaigns_dir), "
                "'root': str(s.root)}))"
            ),
        ],
        cwd=PACKAGE_ROOT,
        env={**os.environ, "PYTHONPATH": PYTHONPATH, **env},
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_campaign_artifacts_default_outside_source_checkout(tmp_path: Path) -> None:
    source = tmp_path / "creator-os"
    artifacts = tmp_path / "artifacts"

    paths = _settings_paths(
        {
            "CREATOR_OS_ROOT": str(source),
            "CREATOR_OS_ARTIFACT_ROOT": str(artifacts),
            "CAMPAIGN_FACTORY_ROOT": str(source / "python_packages/campaign_factory"),
        }
    )

    assert paths["campaigns"] == str(artifacts / "campaign_factory/campaigns")
    assert paths["root"] == str(source / "python_packages/campaign_factory")


def test_campaign_artifacts_honor_explicit_rollback_override(tmp_path: Path) -> None:
    override = tmp_path / "legacy-campaigns"

    paths = _settings_paths(
        {
            "CREATOR_OS_ROOT": str(tmp_path / "creator-os"),
            "CREATOR_OS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(override),
        }
    )

    assert paths["campaigns"] == str(override)
