from __future__ import annotations

import json
from pathlib import Path

from ai_visual_qc import record_from_scores
from caption_bank import CaptionBankStore, caption_hash, empty_performance_payload
from higgsfield_cost_preflight import check_higgsfield_cost_preflight
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


def test_higgsfield_cost_preflight_blocks_missing_policy(monkeypatch) -> None:
    for key in (
        "HIGGSFIELD_DAILY_BUDGET_USD",
        "HIGGSFIELD_RUN_MAX_ASSETS",
        "HIGGSFIELD_MIN_BALANCE_USD",
    ):
        monkeypatch.delenv(key, raising=False)

    result = check_higgsfield_cost_preflight(
        asset_count=1, provider=FakeBalanceProvider(25.0)
    )

    assert result["allowed"] is False
    assert "budget_policy_missing" in result["blockingReasons"]
    assert result["balanceChecked"] is True


def test_higgsfield_cost_preflight_allows_with_policy(monkeypatch) -> None:
    monkeypatch.setenv("HIGGSFIELD_DAILY_BUDGET_USD", "100")
    monkeypatch.setenv("HIGGSFIELD_RUN_MAX_ASSETS", "3")
    monkeypatch.setenv("HIGGSFIELD_MIN_BALANCE_USD", "5")

    result = check_higgsfield_cost_preflight(
        asset_count=2, estimated_cost_usd=12, provider=FakeBalanceProvider(25.0)
    )

    assert result["allowed"] is True
    assert result["blockingReasons"] == []


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
