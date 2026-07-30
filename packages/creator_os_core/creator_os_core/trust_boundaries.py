"""Fail-closed primitives for local file, URL, JSON, archive, and tool boundaries."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlsplit, urlunsplit

DEFAULT_MAX_JSON_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def has_symlink_component(path: Path | str) -> bool:
    """Return true when any existing lexical path component is a symlink."""

    absolute = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            continue
    return False


def contained_path(
    root: Path | str,
    candidate: Path | str,
    *,
    require_file: bool = False,
    require_directory: bool = False,
) -> Path:
    """Resolve a non-symlink path and require it to remain under ``root``."""

    root_path = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
    if has_symlink_component(root_path):
        raise ValueError("trusted_root_contains_symlink")
    raw = Path(candidate).expanduser()
    if not raw.is_absolute():
        if ".." in raw.parts:
            raise ValueError("trusted_path_traversal")
        raw = root_path / raw
    lexical = Path(os.path.abspath(os.fspath(raw)))
    try:
        lexical.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("trusted_path_outside_root") from exc
    if has_symlink_component(lexical):
        raise ValueError("trusted_path_contains_symlink")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(root_path.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("trusted_path_outside_root") from exc
    if require_file and not _regular_file(resolved):
        raise ValueError("trusted_path_requires_regular_file")
    if require_directory and not resolved.is_dir():
        raise ValueError("trusted_path_requires_directory")
    return resolved


def regular_file(
    path: Path | str,
    *,
    root: Path | str | None = None,
    max_bytes: int | None = None,
) -> Path:
    """Require a regular, non-symlink file and optionally bind it to a root."""

    raw = Path(path).expanduser()
    resolved = contained_path(root, raw, require_file=True) if root else raw.resolve()
    if has_symlink_component(raw) or not _regular_file(resolved):
        raise ValueError("trusted_input_requires_regular_file")
    if max_bytes is not None and resolved.stat().st_size > max_bytes:
        raise ValueError("trusted_input_exceeds_size_limit")
    return resolved


def load_json_object(
    path: Path | str,
    *,
    root: Path | str | None = None,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
    validator: Callable[[Mapping[str, Any]], bool | None] | None = None,
) -> dict[str, Any]:
    """Load one bounded JSON object and run its domain validator when supplied."""

    source = regular_file(path, root=root, max_bytes=max_bytes)
    try:
        decoded = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("trusted_json_invalid") from exc
    if not isinstance(decoded, dict):
        raise ValueError("trusted_json_object_required")
    if validator is not None and validator(decoded) is False:
        raise ValueError("trusted_json_schema_rejected")
    return decoded


def validate_public_http_url(
    value: str,
    *,
    require_https: bool = True,
    resolver: Callable[..., Iterable[Any]] = socket.getaddrinfo,
) -> str:
    """Require an HTTP(S) URL whose current DNS answers are globally routable."""

    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if (
        parsed.scheme.lower() not in allowed_schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("public_url_invalid")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("public_url_invalid_port") from exc
    if port not in {None, 80, 443}:
        raise ValueError("public_url_invalid_port")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("public_url_private_host")
    addresses: set[str] = set()
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            answers = resolver(hostname, port or 443, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise ValueError("public_url_dns_unavailable") from exc
        for answer in answers:
            addresses.add(str(answer[4][0]).split("%", 1)[0])
    else:
        addresses.add(str(literal))
    if not addresses:
        raise ValueError("public_url_dns_unavailable")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("public_url_dns_invalid") from exc
        if not ip.is_global:
            raise ValueError("public_url_private_host")
    return raw


def sanitized_url(value: str) -> str:
    """Remove credentials, query parameters, and fragments from URL evidence."""

    parsed = urlsplit(str(value or ""))
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # noqa: PLR0913 - stdlib callback signature
        self,
        req: urllib.request.Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_public_file(
    url: str,
    destination: Path | str,
    *,
    expected_sha256: str | None,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    timeout: int = 60,
    user_agent: str = "CreatorOS/1.0",
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download to a private staging file, hash it, then atomically install it."""

    validated = validate_public_http_url(url)
    if max_bytes <= 0:
        raise ValueError("download_size_limit_invalid")
    target = Path(destination).expanduser()
    if has_symlink_component(target.parent) or target.is_symlink():
        raise ValueError("download_destination_symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        validated,
        headers={"User-Agent": user_agent},
    )
    open_request = (
        opener or urllib.request.build_opener(_ValidatedRedirectHandler()).open
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".download",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    content_type: str | None = None
    final_url = validated
    try:
        with os.fdopen(descriptor, "wb") as output:
            with open_request(request, timeout=timeout) as response:
                response_url = (
                    response.geturl()
                    if callable(getattr(response, "geturl", None))
                    else validated
                )
                final_url = validate_public_http_url(response_url)
                content_type = response.headers.get_content_type()
                declared = (
                    response.headers.get("Content-Length")
                    if callable(getattr(response.headers, "get", None))
                    else None
                )
                if declared is not None:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise ValueError("download_content_length_invalid") from exc
                    if declared_size < 0 or declared_size > max_bytes:
                        raise ValueError("download_exceeds_size_limit")
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("download_exceeds_size_limit")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size <= 0:
            raise ValueError("download_empty")
        observed = digest.hexdigest()
        if expected_sha256 is not None and observed != expected_sha256.lower():
            raise ValueError("download_sha256_mismatch")
        if target.exists():
            if not _regular_file(target) or _sha256_file(target) != observed:
                raise FileExistsError("download_destination_collision")
            temporary.unlink()
        else:
            os.replace(temporary, target)
            target.chmod(0o600)
        return {
            "url": sanitized_url(validated),
            "finalUrl": sanitized_url(final_url),
            "sha256": observed,
            "bytes": size,
            "contentType": content_type,
        }
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def safe_extract_zip(
    archive: Path | str,
    destination: Path | str,
    *,
    max_files: int = 256,
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
) -> list[Path]:
    """Extract regular Zip members while rejecting traversal, links, and bombs."""

    source = regular_file(archive)
    target = Path(destination).expanduser()
    if has_symlink_component(target):
        raise ValueError("archive_destination_symlink")
    target.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    extracted: list[Path] = []
    total = 0
    with zipfile.ZipFile(source) as bundle:
        members = bundle.infolist()
        if len(members) > max_files:
            raise ValueError("archive_file_count_exceeded")
        for member in members:
            relative = PurePosixPath(member.filename)
            unix_mode = member.external_attr >> 16
            file_type = stat.S_IFMT(unix_mode)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in member.filename
                or stat.S_ISLNK(unix_mode)
                or (file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR})
            ):
                raise ValueError("archive_member_unsafe")
            total += int(member.file_size)
            if total > max_uncompressed_bytes:
                raise ValueError("archive_uncompressed_size_exceeded")
            output = contained_path(target, Path(*relative.parts))
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output.name}.",
                suffix=".extract",
                dir=output.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle, bundle.open(member) as item:
                    while chunk := item.read(1024 * 1024):
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, output)
                output.chmod(0o600)
            finally:
                temporary.unlink(missing_ok=True)
            extracted.append(output)
    return extracted


def run_argv(
    argv: Sequence[str],
    *,
    allowed_executables: Iterable[str] | None = None,
    cwd: Path | str | None = None,
    timeout: int,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an explicit argument array without a shell or inherited stdin."""

    if (
        isinstance(argv, (str, bytes))
        or not argv
        or any(not isinstance(item, str) or "\x00" in item for item in argv)
    ):
        raise ValueError("subprocess_argv_required")
    executable = Path(argv[0]).name
    if allowed_executables is not None and executable not in set(allowed_executables):
        raise ValueError("subprocess_executable_not_allowed")
    resolved_cwd = None
    if cwd is not None:
        resolved_cwd = regular_directory(cwd)
    return subprocess.run(
        list(argv),
        capture_output=True,
        check=False,
        cwd=resolved_cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
    )


def regular_directory(path: Path | str) -> Path:
    raw = Path(path).expanduser()
    if has_symlink_component(raw):
        raise ValueError("trusted_directory_contains_symlink")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise ValueError("trusted_directory_required")
    return resolved


def _regular_file(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
