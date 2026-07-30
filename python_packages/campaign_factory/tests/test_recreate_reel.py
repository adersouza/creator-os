from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import campaign_factory.production_batch_results as production_batch_results
import campaign_factory.production_higgsfield_authorization as authorization_subject
import campaign_factory.production_lane as production_lane
import pytest
from campaign_factory.production_higgsfield_authorization import (
    _authorize_batch_balance,
    _authorize_prepared_higgsfield_jobs,
    _completed_higgsfield_recovery,
    higgsfield_request,
    higgsfield_spend_scope,
)
from campaign_factory.production_lane import plan_production_batch
from campaign_factory.production_prompts import CREATOR_SOUL_IDS
from campaign_factory.provider_spend import ensure_authorization_table
from campaign_factory.recreate_reel import (
    RECREATION_REVIEW_FIELDS,
    analyze_reference_reel,
    build_recreation_review,
)
from campaign_test_support import make_factory
from creator_os_core.provider_spend import sign_authorization
from creator_os_core.recreation_anchor_approval import (
    write_recreation_anchor_approval,
)
from PIL import Image
from reel_factory.higgsfield_production import (
    HiggsfieldProductionRequest,
    build_higgsfield_production_plan,
    higgsfield_execution_fingerprint,
)

from pipeline_contracts import validate_provider_spend_authorization


def _governed(job: dict) -> dict:
    return {
        **job,
        "_creatorGovernance": {
            "creatorSlug": str(job["creator"]),
            "providerIdentityId": CREATOR_SOUL_IDS[str(job["creator"])],
        },
    }


def _factory(tmp_path: Path, *, status: str = "approved") -> SimpleNamespace:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaigns (id TEXT PRIMARY KEY, slug TEXT, updated_at TEXT);
        CREATE TABLE models (id TEXT PRIMARY KEY, slug TEXT);
        CREATE TABLE campaign_governance (
          campaign_id TEXT PRIMARY KEY, model_id TEXT, lifecycle_status TEXT
        );
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY, campaign_id TEXT, model_id TEXT, content_hash TEXT,
          stored_path TEXT, media_type TEXT, status TEXT, created_at TEXT,
          metadata_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO campaigns VALUES ('campaign-1','stacey-main','2026')")
    conn.execute("INSERT INTO models VALUES ('model-1','stacey')")
    conn.execute(
        "INSERT INTO campaign_governance VALUES "
        "('campaign-1','model-1','production_ready')"
    )
    source = tmp_path / "stacey-approved.png"
    Image.new("RGB", (360, 640), "#8f5a69").save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    conn.execute(
        "INSERT INTO source_assets VALUES "
        "('source-stacey','campaign-1','model-1',?,?,'image',?,'2026','{}')",
        (digest, str(source), status),
    )
    governance = SimpleNamespace(
        active_identity_profile=lambda _creator, provider: {
            "creator_id": "model-1",
            "creator_slug": "stacey",
            "provider": provider,
            "provider_identity_id": CREATOR_SOUL_IDS["stacey"],
        },
        resolve_operation=lambda **_kwargs: {
            "creatorId": "model-1",
            "creatorSlug": "stacey",
            "creatorLifecycleVersion": 1,
            "campaignId": "campaign-1",
            "campaignLifecycleVersion": 1,
            "identityProfileId": "identity-1",
            "identityProfileVersion": 1,
            "identityProfileFingerprint": "i" * 64,
            "providerIdentityId": CREATOR_SOUL_IDS["stacey"],
            "authorizationEventIds": ["authorization-reference-1"],
            "governanceFingerprint": "g" * 64,
        },
    )
    return SimpleNamespace(
        conn=conn,
        domains=SimpleNamespace(creator_governance=governance),
    )


