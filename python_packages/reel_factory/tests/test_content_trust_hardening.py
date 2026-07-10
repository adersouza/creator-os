from __future__ import annotations

import json
import sqlite3
from argparse import ArgumentTypeError
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from ai_visual_qc import record_from_scores
from asset_prompt_contract import AssetPromptSet
from caption_bank import CaptionBankStore, caption_hash, empty_performance_payload
from generate_assets import (
    AssetGenerationPlan,
    _record_cost_preflight_block,
    _record_generation_costs,
    create_image_asset,
    download_result,
    generated_image_qc,
    generated_image_qc_failure_reason,
    generated_video_qc,
    generated_video_qc_failure_reason,
    list_failed_generations,
)
from higgsfield_cost_preflight import (
    _parse_balance,
    cancel_higgsfield_spend_reservation,
    check_higgsfield_cost_preflight,
    consume_higgsfield_spend_reservation,
    nonnegative_float_arg,
    positive_int_arg,
    reserve_higgsfield_credits,
    reserve_higgsfield_spend,
)
from hook_ai import hook_similarity_mode
from identity_verification import (
    build_reference_set,
    delete_reference_set,
    identity_health,
    verify_identity,
)
from media_metadata import normalize_media_metadata
from PIL import Image


@pytest.fixture(autouse=True)
def _isolate_campaign_cost_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(tmp_path / "campaign_factory.sqlite"))


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


class FakeDownloadResponse:
    def __init__(self, chunks: list[bytes], content_type: str = "image/png"):
        self._chunks = list(chunks)
        self.headers = self
        self._content_type = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_content_type(self) -> str:
        return self._content_type

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


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


def test_download_result_rejects_truncated_response_without_partial_file(
    tmp_path: Path, monkeypatch
) -> None:
    import generate_assets

    monkeypatch.setattr(
        generate_assets.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeDownloadResponse([b"tiny"], "image/png"),
    )

    out = tmp_path / "asset.png"
    try:
        download_result("https://example.test/asset.png", out)
    except RuntimeError as exc:
        assert "downloaded result too small" in str(exc)
    else:
        raise AssertionError("truncated download was accepted")

    assert not out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_download_result_timeout_leaves_no_asset_file(
    tmp_path: Path, monkeypatch
) -> None:
    import generate_assets

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(generate_assets.urllib.request, "urlopen", timeout)

    out = tmp_path / "asset.mp4"
    try:
        download_result("https://example.test/asset.mp4", out)
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout was accepted")

    assert not out.exists()


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


def test_identity_reference_build_rejects_output_outside_reference_root(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        output=tmp_path / "tracked.json",
        provider=FakeIdentityProvider(),
    )

    assert result["status"] == "failed"
    assert result["failureReason"] == "output_must_be_under_identity_references"
    assert not (tmp_path / "tracked.json").exists()


