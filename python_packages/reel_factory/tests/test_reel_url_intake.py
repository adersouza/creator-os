from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from reel_factory.reel_url_import import (
    _needs_auth,
    _runner_cmd,
    _sanitize_command,
    _validate_direct_redirect_chain,
    canonicalize_reel_url,
)


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]


@patch("reel_factory.reel_url_import.socket.getaddrinfo", side_effect=_public_dns)
def test_supported_url_canonicalization(_dns) -> None:
    instagram = canonicalize_reel_url(
        "https://www.instagram.com/reel/DbQdqWFIvKQ/?igsh=secret"
    )
    assert instagram == {
        "originalUrl": "https://www.instagram.com/reel/DbQdqWFIvKQ/",
        "canonicalUrl": "https://www.instagram.com/reel/DbQdqWFIvKQ/",
        "platform": "instagram",
        "nativeMediaId": "DbQdqWFIvKQ",
    }
    assert (
        canonicalize_reel_url(
            "https://www.tiktok.com/@creator/video/7412345678901234567?x=1"
        )["nativeMediaId"]
        == "7412345678901234567"
    )
    assert (
        canonicalize_reel_url(
            "https://www.youtube.com/shorts/abc_DEF-12?feature=share"
        )["canonicalUrl"]
        == "https://www.youtube.com/shorts/abc_DEF-12"
    )
    assert (
        canonicalize_reel_url("https://cdn.example.com/reel.mp4")["platform"]
        == "direct_http"
    )


def test_private_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="public"):
        canonicalize_reel_url("http://127.0.0.1/reel.mp4")


@patch("reel_factory.reel_url_import.socket.getaddrinfo")
@patch("reel_factory.reel_url_import.requests.get")
def test_direct_redirect_to_private_host_is_rejected(request_get, dns) -> None:
    class Response:
        is_redirect = True
        is_permanent_redirect = False
        status_code = 302
        headers = {"location": "http://127.0.0.1/private.mp4"}

        def close(self) -> None:
            return None

    request_get.return_value = Response()
    dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
    with pytest.raises(ValueError, match="public"):
        _validate_direct_redirect_chain("https://cdn.example.com/reel.mp4")


def test_cookie_fallback_contract_is_private_and_sanitized(tmp_path) -> None:
    from subprocess import CompletedProcess

    with patch(
        "reel_factory.reel_url_import.shutil.which",
        return_value="/usr/bin/yt-dlp",
    ):
        command = _runner_cmd(
            "https://www.instagram.com/reel/abc/?igsh=private",
            tmp_path / "clip.%(ext)s",
            browser_cookies=True,
        )
    assert "--ignore-config" in command
    assert "--abort-on-error" in command
    assert "--no-write-comments" in command
    assert "chrome:Default" in command
    sanitized = _sanitize_command(command)
    assert "chrome:Default" not in sanitized
    assert "<private-browser-profile>" in sanitized
    assert not any("igsh=" in value for value in sanitized)
    assert _needs_auth(CompletedProcess(command, 1, "", "Login required; use cookies"))