def _reference(tmp_path: Path, *, audio: bool = True) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg required")
    path = tmp_path / ("reference-audio.mp4" if audio else "reference-silent.mp4")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=180x320:r=24",
    ]
    if audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000",
            ]
        )
    command.extend(
        [
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if audio:
        command.extend(["-c:a", "aac", "-shortest"])
    else:
        command.append("-an")
    command.append(str(path))
    subprocess.run(command, check=True)
    return path


def _reference_elements(tmp_path: Path, creator: str = "stacey") -> Path:
    path = tmp_path / f"{creator}-reference-elements.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": f"{creator}-reference",
                    "name": creator,
                    "medias": [],
                    "video_medias": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _anchor_approval(
    tmp_path: Path,
    *,
    source: Path,
    reference: Path,
    soul_id: str = "soul-stacey",
) -> dict[str, Any]:
    return write_recreation_anchor_approval(
        output_dir=tmp_path / "anchor-approvals",
        creator="stacey",
        soul_id=soul_id,
        anchor_generation_id="anchor-generation-1",
        anchor_file=source,
        prompt_pack_id="prompt-pack-1",
        prompt_pack_fingerprint="a" * 64,
        anchor_prompt_fingerprint="b" * 64,
        creator_image_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        reference_video_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        selected_composition_frame_sha256="c" * 64,
        approved_by="operator@test",
    )


def _capabilities() -> dict[str, Any]:
    return {
        "authentication": {"authenticated": True},
        "souls": [
            {
                "id": "soul-stacey",
                "name": "Stacey",
                "status": "completed",
                "type": "soul_2",
            }
        ],
        "models": [
            {"job_type": "seedance_2_0_mini"},
            {"job_type": "seedance_2_0"},
        ],
        "workflows": [],
    }


def _plan(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "factory": _factory(tmp_path),
        "creator": "stacey",
        "intent": "recreate_reel",
        "count": 1,
        "execution": "cloud",
        "accounts": "stacey-main",
        "audio_preference": "embedded_trending",
        "reference_video_path": _reference(tmp_path),
        "reference_platform": "instagram",
        "reference_authorized": True,
    }
    values.update(overrides)
    return plan_production_batch(**values)


def test_recreate_reel_requires_reference_video(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires --reference-video"):
        plan_production_batch(
            _factory(tmp_path),
            creator="stacey",
            intent="recreate_reel",
            count=1,
            execution="cloud",
            accounts="stacey-main",
            audio_preference="embedded_trending",
        )


def test_recreate_plan_retains_reference_sha_without_registering_it(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    batch = _plan(tmp_path, factory=factory)
    job = batch["jobs"][0]
    reference = Path(job["referenceVideoPath"])
    assert (
        job["referenceVideoSha256"]
        == hashlib.sha256(reference.read_bytes()).hexdigest()
    )
    assert job["referenceVideo"]["referenceVideoId"].startswith("reference_video_")
    assert batch["provider"] == "higgsfield"
    tables = {
        row[0]
        for row in factory.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "rendered_assets" not in tables


def test_recreate_uses_internal_seedance_recipe_and_silent_contract(
    tmp_path: Path,
) -> None:
    job = _plan(tmp_path)["jobs"][0]
    stage = job["productionRecipe"]["stages"][0]
    assert stage["providerModel"] == "seedance_2_0"
    assert stage["resolution"] == "480p"
    assert stage["recipeId"] == "higgsfield_recreate_reel"
    assert stage["task"] == "reference_to_video"
    assert job["productionRecipe"]["status"] == "experimental"
    assert (
        "for motion, timing, framing, and camera movement only"
        in job["compiledPrompt"]["text"]
    )
    assert (
        "Do not copy the other person's face, hair, body, clothing"
        in job["compiledPrompt"]["text"]
    )


def test_seedance_request_uses_verified_video_and_image_reference_roles(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (360, 640), "purple").save(source)
    reference = _reference(tmp_path)
    approval = _anchor_approval(tmp_path, source=source, reference=reference)
    request = HiggsfieldProductionRequest(
        recipe_id="higgsfield_recreate_reel",
        creator="stacey",
        soul_id="soul-stacey",
        source_approval=approval["approvalFingerprint"],
        source_image_path=Path(approval["anchorFilePath"]),
        driving_video_path=reference,
        output_path=tmp_path / "output.mp4",
        review_root=tmp_path / "review",
        prompt=(
            "Closely follow the broad performance and camera progression while "
            "preserving the supplied creator identity."
        ),
        model="seedance_2_0",
        duration_seconds=5,
        max_credits=30,
        reference_elements_path=_reference_elements(tmp_path),
        recreation_anchor_approval=approval,
    )
    plan = build_higgsfield_production_plan(
        request,
        capabilities=_capabilities(),
    )
    command = plan["command"]
    assert (
        command[command.index("--image-references") + 1] == approval["anchorFilePath"]
    )
    assert command[command.index("--video-references") + 1] == str(reference)
    assert command[command.index("--generate_audio") + 1] == "false"
    assert command[3] == "seedance_2_0"
    assert "kling3_0_motion_control" not in command
    assert plan["source"]["kind"] == "approved_recreation_anchor"
    assert (
        plan["recreationAnchorApproval"]["approvalFingerprint"]
        == approval["approvalFingerprint"]
    )
    assert plan["referenceElement"]["deliveryMethod"] == "prompt_token"
    assert (
        plan["referenceElement"]["fileSha256"]
        == hashlib.sha256(_reference_elements(tmp_path).read_bytes()).hexdigest()
    )


def test_talking_reference_fails_before_provider_planning(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="recreate_talking_reel_unresolved"):
        _plan(tmp_path, reference_talking=True)


def test_reference_audio_policy_retains_exact_source_audio_identity(
    tmp_path: Path,
) -> None:
    batch = _plan(tmp_path, audio_preference="reference_audio_required")
    job = batch["jobs"][0]
    assert job["audioPolicy"] == "original_embedded"
    assert (
        job["referenceVideo"]["audio"]["identity"]["sourceVideoSha256"]
        == job["referenceVideoSha256"]
    )


@pytest.mark.parametrize("receipt_status", ["completed", "downloaded_output"])
def test_completed_receipt_is_recovered_only_with_exact_source_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_status: str,
) -> None:
    monkeypatch.setattr(
        production_batch_results,
        "probe_production_video",
        lambda _path: {"codec": "h264"},
    )
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    output = tmp_path / "output.mp4"
    output.write_bytes(b"completed output")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    reference_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    output_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    fingerprint = "a" * 64
    review_root = tmp_path / "review"
    execution_fingerprint = higgsfield_execution_fingerprint(
        fingerprint,
        output_path=output,
        review_root=review_root,
    )
    receipt_path = (
        review_root / "receipts" / f"{fingerprint}.higgsfield_submission.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "status": receipt_status,
                "requestFingerprint": fingerprint,
                "providerRequestFingerprint": fingerprint,
                "executionFingerprint": execution_fingerprint,
                "providerCommandFingerprint": "c" * 64,
                "workItemId": "job-1",
                "attemptId": "pipeline-1:1",
                "authorizationId": "authorization-1",
                "generationId": "generation-1",
                "model": "seedance_2_0",
                "seed": 42,
                "creditQuote": {
                    "provider": "higgsfield",
                    "amount": 8.0,
                    "unit": "higgsfield_credits",
                },
                "source": {
                    "assetId": "source-1",
                    "approvalId": "approval-1",
                    "sha256": source_sha,
                },
                "drivingVideo": {"sha256": reference_sha},
                **(
                    {
                        "downloadedOutput": {
                            "temporaryPath": str(tmp_path / "missing.download"),
                            "finalPath": str(output),
                            "sha256": output_sha,
                        }
                    }
                    if receipt_status == "downloaded_output"
                    else {"finalOutput": {"path": str(output), "sha256": output_sha}}
                ),
            }
        ),
        encoding="utf-8",
    )
    recovery = _completed_higgsfield_recovery(
        {
            "providerOutputPath": str(output),
            "providerReviewRoot": str(review_root),
            "jobId": "job-1",
            "sourceAssetId": "source-1",
            "sourceApproval": {
                "approvalEventId": "approval-1",
                "approvalFingerprint": "d" * 64,
            },
            "sourceSha256": source_sha,
            "referenceVideoSha256": reference_sha,
            "seed": 42,
            "productionRecipe": {"stages": [{"providerModel": "seedance_2_0"}]},
        },
    )

    expected_recovery = {
        "receiptPath": str(receipt_path),
        "receiptSha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "generationId": "generation-1",
        "outputPath": str(output),
        "outputSha256": output_sha,
        "authorizationId": "authorization-1",
        "attemptId": "pipeline-1:1",
        "providerRequestFingerprint": fingerprint,
        "executionFingerprint": execution_fingerprint,
        "providerCommandFingerprint": "c" * 64,
        "creditQuote": {
            "provider": "higgsfield",
            "amount": 8.0,
            "unit": "higgsfield_credits",
        },
    }
    if receipt_status == "downloaded_output":
        expected_recovery["recoveryStatus"] = "downloaded_output"
    assert recovery == expected_recovery


def test_completed_receipt_recovery_rejects_wrong_source(tmp_path: Path) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"completed output")
    fingerprint = "a" * 64
    review_root = tmp_path / "review"
    receipt_path = (
        review_root / "receipts" / f"{fingerprint}.higgsfield_submission.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "requestFingerprint": fingerprint,
                "providerRequestFingerprint": fingerprint,
                "workItemId": "job-1",
                "attemptId": "pipeline-1:1",
                "authorizationId": "authorization-1",
                "generationId": "generation-1",
                "model": "seedance_2_0",
                "seed": 42,
                "creditQuote": {
                    "provider": "higgsfield",
                    "amount": 8.0,
                    "unit": "higgsfield_credits",
                },
                "source": {"sha256": "b" * 64},
                "drivingVideo": {"sha256": "c" * 64},
                "finalOutput": {
                    "path": str(output),
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PermissionError, match="source_binding_mismatch"):
        _completed_higgsfield_recovery(
            {
                "providerOutputPath": str(output),
                "providerReviewRoot": str(review_root),
                "jobId": "job-1",
                "sourceSha256": "d" * 64,
                "referenceVideoSha256": "c" * 64,
                "seed": 42,
                "productionRecipe": {"stages": [{"providerModel": "seedance_2_0"}]},
            },
        )


def test_reference_audio_policy_rejects_silent_reference(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs an audio stream"):
        _plan(
            tmp_path,
            reference_video_path=_reference(tmp_path, audio=False),
            audio_preference="reference_audio_required",
        )


def test_recreate_reel_rejects_unapproved_creator_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no explicitly approved image inventory"):
        _plan(tmp_path, factory=_factory(tmp_path, status="imported"))


def test_recreate_reel_is_single_request_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one output"):
        _plan(tmp_path, count=2)


def test_paid_request_requires_and_uses_exact_approved_anchor(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    reference = _reference(tmp_path)
    source_row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = 'source-stacey'"
    ).fetchone()
    assert source_row is not None
    source = Path(source_row["stored_path"])
    anchor = tmp_path / "scene-matched-anchor.png"
    Image.new("RGB", (360, 640), "gold").save(anchor)
    prompt_pack = {
        "promptPackFingerprint": "a" * 64,
        "seedancePrompt": (
            "Use the approved anchor as the exact person and follow the reference "
            "motion with stable identity."
        ),
        "klingPrompt": "Use the approved anchor as the exact person.",
        "promptPlanning": {},
        "cache": {"providerCallMade": False},
    }
    approval = write_recreation_anchor_approval(
        output_dir=tmp_path / "anchor-approvals",
        creator="stacey",
        soul_id=CREATOR_SOUL_IDS["stacey"],
        anchor_generation_id="anchor-generation-1",
        anchor_file=anchor,
        prompt_pack_id="prompt-pack-1",
        prompt_pack_fingerprint=prompt_pack["promptPackFingerprint"],
        anchor_prompt_fingerprint="b" * 64,
        creator_image_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        reference_video_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        selected_composition_frame_sha256="c" * 64,
        approved_by="operator@test",
    )
    batch = _plan(
        tmp_path,
        factory=factory,
        reference_video_path=reference,
        prompt_pack_provider=lambda **_kwargs: prompt_pack,
        recreation_anchor_approval_path=Path(approval["receiptPath"]),
    )
    job = batch["jobs"][0]
    job["providerOutputPath"] = str(tmp_path / "provider-output.mp4")
    job["providerReviewRoot"] = str(tmp_path / "provider-review")
    request = higgsfield_request(_governed(job), max_credits=20)

    retained_anchor = Path(approval["anchorFilePath"])
    assert Path(request.source_image_path) == retained_anchor
    assert retained_anchor != anchor.resolve()
    assert request.source_approval == approval["approvalFingerprint"]
    assert job["sourcePath"] == str(source)
    assert (
        job["recreationAnchorSha256"] == hashlib.sha256(anchor.read_bytes()).hexdigest()
    )

    retained_anchor.write_bytes(b"changed after approval")
    with pytest.raises(PermissionError, match="sha_mismatch"):
        higgsfield_request(_governed(job), max_credits=20)


def test_paid_request_without_anchor_approval_fails_before_quote(
    tmp_path: Path,
) -> None:
    job = _plan(tmp_path)["jobs"][0]
    with pytest.raises(
        PermissionError,
        match="recreation_anchor_approval_required_before_quote",
    ):
        higgsfield_request(_governed(job), max_credits=20)


def test_recreation_review_keeps_fidelity_dimensions_separate(tmp_path: Path) -> None:
    analysis = analyze_reference_reel(
        _reference(tmp_path),
        source_platform="instagram",
        operator_authorized=True,
    )
    final_sha = "a" * 64
    review = build_recreation_review(
        final_sha256=final_sha,
        reference_analysis=analysis,
        ratings={
            "broadActionFidelity": "good",
            "cameraFramingFidelity": "mixed",
            "choreographyFidelity": "",
        },
    )
    assert set(review["ratings"]) == {
        "broadActionFidelity",
        "cameraFramingFidelity",
    }
    assert review["wouldPost"] is None
    assert "choreographyFidelity" in RECREATION_REVIEW_FIELDS


def test_passive_selfie_remains_kling_default(tmp_path: Path) -> None:
    batch = plan_production_batch(
        _factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )
    assert (
        batch["jobs"][0]["productionRecipe"]["modelId"] == "higgsfield_kling3_turbo_i2v"
    )


def test_passive_paid_request_requires_exact_source_approval_fingerprint(
    tmp_path: Path,
) -> None:
    job = plan_production_batch(
        _factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )["jobs"][0]
    job["providerOutputPath"] = str(tmp_path / "output.mp4")
    job["providerReviewRoot"] = str(tmp_path / "review")

    with pytest.raises(
        PermissionError,
        match="exact_source_approval_fingerprint_required",
    ):
        higgsfield_request(_governed(job), max_credits=20)

    job["sourceApproval"] = {
        "approvalEventId": "approval-event-1",
        "approvalFingerprint": "a" * 64,
    }
    request = higgsfield_request(_governed(job), max_credits=20)
    assert request.source_approval == "a" * 64
    assert request.balance_delta_attribution_allowed is False


def test_recovery_request_reuses_exact_authorization_and_quote(tmp_path: Path) -> None:
    job = plan_production_batch(
        _factory(tmp_path),
        creator="stacey",
        intent="passive_selfie",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
    )["jobs"][0]
    quote = {
        "provider": "higgsfield",
        "amount": 8.0,
        "unit": "higgsfield_credits",
    }
    job.update(
        {
            "providerOutputPath": str(tmp_path / "output.mp4"),
            "providerReviewRoot": str(tmp_path / "review"),
            "providerPlanFingerprint": "b" * 64,
            "sourceApproval": {
                "approvalEventId": "approval-event-1",
                "approvalFingerprint": "a" * 64,
            },
            "_higgsfieldAuthorization": None,
            "_higgsfieldRecovery": {
                "authorizationId": "authorization-1",
                "creditQuote": quote,
            },
        }
    )

    request = higgsfield_request(
        _governed(job), max_credits=20, attempt_id="pipeline-1:1"
    )

    assert request.authorization_id == "authorization-1"
    assert (
        request.authorized_quote_fingerprint
        == hashlib.sha256(
            json.dumps(quote, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_reference_analysis_is_bounded_and_retains_private_identity(
    tmp_path: Path,
) -> None:
    reference = _reference(tmp_path)
    analysis = analyze_reference_reel(
        reference,
        source_platform="instagram",
        operator_authorized=True,
    )
    assert analysis["analysisLimits"] == {
        "boundedFrameSamples": 12,
        "semanticFieldsInvented": False,
        "signedSourceUrlRetained": False,
        "providerCalls": 0,
    }
    assert analysis["operatorAuthorization"] == {
        "authorized": True,
        "intendedUse": "recreate_reel",
    }
    assert analysis["originalLocalFile"]["path"] == str(reference.resolve())


def test_reference_analysis_rejects_unsupported_geometry(tmp_path: Path) -> None:
    path = tmp_path / "landscape.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=24",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="portrait 9:16"):
        analyze_reference_reel(path, operator_authorized=True)


def test_plan_never_serializes_wavespeed_or_motion_control(tmp_path: Path) -> None:
    batch = _plan(tmp_path)
    serialized = str(batch).lower()
    assert "wavespeed" not in serialized
    assert "motion_control" not in serialized
    assert batch["provider"] == "higgsfield"


def test_trending_audio_is_explicit_finishing_policy(tmp_path: Path) -> None:
    job = _plan(tmp_path, audio_preference="embedded_trending")["jobs"][0]
    assert job["audioPolicy"] == "embedded_trending_required"
    assert job["productionRecipe"]["stages"][0]["generatedAudio"] is False


def test_explicit_silence_is_allowed_without_changing_provider(tmp_path: Path) -> None:
    job = _plan(tmp_path, audio_preference="silent_allowed")["jobs"][0]
    assert job["audioPolicy"] == "silent_allowed"
    assert job["productionRecipe"]["provider"] == "higgsfield"


def test_wrong_creator_inventory_cannot_be_selected(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    factory.conn.execute("INSERT INTO models VALUES ('model-2','larissa')")
    larissa = tmp_path / "larissa.png"
    Image.new("RGB", (360, 640), "#333333").save(larissa)
    factory.conn.execute(
        "INSERT INTO source_assets VALUES "
        "('source-larissa','campaign-1','model-2',?,?,'image','approved','2026','{}')",
        (hashlib.sha256(larissa.read_bytes()).hexdigest(), str(larissa)),
    )
    job = _plan(tmp_path, factory=factory)["jobs"][0]
    assert job["sourceAssetId"] == "source-stacey"
    assert job["creator"] == "stacey"


def test_soul_identity_remains_bound_in_provider_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (360, 640), "purple").save(source)
    reference = _reference(tmp_path)
    approval = _anchor_approval(tmp_path, source=source, reference=reference)
    request = HiggsfieldProductionRequest(
        recipe_id="higgsfield_recreate_reel",
        creator="stacey",
        soul_id="soul-stacey",
        source_approval=approval["approvalFingerprint"],
        source_asset_id=f"sha256:{approval['anchorFileSha256']}",
        campaign_source_asset_id="source-asset-1",
        source_approval_id=(
            f"recreation_anchor_approval:{approval['approvalFingerprint']}"
        ),
        source_image_path=Path(approval["anchorFilePath"]),
        driving_video_path=reference,
        output_path=tmp_path / "output.mp4",
        review_root=tmp_path / "review",
        prompt="Closely follow broad structure with stable creator identity.",
        model="seedance_2_0",
        duration_seconds=5,
        max_credits=30,
        reference_elements_path=_reference_elements(tmp_path),
        recreation_anchor_approval=approval,
    )
    plan = build_higgsfield_production_plan(request, capabilities=_capabilities())
    assert plan["soul"]["id"] == "soul-stacey"
    assert plan["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_quote_contract_uses_same_reference_roles_as_submission(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (360, 640), "purple").save(source)
    reference = _reference(tmp_path)
    approval = _anchor_approval(tmp_path, source=source, reference=reference)
    request = HiggsfieldProductionRequest(
        recipe_id="higgsfield_recreate_reel",
        creator="stacey",
        soul_id="soul-stacey",
        source_approval=approval["approvalFingerprint"],
        source_image_path=Path(approval["anchorFilePath"]),
        driving_video_path=reference,
        output_path=tmp_path / "output.mp4",
        review_root=tmp_path / "review",
        prompt="Closely follow broad structure with stable creator identity.",
        model="seedance_2_0",
        duration_seconds=5,
        max_credits=30,
        reference_elements_path=_reference_elements(tmp_path),
        recreation_anchor_approval=approval,
    )
    plan = build_higgsfield_production_plan(request, capabilities=_capabilities())
    assert plan["quoteCommand"][2:4] == ["cost", "seedance_2_0"]
    quote = plan["quoteCommand"]
    assert quote[quote.index("--image-references") + 1] == approval["anchorFilePath"]
    assert quote[quote.index("--video-references") + 1] == str(reference)


def test_spend_scope_binds_approved_anchor_and_reference_bytes(tmp_path: Path) -> None:
    job = _plan(tmp_path)["jobs"][0]
    anchor = tmp_path / "approved-anchor.png"
    Image.new("RGB", (360, 640), "gold").save(anchor)
    approval = write_recreation_anchor_approval(
        output_dir=tmp_path / "anchor-approvals",
        creator="stacey",
        soul_id=CREATOR_SOUL_IDS["stacey"],
        anchor_generation_id="anchor-generation-1",
        anchor_file=anchor,
        prompt_pack_id="prompt-pack-1",
        prompt_pack_fingerprint="a" * 64,
        anchor_prompt_fingerprint="b" * 64,
        creator_image_sha256=job["sourceSha256"],
        reference_video_sha256=job["referenceVideoSha256"],
        selected_composition_frame_sha256="c" * 64,
        approved_by="operator@test",
    )
    job["promptCard"]["openaiPromptPackFingerprint"] = "a" * 64
    job["recreationAnchorApprovalPath"] = approval["receiptPath"]
    job["recreationAnchorApprovalFingerprint"] = approval["approvalFingerprint"]
    job["recreationAnchorPath"] = approval["anchorFilePath"]
    job["recreationAnchorSha256"] = approval["anchorFileSha256"]
    stage = job["productionRecipe"]["stages"][0]
    reference_elements = _reference_elements(tmp_path)
    request = HiggsfieldProductionRequest(
        recipe_id="higgsfield_recreate_reel",
        creator="stacey",
        soul_id=CREATOR_SOUL_IDS["stacey"],
        source_approval=approval["approvalFingerprint"],
        source_asset_id=f"sha256:{approval['anchorFileSha256']}",
        campaign_source_asset_id=job["sourceAssetId"],
        source_approval_id=(
            f"recreation_anchor_approval:{approval['approvalFingerprint']}"
        ),
        source_image_path=Path(approval["anchorFilePath"]),
        driving_video_path=Path(job["referenceVideoPath"]),
        output_path=tmp_path / "output.mp4",
        review_root=tmp_path / "review",
        prompt=job["prompt"],
        model=stage["providerModel"],
        duration_seconds=stage["durationSeconds"],
        max_credits=30,
        seed=job["seed"],
        reference_elements_path=reference_elements,
        work_item_id=job["jobId"],
        attempt_id="pipeline-1:1",
        recreation_anchor_approval=approval,
        public_mode="recreate_reel",
        campaign=job["campaign"],
        cohort_id=job["jobId"],
        prompt_card_fingerprint=job["promptCard"]["promptCardFingerprint"],
        prompt_builder_fingerprint="f" * 64,
        batch_balance_snapshot_fingerprint="9" * 64,
    )
    capabilities = _capabilities()
    capabilities["souls"][0]["id"] = CREATOR_SOUL_IDS["stacey"]
    provider_plan = build_higgsfield_production_plan(request, capabilities=capabilities)
    provider_quote = {
        "provider": "higgsfield",
        "amount": 8.0,
        "unit": "higgsfield_credits",
    }
    scope = higgsfield_spend_scope(
        job,
        provider_plan=provider_plan,
        provider_quote=provider_quote,
    )
    assert scope["provider"] == "higgsfield"
    assert scope["providerModels"] == ["seedance_2_0"]
    assert scope["source"]["sha256"] == approval["anchorFileSha256"]
    assert scope["drivingVideo"]["sha256"] == job["referenceVideoSha256"]
    assert (
        scope["recreationAnchorApproval"]["approvalFingerprint"]
        == approval["approvalFingerprint"]
    )
    assert scope["referenceElement"]["fileSha256"]
    assert scope["resolvedPromptSha256"]
    assert scope["providerCommandFingerprint"]
    assert scope["providerCallCount"] == 1
    assert scope["requestFingerprint"] == provider_plan["providerRequestFingerprint"]
    changed_elements = json.loads(reference_elements.read_text(encoding="utf-8"))
    changed_elements[0]["revision"] = 2
    reference_elements.write_text(json.dumps(changed_elements), encoding="utf-8")
    changed_plan = build_higgsfield_production_plan(request, capabilities=capabilities)
    assert (
        changed_plan["providerRequestFingerprint"]
        != provider_plan["providerRequestFingerprint"]
    )
    authorization = sign_authorization(
        {
            "schema": "campaign_factory.provider_spend_authorization.v1",
            "authorizationId": "authorization-1",
            "reservationId": "reservation-1",
            "issuer": "campaign_factory",
            "status": "authorized",
            "legacyCompatibility": True,
            "issuedAt": "2026-07-29T12:00:00Z",
            "expiresAt": "2026-07-29T12:05:00Z",
            "scope": scope,
            "providerQuote": provider_quote,
        },
        secret="test-only-provider-secret-at-least-32-bytes",
    )
    validate_provider_spend_authorization(authorization)


def test_dry_run_quotes_but_never_authorizes_or_submits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quoted = {"called": 0}

    def fake_quote(_factory: Any, jobs: list[dict[str, Any]], **_kwargs: Any):
        quoted["called"] += 1
        return [{**jobs[0], "quotedProviderCredits": 12.5}]

    def forbidden(*_args: Any, **_kwargs: Any):
        raise AssertionError("dry-run must not authorize or submit")

    monkeypatch.setattr(production_lane, "_prepare_higgsfield_job_quotes", fake_quote)
    monkeypatch.setattr(production_lane, "_authorize_higgsfield_jobs", forbidden)
    monkeypatch.setattr(production_lane, "_run_production_job", forbidden)
    result = production_lane.run_production_batch(
        _factory(tmp_path),
        creator="stacey",
        intent="recreate_reel",
        count=1,
        execution="cloud",
        accounts="stacey-main",
        audio_preference="embedded_trending",
        apply=False,
        max_total_credits=20,
        reference_video_path=_reference(tmp_path),
        reference_authorized=True,
    )
    assert quoted["called"] == 1
    assert result["paidGenerationAuthorized"] is False
    assert result["providerQuoteStatus"] == "quoted_not_authorized"
    assert result["quotedProviderCredits"] == 12.5


def test_complete_batch_must_fit_one_balance_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "1")
    jobs = [
        {
            "jobId": f"job-{index}",
            "quotedProviderCredits": 15.0,
            "_higgsfieldCapabilities": {
                "observedAt": "2026-07-29T12:00:00Z",
                "authentication": {"credits": 20.0},
            },
        }
        for index in range(2)
    ]

    with pytest.raises(
        PermissionError,
        match="complete_batch_exceeds_available_balance",
    ):
        _authorize_batch_balance(factory, jobs)

    assert (
        factory.conn.execute(
            "SELECT COUNT(*) FROM provider_spend_authorizations"
        ).fetchone()[0]
        == 0
    )


def test_batch_authorization_rolls_back_before_bad_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = make_factory(tmp_path)
    ensure_authorization_table(factory.conn)
    pipeline_job = factory.domains.events.create_pipeline_job(
        "higgsfield_motion_generation",
        None,
    )
    pipeline_job = factory.domains.events.start_pipeline_job(pipeline_job["id"])
    monkeypatch.setattr(
        authorization_subject,
        "_provider_balance_snapshot",
        lambda: {
            "credits": 100.0,
            "observedAt": "2026-07-29T12:00:00Z",
            "evidenceFingerprint": "b" * 64,
        },
    )
    monkeypatch.setattr(
        authorization_subject,
        "_authorize_batch_balance",
        lambda *_args, **_kwargs: {"fingerprint": "c" * 64, "credits": 100.0},
    )
    monkeypatch.setattr(
        authorization_subject,
        "validate_provider_spend_batch_capacity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        authorization_subject,
        "higgsfield_spend_scope",
        lambda *_args, **_kwargs: {
            "requestFingerprint": "d" * 64,
            "providerCommandFingerprint": "e" * 64,
            "quoteFingerprint": "f" * 64,
        },
    )

    def issue(conn: sqlite3.Connection, **_kwargs: Any) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO provider_spend_authorizations
              (authorization_id, reservation_id, provider, campaign_id, cohort_id,
               request_fingerprint, amount, unit, scope_json, provider_quote_json,
               status, issued_at, expires_at)
            VALUES ('auth-fresh', 'res-fresh', 'higgsfield', NULL, 'cohort',
                    ?, 1, 'higgsfield_credits', '{}', '{}', 'authorized',
                    '2026-07-29T12:00:00Z', '2099-01-01T00:00:00Z')
            """,
            ("d" * 64,),
        )
        conn.commit()
        return {
            "authorizationId": "auth-fresh",
            "reservationId": "res-fresh",
        }

    monkeypatch.setattr(
        authorization_subject,
        "issue_provider_spend_authorization",
        issue,
    )
    prepared = [
        {
            "jobId": "fresh",
            "quotedProviderCredits": 1.0,
            "_campaignId": "campaign-1",
            "_providerPipelineJobId": pipeline_job["id"],
            "_higgsfieldPlan": {
                "providerRequestFingerprint": "d" * 64,
                "executionFingerprint": "e" * 64,
                "selectedModel": "kling3_0",
                "command": [],
                "quoteCommand": [],
            },
            "_higgsfieldQuote": {
                "provider": "higgsfield",
                "amount": 1.0,
                "unit": "higgsfield_credits",
            },
            "_higgsfieldRecovery": None,
        },
        {
            "jobId": "bad-recovery",
            "_higgsfieldRecovery": {
                "authorizationId": "missing",
                "providerRequestFingerprint": "f" * 64,
                "attemptId": "missing-job:1",
            },
        },
    ]

    with pytest.raises(
        PermissionError,
        match="recovery_authorization_binding_missing",
    ):
        _authorize_prepared_higgsfield_jobs(factory, prepared)

    assert (
        factory.conn.execute(
            "SELECT COUNT(*) FROM provider_spend_authorizations "
            "WHERE status = 'authorized'"
        ).fetchone()[0]
        == 0
    )
    factory.close()


def test_batch_balance_evidence_persists_projected_remaining(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    job = {
        "jobId": "job-1",
        "quotedProviderCredits": 15.0,
        "_higgsfieldCapabilities": {
            "observedAt": "2026-07-29T12:00:00Z",
            "authentication": {"credits": 20.0},
        },
    }

    snapshot = _authorize_batch_balance(
        factory,
        [job],
        provider_snapshot={
            "observedAt": "2026-07-29T12:01:00Z",
            "credits": 20.0,
            "evidenceFingerprint": "e" * 64,
        },
    )

    assert snapshot["balanceEvidenceFingerprint"] == "e" * 64
    assert snapshot["existingActiveReservations"] == 0
    assert snapshot["preparedBatchQuote"] == 15.0
    assert snapshot["projectedRemainingBalance"] == 5.0


def test_apply_requires_reference_authorization_before_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        production_lane,
        "_authorize_higgsfield_jobs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("authorization must not be reached")
        ),
    )
    with pytest.raises(PermissionError, match="--reference-authorized"):
        production_lane.run_production_batch(
            _factory(tmp_path),
            creator="stacey",
            intent="recreate_reel",
            count=1,
            execution="cloud",
            accounts="stacey-main",
            audio_preference="embedded_trending",
            apply=True,
            max_total_credits=20,
            reference_video_path=_reference(tmp_path),
            reference_authorized=False,
        )
