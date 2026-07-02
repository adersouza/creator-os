from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ai_visual_qc import record_from_scores
from caption_bank import CaptionBankStore, caption_hash, empty_performance_payload
from generate_assets import (
    AssetGenerationPlan,
    _record_generation_costs,
    generated_image_qc,
    generated_image_qc_failure_reason,
    generated_video_qc,
    generated_video_qc_failure_reason,
)
from higgsfield_cost_preflight import _parse_balance, check_higgsfield_cost_preflight
from hook_ai import hook_similarity_mode
from identity_verification import build_reference_set, identity_health, verify_identity
from media_metadata import normalize_media_metadata
from PIL import Image


class FakeIdentityProvider:
    name = "fake_identity"

    def __init__(self, embedding: list[float] | None = None, available: bool = True):
        self._embedding = embedding or [1.0, 0.0]
        self._available = available

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self._available else (False, "fake_unavailable")

    def embedding(self, image_path: Path) -> list[float] | None:
        return self._embedding


class PathIdentityProvider(FakeIdentityProvider):
    def __init__(self, embeddings_by_name: dict[str, list[float]]):
        super().__init__([1.0, 0.0])
        self._embeddings_by_name = embeddings_by_name

    def embedding(self, image_path: Path) -> list[float] | None:
        return self._embeddings_by_name.get(image_path.name, [1.0, 0.0])


def _write_reference_set(
    root: Path, creator: str, embeddings: list[list[float]]
) -> None:
    target = root / "identity_references" / f"{creator.lower()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"referenceSetId": f"{creator.lower()}_refs", "embeddings": embeddings}
        ),
        encoding="utf-8",
    )


def _write_image(path: Path) -> None:
    Image.new("RGB", (24, 24), (120, 90, 80)).save(path)


def test_identity_verification_pass_fail_and_unavailable(tmp_path: Path) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    passed = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider([1.0, 0.0]),
    )
    failed = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider([0.0, 1.0]),
    )
    unavailable = verify_identity(
        image,
        creator="Stacey",
        root=tmp_path,
        provider=FakeIdentityProvider(available=False),
    )

    assert passed["status"] == "passed"
    assert failed["status"] == "failed"
    assert failed["failureReason"] == "identity_similarity_below_threshold"
    assert unavailable["status"] == "unavailable"
    assert unavailable["failureReason"] == "fake_unavailable"
    assert passed["frameCount"] == 1


def test_video_identity_uses_worst_sampled_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    early = tmp_path / "early.png"
    late = tmp_path / "late.png"
    _write_image(early)
    _write_image(late)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=PathIdentityProvider(
            {"early.png": [1.0, 0.0], "late.png": [0.0, 1.0]}
        ),
        frame_extractor=lambda _path: [early, late],
    )

    assert result["status"] == "failed"
    assert result["score"] == 0.0
    assert result["frameScores"] == [1.0, 0.0]


def test_video_identity_passes_when_all_sampled_frames_match(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    early = tmp_path / "early.png"
    late = tmp_path / "late.png"
    _write_image(early)
    _write_image(late)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    result = verify_identity(
        video,
        creator="Stacey",
        root=tmp_path,
        provider=PathIdentityProvider(
            {"early.png": [1.0, 0.0], "late.png": [0.9, 0.1]}
        ),
        frame_extractor=lambda _path: [early, late],
    )

    assert result["status"] == "passed"
    assert result["score"] == 0.9
    assert result["frameCount"] == 2


def test_identity_reference_build_and_health_use_provider_seam(tmp_path: Path) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")
    _write_image(input_dir / "ref_b.png")

    built = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider([1.0, 0.0]),
    )
    health = identity_health(
        creator="Stacey", root=tmp_path, provider=FakeIdentityProvider([1.0, 0.0])
    )

    assert built["schema"] == "reel_factory.identity_reference_set.v1"
    assert built["status"] == "ready"
    assert len(built["embeddings"]) == 2
    assert all(item["status"] == "embedded" for item in built["sourceImages"])
    assert health["status"] == "ready"
    assert health["referenceEmbeddings"] == 2


def test_identity_reference_build_fails_closed_when_provider_missing(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider(available=False),
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "fake_unavailable"
    assert not (tmp_path / "identity_references" / "stacey.json").exists()


def test_generated_image_qc_gates_identity_with_injected_provider(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])
    monkeypatch.setattr(
        "generate_assets.assess_image_qc",
        lambda *args, **kwargs: {
            "available": True,
            "anatomy": {"plausible": True, "severity": "none", "defects": []},
            "exposure": {"safe": True, "severity": "none", "issues": []},
        },
    )

    passed = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([1.0, 0.0]),
    )
    failed = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([0.0, 1.0]),
    )

    assert passed["status"] == "passed"
    assert passed["results"][0]["identityVerification"]["status"] == "passed"
    assert failed["status"] == "failed"
    assert failed["results"][0]["postable"] is False
    assert (
        failed["results"][0]["identityVerification"]["failureReason"]
        == "identity_similarity_below_threshold"
    )


