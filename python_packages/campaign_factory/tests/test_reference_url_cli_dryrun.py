from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import campaign_factory.cli as cli
import campaign_factory.cli_dispatch_pipeline as pipeline_dispatch
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


def test_create_routes_standalone_creator_image_to_structural_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(b"structural image")
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline_dispatch,
        "run_structural_image_analysis",
        lambda _factory, **kwargs: observed.update(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(pipeline_dispatch, "print_json", lambda _value: None)
    args = SimpleNamespace(
        cmd="create",
        reference_id=None,
        recreation_anchor_approval=None,
        reference_url=None,
        reference_video=None,
        creator_image=image,
        creator="stacey",
        mode="static_reel",
        reference_authorized=True,
        through="anchor",
        max_credits=10.0,
        recreation_attempt_id=None,
        apply=False,
    )

    assert (
        pipeline_dispatch.dispatch_pipeline_commands(
            args,
            object(),
            SimpleNamespace(reference_factory_db=tmp_path / "ref.sqlite"),
        )
        == 0
    )
    assert observed["reference_image_path"] == image
    assert observed["creator"] == "stacey"
    assert observed["through"] == "anchor"


def test_structural_image_dry_run_binds_active_soul_without_provider_calls(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="stacey-image-plan",
            provider="higgsfield",
            soul_id="soul-stacey-active",
            reference_video_use=True,
        )
        image = tmp_path / "reference.png"
        image.write_bytes(b"authorized structural image")

        result = workflow.run_structural_image_analysis(
            cf,
            creator="stacey",
            reference_image_path=image,
            reference_authorized=True,
            through="anchor",
            max_credits=10.0,
            recreation_attempt_id=None,
            apply=False,
        )

        assert result["status"] == "planned_no_provider_calls"
        assert result["providerCalls"] == 0
        assert result["referenceImage"]["role"] == "structural_reference"
        assert result["soulIdentity"]["soulId"] == "soul-stacey-active"
    finally:
        cf.close()


def test_reference_recreation_plan_uses_active_soul_without_creator_image(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        governance = authorize_campaign_governance(
            cf,
            tmp_path,
            creator="stacey",
            campaign="stacey-reference-plan",
            provider="higgsfield",
            soul_id="soul-stacey-active",
            reference_video_use=True,
        )
        source = tmp_path / "reference.mp4"
        source.write_bytes(b"exact-reference-video")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        observed: dict[str, object] = {}
        monkeypatch.setattr(
            workflow,
            "resolve_reference_analysis_governance",
            lambda *_args, **_kwargs: {
                "creatorSlug": "stacey",
                "creatorId": governance["model"]["id"],
                "campaignId": governance["campaign"]["id"],
            },
        )
        monkeypatch.setattr(
            workflow,
            "_run_reference_factory",
            lambda **_kwargs: {
                "referenceId": "reference-1",
                "source": {"path": str(source), "sha256": source_sha},
                "overlayTextInventory": {},
                "proposedMutations": [],
            },
        )
        monkeypatch.setattr(
            workflow,
            "_analyze_reference_structure",
            lambda **_kwargs: {
                "status": "planned",
                "providerCalls": 0,
                "cost": {"reconciliationState": "not_submitted", "actualUsd": 0},
            },
        )
        monkeypatch.setattr(
            workflow,
            "inspect_reference_audio",
            lambda *_args, **_kwargs: {"proposedMutations": []},
        )

        def fake_build_openai_prompt_pack(**kwargs):
            observed["promptKwargs"] = kwargs
            return {
                "promptPackFingerprint": "a" * 64,
                "soulIdentity": kwargs["soul_identity"],
                "cache": {"providerCallMade": False},
                "promptPlanning": {},
            }

        monkeypatch.setattr(
            workflow, "build_openai_prompt_pack", fake_build_openai_prompt_pack
        )
        monkeypatch.setattr(
            workflow,
            "plan_recreation",
            lambda **kwargs: {
                "quote": {"quoteCalls": 0},
                "promptPackFingerprint": kwargs["prompt_pack"]["promptPackFingerprint"],
            },
        )

        result = workflow.run_reference_analysis(
            cf,
            creator="stacey",
            reference_url=None,
            reference_video_path=source,
            reference_platform="private_reference",
            reference_authorized=True,
            declared_talking=False,
            through="plan",
            creator_image_path=None,
            apply=False,
        )

        prompt_kwargs = observed["promptKwargs"]
        assert isinstance(prompt_kwargs, dict)
        assert "creator_image" not in prompt_kwargs
        assert prompt_kwargs["reference_video"] == source
        assert prompt_kwargs["soul_identity"]["soulId"] == "soul-stacey-active"
        assert result["providerCalls"] == 0
    finally:
        cf.close()


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
    factory = SimpleNamespace(
        conn=object(),
        settings=SimpleNamespace(reference_factory_db=tmp_path / "reference.sqlite"),
    )
    rights = {
        "eligible": True,
        "rightsEvidenceFingerprint": "e" * 64,
    }
    monkeypatch.setattr(
        workflow.shutil,
        "which",
        lambda command: "/usr/local/bin/gemini" if command == "gemini" else None,
    )
    monkeypatch.setattr(
        workflow,
        "_authorize_gemini_structure_analysis",
        lambda *_args, **_kwargs: {
            "campaignLedgerEventId": "cost-event-1",
            "model": "gemini-2.5-flash",
        },
    )
    monkeypatch.setattr(
        workflow,
        "_require_reference_provider_rights",
        lambda **_kwargs: rights,
    )
    monkeypatch.setattr(
        workflow,
        "reconcile_paid_action_cost",
        lambda *_args, **_kwargs: {
            "schema": "campaign_factory.unified_paid_action_ledger.v1",
            "eventId": "cost-event-1",
            "quotedUsd": 0.25,
            "actualUsd": None,
            "reconciliationState": "unknown",
        },
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
        factory=factory,
        source=source,
        reference_id="ref_url_example",
        overlay_inventory={
            "status": "observed",
            "observations": [{"text": "OLD OVERLAY"}],
        },
        governance_context={"creatorId": "creator-1", "campaignId": "campaign-1"},
        provider_rights=rights,
        apply=True,
    )
    assert result["status"] == "ready"
    assert result["analysis"]["structure"]["timeline"][1]["endSeconds"] == 7.0
    assert result["overlayTextExcludedFromGenerationPrompt"] is True
    assert "--approval-mode" in observed["command"]
    assert "plan" in observed["command"]
    assert observed["command"][observed["command"].index("--model") + 1] == (
        "gemini-2.5-flash"
    )
    assert observed["kwargs"]["cwd"] == tmp_path


def test_gemini_structure_analysis_dry_run_makes_no_provider_or_spend_call(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run must not authorize spend or call Gemini")

    monkeypatch.setattr(workflow, "_authorize_gemini_structure_analysis", forbidden)
    monkeypatch.setattr(workflow.subprocess, "run", forbidden)
    result = workflow._analyze_reference_structure(
        factory=SimpleNamespace(),
        source=source,
        reference_id="ref_url_example",
        overlay_inventory={},
        governance_context={},
        provider_rights=None,
        apply=False,
    )

    assert result["status"] == "planned"
    assert result["providerCalls"] == 0
    assert result["cost"]["reconciliationState"] == "not_submitted"


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


def test_resolve_stored_reference_verifies_exact_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"stored-reference")
    reference_id = "ref_url_example"
    payload = {
        "schema": "reference_factory.url_intake_resolution.v1",
        "referenceId": reference_id,
        "source": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "videoProbe": {"valid": 1},
        "intakeMetadata": {"operatorClassification": "passive_single_shot"},
    }
    commands: list[list[str]] = []
    monkeypatch.setattr(workflow.shutil, "which", lambda _name: "/usr/bin/uv")

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)

    result = workflow.resolve_stored_reference(
        db_path=tmp_path / "reference.sqlite",
        reference_id=reference_id,
    )

    assert result["exactBytesVerified"] is True
    assert result["resolvedPath"] == str(source.resolve())
    assert commands[0][4:7] == ["python", "-m", "reference_factory.cli"]


def test_resolve_stored_reference_rejects_byte_drift(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"changed")
    payload = {
        "referenceId": "ref_url_example",
        "source": {"path": str(source), "sha256": "0" * 64},
        "videoProbe": {"valid": 1},
    }
    monkeypatch.setattr(workflow.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        workflow.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        workflow.resolve_stored_reference(
            db_path=tmp_path / "reference.sqlite",
            reference_id="ref_url_example",
        )
