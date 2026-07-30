from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import campaign_factory.cli as cli
import campaign_factory.reference_url_workflow as workflow
import pytest
from campaign_factory.config import Settings
from campaign_test_support import authorize_campaign_governance, make_factory


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
        observed["classification"] = args.reference_classification
        observed["warnings"] = args.reference_warning
        observed["nonTalking"] = args.reference_non_talking
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
            "--mode",
            "recreate_reel",
            "--reference-video",
            str(tmp_path / "input.mp4"),
            "--through",
            "analyze",
            "--reference-classification",
            "walking",
            "--reference-warning",
            "secondary_person_interaction",
            "--reference-non-talking",
        ],
    )
    assert cli.main() == 0
    assert observed == {
        "queryOnly": 1,
        "through": "analyze",
        "classification": "walking",
        "warnings": ["secondary_person_interaction"],
        "nonTalking": True,
    }
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
            "--mode",
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


def test_gemini_structure_analysis_is_contract_valid_and_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    analysis = {
        "schema": "reel_factory.reference_video_motion_analysis.v1",
        "analysisId": "analysis_ref_url_example",
        "referenceId": "ref_url_example",
        "provider": "gemini",
        "model": "gemini-cli-default",
        "status": "ready",
        "source": {
            "durationSeconds": 7.0,
            "shotCount": 1,
            "hasCuts": False,
            "aspectRatio": "9:16",
        },
        "structure": {
            "hookDescription": "Immediate eye contact.",
            "firstFrameDescription": "Centered waist-up framing.",
            "lastFrameDescription": "Same framing after a shoulder turn.",
            "subjectMotion": "One shoulder turn and a final hold.",
            "cameraMotion": "Slight handheld drift.",
            "pacing": "One continuous motion.",
            "timeline": [
                {
                    "startSeconds": 0.0,
                    "endSeconds": 3.0,
                    "action": "Begin a shoulder turn.",
                    "camera": "Keep the framing fixed.",
                },
                {
                    "startSeconds": 3.0,
                    "endSeconds": 7.0,
                    "action": "Complete the turn and hold.",
                    "camera": "Allow slight handheld drift.",
                },
            ],
        },
        "distinctness": {
            "preserveElements": ["pose_arc", "camera_path", "pacing"],
            "transformElements": ["identity", "wardrobe", "surface_text"],
            "literalCopyRisk": "medium",
        },
        "sourceTextPolicy": {
            "reuseVerbatim": False,
            "transcriptionUsedForMotionOnly": True,
        },
        "motionPrompt": (
            "Create one continuous vertical shot with a shoulder turn and final hold."
        ),
        "requiresReferenceVideoConditioning": True,
    }
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        workflow.shutil,
        "which",
        lambda command: "/usr/local/bin/gemini" if command == "gemini" else None,
    )

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"response": json.dumps(analysis)}),
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    result = workflow._analyze_reference_structure(
        source=source,
        reference_id="ref_url_example",
        overlay_inventory={
            "status": "observed",
            "observations": [{"text": "OLD OVERLAY"}],
        },
    )
    assert result["status"] == "ready"
    assert result["analysis"]["structure"]["timeline"][1]["endSeconds"] == 7.0
    assert result["overlayTextExcludedFromGenerationPrompt"] is True
    assert "--approval-mode" in observed["command"]
    assert "plan" in observed["command"]
    assert observed["kwargs"]["cwd"] == tmp_path


def test_reference_rights_block_before_download_or_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="may",
            provider="higgsfield",
            reference_video_use=False,
        )

        def forbidden(*_args, **_kwargs):
            raise AssertionError("reference media must not be touched before rights")

        monkeypatch.setattr(workflow, "canonicalize_reel_url", forbidden)
        monkeypatch.setattr(workflow, "download_reel_url", forbidden)
        monkeypatch.setattr(workflow, "_run_reference_factory", forbidden)
        monkeypatch.setattr(workflow, "_analyze_reference_structure", forbidden)

        with pytest.raises(
            PermissionError, match="creator_authorization_missing:reference_video_use"
        ):
            workflow.run_reference_analysis(
                cf,
                creator="stacey",
                reference_url="https://www.instagram.com/reel/example/",
                reference_video_path=None,
                reference_platform="instagram",
                reference_authorized=True,
                declared_talking=False,
                apply=False,
            )
    finally:
        cf.close()