def test_generated_image_qc_names_identity_reference_seeding_remedy(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    monkeypatch.setattr(
        "generate_assets.assess_image_qc",
        lambda *args, **kwargs: {
            "available": True,
            "anatomy": {"plausible": True, "severity": "none", "defects": []},
            "exposure": {"safe": True, "severity": "none", "issues": []},
        },
    )

    result = generated_image_qc(
        {"image": str(image)},
        root=tmp_path,
        required=True,
        creator="Stacey",
        identity_provider=FakeIdentityProvider([1.0, 0.0]),
    )

    failure = result["results"][0]["identityVerification"]["failureReason"]
    assert result["status"] == "failed"
    assert (
        failure == "no identity reference set for Stacey - run identity-reference-build"
    )
    assert generated_image_qc_failure_reason(result) == (
        "generated image failed identity QC: "
        "no identity reference set for Stacey - run identity-reference-build"
    )


def test_generated_video_qc_passes_clean_sampled_frames(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_ok.png"
    _write_image(frame)

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=lambda _frames, _prompt: json.dumps(
            {
                "anatomy": {"plausible": True, "severity": "none", "defects": []},
                "exposure": {"safe": True, "severity": "none", "issues": []},
            }
        ),
    )

    assert result["status"] == "passed"
    assert result["results"][0]["frames"][0]["postable"] is True


def test_generated_video_qc_rejects_bad_sampled_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_bad.png"
    _write_image(frame)

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=lambda _frames, _prompt: json.dumps(
            {
                "anatomy": {
                    "plausible": False,
                    "severity": "severe",
                    "defects": ["warped hand"],
                },
                "exposure": {"safe": True, "severity": "none", "issues": []},
            }
        ),
    )

    assert result["status"] == "failed"
    assert "warped hand" in generated_video_qc_failure_reason(result)


