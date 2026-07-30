from __future__ import annotations

import pytest
from creator_os_core.configuration_registry import (
    CONFIG_REGISTRY,
    ConfigurationValidationError,
    configuration_manifest,
    redact_mapping,
    validate_operation_configuration,
)
from creator_os_core.runtime_guards import require_global_write_allowed


def test_registry_has_typed_safety_secret_rotation_and_change_metadata() -> None:
    required = {
        "CREATOR_OS_KILL_SWITCH",
        "CREATOR_OS_EVIDENCE_AUTH_SECRET",
        "CREATOR_OS_SPEND_AUTH_SECRET",
        "OPENAI_API_KEY",
        "CREATOR_OS_SOUL_ID_STACEY",
        "CREATOR_OS_STATE_ROOT",
        "CAMPAIGN_FACTORY_DB",
        "reel_factory.output_profile",
    }
    assert required <= CONFIG_REGISTRY.keys()
    for item in CONFIG_REGISTRY.values():
        assert item.owner
        assert item.purpose
        assert item.validation
        assert item.rotation
        assert item.redaction
        assert item.change_impact
    assert CONFIG_REGISTRY["OPENAI_API_KEY"].sensitive is True
    assert (
        CONFIG_REGISTRY["CREATOR_OS_KILL_SWITCH"].fail_behavior.value == "fail_closed"
    )


def test_scoped_validation_does_not_break_harmless_read_only_operations() -> None:
    receipt = validate_operation_configuration(
        "read_only",
        values={"ALLOW_INSECURE_LOCAL": "true"},
        environment="production",
    )
    assert receipt["eligible"] is True
    assert receipt["checked"] == []


def test_production_write_requires_explicit_inactive_kill_switch() -> None:
    with pytest.raises(
        ConfigurationValidationError,
        match="CREATOR_OS_KILL_SWITCH:missing_required",
    ):
        validate_operation_configuration(
            "state_change",
            values={},
            environment="production",
        )
    with pytest.raises(PermissionError, match="CREATOR_OS_KILL_SWITCH"):
        require_global_write_allowed(
            "paid generation",
            environ={"CREATOR_OS_ENVIRONMENT": "production"},
        )
    require_global_write_allowed(
        "paid generation",
        environ={
            "CREATOR_OS_ENVIRONMENT": "production",
            "CREATOR_OS_KILL_SWITCH": "false",
        },
    )


def test_paid_configuration_requires_only_the_selected_provider_scope() -> None:
    common = {
        "CREATOR_OS_ENVIRONMENT": "production",
        "CREATOR_OS_KILL_SWITCH": "0",
        "CREATOR_OS_SPEND_AUTH_SECRET": "s" * 32,
        "CREATOR_OS_PAID_DAILY_CAP_USD": "10",
        "CREATOR_OS_PAID_MONTHLY_CAP_USD": "100",
        "CREATOR_OS_CREATOR_DAILY_CAP_USD": "5",
        "CREATOR_OS_CAMPAIGN_DAILY_CAP_USD": "5",
        "CREATOR_OS_OPENAI_DAILY_CAP_USD": "10",
    }
    with pytest.raises(
        ConfigurationValidationError,
        match="OPENAI_API_KEY:missing_required",
    ):
        validate_operation_configuration("paid_openai", values=common)
    receipt = validate_operation_configuration(
        "paid_openai",
        values={**common, "OPENAI_API_KEY": "provider-secret-key"},
    )
    assert "OPENAI_API_KEY" in receipt["checked"]
    assert "GEMINI_API_KEY" not in receipt["checked"]


def test_manifest_and_nested_redaction_never_expose_secret_values() -> None:
    secret = "never-show-this-provider-key"
    manifest = configuration_manifest(
        values={
            "OPENAI_API_KEY": secret,
            "CREATOR_OS_STATE_ROOT": "/private/state",
        }
    )
    serialized = repr(manifest)
    assert secret not in serialized
    by_name = {item["name"]: item for item in manifest["items"]}
    assert by_name["OPENAI_API_KEY"]["value"] == "[REDACTED]"
    assert by_name["CREATOR_OS_STATE_ROOT"]["value"] == "/private/state"

    redacted = redact_mapping(
        {
            "OPENAI_API_KEY": secret,
            "nested": {"unregistered_password": "also-secret", "safe": "ok"},
        }
    )
    assert redacted == {
        "OPENAI_API_KEY": "[REDACTED]",
        "nested": {"unregistered_password": "[REDACTED]", "safe": "ok"},
    }
