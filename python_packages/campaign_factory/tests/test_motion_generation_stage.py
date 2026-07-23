from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from campaign_asset_test_support import add_audit_report
from campaign_factory import motion_qc_publishability as motion_qc_module
from campaign_factory.canonical_analyzer_registry import (
    CanonicalAnalyzerRegistryError,
)
from campaign_factory.cli_dispatch_operations import dispatch_operations_commands
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.contentforge_cli import run_contentforge
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.motion_generation_stage import (
    MotionWorkerError,
    _ensure_motion_edit_source_asset,
    _invoke_worker,
    _motion_request_fingerprint,
    _register_review_asset,
    _worker_command,
    run_motion_generation_stage,
)
from campaign_test_support import add_source_asset, make_factory
from creator_os_core.evidence_attestation import (
    payload_fingerprint,
    sign_evidence_attestation,
)
from reel_factory import motion_generate as reel_motion_generate
from reel_factory.local_video import LocalVideoRequest

PROMPT = "Natural breathing, a gentle head turn, and a slow cinematic camera push"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_SECRET = "creator-os-test-evidence-secret-32-bytes-long"


@pytest.fixture(autouse=True)
def _evidence_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)


def _fingerprint(value: object) -> str:
    return payload_fingerprint(value)


@lru_cache(maxsize=1)
def _canonical_analyzer_registry() -> dict:
    return run_contentforge(
        REPOSITORY_ROOT / "packages" / "contentforge",
        "analyzer-registry",
        {"producedAt": "2026-07-22T20:00:00Z"},
        timeout=30,
    )


def _local_motion_admission(model_id: str) -> dict:
    summary_fingerprint = "b" * 64
    runtime_binding = {
        "runtimeId": "mlx_video",
        "repository": "https://example.invalid/mlx-video.git",
        "revision": "runtime-revision-1",
        "platform": "Darwin",
        "platformRelease": "25.0.0",
        "osBuild": "25A123",
        "machine": "arm64",
        "python": "3.12.10",
        "pythonExecutable": "/opt/creator-os/bin/python",
        "pythonExecutableResolved": "/opt/creator-os/bin/python3.12",
        "mlxVersion": "0.29.3",
        "runtimeReceiptFingerprint": "1" * 64,
        "resolvedEnvironmentFingerprint": "2" * 64,
        "ffmpegExecutable": "/opt/homebrew/bin/ffmpeg",
        "ffmpegSha256": "3" * 64,
        "ffmpegSize": 1_024,
        "ffmpegVersion": "ffmpeg version 8.0",
        "ffprobeExecutable": "/opt/homebrew/bin/ffprobe",
        "ffprobeSha256": "4" * 64,
        "ffprobeSize": 512,
        "ffprobeVersion": "ffprobe version 8.0",
    }
    license_policy = {
        "licenseId": "apache-2.0",
        "commercialUse": True,
        "declaredAnnualRevenueUsd": None,
        "commercialRevenueLimitUsd": None,
        "commercialUseAllowed": True,
        "aiDisclosureRequired": False,
    }
    runtime_fingerprint = _fingerprint(runtime_binding)
    license_fingerprint = _fingerprint(license_policy)
    request = {
        "creatorId": "stacey",
        "identityProfileId": "profile-1",
        "identityProfileFingerprint": "1" * 64,
        "contentIntentId": "intent-1",
        "contentIntentFingerprint": "2" * 64,
        "taskKind": "image_to_video",
        "capabilityCohort": "image_to_video",
    }
    cohort_key = dict(request)
    promotion = {
        "approvalEventId": "promotion-1",
        "approvalEventHash": "3" * 64,
        "hardwareFingerprint": "4" * 64,
        "evidenceFingerprint": "5" * 64,
        "candidateBenchmarkIds": ["benchmark-1"],
    }
    winning = {
        "arenaSummaryFingerprint": summary_fingerprint,
        "cohortKey": cohort_key,
        "promotionApproval": promotion,
        "runtimeBinding": runtime_binding,
        "runtimeBindingFingerprint": runtime_fingerprint,
        "licensePolicy": license_policy,
        "licensePolicyFingerprint": license_fingerprint,
    }
    decision_core = {
        "schema": "reel_factory.local_model_router_decision.v1",
        "decisionId": "decision-1",
        "request": request,
        "selectedModelId": model_id,
        "selectedModelFingerprint": "6" * 64,
        "consideredCandidates": [
            {
                "modelId": model_id,
                "runtimeBinding": runtime_binding,
                "runtimeBindingFingerprint": runtime_fingerprint,
                "licensePolicy": license_policy,
                "licensePolicyFingerprint": license_fingerprint,
            }
        ],
        "paidProviderFallbackAllowed": False,
        "legacyLocalMotionFallbackAllowed": False,
        "winningEvidence": winning,
    }
    decision = {
        **decision_core,
        "decisionFingerprint": _fingerprint(decision_core),
    }
    admission_core = {
        "schema": "campaign_factory.local_motion_admission.v1",
        "routerDecision": decision,
        "arenaSummary": {
            "summaryId": "summary-1",
            "summaryFingerprint": summary_fingerprint,
            "purpose": "promotion_eligible",
        },
        "evidenceRecords": {
            "creatorIdentityProfile": {
                "profileId": "profile-1",
                "creatorKey": "stacey",
            },
            "contentIntent": {
                "intentId": "intent-1",
                "sourceAssetFingerprints": ["c" * 64],
            },
            "benchmarkRecipe": {"recipeId": "recipe-1"},
            "analyzerRegistry": {"registryId": "registry-1"},
        },
        "inputFingerprints": ["c" * 64],
        "resourceSnapshot": {
            "schema": "campaign_factory.local_motion_resource_snapshot.v1"
        },
    }
    return {
        **admission_core,
        "admissionFingerprint": _fingerprint(admission_core),
    }


def test_motion_request_fingerprint_changes_for_every_material_input(
    tmp_path: Path,
) -> None:
    still = tmp_path / "still.jpg"
    audio = tmp_path / "voice.wav"
    still.write_bytes(b"still")
    audio.write_bytes(b"audio")
    base = dict(
        model_id="local_ltx23_distilled_mlx",
        prompt=PROMPT,
        still=still,
        duration_seconds=6,
        resolution="576x1024",
        seed=42,
        steps=8,
        audio_path=audio,
        generate_audio=False,
        last_image_path=None,
        reference_image_paths=(),
        reference_video_paths=(),
        enable_prompt_expansion=False,
        shot_type="single",
        local_model_dir=None,
        motion_task="audio_image_to_video",
        motion_lora_path=None,
        motion_lora_strength=1.0,
    )
    first = _motion_request_fingerprint(**base)
    assert first == _motion_request_fingerprint(**base)
    for key, value in {
        "prompt": PROMPT + " outdoors",
        "duration_seconds": 10,
        "seed": 43,
        "motion_task": "image_to_video",
        "generate_audio": True,
    }.items():
        changed = {**base, key: value}
        assert _motion_request_fingerprint(**changed) != first