def test_generated_video_qc_fails_closed_when_provider_unavailable(
    tmp_path: Path,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    frame = tmp_path / "frame_unknown.png"
    _write_image(frame)

    def unavailable(_frames, _prompt):
        raise RuntimeError("provider missing")

    result = generated_video_qc(
        {"video": str(video)},
        root=tmp_path,
        required=True,
        frame_sampler=lambda _path: [frame],
        vision_call=unavailable,
    )

    assert result["status"] == "failed"
    assert result["results"][0]["frames"][0]["available"] is False


def test_ai_visual_qc_status_marks_dependency_unavailable() -> None:
    record = record_from_scores("x.mp4", "/tmp/x.mp4", {"opencv_available": 0})

    assert record.visualQcStatus == "unavailable"
    assert record.visualQcDependencyStatus["opencv"] == "unavailable"
    assert "opencv_unavailable" in record.visualQcWarnings


def test_caption_bank_uses_approved_outcome_weights(tmp_path: Path) -> None:
    first = {
        "caption_hash": caption_hash("first"),
        "text": "first",
        "banks": ["shared_girl_next_door"],
        "source_type": "fixture",
        "source_file": "fixture",
    }
    second = {
        "caption_hash": caption_hash("second"),
        "text": "second",
        "banks": ["shared_girl_next_door"],
        "source_type": "fixture",
        "source_file": "fixture",
    }
    performance = empty_performance_payload()
    performance["approvedWeights"] = {"captionHashes": {second["caption_hash"]: 100.0}}
    store = CaptionBankStore(
        banks={"shared_girl_next_door": [first, second]},
        mixes={"Stacey": {"shared_girl_next_door": 1}},
        performance=performance,
        version="caption_banks_v1",
        source_hash="hash",
    )

    selected = store.resolve_mix("Stacey", limit=1, seed=1)[0]
    lineage = store.lineage_for(
        selected, selected_mix="Stacey", selected_banks=selected["selected_banks"]
    )

    assert selected["caption_hash"] == second["caption_hash"]
    assert lineage["weightSource"] == "approved_outcome_weights"
    assert lineage["outcomeWeight"] == 100.0


def test_hook_similarity_hash_mode_is_named_lexical_fallback() -> None:
    assert hook_similarity_mode("hash-v1") == "lexical_fallback_similarity"


class FakeBalanceProvider:
    name = "fake_balance"

    def __init__(self, balance: float | None, reason: str | None = None):
        self._balance = balance
        self._reason = reason

    def balance(self) -> tuple[float | None, str | None]:
        return self._balance, self._reason


def test_higgsfield_cost_preflight_allows_default_policy(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=8,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is True
    assert result["blockingReasons"] == []
    assert result["budgetPolicy"]["dailyBudgetUsd"] == 10.0
    assert result["budgetPolicy"]["perRunMaxAssets"] == 2
    assert result["budgetPolicy"]["minimumBalanceUsd"] == 5.0
    assert result["balanceChecked"] is True


def test_higgsfield_balance_parser_accepts_account_status_credits() -> None:
    assert _parse_balance({"email": "hidden@example.test", "credits": 506.53}) == 506.53


def test_higgsfield_cost_preflight_env_policy_overrides_config(monkeypatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_USD", "100")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "3")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_USD", "5")

    result = check_higgsfield_cost_preflight(
        asset_count=2, estimated_cost_usd=12, provider=FakeBalanceProvider(25.0)
    )

    assert result["allowed"] is True
    assert result["blockingReasons"] == []


def test_higgsfield_cost_preflight_blocks_over_default_budget(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=12,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "estimated_cost_exceeds_daily_budget" in result["blockingReasons"]


def test_higgsfield_cost_preflight_sums_existing_daily_spend(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)
    db_path = tmp_path / "campaign_factory.sqlite"
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE ai_cost_events (
                estimated_cost_usd REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO ai_cost_events VALUES (?, ?)",
            (7.25, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
        )

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=3.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "estimated_cost_exceeds_daily_budget" in result["blockingReasons"]
    assert result["budgetPolicy"]["spentTodayUsd"] == 7.25
    assert result["budgetPolicy"]["projectedDailySpendUsd"] == 10.25


def test_higgsfield_cost_preflight_blocks_over_asset_limit(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=3,
        estimated_cost_usd=8,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "run_asset_limit_exceeded" in result["blockingReasons"]


def test_higgsfield_cost_preflight_blocks_under_minimum_balance(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=2,
        provider=FakeBalanceProvider(4.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "minimum_balance_not_met" in result["blockingReasons"]


def test_higgsfield_cost_preflight_blocks_when_balance_unreadable(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=2,
        provider=FakeBalanceProvider(None, "higgsfield_balance_unavailable"),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert result["balanceChecked"] is False
    assert "higgsfield_balance_unavailable" in result["blockingReasons"]


def test_reel_generation_costs_record_completed_provider_events(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))
    plan = AssetGenerationPlan(
        prompt_json=tmp_path / "prompt.json",
        stem="clip_001",
        reference=None,
        soul_id="soul_1",
        soul_name="Stacey",
        start_image=None,
        out_dir=tmp_path / "out",
        source_dir=tmp_path / "sources",
        campaign="daily",
        creator="Stacey",
    )
    records = [
        {
            "provider": "higgsfield",
            "operation": "image_create",
            "model": "text2image_soul_v2",
            "raw": {"id": "img_1", "status": "completed", "credits": 0.12},
        },
        {
            "provider": "kling",
            "operation": "video_create",
            "model": "kling3_0",
            "raw": {"id": "vid_1", "status": "completed", "credits": 7.5},
        },
        {
            "provider": "kling",
            "operation": "video_create",
            "model": "kling3_0",
            "raw": {"id": "vid_failed", "status": "failed", "credits": 7.5},
        },
    ]

    first = _record_generation_costs(
        plan, lineage_path_text=str(tmp_path / "lineage.json"), records=records
    )
    second = _record_generation_costs(
        plan, lineage_path_text=str(tmp_path / "lineage.json"), records=records
    )

    assert [event["provider"] for event in first["events"]] == ["higgsfield", "kling"]
    assert second["events"][0]["eventId"] == first["events"][0]["eventId"]
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT provider, operation, campaign_id, metadata_json FROM ai_cost_events ORDER BY provider"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "higgsfield"
    assert rows[0][2] == "daily"
    assert json.loads(rows[0][3])["actualCredits"] == 0.12
    assert rows[1][0] == "kling"


def test_metadata_normalization_reports_missing_exiftool_without_spoofing(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake media")
    monkeypatch.setattr("media_metadata.shutil.which", lambda name: None)

    result = normalize_media_metadata(media, dry_run=False)

    assert result["metadataNormalized"] is False
    assert "exiftool_unavailable" in result["metadataWarnings"]
    assert result["spoofedDeviceMetadata"] is False
    assert result["spoofedPlatformMetadata"] is False


def test_metadata_normalization_strips_mp4_metadata_tags(
    tmp_path: Path, monkeypatch
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake media")
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Proc()

    monkeypatch.setattr("media_metadata.shutil.which", lambda name: "/usr/bin/exiftool")
    monkeypatch.setattr("media_metadata.subprocess.run", fake_run)

    result = normalize_media_metadata(media, dry_run=False)

    assert result["metadataNormalized"] is True
    assert calls
    assert "-all=" in calls[0]
    assert str(media.resolve()) == calls[0][-1]