def test_identity_reference_build_writes_private_file_and_delete_removes_it(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")

    result = build_reference_set(
        creator="Stacey",
        input_dir=input_dir,
        root=tmp_path,
        provider=FakeIdentityProvider(),
    )
    target = Path(result["outputPath"])

    assert result["status"] == "ready"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    deleted = delete_reference_set(creator="Stacey", root=tmp_path)
    assert deleted["deleted"] is True
    assert not target.exists()


def test_identity_reference_cli_redacts_embeddings_by_default(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    import identity_verification

    input_dir = tmp_path / "approved_refs"
    input_dir.mkdir()
    _write_image(input_dir / "ref_a.png")
    monkeypatch.setattr(
        identity_verification,
        "get_identity_provider",
        lambda: FakeIdentityProvider(),
    )

    exit_code = identity_verification.main(
        [
            "identity-reference-build",
            "--creator",
            "Stacey",
            "--input-dir",
            str(input_dir),
            "--root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"referenceSetId"' in output
    assert '"embeddings"' not in output


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


def test_higgsfield_cost_preflight_blocks_missing_estimate_even_under_budget(
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
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "cost_estimate_missing" in result["blockingReasons"]

    override = check_higgsfield_cost_preflight(
        asset_count=1,
        provider=FakeBalanceProvider(25.0),
        allow_unbudgeted_local_test=True,
        root=tmp_path,
    )

    assert override["allowed"] is True


def test_higgsfield_balance_parser_accepts_account_status_credits() -> None:
    assert _parse_balance({"email": "hidden@example.test", "credits": 506.53}) == 506.53


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_higgsfield_cost_preflight_rejects_invalid_cost_estimates(
    tmp_path: Path, value: float
) -> None:
    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=value,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "invalid_cost_estimate" in result["blockingReasons"]
    assert result["budgetPolicy"]["estimatedCostUsd"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_higgsfield_cost_preflight_rejects_invalid_balances(
    tmp_path: Path, value: float
) -> None:
    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(value),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "balance_invalid" in result["blockingReasons"]
    assert result["balanceUsd"] is None


@pytest.mark.parametrize("asset_count", [0, -1, 1.5, float("nan"), True])
def test_higgsfield_cost_preflight_requires_positive_integer_asset_count(
    tmp_path: Path, asset_count
) -> None:
    result = check_higgsfield_cost_preflight(
        asset_count=asset_count,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "invalid_asset_count" in result["blockingReasons"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HIGGSFIELD_DAILY_BUDGET_USD", "nan"),
        ("HIGGSFIELD_DAILY_BUDGET_USD", "-1"),
        ("HIGGSFIELD_MIN_BALANCE_USD", "inf"),
        ("HIGGSFIELD_MIN_BALANCE_USD", "-1"),
        ("HIGGSFIELD_RUN_MAX_ASSETS", "0"),
        ("HIGGSFIELD_RUN_MAX_ASSETS", "1.5"),
    ],
)
def test_higgsfield_cost_preflight_rejects_invalid_env_policy_without_fallback(
    tmp_path: Path, monkeypatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert result["blockingReason"] == "budget_policy_invalid"
    assert name in result["budgetPolicy"]["invalidPolicyFields"]


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_higgsfield_cli_money_parser_rejects_nonfinite_or_negative(value: str) -> None:
    with pytest.raises(ArgumentTypeError, match="finite, non-negative"):
        nonnegative_float_arg(value)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nan"])
def test_higgsfield_cli_asset_parser_rejects_non_positive_integer(value: str) -> None:
    with pytest.raises(ArgumentTypeError, match="positive integer"):
        positive_int_arg(value)


def test_higgsfield_cost_preflight_env_policy_overrides_config(monkeypatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_USD", "100")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "3")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_USD", "5")

    result = check_higgsfield_cost_preflight(
        asset_count=2, estimated_cost_usd=12, provider=FakeBalanceProvider(25.0)
    )

    assert result["allowed"] is True
    assert result["blockingReasons"] == []


def test_documented_env_names_match_active_code() -> None:
    root = Path(__file__).resolve().parents[3]
    env_template = (root / ".env.example").read_text(encoding="utf-8")
    sscd_code = (root / "python_packages/reel_factory/sscd_video.py").read_text(
        encoding="utf-8"
    )
    smoke_script = (root / "apps/contentforge/scripts/e2e-smoke.mjs").read_text(
        encoding="utf-8"
    )

    for name in (
        "CONTENTFORGE_BASE_URL",
        "CONTENTFORGE_REAL_SAMPLE_MANIFEST",
        "CONTENTFORGE_SSCD_MODEL_PATH",
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
        "CREATOR_OS_PROACTIVE_CYCLE_DISABLED",
        "REEL_GUI_URL",
        "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS",
        "REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS",
        "REEL_FACTORY_ENV",
        "APP_ENV",
        "ENV",
        "NODE_ENV",
        "VERCEL_ENV",
    ):
        assert name in env_template
    assert "CONTENTFORGE_URL=" not in env_template
    assert "CONTENTFORGE_SSCD_MODEL_PATH" in sscd_code
    assert "CONTENTFORGE_BASE_URL" in smoke_script
    assert "CONTENTFORGE_URL" not in smoke_script


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


def _set_higgsfield_guardrail_env(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "2")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_USD", "5")


def _set_higgsfield_credit_guardrail_env(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_CREDITS", "8")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "2")
    monkeypatch.setenv("HIGGSFIELD_COHORT_MAX_CREDITS", "150")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_CREDITS", "25")


def test_higgsfield_native_credit_reservation_tracks_cohort_and_quote(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_credit_guardrail_env(monkeypatch, db_path)
    quote = {
        "schema": "reel_factory.higgsfield_provider_quote.v1",
        "amount": 1.5,
        "unit": "higgsfield_credits",
        "model": "soul_2",
    }

    result = reserve_higgsfield_credits(
        provider_quote=quote,
        asset_count=1,
        cohort_id="stacey_learning_cohort_v1",
        provider=FakeBalanceProvider(50),
        root=tmp_path,
    )

    assert result["allowed"] is True
    assert result["budgetPolicy"]["projectedBalanceCredits"] == 48.5
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """SELECT amount, unit, cohort_id, estimated_cost_usd
            FROM higgsfield_spend_reservations"""
        ).fetchone()
    assert row == (1.5, "higgsfield_credits", "stacey_learning_cohort_v1", 0.0)


def test_higgsfield_native_credit_reservation_fails_closed_on_caps(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_credit_guardrail_env(monkeypatch, db_path)
    quote = {"amount": 7.0, "unit": "higgsfield_credits"}
    first = reserve_higgsfield_credits(
        provider_quote=quote,
        asset_count=2,
        cohort_id="stacey_learning_cohort_v1",
        provider=FakeBalanceProvider(50),
        root=tmp_path,
    )
    assert first["allowed"] is True

    retry = reserve_higgsfield_credits(
        provider_quote={"amount": 2.0, "unit": "higgsfield_credits"},
        asset_count=1,
        cohort_id="stacey_learning_cohort_v1",
        provider=FakeBalanceProvider(50),
        root=tmp_path,
    )
    assert retry["allowed"] is False
    assert "projected_daily_credits_exceeded" in retry["blockingReasons"]

    low_balance = reserve_higgsfield_credits(
        provider_quote={"amount": 1.0, "unit": "higgsfield_credits"},
        asset_count=1,
        cohort_id="other_cohort",
        provider=FakeBalanceProvider(25.5),
        root=tmp_path,
    )
    assert low_balance["allowed"] is False
    assert "projected_balance_below_minimum" in low_balance["blockingReasons"]


def test_higgsfield_atomic_reservation_prevents_concurrent_overspend(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, db_path)
    barrier = Barrier(2)

    class BarrierBalanceProvider(FakeBalanceProvider):
        def balance(self) -> tuple[float | None, str | None]:
            barrier.wait(timeout=5)
            return super().balance()

    provider = BarrierBalanceProvider(25.0)

    def reserve(index: int) -> dict:
        return reserve_higgsfield_spend(
            asset_count=1,
            estimated_cost_usd=6.0,
            provider=provider,
            source=f"concurrent_{index}",
            root=tmp_path,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))

    allowed = [result for result in results if result["allowed"]]
    blocked = [result for result in results if not result["allowed"]]
    assert len(allowed) == 1
    assert len(blocked) == 1
    assert blocked[0]["blockingReasons"] == ["estimated_cost_exceeds_daily_budget"]
    assert blocked[0]["budgetPolicy"]["spentTodayUsd"] == 6.0
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, estimated_cost_usd FROM higgsfield_spend_reservations"
        ).fetchall()
    assert rows == [("reserved", 6.0)]


def test_higgsfield_consumed_reservation_blocks_retry_overspend(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, db_path)
    provider = FakeBalanceProvider(25.0)
    first = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=6.0,
        provider=provider,
        source="first_attempt",
        root=tmp_path,
    )
    reservation_id = first["reservation"]["id"]

    assert first["allowed"] is True
    assert reservation_id
    assert consume_higgsfield_spend_reservation(reservation_id, root=tmp_path)

    retry = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=6.0,
        provider=provider,
        source="retry_attempt",
        root=tmp_path,
    )

    assert retry["allowed"] is False
    assert retry["blockingReasons"] == ["estimated_cost_exceeds_daily_budget"]
    assert retry["budgetPolicy"]["reservedOrConsumedTodayUsd"] == 6.0


def test_higgsfield_reservation_uses_explicit_shared_cost_database(
    tmp_path: Path, monkeypatch
) -> None:
    shared_db = tmp_path / "shared" / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, tmp_path / "wrong.sqlite")
    first = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=6.0,
        provider=FakeBalanceProvider(25.0),
        source="reference_factory",
        root=tmp_path / "reference_factory",
        cost_db_path=shared_db,
    )
    reservation_id = first["reservation"]["id"]

    assert reservation_id
    assert consume_higgsfield_spend_reservation(
        reservation_id,
        root=tmp_path / "reel_factory",
        cost_db_path=shared_db,
    )
    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=5.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path / "different_root",
        cost_db_path=shared_db,
    )

    assert result["allowed"] is False
    assert result["budgetPolicy"]["spentTodayUsd"] == 6.0
    assert result["blockingReasons"] == ["estimated_cost_exceeds_daily_budget"]
    assert not (tmp_path / "wrong.sqlite").exists()


def test_higgsfield_unconsumed_reservation_can_be_cancelled(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, db_path)
    provider = FakeBalanceProvider(25.0)
    first = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=6.0,
        provider=provider,
        source="setup_only",
        root=tmp_path,
    )
    reservation_id = first["reservation"]["id"]

    assert reservation_id
    assert cancel_higgsfield_spend_reservation(reservation_id, root=tmp_path)
    second = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=6.0,
        provider=provider,
        source="after_cancel",
        root=tmp_path,
    )
    assert second["allowed"] is True