def test_motion_worker_binds_exact_benchmark_evidence(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        recipe = {
            "schema": "creator_os.benchmark_recipe.v1",
            "recipeId": "recipe-1",
        }
        registry = {
            "schema": "creator_os.analyzer_registry.v1",
            "registryId": "registry-1",
        }
        base = dict(
            model_id="local_wan22_i2v_a14b_q4_mlx",
            prompt=PROMPT,
            still=still,
            duration_seconds=6,
            resolution="720p",
            seed=42,
            steps=20,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="image_to_video",
            motion_lora_path=None,
            motion_lora_strength=1.0,
        )
        unlinked = _motion_request_fingerprint(**base)
        linked = _motion_request_fingerprint(
            **base,
            benchmark_recipe=recipe,
            analyzer_registry=registry,
        )
        assert linked != unlinked
        command = _worker_command(
            cf,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            dry_run=True,
            benchmark_recipe=recipe,
            analyzer_registry=registry,
            evidence_transport_dir=tmp_path / "worker-evidence",
            **base,
        )
        recipe_index = command.index("--benchmark-recipe")
        registry_index = command.index("--analyzer-registry")
        recipe_path = Path(command[recipe_index + 1])
        registry_path = Path(command[registry_index + 1])
        assert json.loads(recipe_path.read_text()) == recipe
        assert json.loads(registry_path.read_text()) == registry
        assert command[command.index("--benchmark-recipe-sha256") + 1] == (
            hashlib.sha256(recipe_path.read_bytes()).hexdigest()
        )
        assert command[command.index("--analyzer-registry-sha256") + 1] == (
            hashlib.sha256(registry_path.read_bytes()).hexdigest()
        )
        assert not any(arg.lstrip().startswith("{") for arg in command)
        assert recipe_path.stat().st_mode & 0o222 == 0
        recipe_path.chmod(0o644)
        with pytest.raises(ValueError, match="evidence file is mutable"):
            _worker_command(
                cf,
                output_path=tmp_path / "out.mp4",
                campaign_slug="may",
                dry_run=True,
                benchmark_recipe=recipe,
                analyzer_registry=registry,
                evidence_transport_dir=tmp_path / "worker-evidence",
                **base,
            )
    finally:
        cf.close()


def test_motion_worker_forwards_exact_router_admission(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        admission = _local_motion_admission("local_wan22_i2v_a14b_q4_mlx")
        command = _worker_command(
            cf,
            model_id="local_wan22_i2v_a14b_q4_mlx",
            prompt=PROMPT,
            still=still,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            duration_seconds=6,
            resolution="704x1280",
            seed=42,
            steps=20,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="image_to_video",
            motion_lora_path=None,
            motion_lora_strength=1.0,
            local_motion_admission=admission,
            evidence_transport_dir=tmp_path / "worker-evidence",
            dry_run=True,
        )
        index = command.index("--local-motion-admission")
        admission_path = Path(command[index + 1])
        assert json.loads(admission_path.read_text()) == admission
        assert command[command.index("--local-motion-admission-sha256") + 1] == (
            hashlib.sha256(admission_path.read_bytes()).hexdigest()
        )
        assert not any(str(admission["admissionFingerprint"]) in arg for arg in command)
    finally:
        cf.close()


def test_campaign_worker_command_cross_package_dry_run_preserves_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted-cross-package.jpg"
        still.write_bytes(b"accepted-cross-package-still")
        output = tmp_path / "must-not-be-written.mp4"
        admission = _local_motion_admission("local_wan22_i2v_a14b_q4_mlx")
        recipe = {"recipeId": "cross-package-recipe"}
        registry = {"registryId": "cross-package-registry"}
        command = _worker_command(
            cf,
            model_id="local_wan22_i2v_a14b_q4_mlx",
            prompt=PROMPT,
            still=still,
            output_path=output,
            campaign_slug="may",
            duration_seconds=6,
            resolution="720p",
            seed=42,
            steps=20,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="image_to_video",
            motion_lora_path=None,
            motion_lora_strength=1.0,
            benchmark_recipe=recipe,
            analyzer_registry=registry,
            local_motion_admission=admission,
            evidence_transport_dir=tmp_path / "worker-evidence",
            dry_run=True,
        )
        captured: dict[str, object] = {}

        def fake_local_generation(request, *, dry_run):
            captured["request"] = request
            captured["dry_run"] = dry_run
            return {
                "schema": "reel_factory.local_video_run.v1",
                "status": "planned",
                "providerCalls": 0,
            }

        monkeypatch.setattr(
            reel_motion_generate, "run_local_video", fake_local_generation
        )
        monkeypatch.setattr(
            reel_motion_generate,
            "execute_wavespeed",
            lambda *_args, **_kwargs: pytest.fail("paid provider must not be called"),
        )
        before_rows = cf.conn.execute(
            "SELECT COUNT(*) FROM rendered_assets"
        ).fetchone()[0]
        argv = command[command.index("reel_factory.motion_generate") + 1 :]

        assert reel_motion_generate.main(argv) == 0
        response = json.loads(capsys.readouterr().out)
        request = captured["request"]
        assert isinstance(request, LocalVideoRequest)
        assert captured["dry_run"] is True
        assert request.local_motion_admission == admission
        assert request.benchmark_recipe == recipe
        assert request.analyzer_registry == registry
        assert response["providerCalls"] == 0
        assert response["paidGeneration"] is False
        assert output.exists() is False
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0]
            == before_rows
        )
    finally:
        cf.close()


def _register_motion_fixture(
    cf,
    tmp_path: Path,
    *,
    model_id: str = "local_wan22_i2v_a14b_q4_mlx",
    audio_mode: str = "none",
    motion_task: str = "image_to_video",
) -> dict:
    source = add_source_asset(cf, tmp_path)
    still = tmp_path / f"{model_id}-accepted.jpg"
    still.write_bytes(b"accepted-still")
    output = tmp_path / f"{model_id}-motion.mp4"
    output.write_bytes(f"generated-{model_id}-{audio_mode}".encode())
    return _register_review_asset(
        cf,
        campaign=cf.domains.campaign_by_slug("may"),
        source_asset_id=source["id"],
        model_slug="stacey",
        model_id=model_id,
        source_path=still,
        source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
        output_path=output,
        worker_result={
            "result": {
                "audio": {
                    "mode": audio_mode,
                    "nativePlatformAudio": False,
                }
            }
        },
        paid=False,
        motion_task=motion_task,
    )


def test_generation_blob_deduplicates_bytes_but_preserves_every_attempt(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        campaign = cf.domains.campaign_by_slug("may")
        still_one = tmp_path / "input-one.jpg"
        still_two = tmp_path / "input-two.jpg"
        still_one.write_bytes(b"input-one")
        still_two.write_bytes(b"input-two")
        output_one = tmp_path / "attempt-one.mp4"
        output_two = tmp_path / "attempt-two.mp4"
        output_one.write_bytes(b"identical-motion-output")
        output_two.write_bytes(b"identical-motion-output")

        first = _register_review_asset(
            cf,
            campaign=campaign,
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_wan22_i2v_a14b_q4_mlx",
            source_path=still_one,
            source_hash=hashlib.sha256(still_one.read_bytes()).hexdigest(),
            output_path=output_one,
            worker_result={"result": {"audio": {"mode": "none"}}},
            paid=False,
            request_fingerprint="1" * 64,
            prompt="first material prompt",
            local_motion_admission={"admissionFingerprint": "a" * 64},
        )
        second = _register_review_asset(
            cf,
            campaign=campaign,
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_ltx23_dev_mlx",
            source_path=still_two,
            source_hash=hashlib.sha256(still_two.read_bytes()).hexdigest(),
            output_path=output_two,
            worker_result={"result": {"audio": {"mode": "none"}}},
            paid=False,
            request_fingerprint="2" * 64,
            prompt="second materially different prompt",
            local_motion_admission={"admissionFingerprint": "b" * 64},
        )

        assert second["id"] == first["id"]
        assert output_one.is_file()
        assert not output_two.exists()
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE campaign_id = ?",
                (campaign["id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM generation_output_blobs").fetchone()[
                0
            ]
            == 1
        )
        attempts = cf.conn.execute(
            """
            SELECT model_id, request_fingerprint, prompt_sha256, source_sha256,
                   admission_fingerprint, duplicate_disposition, output_blob_id
            FROM generation_attempts
            WHERE rendered_asset_id = ? ORDER BY created_at, id
            """,
            (first["id"],),
        ).fetchall()
        assert len(attempts) == 2
        assert {row["model_id"] for row in attempts} == {
            "local_wan22_i2v_a14b_q4_mlx",
            "local_ltx23_dev_mlx",
        }
        assert {row["request_fingerprint"] for row in attempts} == {
            "1" * 64,
            "2" * 64,
        }
        assert len({row["prompt_sha256"] for row in attempts}) == 2
        assert len({row["source_sha256"] for row in attempts}) == 2
        assert {row["admission_fingerprint"] for row in attempts} == {
            "a" * 64,
            "b" * 64,
        }
        assert {row["duplicate_disposition"] for row in attempts} == {
            "canonical_output",
            "removed_unreferenced_duplicate",
        }
        assert len({row["output_blob_id"] for row in attempts}) == 1
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM generation_lineage_edges WHERE rendered_asset_id = ?",
                (first["id"],),
            ).fetchone()[0]
            == 2
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            cf.conn.execute(
                "UPDATE generation_attempts SET model_id = 'mutated' "
                "WHERE rendered_asset_id = ?",
                (first["id"],),
            )
    finally:
        cf.close()


