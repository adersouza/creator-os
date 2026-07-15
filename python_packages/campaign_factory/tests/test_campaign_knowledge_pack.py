from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_core import make_factory

from pipeline_contracts import load_example


def test_campaign_imports_versioned_pack_without_recalculating_status(tmp_path: Path):
    local_reference = tmp_path / "reference.mp4"
    local_reference.write_bytes(b"reference")
    pack = load_example("reference_factory_knowledge_pack")
    pack["goldReferences"][0]["localPath"] = str(local_reference)
    pack["patternCards"][0]["recommendationStatus"] = "advisory"
    pack["patternCards"][0]["measuredExampleCount"] = 1
    _seal_pack(pack)
    pack_path = tmp_path / "knowledge_pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")

    cf = make_factory(tmp_path)
    try:
        preview = cf.import_reference_bank(
            pack_path, dry_run=True, require_local_paths=True
        )
        assert preview["schema"] == "campaign_factory.knowledge_pack_import.v1"
        assert preview["knowledgePackId"] == pack["packId"]
        assert cf.reference_patterns()["patterns"] == []
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM reference_knowledge_packs"
            ).fetchone()[0]
            == 0
        )

        imported = cf.import_reference_bank(pack_path, require_local_paths=True)
        assert imported["patternsCreated"] == 1
        assert imported["knowledgePackSourceFingerprint"] == pack["sourceFingerprint"]
        pattern = cf.reference_patterns()["patterns"][0]
        assert pattern["knowledge"]["packId"] == pack["packId"]
        assert pattern["recommendationStatus"] == "advisory"
        assert pattern["measuredExampleCount"] == 1
        assert (
            pattern["knowledge"]["measuredOutcomeProvenance"]
            == pack["patternCards"][0]["measuredOutcomeProvenance"]
        )
        stored = cf.conn.execute(
            "SELECT * FROM reference_knowledge_packs WHERE id = ?", (pack["packId"],)
        ).fetchone()
        assert stored is not None
        assert (
            json.loads(stored["payload_json"])["sourceFingerprint"]
            == pack["sourceFingerprint"]
        )

        repeated = cf.import_reference_bank(pack_path)
        assert repeated["patternsUnchanged"] == 1
        assert repeated["patternsImported"] == 0
    finally:
        cf.close()


def test_campaign_rejects_tampered_knowledge_pack(tmp_path: Path):
    pack = load_example("reference_factory_knowledge_pack")
    _seal_pack(pack)
    pack["patternCards"][0]["recommendationStatus"] = "eligible"
    pack_path = tmp_path / "tampered.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="sourceFingerprint"):
            cf.import_reference_bank(pack_path, dry_run=True)
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("sample_size", "expected_status", "approval_required"),
    [(2, "advisory", True), (3, "eligible", False)],
)
def test_reference_pattern_recommendations_require_three_measured_examples(
    tmp_path: Path,
    sample_size: int,
    expected_status: str,
    approval_required: bool,
):
    cf = make_factory(tmp_path)
    try:
        selected = {"id": "refpat_1", "clusterKey": "mirror::question"}
        evidence = cf.services.recommendation_reference_pattern_evidence(
            [
                {
                    "patternId": "refpat_1",
                    "clusterKey": "mirror::question",
                    "sampleSize": sample_size,
                    "recommendationStatus": expected_status,
                }
            ],
            selected,
        )
        assert evidence["recommendationStatus"] == expected_status
        assert evidence["operatorApprovalRequired"] is approval_required
        assert evidence["minimumMeasuredExamples"] == 3
    finally:
        cf.close()


def _seal_pack(pack: dict[str, object]) -> None:
    core = {
        key: value
        for key, value in pack.items()
        if key not in {"schema", "packId", "sourceFingerprint", "generatedAt"}
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    pack["sourceFingerprint"] = fingerprint
    pack["packId"] = f"kp_{fingerprint[:16]}"
