from __future__ import annotations

import ipaddress
import os

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response


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
) -> None:
    authorize_local_api_request(request, authorization)


def authorize_local_api_request(request: Request, authorization: str | None) -> None:
    token = os.environ.get("CREATOR_OS_API_TOKEN")
    if token:
        if authorization == f"Bearer {token}":
            return
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _truthy(os.environ.get("ALLOW_INSECURE_LOCAL")) and _is_loopback(
        request.client.host if request.client else None
    ):
        return

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
            authorize_local_api_request(request, request.headers.get("authorization"))
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        return await call_next(request)