def test_generation_lineage_backfills_legacy_assets_without_changing_asset_reads(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        legacy, _ = _legacy_rendered_asset_fixture(cf, tmp_path)
        legacy_id = legacy["id"]
        legacy_hash = legacy["content_hash"]
    finally:
        cf.close()

    reopened = make_factory(tmp_path)
    try:
        assert (
            reopened.conn.execute(
                "SELECT content_hash FROM rendered_assets WHERE id = ?", (legacy_id,)
            ).fetchone()[0]
            == legacy_hash
        )
        attempt = reopened.conn.execute(
            "SELECT * FROM generation_attempts WHERE id = ?",
            (f"attempt_legacy_{legacy_id}",),
        ).fetchone()
        assert attempt is not None
        assert attempt["duplicate_disposition"] == "legacy_reference"
        assert attempt["output_blob_id"] == f"blob_{legacy_hash}"
        assert (
            reopened.conn.execute(
                "SELECT COUNT(*) FROM generation_lineage_edges "
                "WHERE generation_attempt_id = ?",
                (attempt["id"],),
            ).fetchone()[0]
            == 1
        )
    finally:
        reopened.close()


def _legacy_rendered_asset_fixture(cf, tmp_path: Path) -> tuple[dict, Path]:
    source = add_source_asset(cf, tmp_path)
    output = tmp_path / "legacy-motion.mp4"
    output.write_bytes(b"legacy-motion")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    now = "2026-07-22T20:00:00+00:00"
    asset_id = "asset_legacy_motion"
    cf.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path,
         filename, media_type, content_surface, recipe, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'reel', 'legacy_motion', ?, ?)
        """,
        (
            asset_id,
            source["campaign_id"],
            source["id"],
            digest,
            str(output),
            str(output),
            output.name,
            now,
            now,
        ),
    )
    cf.conn.commit()
    row = dict(
        cf.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    )
    return row, output


def _motion_qc_receipt(
    subject_sha256: str,
    *,
    source_sha256: str = "c" * 64,
    audio_alignment: bool = False,
    lip_sync: bool = False,
) -> dict:
    requirements = {
        "motion": True,
        "temporal": True,
        "freeze": True,
        "anatomy": True,
        "identity": True,
        "loop": False,
        "audioAlignment": audio_alignment,
        "lipSync": lip_sync,
    }
    registry = deepcopy(_canonical_analyzer_registry())
    registry_fingerprint = _fingerprint(registry)
    analyzer_ids = {
        "contentforge.media_integrity",
        "contentforge.temporal_motion",
        "contentforge.audio_integrity",
        "contentforge.overlay_delivery",
        "contentforge.local_lip_sync",
    }
    analyzer_records = [
        item for item in registry["analyzers"] if item["analyzerId"] in analyzer_ids
    ]
    registrations = {item["analyzerId"]: item for item in analyzer_records}
    tools = {
        "node": "fixture",
        "platform": "fixture",
        "ffmpeg": {"available": True, "version": "fixture"},
        "ffprobe": {"available": True, "version": "fixture"},
    }
    observations = [
        {
            **item,
            "analyzerRegistryId": registry["registryId"],
            "analyzerRegistryFingerprint": registry_fingerprint,
            "toolRevisions": tools,
            "status": "measured",
            "observations": {"available": True},
        }
        for item in analyzer_records
    ]
    for observation in observations:
        if observation["analyzerId"] == "contentforge.temporal_motion":
            observation["observations"] = {
                "sampling": {
                    "framesPerSecond": 8,
                    "width": 180,
                    "height": 320,
                    "sampledFrames": 48,
                    "comparisons": 47,
                    "totalFrames": 144,
                    "durationSeconds": 6.0,
                    "durationCoverageRatio": 1,
                    "frameSetFingerprint": "7" * 64,
                    "briefFrameOutlierCount": 1,
                },
                "meanNormalizedFrameDelta": 0.12,
                "p95NormalizedFrameDelta": 0.1,
                "discontinuityCandidateCount": 1,
                "discontinuityComparisonCount": 10,
                "discontinuityRate": 0.1,
                "discontinuityThreshold": 0.18,
                "frozenFrameRatio": 0.05,
                "loopSeamScore": 0.1,
            }
        elif observation["analyzerId"] == "contentforge.audio_integrity":
            observation["observations"] = {
                "available": True,
                "avStreamStartOffsetMs": 0 if audio_alignment else None,
                "avDurationDeltaMs": 0 if audio_alignment else None,
            }
        elif observation["analyzerId"] == "contentforge.local_lip_sync":
            if lip_sync:
                observation["observations"] = {
                    "available": True,
                    "confidence": 0.9,
                    "offsetMs": 0,
                    "aligned": True,
                    "correlation": 0.8,
                    "sampleCount": 10,
                    "faceTrackCoverage": 0.9,
                    "speechActivityRatio": 0.5,
                }
            else:
                observation["status"] = "not_applicable"
                observation["observations"] = {
                    "available": False,
                    "reason": "speech_not_requested",
                }
    analysis_id = (
        "analysis_"
        + _fingerprint(
            {
                "mediaSha256": subject_sha256,
                "sourceSha256": source_sha256,
                "registryFingerprint": registry_fingerprint,
                "analyzers": observations,
            }
        )[:24]
    )
    analysis = {
        "schema": "contentforge.trusted_media_analysis.v1",
        "analysisId": analysis_id,
        "subject": {
            "mediaPath": "/fixture/output.mp4",
            "mediaSha256": subject_sha256,
            "sourcePath": "/fixture/source.png",
            "sourceSha256": source_sha256,
        },
        "producedAt": "2026-07-22T20:00:00Z",
        "producer": "contentforge.trusted_media_analysis",
        "analyzerRegistry": {
            "registryId": registry["registryId"],
            "registryFingerprint": registry_fingerprint,
        },
        "rawObservations": observations,
        "analyzerVerdicts": [
            {
                "schema": "contentforge.trusted_analyzer_receipt.v1",
                "policy": {
                    "id": observation["analyzerId"],
                    "version": observation["analyzerVersion"],
                },
                "subjectSha256": subject_sha256,
                "analysisId": analysis_id,
                "observationFingerprint": _fingerprint(observation),
                "implementationRef": observation["implementationRef"],
                "implementationFingerprint": observation["implementationFingerprint"],
                "analyzerRegistryId": registry["registryId"],
                "analyzerRegistryFingerprint": registry_fingerprint,
                "verdict": "pass",
                "passed": True,
                "evidenceOnly": True,
                "providerCalls": 0,
                "reasons": [],
            }
            for observation in observations
        ],
        "unavailableMeasurements": {},
        "humanReviewSampling": {
            "sampleFps": 8,
            "width": 180,
            "height": 320,
            "sampledFrames": 48,
            "totalFrames": 144,
            "durationSeconds": 6.0,
            "durationCoverageRatio": 1,
            "frameSetFingerprint": "7" * 64,
            "briefFrameOutlierCount": 1,
        },
    }
    analysis["analysisFingerprint"] = _fingerprint(analysis)
    analysis["producerAttestation"] = sign_evidence_attestation(
        analysis,
        issuer="contentforge.trusted_media_analysis",
        issued_at=analysis["producedAt"],
        secret=EVIDENCE_SECRET,
    )
    review = {
        "schema": "reel_factory.human_media_review.v1",
        "reviewId": "fixture-review",
        "arenaPlanId": "fixture-plan",
        "sampleId": "fixture-sample",
        "blindedCandidateId": "fixture-candidate",
        "subjectSha256": subject_sha256,
        "sourceSha256": source_sha256,
        "reviewer": "fixture-reviewer",
        "reviewedAt": "2026-07-22T20:01:00Z",
        "rubricVersion": "1.0.0",
        "samplingEvidence": {
            "analysisId": analysis_id,
            "analysisFingerprint": analysis["analysisFingerprint"],
            "sampleFps": 8,
            "width": 180,
            "height": 320,
            "sampledFrames": 48,
            "totalFrames": 144,
            "durationSeconds": 6.0,
            "durationCoverageRatio": 1,
            "frameSetFingerprint": "7" * 64,
            "briefFrameOutlierCount": 1,
            "briefFrameOutliersReviewed": True,
        },
        "ratings": {
            "realism": 0.9,
            "attractiveness": 0.9,
            "creatorIdentitySimilarity": 0.9,
            "faceStability": 0.9,
            "motionNaturalness": 0.9,
            "faceArtifactScore": 0.05,
            "handsVisible": False,
            "handArtifactScore": None,
            "bodyArtifactScore": 0.05,
            "conversionUsefulness": 0.9,
            "intentAdherence": 0.9,
            "loopAcceptable": True,
        },
        "decisions": {
            "creatorIdentityPreserved": True,
            "anatomyAcceptable": True,
            "operatorUseful": True,
            "approvedForBenchmark": True,
        },
        "provenance": {
            "reviewMode": "blinded",
            "unblindingReason": None,
            "sourceReferences": [
                {
                    "recordId": analysis_id,
                    "fingerprint": analysis["analysisFingerprint"],
                }
            ],
        },
    }
    review["reviewFingerprint"] = _fingerprint(review)
    review["operatorAttestation"] = sign_evidence_attestation(
        review,
        issuer="reel_factory.structured_human_media_review",
        issued_at=review["reviewedAt"],
        secret=EVIDENCE_SECRET,
    )
    sources = {}
    for name, required in requirements.items():
        if not required and name not in {"loop"}:
            sources[name] = {
                "available": False,
                "analyzer": None,
                "analyzerVersion": None,
                "evidenceId": None,
                "subjectSha256": subject_sha256,
                "analysisFingerprint": None,
                "analyzerRegistryId": None,
                "analyzerRegistryFingerprint": None,
                "implementationRef": None,
                "implementationFingerprint": None,
                "reviewFingerprint": None,
            }
            continue
        if name in {"identity", "anatomy"}:
            sources[name] = {
                "available": True,
                "analyzer": "reel_factory.structured_human_media_review",
                "analyzerVersion": "1.0.0",
                "evidenceId": review["reviewId"],
                "subjectSha256": subject_sha256,
                "reviewFingerprint": review["reviewFingerprint"],
                "analysisFingerprint": None,
                "analyzerRegistryId": None,
                "analyzerRegistryFingerprint": None,
                "implementationRef": None,
                "implementationFingerprint": None,
            }
        else:
            analyzer_id = {
                "lipSync": "contentforge.local_lip_sync",
                "audioAlignment": "contentforge.audio_integrity",
            }.get(name, "contentforge.temporal_motion")
            registration = registrations[analyzer_id]
            sources[name] = {
                "available": True,
                "analyzer": analyzer_id,
                "analyzerVersion": "1.0.0",
                "evidenceId": analysis_id,
                "subjectSha256": subject_sha256,
                "analysisFingerprint": analysis["analysisFingerprint"],
                "analyzerRegistryId": registry["registryId"],
                "analyzerRegistryFingerprint": registry_fingerprint,
                "implementationRef": registration["implementationRef"],
                "implementationFingerprint": registration["implementationFingerprint"],
                "reviewFingerprint": None,
            }
    receipt = {
        "schema": "contentforge.motion_specific_qc_receipt.v2",
        "producer": "contentforge.trusted_motion_qc",
        "policy": {
            "id": "contentforge.motion_specific_qc",
            "version": "2.0.0",
        },
        "subjectSha256": subject_sha256,
        "sourceSha256": source_sha256,
        "verdict": "pass",
        "passed": True,
        "evidenceOnly": True,
        "modelCalls": 0,
        "providerCalls": 0,
        "requirements": requirements,
        "thresholds": {
            "minMotionScore": 0.03,
            "subtleMotionMax": 0.18,
            "moderateMotionMax": 0.5,
            "maxTemporalDiscontinuityScore": 0.25,
            "maxFrozenFrameRatio": 0.2,
            "maxLoopSeamScore": 0.25,
            "maxFaceAnomalyScore": 0.25,
            "maxHandAnomalyScore": 0.3,
            "maxBodyAnomalyScore": 0.25,
            "minIdentitySimilarityScore": 0.75,
            "minLipSyncConfidence": 0.65,
            "maxLipSyncOffsetMs": 120,
            "minAudioAlignmentConfidence": 0.65,
            "maxAudioAlignmentOffsetMs": 120,
        },
        "measurements": {
            "motion": {"score": 0.12, "amount": "subtle"},
            "temporal": {
                "discontinuityScore": 0.1,
                "discontinuityCandidateCount": 1,
                "discontinuityComparisonCount": 10,
                "discontinuityRate": 0.1,
                "outlierThreshold": 0.18,
            },
            "freeze": {"frozenFrameRatio": 0.05},
            "loop": {"seamScore": 0.1, "loopable": True},
            "anatomy": {
                "face": {
                    "applicable": True,
                    "anomalyScore": 0.05,
                    "notApplicableReason": None,
                },
                "hands": {
                    "applicable": False,
                    "anomalyScore": None,
                    "notApplicableReason": "hands_not_visible_in_reviewed_media",
                },
                "body": {
                    "applicable": True,
                    "anomalyScore": 0.05,
                    "notApplicableReason": None,
                },
            },
            "identity": {"similarityScore": 0.9, "matched": True},
            "lipSync": {
                "confidence": 0.9 if lip_sync else None,
                "offsetMs": 0 if lip_sync else None,
                "aligned": True if lip_sync else None,
                "correlation": 0.8 if lip_sync else None,
                "sampleCount": 10 if lip_sync else 0,
                "faceTrackCoverage": 0.9 if lip_sync else None,
                "speechActivityRatio": 0.5 if lip_sync else None,
            },
            "audioAlignment": {
                "confidence": 1.0 if audio_alignment else None,
                "offsetMs": 0 if audio_alignment else None,
                "aligned": True if audio_alignment else None,
            },
        },
        "evidenceSources": sources,
        "reasons": [],
        "trustedEvidence": {
            "analysis": analysis,
            "analyzerRegistry": registry,
            "humanReview": review,
        },
        "bindings": {
            "analysisId": analysis_id,
            "analysisFingerprint": analysis["analysisFingerprint"],
            "analyzerRegistryId": registry["registryId"],
            "analyzerRegistryFingerprint": registry_fingerprint,
            "humanReviewId": review["reviewId"],
            "humanReviewFingerprint": review["reviewFingerprint"],
        },
    }
    receipt["receiptFingerprint"] = _fingerprint(receipt)
    receipt["producerAttestation"] = sign_evidence_attestation(
        receipt,
        issuer="contentforge.trusted_motion_qc",
        issued_at=review["reviewedAt"],
        secret=EVIDENCE_SECRET,
    )
    return receipt


def _asset_source_sha256(asset: dict) -> str:
    metadata = json.loads(asset["metadata_json"])
    return metadata["staticFallbackSource"]["sha256"]


def _semantic_qc_failures(receipt: dict) -> list[str]:
    trusted = receipt["trustedEvidence"]
    registrations = {
        (item["analyzerId"], item["analyzerVersion"]): item
        for item in trusted["analyzerRegistry"]["analyzers"]
    }
    return motion_qc_module._trusted_motion_semantic_failures(
        receipt,
        analysis=trusted["analysis"],
        registry=trusted["analyzerRegistry"],
        review=trusted["humanReview"],
        registrations=registrations,
    )


def test_motion_qc_semantics_reject_false_human_decision() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    receipt["trustedEvidence"]["humanReview"]["decisions"]["operatorUseful"] = False
    assert "motion_specific_qc_human_decision_not_approved" in _semantic_qc_failures(
        receipt
    )


def test_motion_qc_semantics_reject_empty_measurements() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    receipt["measurements"] = {}
    assert "motion_specific_qc_measurements_missing" in _semantic_qc_failures(receipt)


def test_motion_qc_semantics_reject_threshold_substitution() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    receipt["thresholds"]["minIdentitySimilarityScore"] = 0.1
    assert "motion_specific_qc_thresholds_mismatch" in _semantic_qc_failures(receipt)


def test_motion_qc_semantics_rejects_temporal_candidate_substitution() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    receipt["measurements"]["temporal"]["discontinuityCandidateCount"] = 2
    assert "motion_specific_qc_temporal_measurement_invalid" in _semantic_qc_failures(
        receipt
    )


def test_motion_qc_semantics_rejects_lip_sync_measurement_substitution() -> None:
    receipt = _motion_qc_receipt("a" * 64, lip_sync=True)
    receipt["measurements"]["lipSync"]["correlation"] = 0.7
    assert "motion_specific_qc_lipSync_evidence_mismatch" in _semantic_qc_failures(
        receipt
    )


def test_motion_qc_semantics_rejects_human_frame_set_substitution() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    receipt["trustedEvidence"]["humanReview"]["samplingEvidence"][
        "frameSetFingerprint"
    ] = "8" * 64
    assert (
        "motion_specific_qc_human_sampling_evidence_mismatch"
        in _semantic_qc_failures(receipt)
    )


def test_motion_qc_semantics_reject_bad_rubric_time_and_source_reference() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    review = receipt["trustedEvidence"]["humanReview"]
    review["rubricVersion"] = "legacy"
    review["reviewedAt"] = "2026-07-22T19:59:00Z"
    review["provenance"]["sourceReferences"] = [
        {"recordId": "wrong-analysis", "fingerprint": "b" * 64}
    ]
    failures = _semantic_qc_failures(receipt)
    assert "motion_specific_qc_human_rubric_unsupported" in failures
    assert "motion_specific_qc_evidence_time_order_invalid" in failures
    assert "motion_specific_qc_human_source_reference_mismatch" in failures


def test_motion_qc_semantics_require_decisive_analyzer_registrations() -> None:
    receipt = _motion_qc_receipt("a" * 64)
    registry = receipt["trustedEvidence"]["analyzerRegistry"]
    registry["analyzers"] = [
        item
        for item in registry["analyzers"]
        if item["analyzerId"]
        not in {
            "contentforge.motion_specific_qc",
            "reel_factory.structured_human_media_review",
        }
    ]
    assert (
        "motion_specific_qc_decisive_analyzer_registration_missing"
        in _semantic_qc_failures(receipt)
    )


def test_motion_qc_rejects_noncanonical_analyzer_registry_even_when_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_sha = "a" * 64
    source_sha = "b" * 64
    receipt = _motion_qc_receipt(subject_sha, source_sha256=source_sha)
    monkeypatch.setattr(
        motion_qc_module,
        "validate_canonical_analyzer_registry",
        lambda _registry: (_ for _ in ()).throw(
            CanonicalAnalyzerRegistryError("analyzer_registry_not_canonical")
        ),
    )
    failures = motion_qc_module.MotionQcPublishabilityMixin._trusted_motion_qc_failures(
        {
            "content_hash": subject_sha,
            "metadata_json": json.dumps(
                {"generationInput": {"sha256": source_sha}}, sort_keys=True
            ),
        },
        receipt,
    )
    assert "motion_specific_qc_analyzer_registry_not_canonical" in failures


def _write_motion_qc_receipt(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / f"{name}.motion-qc.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def test_text_to_video_worker_omits_image_but_keeps_static_fallback_input(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        command = _worker_command(
            cf,
            model_id="local_wan22_ti2v_5b_mlx",
            prompt=PROMPT,
            still=still,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            duration_seconds=6,
            resolution="704x1280",
            seed=42,
            steps=40,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="text_to_video",
            motion_lora_path=None,
            motion_lora_strength=1.0,
            dry_run=True,
        )
        assert command[command.index("--task") + 1] == "text_to_video"
        assert "--image" not in command
        assert still.is_file()
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("motion_task", "controls"),
    [
        (
            "video_retake",
            {
                "retake_start_frame": 2,
                "retake_end_frame": 5,
                "preserve_audio": True,
            },
        ),
        (
            "video_extend",
            {"extend_frames": 8, "extend_direction": "after"},
        ),
    ],
)
def test_local_video_edit_dry_run_uses_only_the_exact_source_video(
    motion_task: str,
    controls: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"exact-source-video")
        captured: dict = {}

        def fake_worker(command, *, factory, log_dir, phase):
            del factory, log_dir
            captured["command"] = command
            captured["phase"] = phase
            return {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "result": {"status": "planned"},
            }

        def fake_revalidate(admission, **kwargs):
            assert kwargs["accepted_still_path"] is None
            assert kwargs["source_video_path"] == source_video.resolve()
            assert kwargs["task_kind"] == motion_task
            return dict(admission)

        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker", fake_worker
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.revalidate_local_motion_admission",
            fake_revalidate,
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage",
            lambda *_args, **_kwargs: pytest.fail(
                "video edits must not create a static fallback"
            ),
        )

        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("local_wan"),
            campaign_slug="may",
            still_path=None,
            source_video_path=source_video,
            prompt=PROMPT,
            model_id="local_ltx23_distilled_mlx",
            duration_seconds=6,
            resolution=None,
            seed=42,
            steps=8,
            dry_run=True,
            apply=False,
            motion_task=motion_task,
            local_motion_admission=_local_motion_admission("local_ltx23_distilled_mlx"),
            local_arena_summary_path=tmp_path / "arena-summary.json",
            campaign_creator="stacey",
            benchmark_recipe={"recipeId": "fixture"},
            analyzer_registry={"registryId": "fixture"},
            **controls,
        )

        command = captured["command"]
        assert captured["phase"] == "preflight"
        assert command[command.index("--source-video") + 1] == str(
            source_video.resolve()
        )
        assert "--image" not in command
        assert result["staticFallback"] is None
        assert result["registeredAsset"] is None
        assert result["providerCalls"] == 0
        job = cf.domains.events.pipeline_job(result["pipelineJobId"])
        assert job["input"]["sourcePath"] == str(source_video.resolve())
        assert job["input"]["sourceRole"] == "source_video_edit"
        assert (
            job["input"]["sourceSha256"]
            == hashlib.sha256(source_video.read_bytes()).hexdigest()
        )
    finally:
        cf.close()


def test_local_video_edit_fails_closed_when_source_video_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: pytest.fail("worker must not run"),
        )
        with pytest.raises(FileNotFoundError, match="source video not found"):
            run_motion_generation_stage(
                cf,
                execution_plan=build_generation_execution_plan("local_wan"),
                campaign_slug="may",
                still_path=None,
                source_video_path=tmp_path / "missing.mp4",
                prompt=PROMPT,
                model_id="local_ltx23_distilled_mlx",
                duration_seconds=6,
                resolution=None,
                seed=42,
                steps=8,
                dry_run=True,
                apply=False,
                motion_task="video_retake",
                retake_start_frame=2,
                retake_end_frame=5,
                local_motion_admission=_local_motion_admission(
                    "local_ltx23_distilled_mlx"
                ),
                local_arena_summary_path=tmp_path / "arena-summary.json",
                campaign_creator="stacey",
                benchmark_recipe={"recipeId": "fixture"},
                analyzer_registry={"registryId": "fixture"},
            )
    finally:
        cf.close()


def test_local_lora_worker_arguments_are_explicit(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        lora = tmp_path / "motion.safetensors"
        command = _worker_command(
            cf,
            model_id="local_wan22_i2v_a14b_q4_mlx",
            prompt=PROMPT,
            still=still,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            duration_seconds=6,
            resolution="704x1280",
            seed=42,
            steps=20,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="image_to_video",
            motion_lora_path=lora,
            motion_lora_strength=0.7,
            dry_run=True,
        )
        assert command[command.index("--lora") + 1] == str(lora)
        assert command[command.index("--lora-strength") + 1] == "0.7"
    finally:
        cf.close()


def test_registered_video_edit_lineage_has_no_static_fallback(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        source_video = tmp_path / "source-edit.mp4"
        source_video.write_bytes(b"source-edit-video")
        source_sha = hashlib.sha256(source_video.read_bytes()).hexdigest()
        output = tmp_path / "retake.mp4"
        output.write_bytes(b"retake-output")
        asset = _register_review_asset(
            cf,
            campaign=cf.domains.campaign_by_slug("may"),
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_ltx23_distilled_mlx",
            source_path=source_video,
            source_hash=source_sha,
            output_path=output,
            worker_result={"result": {"audio": {"mode": "none"}}},
            paid=False,
            motion_task="video_retake",
            request_fingerprint="7" * 64,
            local_motion_admission=_local_motion_admission("local_ltx23_distilled_mlx"),
            prompt=PROMPT,
        )
        metadata = json.loads(asset["metadata_json"])
        expected_source = {"path": str(source_video), "sha256": source_sha}
        assert metadata["source"] == expected_source
        assert metadata["generationInput"] == expected_source
        assert metadata["staticFallbackSource"] is None
        assert metadata["sourceAssetRole"] == "generation_input_only"
        attempt = dict(
            cf.conn.execute(
                "SELECT * FROM generation_attempts WHERE rendered_asset_id = ?",
                (asset["id"],),
            ).fetchone()
        )
        assert attempt["source_sha256"] == source_sha
        assert json.loads(attempt["input_json"])["sourcePath"] == str(source_video)
    finally:
        cf.close()


def test_motion_edit_source_asset_is_exact_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        source_video = tmp_path / "source-edit.mp4"
        source_video.write_bytes(b"exact-source-edit-video")
        source_sha = hashlib.sha256(source_video.read_bytes()).hexdigest()
        campaign = cf.domains.campaign_by_slug("may")
        model_slug = cf.domains.reel_execution.model_slug_for_campaign(campaign["id"])

        first = _ensure_motion_edit_source_asset(
            cf,
            campaign=campaign,
            model_slug=model_slug,
            source_video=source_video.resolve(),
            source_hash=source_sha,
            motion_task="video_retake",
        )
        stored = Path(first["stored_path"])
        assert first["media_type"] == "video"
        assert first["content_hash"] == source_sha
        assert first["original_path"] == str(source_video.resolve())
        assert stored != source_video.resolve()
        assert stored.read_bytes() == source_video.read_bytes()

        replay = _ensure_motion_edit_source_asset(
            cf,
            campaign=campaign,
            model_slug=model_slug,
            source_video=source_video.resolve(),
            source_hash=source_sha,
            motion_task="video_retake",
        )
        assert replay["id"] == first["id"]

        stored.write_bytes(b"substituted")
        with pytest.raises(
            RuntimeError, match="motion_edit_existing_source_asset_mismatch"
        ):
            _ensure_motion_edit_source_asset(
                cf,
                campaign=campaign,
                model_slug=model_slug,
                source_video=source_video.resolve(),
                source_hash=source_sha,
                motion_task="video_retake",
            )
    finally:
        cf.close()


def test_local_wan_apply_preserves_static_fallback_then_registers_review_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        calls: list[str] = []

        def fake_static(*_args, **kwargs):
            calls.append("static")
            assert kwargs["apply"] is True
            return {"registeredAsset": {"source_asset_id": source["id"]}}

        def fake_worker(command, *, factory, log_dir, phase):
            del factory, log_dir, phase
            if "--dry-run" in command:
                calls.append("preflight")
                return {
                    "schema": "reel_factory.motion_generation_result.v1",
                    "providerCalls": 0,
                    "result": {"status": "planned"},
                }
            calls.append("local_apply")
            output = Path(command[command.index("--out") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"generated-motion-video")
            return {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "result": {
                    "status": "completed",
                    "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
            }

        def fake_revalidate(admission, **kwargs):
            calls.append("revalidate")
            assert kwargs["accepted_still_path"] == still
            assert kwargs["last_image_path"] is None
            assert kwargs["task_kind"] == "text_to_video"
            assert kwargs["model_id"] == "local_wan22_ti2v_5b_mlx"
            return dict(admission)

        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage", fake_static
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker", fake_worker
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.revalidate_local_motion_admission",
            fake_revalidate,
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("local_wan"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="local_wan22_ti2v_5b_mlx",
            duration_seconds=6,
            resolution=None,
            seed=42,
            steps=40,
            dry_run=False,
            apply=True,
            motion_task="text_to_video",
            local_motion_admission=_local_motion_admission("local_wan22_ti2v_5b_mlx"),
            local_arena_summary_path=tmp_path / "arena-summary.json",
            campaign_creator="stacey",
            benchmark_recipe={"recipeId": "fixture"},
            analyzer_registry={"registryId": "fixture"},
        )
        assert calls == [
            "revalidate",
            "preflight",
            "static",
            "revalidate",
            "local_apply",
        ]
        asset = result["registeredAsset"]
        assert asset["audit_status"] == "pending"
        assert asset["review_state"] == "review_ready"
        assert asset["caption"] == ""
        assert result["providerCalls"] == 0
        assert (
            result["localMotionAdmission"]["routerDecision"]["selectedModelId"]
            == "local_wan22_ti2v_5b_mlx"
        )
        metadata = json.loads(asset["metadata_json"])
        assert metadata["creativeApprovalRequired"] is True
        assert metadata["source"] is None
        assert metadata["generationInput"] is None
        assert metadata["sourceAssetRole"] == "static_fallback_only"
        assert metadata["identityRole"] == "non_creator_broll"
        assert (
            "creative_approval_v2_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "text_to_video_identity_assignment_forbidden"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            metadata["staticFallbackSource"]["sha256"]
            == hashlib.sha256(still.read_bytes()).hexdigest()
        )
    finally:
        cf.close()


def test_wavespeed_dry_run_has_zero_provider_calls_and_no_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        scope = {"requestFingerprint": "a" * 64}
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "spendScope": scope,
            },
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage",
            lambda *_args, **_kwargs: {"dryRun": True},
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.issue_wavespeed_spend_authorization",
            lambda *_args, **_kwargs: pytest.fail("dry-run must not authorize spend"),
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("best_motion"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="wavespeed_wan27_i2v_pro",
            duration_seconds=5,
            resolution="1080p",
            seed=42,
            steps=40,
            dry_run=True,
            apply=False,
        )
        assert result["paidGeneration"] is True
        assert result["providerCalls"] == 0
        assert result["registeredAsset"] is None
    finally:
        cf.close()


def test_best_motion_rejects_local_or_unknown_model_before_any_worker_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: pytest.fail("worker must not run"),
        )
        with pytest.raises(PermissionError, match="does not authorize model"):
            run_motion_generation_stage(
                cf,
                execution_plan=build_generation_execution_plan("best_motion"),
                campaign_slug="may",
                still_path=still,
                prompt=PROMPT,
                model_id="local_wan22_ti2v_5b_mlx",
                duration_seconds=6,
                resolution="720p",
                seed=42,
                steps=40,
                dry_run=True,
                apply=False,
            )
    finally:
        cf.close()


def test_ltx_embedded_audio_is_not_misclassified_as_native_platform_audio(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        output = tmp_path / "ltx.mp4"
        output.write_bytes(b"ltx-video-with-audio")
        campaign = cf.domains.campaign_by_slug("may")
        asset = _register_review_asset(
            cf,
            campaign=campaign,
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_ltx23_distilled_mlx",
            source_path=still,
            source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
            output_path=output,
            worker_result={
                "result": {
                    "audio": {
                        "mode": "generated",
                        "nativePlatformAudio": False,
                        "sidecarSha256": "a" * 64,
                    },
                    "aiDisclosureRequired": True,
                }
            },
            paid=False,
        )
        metadata = json.loads(asset["metadata_json"])
        assert metadata["audioBurned"] is True
        assert metadata["embeddedAudioMode"] == "generated"
        assert metadata["nativeAudioResolved"] is False
        assert (
            "local_audio_policy_review_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "ai_generated_media_disclosure_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "motion_specific_qc_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "audio_video_alignment_qc_required"
            in metadata["publishability"]["blockingIssues"]
        )
    finally:
        cf.close()


def test_longcat_talking_asset_requires_lip_sync_qc(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        output = tmp_path / "talking.mp4"
        output.write_bytes(b"talking-video")
        asset = _register_review_asset(
            cf,
            campaign=cf.domains.campaign_by_slug("may"),
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_longcat_avatar15_q4_mlx",
            source_path=still,
            source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
            output_path=output,
            worker_result={
                "result": {
                    "audio": {"mode": "source", "nativePlatformAudio": False},
                    "aiDisclosureRequired": True,
                }
            },
            paid=False,
        )
        blockers = json.loads(asset["metadata_json"])["publishability"][
            "blockingIssues"
        ]
        assert "motion_specific_qc_required" in blockers
        assert "audio_video_alignment_qc_required" in blockers
        assert "lip_sync_qc_required" in blockers
    finally:
        cf.close()


def test_generated_motion_stays_blocked_after_generic_audit_and_human_approval(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id=asset["id"])

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert "motion_specific_qc_required" in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is False
        assert explanation["motionSpecificQcReceipt"] is None
        motion_finding = next(
            item
            for item in explanation["findings"]
            if item["code"] == "motion_specific_qc_required"
        )
        assert motion_finding["operatorAction"] == "run_motion_qc_analyzers"
    finally:
        cf.close()


def test_motion_qc_receipt_rejects_mismatched_media_subject(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "mismatch",
            _motion_qc_receipt("a" * 64, source_sha256=_asset_source_sha256(asset)),
        )

        with pytest.raises(ValueError, match="motion_specific_qc_subject_mismatch"):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        count = cf.conn.execute(
            "SELECT COUNT(*) FROM motion_qc_receipts WHERE rendered_asset_id = ?",
            (asset["id"],),
        ).fetchone()[0]
        assert count == 0
    finally:
        cf.close()


def test_motion_qc_receipt_rejects_self_asserted_legacy_v1(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "legacy-self-asserted",
            {
                "policy": {
                    "id": "contentforge.motion_specific_qc",
                    "version": "1.0.0",
                },
                "subjectSha256": asset["content_hash"],
                "verdict": "pass",
                "passed": True,
                "evidenceOnly": True,
                "modelCalls": 0,
                "providerCalls": 0,
                "requirements": {
                    name: True
                    for name in ("motion", "temporal", "freeze", "anatomy", "identity")
                },
                "evidenceSources": {},
                "reasons": [],
            },
        )
        with pytest.raises(ValueError, match="motion_specific_qc_contract_invalid"):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM motion_qc_receipts WHERE rendered_asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_motion_qc_receipt_rejects_tampered_producer_attestation(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt = _motion_qc_receipt(
            asset["content_hash"], source_sha256=_asset_source_sha256(asset)
        )
        receipt["producerAttestation"]["signature"] = "0" * 64
        receipt_path = _write_motion_qc_receipt(
            tmp_path, "tampered-attestation", receipt
        )
        with pytest.raises(ValueError, match="motion_specific_qc_attestation_invalid"):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )
    finally:
        cf.close()


def test_motion_qc_receipt_rejects_current_analyzer_implementation_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "implementation-drift",
            _motion_qc_receipt(
                asset["content_hash"], source_sha256=_asset_source_sha256(asset)
            ),
        )
        original_sha256_file = motion_qc_module._sha256_file

        def drifted_sha256_file(path: Path) -> tuple[str, int]:
            digest, size = original_sha256_file(path)
            if path.name == "trusted-media-analysis.js":
                return "d" * 64, size
            return digest, size

        monkeypatch.setattr(motion_qc_module, "_sha256_file", drifted_sha256_file)
        with pytest.raises(
            ValueError, match="motion_specific_qc_registry_implementation_drift"
        ):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM motion_qc_receipts WHERE rendered_asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_embedded_audio_motion_requires_audio_alignment_in_receipt(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path, audio_mode="generated")
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "missing-audio-alignment",
            _motion_qc_receipt(
                asset["content_hash"], source_sha256=_asset_source_sha256(asset)
            ),
        )

        with pytest.raises(
            ValueError,
            match="motion_specific_qc_requirement_missing:audioAlignment",
        ):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])
        assert "audio_video_alignment_qc_required" in explanation["failureReasons"]
    finally:
        cf.close()


def test_longcat_motion_requires_lip_sync_in_receipt(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            model_id="local_longcat_avatar15_q4_mlx",
            audio_mode="source",
        )
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "missing-lip-sync",
            _motion_qc_receipt(
                asset["content_hash"],
                source_sha256=_asset_source_sha256(asset),
                audio_alignment=True,
            ),
        )

        with pytest.raises(
            ValueError,
            match="motion_specific_qc_requirement_missing:lipSync",
        ):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])
        assert "lip_sync_qc_required" in explanation["failureReasons"]
    finally:
        cf.close()


def test_exact_longcat_motion_qc_receipt_clears_only_bound_motion_gates(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            model_id="local_longcat_avatar15_q4_mlx",
            audio_mode="source",
        )
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-longcat",
            _motion_qc_receipt(
                asset["content_hash"],
                source_sha256=_asset_source_sha256(asset),
                audio_alignment=True,
                lip_sync=True,
            ),
        )

        registered = cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path, created_by="test"
        )
        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert registered["subjectSha256"] == asset["content_hash"]
        assert registered["policy"] == {
            "id": "contentforge.motion_specific_qc",
            "version": "2.0.0",
        }
        assert "motion_specific_qc_required" not in explanation["failureReasons"]
        assert "audio_video_alignment_qc_required" not in explanation["failureReasons"]
        assert "lip_sync_qc_required" not in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is True
        assert explanation["checks"]["audio_video_alignment_qc_passed"] is True
        assert explanation["checks"]["lip_sync_qc_passed"] is True
        assert explanation["motionSpecificQcReceipt"]["id"] == registered["id"]
        with pytest.raises(
            sqlite3.IntegrityError, match="motion QC receipts are immutable"
        ):
            cf.conn.execute(
                "UPDATE motion_qc_receipts SET created_by = 'tampered' WHERE id = ?",
                (registered["id"],),
            )
    finally:
        cf.close()


def test_registered_motion_qc_receipt_fails_closed_after_media_substitution(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-before-substitution",
            _motion_qc_receipt(
                asset["content_hash"], source_sha256=_asset_source_sha256(asset)
            ),
        )
        cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path
        )
        Path(asset["campaign_path"]).write_bytes(b"substituted-video")

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert "motion_specific_qc_media_hash_mismatch" in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is False
    finally:
        cf.close()


def test_text_to_video_broll_cannot_be_creator_assigned_by_audit_approval_or_qc(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            motion_task="text_to_video",
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id=asset["id"])
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-text-to-video-broll",
            _motion_qc_receipt(
                asset["content_hash"], source_sha256=_asset_source_sha256(asset)
            ),
        )
        cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path
        )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert (
            "text_to_video_identity_assignment_forbidden"
            in explanation["failureReasons"]
        )
        assert explanation["checks"]["motion_specific_qc_passed"] is True
        assert explanation["checks"]["creator_identity_assignment_allowed"] is False
        assert explanation["publishableCandidate"] is False
        identity_finding = next(
            item
            for item in explanation["findings"]
            if item["code"] == "text_to_video_identity_assignment_forbidden"
        )
        assert identity_finding["retryable"] is False
    finally:
        cf.close()


def test_campaign_cli_registers_exact_motion_qc_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "campaign-cli-passing",
            _motion_qc_receipt(
                asset["content_hash"], source_sha256=_asset_source_sha256(asset)
            ),
        )
        args = build_cli_parser().parse_args(
            [
                "register-motion-qc-receipt",
                "--rendered-asset-id",
                asset["id"],
                "--receipt",
                str(receipt_path),
                "--operator",
                "operator_1",
            ]
        )

        result = dispatch_operations_commands(args, cf, cf.settings)
        payload = json.loads(capsys.readouterr().out)

        assert result == 0
        assert payload["renderedAssetId"] == asset["id"]
        assert payload["subjectSha256"] == asset["content_hash"]
        assert payload["createdBy"] == "operator_1"
    finally:
        cf.close()


def test_worker_streams_large_stderr_to_immutable_hashed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "do-not-persist-this-worker-secret"
    monkeypatch.setenv("WAVESPEED_API_KEY", secret)
    factory = SimpleNamespace(settings=SimpleNamespace(reel_factory_root=tmp_path))
    script = (
        "import json, os, sys; "
        "sys.stderr.write('x' * 2_000_000 + os.environ['WAVESPEED_API_KEY']); "
        "print(json.dumps({'schema': "
        "'reel_factory.motion_generation_result.v1', 'providerCalls': 0}))"
    )

    result = _invoke_worker(
        [sys.executable, "-c", script],
        factory=factory,
        log_dir=tmp_path / "logs",
        phase="preflight",
    )

    evidence = result.pop("_campaignExecutionLogEvidence")
    assert result["providerCalls"] == 0
    stderr = Path(evidence["stderr"]["path"])
    assert evidence["stderr"]["byteLength"] == 2_000_000 + len(secret)
    assert (
        evidence["stderr"]["sha256"] == hashlib.sha256(stderr.read_bytes()).hexdigest()
    )
    assert secret.encode() not in stderr.read_bytes()
    assert evidence["stderr"]["redactionCount"] == 1
    assert stderr.stat().st_mode & 0o222 == 0


def test_worker_rejects_oversized_stdout_after_streaming_complete_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "campaign_factory.motion_worker_process._WORKER_STDOUT_CAPTURE_BYTES", 128
    )
    factory = SimpleNamespace(settings=SimpleNamespace(reel_factory_root=tmp_path))
    script = "import sys; sys.stdout.write('x' * 4096)"

    with pytest.raises(MotionWorkerError, match="bounded capture limit") as raised:
        _invoke_worker(
            [sys.executable, "-c", script],
            factory=factory,
            log_dir=tmp_path / "oversized-stdout-logs",
            phase="preflight",
        )

    stdout_evidence = raised.value.log_evidence["stdout"]
    stdout = Path(stdout_evidence["path"])
    assert stdout_evidence["byteLength"] == 4096
    assert stdout_evidence["sha256"] == hashlib.sha256(stdout.read_bytes()).hexdigest()
    assert stdout.stat().st_mode & 0o222 == 0


def test_worker_timeout_stops_process_and_preserves_bounded_log_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "campaign_factory.motion_worker_process._WORKER_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr(
        "campaign_factory.motion_worker_process._WORKER_TERMINATE_GRACE_SECONDS",
        0.1,
    )
    factory = SimpleNamespace(settings=SimpleNamespace(reel_factory_root=tmp_path))
    script = (
        "import sys, time; "
        "sys.stderr.write('worker-started\\n'); sys.stderr.flush(); time.sleep(30)"
    )

    with pytest.raises(MotionWorkerError, match="motion worker timed out") as raised:
        _invoke_worker(
            [sys.executable, "-c", script],
            factory=factory,
            log_dir=tmp_path / "timeout-logs",
            phase="apply",
        )

    stderr_evidence = raised.value.log_evidence["stderr"]
    stderr = Path(stderr_evidence["path"])
    assert stderr.read_text(encoding="utf-8") == "worker-started\n"
    assert stderr_evidence["sha256"] == hashlib.sha256(stderr.read_bytes()).hexdigest()
    assert stderr.stat().st_mode & 0o222 == 0
