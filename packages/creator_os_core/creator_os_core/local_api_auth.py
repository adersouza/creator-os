from __future__ import annotations

import hashlib
import ipaddress
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response


@dataclass(frozen=True)
class LocalApiAuthContext:
    actor_fingerprint: str
    role: str
    authenticated: bool


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def require_local_api_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> LocalApiAuthContext:
    context = getattr(request.state, "local_api_auth", None)
    if not isinstance(context, LocalApiAuthContext):
        context = authorize_local_api_request(request, authorization)
        request.state.local_api_auth = context
    authorizer = getattr(request.app.state, "local_api_authorizer", None)
    if callable(authorizer):
        authorizer(request, context)
    return context


def authorize_local_api_request(
    request: Request, authorization: str | None
) -> LocalApiAuthContext:
    token = os.environ.get("CREATOR_OS_API_TOKEN")
    if token:
        if authorization == f"Bearer {token}":
            return LocalApiAuthContext(
                actor_fingerprint="token:"
                + hashlib.sha256(token.encode()).hexdigest()[:20],
                role=str(os.environ.get("CREATOR_OS_API_ROLE") or "operator"),
                authenticated=True,
            )
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _truthy(os.environ.get("ALLOW_INSECURE_LOCAL")) and _is_loopback(
        request.client.host if request.client else None
    ):
        return LocalApiAuthContext(
            actor_fingerprint="loopback:insecure",
            role="reader",
            authenticated=False,
        )

    raise HTTPException(
        status_code=401,
        detail="CREATOR_OS_API_TOKEN is required for non-loopback access",
        headers={"WWW-Authenticate": "Bearer"},
    )


def install_local_api_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def local_api_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            context = authorize_local_api_request(
                request, request.headers.get("authorization")
            )
            request.state.local_api_auth = context
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        return await call_next(request)
