"""Private, content-addressed audio acquisition and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .models import AudioLocator

_MAX_AUDIO_BYTES = 150 * 1024 * 1024
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class AudioAcquisitionError(RuntimeError):
    """Audio bytes were missing, unsafe, invalid, or substituted."""


@dataclass(frozen=True)
class AcquiredAudio:
    """Verified private-cache object and immutable acquisition receipt."""

    cache_path: Path
    provider: str
    platform: str
    track_id: str
    retrieved_at: str
    source_kind: str
    source_fingerprint: str
    byte_sha256: str
    size_bytes: int
    duration_seconds: float
    codec: str
    sample_rate: int | None
    channels: int | None

    def receipt(self) -> dict[str, Any]:
        value = asdict(self)
        value["cache_path"] = str(self.cache_path)
        value["schema"] = "creator_os.audio_acquisition_receipt.v1"
        return value


class AudioCache:
    """Acquire one approved locator into a private content-addressed cache."""

    def __init__(
        self,
        root: Path,
        *,
        session: requests.Session | None = None,
        max_bytes: int = _MAX_AUDIO_BYTES,
    ) -> None:
        raw_root = root.expanduser()
        if raw_root.exists() and raw_root.is_symlink():
            raise AudioAcquisitionError("audio cache root must not be a symlink")
        self.root = raw_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.session = session or requests.Session()
        self.max_bytes = max_bytes

    def acquire(self, locator: AudioLocator, *, retrieved_at: str) -> AcquiredAudio:
        """Copy/download, hash, probe, and atomically install one audio object."""

        source_fingerprint = hashlib.sha256(
            f"{locator.kind}:{locator.value}".encode()
        ).hexdigest()
        suffix = _source_suffix(locator.value)
        safe_provider = _safe_component(locator.provider, fallback="provider")
        safe_platform = _safe_component(locator.platform, fallback="platform")
        safe_track_id = _safe_component(locator.track_id, fallback="track")
        destination = self.root / (
            f"{safe_provider}-{safe_platform}-{safe_track_id}-"
            f"{source_fingerprint[:16]}{suffix}"
        )
        if destination.exists():
            return self._validated_receipt(
                destination,
                locator=locator,
                retrieved_at=retrieved_at,
                source_fingerprint=source_fingerprint,
            )
        fd, temporary_name = tempfile.mkstemp(
            prefix=".audio-partial-",
            dir=self.root,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            if locator.kind == "local_file":
                self._copy_local(locator, temporary)
            else:
                self._download(locator, temporary)
            temporary.chmod(0o600)
            receipt = self._validated_receipt(
                temporary,
                locator=locator,
                retrieved_at=retrieved_at,
                source_fingerprint=source_fingerprint,
            )
            os.replace(temporary, destination)
            destination.chmod(0o600)
            return AcquiredAudio(
                **{
                    **asdict(receipt),
                    "cache_path": destination,
                }
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def delete_verified(self, path: Path, *, expected_sha256: str) -> int:
        """Delete one exact cached object after containment and hash checks."""

        raw_path = path.expanduser()
        if raw_path.is_symlink():
            raise AudioAcquisitionError("cached audio object must not be a symlink")
        resolved = raw_path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise AudioAcquisitionError(
                "cached audio object is outside the private cache"
            ) from exc
        if not resolved.is_file():
            raise AudioAcquisitionError("cached audio object is missing")
        actual_sha256 = _sha256_file(resolved)
        if actual_sha256 != expected_sha256:
            raise AudioAcquisitionError("cached audio object hash does not match")
        size = resolved.stat().st_size
        resolved.unlink()
        return size

    def _copy_local(self, locator: AudioLocator, temporary: Path) -> None:
        source = Path(locator.value).expanduser()
        if source.is_symlink():
            raise AudioAcquisitionError("local audio source must not be a symlink")
        source = source.resolve()
        if not source.is_file():
            raise AudioAcquisitionError("local audio source is missing")
        info = source.stat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= self.max_bytes:
            raise AudioAcquisitionError("local audio source size is invalid")
        shutil.copyfile(source, temporary)

    def _download(self, locator: AudioLocator, temporary: Path) -> None:
        parsed = urlparse(locator.value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise AudioAcquisitionError("audio acquisition URL must use HTTPS")
        if not locator.allowed_hosts or not any(
            host == allowed or host.endswith(f".{allowed}")
            for allowed in locator.allowed_hosts
        ):
            raise AudioAcquisitionError("audio acquisition host is not allowlisted")
        response = self.session.get(
            locator.value,
            headers=dict(locator.request_headers),
            stream=True,
            timeout=(10, 60),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise AudioAcquisitionError(
                f"audio acquisition failed: HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "").lower()
        if not (
            content_type.startswith("audio/")
            or content_type.startswith("video/")
            or content_type.startswith("application/octet-stream")
        ):
            raise AudioAcquisitionError("audio acquisition content type is invalid")
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            raise AudioAcquisitionError("audio acquisition exceeds size limit")
        total = 0
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_bytes:
                    raise AudioAcquisitionError("audio acquisition exceeds size limit")
                handle.write(chunk)
        if total <= 0:
            raise AudioAcquisitionError("audio acquisition returned no bytes")

    def _validated_receipt(
        self,
        path: Path,
        *,
        locator: AudioLocator,
        retrieved_at: str,
        source_fingerprint: str,
    ) -> AcquiredAudio:
        size = path.stat().st_size
        if not 0 < size <= self.max_bytes:
            raise AudioAcquisitionError("acquired audio size is invalid")
        digest = _sha256_file(path)
        probe = probe_media(path)
        audio_streams = [
            value
            for value in probe.get("streams", [])
            if isinstance(value, dict) and value.get("codec_type") == "audio"
        ]
        if not audio_streams:
            raise AudioAcquisitionError("acquired media has no audio stream")
        stream = audio_streams[0]
        duration = _duration(probe)
        codec = str(stream.get("codec_name") or "").strip()
        if duration <= 0 or not codec:
            raise AudioAcquisitionError("acquired audio probe is incomplete")
        return AcquiredAudio(
            cache_path=path,
            provider=locator.provider,
            platform=locator.platform,
            track_id=locator.track_id,
            retrieved_at=retrieved_at,
            source_kind=locator.kind,
            source_fingerprint=source_fingerprint,
            byte_sha256=digest,
            size_bytes=size,
            duration_seconds=duration,
            codec=codec,
            sample_rate=_optional_int(stream.get("sample_rate")),
            channels=_optional_int(stream.get("channels")),
        )


def probe_media(path: Path) -> dict[str, Any]:
    """Return bounded ffprobe JSON for a regular, non-symlink media file."""

    resolved = path.expanduser()
    if resolved.is_symlink():
        raise AudioAcquisitionError("media probe path must not be a symlink")
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise AudioAcquisitionError("media probe path is missing")
    result = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(resolved),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        raise AudioAcquisitionError((result.stderr or "ffprobe failed")[-2000:].strip())
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioAcquisitionError("ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AudioAcquisitionError("ffprobe response must be an object")
    return payload


def _duration(probe: dict[str, Any]) -> float:
    try:
        return float((probe.get("format") or {}).get("duration") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_suffix(value: str) -> str:
    suffix = Path(urlparse(value).path).suffix.lower()
    return (
        suffix
        if suffix in {".mp3", ".m4a", ".aac", ".wav", ".flac", ".mp4"}
        else ".bin"
    )


def _safe_component(value: str, *, fallback: str) -> str:
    return _SAFE_ID_RE.sub("_", value).strip("._") or fallback
