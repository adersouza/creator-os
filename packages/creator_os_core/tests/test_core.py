from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from creator_os_core.fileops import atomic_write_json, atomic_write_text, file_lock
from creator_os_core.local_api_auth import authorize_local_api_request
from creator_os_core.media_probe import probe_video_stream
from creator_os_core.sqlite import connect_sqlite, ensure_columns
from creator_os_core.vectors import cosine_similarity, normalize_vector
from fastapi import HTTPException
from starlette.requests import Request


def _request(host: str = "127.0.0.1") -> Request:
    return Request({"type": "http", "client": (host, 1234), "headers": []})


def test_atomic_writes_and_nonblocking_lock(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, "first")
    assert target.read_text() == "first"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text()) == {"ok": True}
    with file_lock(target):
        with pytest.raises(BlockingIOError), file_lock(target, blocking=False):
            pass


def test_sqlite_connection_and_idempotent_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    with connect_sqlite(db_path) as conn:
        conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY)")
        ensure_columns(conn, "items", {"label": "TEXT"})
        ensure_columns(conn, "items", {"label": "TEXT"})
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
        assert columns == {"id", "label"}


def test_vector_contract() -> None:
    assert normalize_vector([3.0, 4.0]) == [0.6, 0.8]
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_local_auth_requires_token_unless_loopback_is_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    with pytest.raises(HTTPException) as exc:
        authorize_local_api_request(_request(), None)
    assert exc.value.status_code == 401

    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    authorize_local_api_request(_request(), None)

    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "secret")
    authorize_local_api_request(_request("203.0.113.10"), "Bearer secret")


def test_media_probe_parses_first_video_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *_args, **_kwargs: json.dumps(
            {"streams": [{"width": 1080, "height": 1920, "duration": "4.5"}]}
        ),
    )
    assert probe_video_stream("clip.mp4") == {
        "width": 1080,
        "height": 1920,
        "duration": 4.5,
    }
