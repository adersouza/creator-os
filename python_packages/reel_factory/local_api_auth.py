"""Compatibility module for the packaged Reel Factory local API auth helpers."""

from __future__ import annotations

from reel_factory.local_api_auth import (
    authorize_local_api_request,
    install_local_api_auth_middleware,
    require_local_api_auth,
)

__all__ = [
    "authorize_local_api_request",
    "install_local_api_auth_middleware",
    "require_local_api_auth",
]