def test_higgsfield_fabricated_reservation_id_cannot_hide_ledger_spend(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, db_path)
    setup = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(25.0),
        source="setup_schema",
        root=tmp_path,
    )
    assert cancel_higgsfield_spend_reservation(
        setup["reservation"]["id"], root=tmp_path
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE ai_cost_events (
                estimated_cost_usd REAL NOT NULL,
                reservation_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO ai_cost_events VALUES (?, ?, ?)",
            (
                9.0,
                "hfr_not_a_real_reservation",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ),
        )

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=2.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert result["budgetPolicy"]["spentTodayUsd"] == 9.0
    assert result["budgetPolicy"]["legacyEventSpendTodayUsd"] == 9.0
    assert result["blockingReasons"] == ["estimated_cost_exceeds_daily_budget"]


@pytest.mark.parametrize(
    "override_kwargs",
    [
        {"allow_unbudgeted_local_test": True},
        {"budget_override_ledger_error": True},
    ],
)
def test_higgsfield_paid_reservation_rejects_unsafe_overrides(
    tmp_path: Path, monkeypatch, override_kwargs: dict
) -> None:
    _set_higgsfield_guardrail_env(monkeypatch, tmp_path / "campaign_factory.sqlite")

    result = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
        **override_kwargs,
    )

    assert result["allowed"] is False
    assert (
        "unsafe_cost_override_not_allowed_for_paid_generation"
        in result["blockingReasons"]
    )
    assert result["reservation"]["id"] is None


