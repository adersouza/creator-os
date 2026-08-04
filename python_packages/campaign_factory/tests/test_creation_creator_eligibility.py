from __future__ import annotations

from types import SimpleNamespace

import pytest
from campaign_factory.creation_modes import run_creation_batch
from campaign_factory.production_source_selection import (
    CREATION_ENABLED_CREATORS,
    active_production_identity,
    require_creation_enabled_creator,
    resolve_reference_analysis_governance,
)
from campaign_factory.reference_url_workflow import run_reference_analysis


class _IdentityGovernance:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def active_identity_profile(self, creator: str, *, provider: str) -> dict[str, str]:
        self.calls.append((creator, provider))
        return {
            "creator_id": f"creator-{creator}",
            "creator_slug": creator,
            "provider_identity_id": f"identity-{creator}",
        }


@pytest.mark.parametrize("creator", ["larissa", "Larissa", " stacey ", "STACEY"])
def test_supported_creation_creators_are_normalized(creator: str) -> None:
    assert require_creation_enabled_creator(creator) in CREATION_ENABLED_CREATORS


@pytest.mark.parametrize("creator", ["lola", "other", ""])
def test_unsupported_creation_creator_fails_closed(creator: str) -> None:
    with pytest.raises(
        PermissionError,
        match=r"creator_creation_not_enabled:.*allowed creators: larissa, stacey",
    ):
        require_creation_enabled_creator(creator)


def test_creation_entrypoint_blocks_lola_before_reuse_or_factory_access() -> None:
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        run_creation_batch(
            object(),
            creator="lola",
            mode="static_reel",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="silent_allowed",
            apply=False,
        )


def test_direct_production_identity_resolution_blocks_lola_before_governance() -> None:
    governance = _IdentityGovernance()
    factory = SimpleNamespace(domains=SimpleNamespace(creator_governance=governance))

    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        active_production_identity(factory, "lola")

    assert governance.calls == []


def test_reference_analysis_governance_blocks_lola_before_database_access() -> None:
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        resolve_reference_analysis_governance(object(), "lola")


def test_reference_url_creation_blocks_lola_before_download_or_analysis() -> None:
    with pytest.raises(PermissionError, match="creator_creation_not_enabled:lola"):
        run_reference_analysis(
            object(),
            creator="lola",
            reference_url="https://www.instagram.com/reel/example/",
            reference_video_path=None,
            reference_platform="instagram",
            reference_authorized=True,
            declared_talking=False,
            apply=False,
        )


def test_supported_creator_keeps_existing_identity_binding() -> None:
    governance = _IdentityGovernance()
    factory = SimpleNamespace(domains=SimpleNamespace(creator_governance=governance))

    assert active_production_identity(factory, " Stacey ") == (
        "stacey",
        "identity-stacey",
    )
    assert governance.calls == [("stacey", "higgsfield")]
