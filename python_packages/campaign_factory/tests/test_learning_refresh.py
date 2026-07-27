from __future__ import annotations

import importlib.util
from pathlib import Path

from campaign_factory.config import Settings
from reference_factory.db import connect as connect_reference

REPO_ROOT = Path(__file__).resolve().parents[3]


def _module():
    path = REPO_ROOT / "scripts" / "learning_refresh.py"
    spec = importlib.util.spec_from_file_location("learning_refresh", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_learning_refresh_apply_is_idempotent(tmp_path, monkeypatch) -> None:
    module = _module()
    reference_db = tmp_path / "reference.sqlite"
    connect_reference(reference_db).close()
    campaign_db = tmp_path / "campaign.sqlite"
    settings = Settings(
        root=tmp_path / "campaign",
        db_path=campaign_db,
        reference_reels_root=tmp_path / "reference",
        reference_factory_db=reference_db,
    )
    monkeypatch.setattr(module, "REFERENCE_DB_PATH", reference_db)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setenv("CREATOR_OS_LEARNING_STATE", str(tmp_path / "learning"))

    first = module.refresh(apply=True)
    second = module.refresh(apply=True)

    assert first["knowledgePack"]["persisted"] is True
    assert first["persistentArtifactsWritten"] == 2
    assert second["idempotent"] is True
    assert second["databaseWrites"] == 0
    assert second["persistentArtifactsWritten"] == 0


def test_learning_refresh_dry_run_writes_nothing(tmp_path, monkeypatch) -> None:
    module = _module()
    reference_db = tmp_path / "reference.sqlite"
    connect_reference(reference_db).close()
    campaign_db = tmp_path / "campaign.sqlite"
    settings = Settings(
        root=tmp_path / "campaign",
        db_path=campaign_db,
        reference_reels_root=tmp_path / "reference",
        reference_factory_db=reference_db,
    )
    # Initialize Campaign once, then take the dry-run boundary.
    from campaign_factory.core import CampaignFactory

    CampaignFactory(settings).close()
    state_root = tmp_path / "learning"
    monkeypatch.setattr(module, "REFERENCE_DB_PATH", reference_db)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setenv("CREATOR_OS_LEARNING_STATE", str(state_root))
    before = campaign_db.read_bytes()

    result = module.refresh(apply=False)

    assert result["databaseWrites"] == 0
    assert result["persistentArtifactsWritten"] == 0
    assert campaign_db.read_bytes() == before
    assert not state_root.exists()
