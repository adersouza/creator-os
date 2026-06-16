from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from ai_visual_qc import record_from_scores
from caption_bank import CaptionBankStore, caption_hash, empty_performance_payload
from hook_ai import hook_similarity_mode
from identity_verification import verify_identity


class FakeIdentityProvider:
    name = "fake_identity"

    def __init__(self, embedding: list[float] | None = None, available: bool = True):
        self._embedding = embedding or [1.0, 0.0]
        self._available = available

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self._available else (False, "fake_unavailable")

    def embedding(self, image_path: Path) -> list[float] | None:
        return self._embedding


def _write_reference_set(root: Path, creator: str, embeddings: list[list[float]]) -> None:
    target = root / "identity_references" / f"{creator.lower()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"referenceSetId": f"{creator.lower()}_refs", "embeddings": embeddings}),
        encoding="utf-8",
    )


def _write_image(path: Path) -> None:
    Image.new("RGB", (24, 24), (120, 90, 80)).save(path)


def test_identity_verification_pass_fail_and_unavailable(tmp_path: Path) -> None:
    image = tmp_path / "still.png"
    _write_image(image)
    _write_reference_set(tmp_path, "Stacey", [[1.0, 0.0]])

    passed = verify_identity(image, creator="Stacey", root=tmp_path, provider=FakeIdentityProvider([1.0, 0.0]))
    failed = verify_identity(image, creator="Stacey", root=tmp_path, provider=FakeIdentityProvider([0.0, 1.0]))
    unavailable = verify_identity(image, creator="Stacey", root=tmp_path, provider=FakeIdentityProvider(available=False))

    assert passed["status"] == "passed"
    assert failed["status"] == "failed"
    assert failed["failureReason"] == "identity_similarity_below_threshold"
    assert unavailable["status"] == "unavailable"
    assert unavailable["failureReason"] == "fake_unavailable"


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
    lineage = store.lineage_for(selected, selected_mix="Stacey", selected_banks=selected["selected_banks"])

    assert selected["caption_hash"] == second["caption_hash"]
    assert lineage["weightSource"] == "approved_outcome_weights"
    assert lineage["outcomeWeight"] == 100.0


def test_hook_similarity_hash_mode_is_named_lexical_fallback() -> None:
    assert hook_similarity_mode("hash-v1") == "lexical_fallback_similarity"
