from __future__ import annotations

import sys
from pathlib import Path

import campaign_factory.cli as cli
from campaign_factory.config import Settings


def test_analysis_dry_run_bypasses_mutating_factory(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        root=tmp_path / "campaign-root",
        db_path=tmp_path / "campaign.sqlite",
        campaigns_dir=tmp_path / "campaigns",
        reference_reels_root=tmp_path / "references",
        reference_factory_db=tmp_path / "reference.sqlite",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def forbidden_factory(_settings):
        raise AssertionError("normal mutating CampaignFactory must not be constructed")

    observed = {}

    def fake_dispatch(args, factory, _settings):
        observed["queryOnly"] = factory.conn.execute("PRAGMA query_only").fetchone()[0]
        observed["through"] = args.through
        return 0

    monkeypatch.setattr(cli, "CampaignFactory", forbidden_factory)
    monkeypatch.setattr(cli, "dispatch_pipeline_commands", fake_dispatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "campaign-factory",
            "create",
            "--creator",
            "stacey",
            "--intent",
            "recreate_reel",
            "--reference-video",
            str(tmp_path / "input.mp4"),
            "--through",
            "analyze",
        ],
    )
    assert cli.main() == 0
    assert observed == {"queryOnly": 1, "through": "analyze"}
    assert not settings.db_path.exists()
    assert not settings.campaigns_dir.exists()


def test_full_recreation_dry_run_also_bypasses_mutating_factory(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        root=tmp_path / "campaign-root",
        db_path=tmp_path / "campaign.sqlite",
        campaigns_dir=tmp_path / "campaigns",
        reference_reels_root=tmp_path / "references",
        reference_factory_db=tmp_path / "reference.sqlite",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "CampaignFactory",
        lambda _settings: (_ for _ in ()).throw(
            AssertionError("mutating CampaignFactory must not be constructed")
        ),
    )
    observed = {}

    def fake_dispatch(args, factory, _settings):
        observed["queryOnly"] = factory.conn.execute("PRAGMA query_only").fetchone()[0]
        observed["through"] = args.through
        observed["mode"] = args.recreate_mode
        observed["audio"] = args.audio_preference
        return 0

    monkeypatch.setattr(cli, "dispatch_pipeline_commands", fake_dispatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "campaign-factory",
            "create",
            "--creator",
            "stacey",
            "--intent",
            "recreate_reel",
            "--reference-url",
            "https://www.instagram.com/reel/example/",
            "--recreate-mode",
            "auto",
            "--audio",
            "auto",
        ],
    )
    assert cli.main() == 0
    assert observed == {
        "queryOnly": 1,
        "through": None,
        "mode": "auto",
        "audio": "auto",
    }
    assert not settings.db_path.exists()
    assert not settings.campaigns_dir.exists()
