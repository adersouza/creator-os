from __future__ import annotations

import io
import urllib.error
import urllib.request

from pipeline_contracts.llm_resilience import (
    decode_json_object,
    urlopen_json_with_retry,
)


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def test_urlopen_json_retries_429_and_passes_timeout() -> None:
    request = urllib.request.Request("https://example.test/llm")
    timeouts: list[int] = []

    def fake_urlopen(req, timeout):  # noqa: ANN001
        assert req is request
        timeouts.append(timeout)
        if len(timeouts) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "rate limited", {}, io.BytesIO(b"retry")
            )
        return _Response(b'{"ok": true}')

    result = urlopen_json_with_retry(
        request, timeout=77, urlopen=fake_urlopen, sleep=lambda _seconds: None
    )

    assert result == {"ok": True}
    assert timeouts == [77, 77]


def test_decode_json_object_falls_back_on_malformed_json() -> None:
    assert decode_json_object("not json", fallback={"fallback": True}) == {
        "fallback": True
    }
