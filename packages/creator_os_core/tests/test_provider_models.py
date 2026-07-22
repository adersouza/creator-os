from creator_os_core.provider_models import model_identifiers


def test_model_identifiers_accepts_current_higgsfield_job_type() -> None:
    assert model_identifiers({"job_type": "text2image_soul_v2"}) == {
        "text2image_soul_v2"
    }


def test_model_identifiers_preserves_legacy_and_generic_aliases() -> None:
    assert model_identifiers(
        {
            "job_type": " Kling3_0 ",
            "job_set_type": "KLING3_0_TURBO",
            "id": "provider-id",
            "model_id": "model-id",
        }
    ) == {"kling3_0", "kling3_0_turbo", "provider-id", "model-id"}


def test_model_identifiers_ignores_missing_or_non_string_values() -> None:
    assert not model_identifiers(
        {"job_type": None, "job_set_type": " ", "id": 123, "model_id": False}
    )