def test_higgsfield_paid_reservation_rejects_zero_cost_estimate(
    tmp_path: Path, monkeypatch
) -> None:
    _set_higgsfield_guardrail_env(monkeypatch, tmp_path / "campaign_factory.sqlite")

    result = reserve_higgsfield_spend(
        asset_count=1,
        estimated_cost_usd=0.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert result["blockingReasons"] == [
        "cost_estimate_must_be_positive_for_paid_generation"
    ]


def test_reel_paid_generation_consumes_reservation_before_provider_call(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "campaign_factory.sqlite"
    _set_higgsfield_guardrail_env(monkeypatch, db_path)
    monkeypatch.setattr(
        "higgsfield_cost_preflight.CliBalanceProvider.balance",
        lambda _self: (25.0, None),
    )
    prompt = tmp_path / "prompt.json"
    prompt.write_text(
        json.dumps(
            {
                "higgsfieldGridPrompt": "reference image still",
                "klingMotionPrompt": "motion",
            }
        ),
        encoding="utf-8",
    )
    capabilities = {
        "schema": "cap",
        "createdAt": 1,
        "imageModels": [
            {"job_set_type": "soul_2", "parameters": [{"name": "soul_id"}]}
        ],
        "videoModels": [{"job_set_type": "kling3_0"}],
    }
    monkeypatch.setattr(
        "generate_assets.ensure_required_capabilities", lambda *_args: capabilities
    )
    monkeypatch.setattr(
        "generate_assets.validate_generation_soul", lambda *_args: {"status": "valid"}
    )
    calls: list[list[str]] = []

    def fake_provider_call(cmd):
        calls.append(cmd)
        return {"id": f"img_{len(calls)}", "status": "completed"}

    monkeypatch.setattr("generate_assets._run_json", fake_provider_call)

    def plan(stem: str) -> AssetGenerationPlan:
        return AssetGenerationPlan(
            prompt_json=prompt,
            stem=stem,
            reference=None,
            soul_id="soul_1",
            soul_name="Stacey",
            start_image=None,
            out_dir=tmp_path / "out",
            source_dir=tmp_path / "sources",
            estimated_cost_usd=6.0,
        )

    first = create_image_asset(plan("first"), download=False)
    second = create_image_asset(plan("second"), download=False)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["lineage"]["generation"]["status"] == "cost_preflight_blocked"
    assert second["lineage"]["generation"]["costPreflight"]["blockingReasons"] == [
        "estimated_cost_exceeds_daily_budget"
    ]
    assert len(calls) == 1
    with sqlite3.connect(db_path) as conn:
        reservation = conn.execute(
            "SELECT id, status, estimated_cost_usd FROM higgsfield_spend_reservations"
        ).fetchone()
        cost_event_reservation = conn.execute(
            "SELECT reservation_id FROM ai_cost_events"
        ).fetchone()[0]
    assert reservation[1:] == ("consumed", 6.0)
    assert cost_event_reservation == reservation[0]

    after = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=1.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )
    assert after["budgetPolicy"]["spentTodayUsd"] == 6.0
    assert after["budgetPolicy"]["legacyEventSpendTodayUsd"] == 0.0


def test_higgsfield_cost_preflight_blocks_over_budget_without_estimate(
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
            (10.25, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
        )

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "estimated_cost_exceeds_daily_budget" in result["blockingReasons"]
    assert result["budgetPolicy"]["estimatedCostUsd"] is None


def test_higgsfield_cost_preflight_blocks_when_cost_ledger_unreadable(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)
    db_path = tmp_path / "campaign_factory.sqlite"
    db_path.write_text("not a sqlite database", encoding="utf-8")
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=2.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
    )

    assert result["allowed"] is False
    assert "cost_ledger_unreadable" in result["blockingReasons"]
    assert result["budgetPolicy"]["costLedgerReadable"] is False


def test_higgsfield_cost_preflight_ledger_override_alone_cannot_bypass_error(
    tmp_path: Path, monkeypatch
) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)
    db_path = tmp_path / "campaign_factory.sqlite"
    db_path.write_text("not a sqlite database", encoding="utf-8")
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(db_path))

    result = check_higgsfield_cost_preflight(
        asset_count=1,
        estimated_cost_usd=2.0,
        provider=FakeBalanceProvider(25.0),
        root=tmp_path,
        budget_override_ledger_error=True,
    )

    assert result["allowed"] is False
    assert result["blockingReasons"] == ["cost_ledger_unreadable"]
    assert result["budgetPolicy"]["costLedgerReadable"] is False
    assert result["budgetOverrideLedgerError"] is True


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


