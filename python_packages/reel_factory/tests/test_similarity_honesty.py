from __future__ import annotations

from sscd_check import detector_status


def test_reel_factory_similarity_report_does_not_claim_sscd_validation() -> None:
    status = detector_status()

    assert status["sscdAvailable"] is False
    assert status["detectorValidation"] == "not_validated_against_sscd"
    assert status["freshnessSignal"] == "phash_dhash_whash_consensus"
