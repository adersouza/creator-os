from __future__ import annotations

import io
import json
import stat
import sys
import zipfile
from email.message import Message
from pathlib import Path

import pytest
from creator_os_core.trust_boundaries import (
    contained_path,
    download_public_file,
    load_json_object,
    run_argv,
    safe_extract_zip,
    sanitized_url,
    validate_public_http_url,
)


def _public_resolver(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _private_resolver(*_args, **_kwargs):
    return [(2, 1, 6, "", ("127.0.0.1", 443))]


class FakeResponse:
    def __init__(self, payload: bytes, url: str = "https://93.184.216.34/file"):
        self._payload = io.BytesIO(payload)
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = "application/octet-stream"
        self.headers["Content-Length"] = str(len(payload))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._payload.read(size)


def test_contained_path_rejects_traversal_external_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "source.json"
    source.write_text("{}", encoding="utf-8")
    assert contained_path(root, "source.json", require_file=True) == source

    with pytest.raises(ValueError, match="traversal"):
        contained_path(root, "../outside")
    with pytest.raises(ValueError, match="outside_root"):
        contained_path(root, tmp_path / "outside")

    link = root / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        contained_path(root, link / "payload")


def test_json_loader_is_bounded_object_only_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text('{"schema":"expected"}', encoding="utf-8")
    assert (
        load_json_object(
            path,
            validator=lambda value: value.get("schema") == "expected",
        )["schema"]
        == "expected"
    )

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="object_required"):
        load_json_object(path)
    path.write_text('{"schema":"wrong"}', encoding="utf-8")
    with pytest.raises(ValueError, match="schema_rejected"):
        load_json_object(
            path, validator=lambda value: value.get("schema") == "expected"
        )
    with pytest.raises(ValueError, match="size_limit"):
        load_json_object(path, max_bytes=1)


@pytest.mark.parametrize(
    "url",
    (
        "file:///etc/passwd",
        "https://localhost/file",
        "https://127.0.0.1/file",
        "https://169.254.169.254/latest/meta-data",
        "https://user:secret@example.com/file",
        "https://example.com:444/file",
        "https://example.com/file#fragment",
    ),
)
def test_public_url_rejects_local_credentials_ports_and_non_http(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_http_url(url, resolver=_public_resolver)


def test_public_url_requires_every_dns_answer_to_be_global() -> None:
    assert (
        validate_public_http_url(
            "https://example.com/file",
            resolver=_public_resolver,
        )
        == "https://example.com/file"
    )
    with pytest.raises(ValueError, match="private_host"):
        validate_public_http_url(
            "https://example.com/file",
            resolver=_private_resolver,
        )


def test_public_download_is_staged_hashed_bounded_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified-download"
    expected = __import__("hashlib").sha256(payload).hexdigest()
    monkeypatch.setattr(
        "creator_os_core.trust_boundaries.socket.getaddrinfo",
        _public_resolver,
    )
    destination = tmp_path / "asset.bin"
    receipt = download_public_file(
        "https://93.184.216.34/file?temporary=secret",
        destination,
        expected_sha256=expected,
        max_bytes=1024,
        opener=lambda *_args, **_kwargs: FakeResponse(payload),
    )

    assert destination.read_bytes() == payload
    assert receipt["sha256"] == expected
    assert receipt["url"] == "https://93.184.216.34/file"
    assert "secret" not in json.dumps(receipt)
    assert not list(tmp_path.glob("*.download"))

    rejected = tmp_path / "rejected.bin"
    with pytest.raises(ValueError, match="sha256"):
        download_public_file(
            "https://93.184.216.34/file",
            rejected,
            expected_sha256="0" * 64,
            max_bytes=1024,
            opener=lambda *_args, **_kwargs: FakeResponse(payload),
        )
    assert not rejected.exists()


def test_safe_zip_extraction_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as bundle:
        bundle.writestr("../escape.txt", b"bad")
    with pytest.raises(ValueError, match="member_unsafe"):
        safe_extract_zip(traversal, tmp_path / "traversal-output")
    assert not (tmp_path / "escape.txt").exists()

    linked = tmp_path / "linked.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(linked, "w") as bundle:
        bundle.writestr(info, "target")
    with pytest.raises(ValueError, match="member_unsafe"):
        safe_extract_zip(linked, tmp_path / "linked-output")

    safe = tmp_path / "safe.zip"
    with zipfile.ZipFile(safe, "w") as bundle:
        bundle.writestr("models/model.bin", b"model")
    extracted = safe_extract_zip(safe, tmp_path / "safe-output")
    assert [
        path.relative_to(tmp_path / "safe-output").as_posix() for path in extracted
    ] == ["models/model.bin"]


def test_subprocess_boundary_requires_argv_and_allowlisted_executable(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="argv"):
        run_argv("echo unsafe", timeout=5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not_allowed"):
        run_argv(
            [sys.executable, "-c", "print('ok')"],
            allowed_executables={"nope"},
            timeout=5,
        )

    completed = run_argv(
        [sys.executable, "-c", "print('ok')"],
        allowed_executables={Path(sys.executable).name},
        cwd=tmp_path,
        timeout=5,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "ok"


def test_sanitized_url_removes_userinfo_query_and_fragment() -> None:
    assert (
        sanitized_url("https://user:secret@example.com:443/file?q=secret#fragment")
        == "https://example.com:443/file"
    )