def test_reel_generation_costs_ensure_cost_schema_once_per_connection(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeCostTracker:
        def __init__(self) -> None:
            self.ensure_calls = 0
            self.record_schema_flags: list[bool] = []

        def ensure_cost_table(self, conn) -> None:
            self.ensure_calls += 1
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_cost_events (
                    id TEXT PRIMARY KEY,
                    source_event_key TEXT UNIQUE
                )
                """
            )

        def record_ai_cost(
            self, conn, *, source_event_key: str, ensure_schema: bool, **_kwargs
        ):
            self.record_schema_flags.append(ensure_schema)
            event_id = f"cost_{len(self.record_schema_flags)}"
            conn.execute(
                "INSERT OR IGNORE INTO ai_cost_events VALUES (?, ?)",
                (event_id, source_event_key),
            )
            return event_id

    tracker = FakeCostTracker()
    monkeypatch.setattr("generate_assets._load_cost_tracker_module", lambda: tracker)
    monkeypatch.setenv("CAMPAIGN_FACTORY_DB", str(tmp_path / "campaign_factory.sqlite"))
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
            "raw": {"id": "img_1", "status": "completed"},
        },
        {
            "provider": "kling",
            "operation": "video_create",
            "model": "kling3_0",
            "raw": {"id": "vid_1", "status": "completed"},
        },
    ]

    result = _record_generation_costs(
        plan, lineage_path_text=str(tmp_path / "lineage.json"), records=records
    )

    assert len(result["events"]) == 2
    assert tracker.ensure_calls == 1
    assert tracker.record_schema_flags == [False, False]


def test_cost_preflight_block_appends_failed_generation_dead_letter(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "00_source_videos"
    plan = AssetGenerationPlan(
        prompt_json=tmp_path / "prompt.json",
        stem="blocked_clip",
        reference=None,
        soul_id="soul_1",
        soul_name="Stacey",
        start_image=None,
        out_dir=tmp_path / "out",
        source_dir=source_dir,
        campaign="daily",
        creator="Stacey",
    )
    prompt = AssetPromptSet(
        higgsfieldGridPrompt="grid",
        klingMotionPrompt="motion",
        notes="test",
    )

    result = _record_cost_preflight_block(
        plan,
        prompt=prompt,
        cost_preflight={"blockingReason": "estimated_cost_exceeds_daily_budget"},
    )
    failures = list_failed_generations(tmp_path)

    assert result["ok"] is False
    assert failures["count"] == 1
    assert failures["items"][0]["stem"] == "blocked_clip"
    assert (
        failures["items"][0]["failure"]["reason"]
        == "estimated_cost_exceeds_daily_budget"
    )


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
