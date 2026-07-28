"""Exact reference-audio extraction and durable Audio Radar evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .audio_radar.segment import decoded_audio_fingerprint

SCHEMA = "campaign_factory.reference_audio_intake.v1"
SAMPLE_RATE = 16_000


def load_reference_audio_occurrence(
    conn: sqlite3.Connection, reference_id: str
) -> dict[str, Any] | None:
    if not _table_exists(conn, "audio_reference_occurrences"):
        return None
    try:
        row = conn.execute(
            """
            SELECT o.*, c.cache_path, c.codec, c.duration_seconds, c.chromaprint_version
            FROM audio_reference_occurrences o
            LEFT JOIN audio_cache_objects c
              ON c.audio_catalog_id = o.audio_catalog_id
             AND c.encoded_audio_sha256 = o.encoded_audio_sha256
            WHERE o.reference_id = ?
            ORDER BY c.created_at
            LIMIT 1
            """,
            (reference_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    value = dict(row)
    return {
        "schema": SCHEMA,
        "status": "reused_existing_occurrence",
        "audioPresent": bool(value.get("encoded_audio_sha256")),
        "canonicalAudioId": value.get("audio_catalog_id"),
        "encodedAudioSha256": value.get("encoded_audio_sha256"),
        "canonicalPcmSha256": value.get("canonical_pcm_sha256"),
        "chromaprint": {
            "status": "available" if value.get("chromaprint") else "unavailable",
            "fingerprint": value.get("chromaprint"),
            "version": value.get("chromaprint_version"),
        },
        "classification": value.get("audio_policy_classification"),
        "referenceOccurrence": value.get("id"),
        "exactAudioPath": value.get("cache_path"),
        "dedupe": {"method": "reference_occurrence", "matched": True},
        "proposedMutations": [],
    }


def inspect_reference_audio(
    conn: sqlite3.Connection,
    *,
    source_video: Path,
    reference_id: str,
    metadata: dict[str, Any],
    artifact_root: Path,
    apply: bool,
    declared_talking: bool = False,
    dance_or_synchronized: bool = False,
) -> dict[str, Any]:
    source = source_video.expanduser().resolve()
    source_sha = _sha256(source)
    probe = _probe(source)
    audio_streams = [
        stream
        for stream in probe.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    platform = str(metadata.get("platform") or "private_reference")
    if not audio_streams:
        return {
            "schema": SCHEMA,
            "status": "UNAVAILABLE",
            "audioPresent": False,
            "referenceOccurrence": None,
            "proposedMutations": [],
        }
    stream = audio_streams[0]
    duration = _duration(probe)
    working_parent = (
        artifact_root
        if apply
        else Path(tempfile.mkdtemp(prefix="creator-os-audio-analysis-"))
    )
    working_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(working_parent, 0o700)
    temp_dir = Path(tempfile.mkdtemp(prefix=".reference-audio-", dir=working_parent))
    exact = temp_dir / "exact-reference-audio.mka"
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "copy",
            str(exact),
        ],
        "reference audio stream-copy failed",
    )
    os.chmod(exact, 0o600)
    encoded_sha = _sha256(exact)
    pcm_sha = decoded_audio_fingerprint(exact)
    chroma = _chromaprint(exact)
    loudness = _loudness(exact)
    canonical_id, dedupe = _canonical_identity(
        conn,
        encoded_sha=encoded_sha,
        pcm_sha=pcm_sha,
        chromaprint=str(chroma.get("fingerprint") or ""),
        chromaprint_duration=float(chroma.get("duration") or duration),
        platform=platform,
        native_sound_id=_native_sound_id(metadata),
    )
    occurrence_id = (
        f"audio_occ_{hashlib.sha256(reference_id.encode()).hexdigest()[:20]}"
    )
    cache_object_id = f"audio_cache_{encoded_sha[:20]}"
    segment_id = f"audio_segment_{hashlib.sha256(f'{reference_id}:0:{duration}'.encode()).hexdigest()[:20]}"
    classification = _classification(
        declared_talking=declared_talking,
        dance_or_synchronized=dance_or_synchronized,
    )
    final_exact = (
        artifact_root
        / "reference_audio"
        / canonical_id
        / "encoded"
        / f"{encoded_sha}.mka"
    )
    receipt = {
        "schema": SCHEMA,
        "referenceId": reference_id,
        "sourceVideoSha256": source_sha,
        "encodedAudio": {
            "sha256": encoded_sha,
            "codec": stream.get("codec_name"),
            "container": "matroska",
            "sampleRate": _int(stream.get("sample_rate")),
            "channels": _int(stream.get("channels")),
            "channelLayout": stream.get("channel_layout"),
            "durationSeconds": duration,
            "complete": True,
        },
        "canonicalPcm": {
            "sha256": pcm_sha,
            "format": "s16le_mono_16000hz",
            "sampleRate": SAMPLE_RATE,
        },
        "chromaprint": chroma,
        "loudness": loudness,
        "platformSoundIdentity": _platform_sound_identity(metadata),
        "canonicalAudioId": canonical_id,
        "dedupe": dedupe,
        "classification": classification,
        "toolchain": {
            "ffmpeg": _version("ffmpeg"),
            "ffprobe": _version("ffprobe"),
            "fpcalc": _version("fpcalc"),
        },
    }
    if apply:
        final_exact.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(final_exact.parent, 0o700)
        if not final_exact.exists():
            os.replace(exact, final_exact)
            os.chmod(final_exact, 0o600)
        elif _sha256(final_exact) != encoded_sha:
            raise RuntimeError("canonical reference-audio path hash mismatch")
        receipt_path = final_exact.parent / f"{reference_id}.extraction.json"
        atomic_write_text(
            receipt_path,
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(receipt_path, 0o600)
        try:
            _persist_audio(
                conn,
                canonical_id=canonical_id,
                occurrence_id=occurrence_id,
                segment_id=segment_id,
                cache_object_id=cache_object_id,
                reference_id=reference_id,
                metadata=metadata,
                exact=final_exact,
                source_sha=source_sha,
                duration=duration,
                stream=stream,
                encoded_sha=encoded_sha,
                pcm_sha=pcm_sha,
                chroma=chroma,
                loudness=loudness,
                classification=classification,
                receipt=receipt,
            )
        except Exception:
            conn.rollback()
            raise
        status = "persisted"
    else:
        receipt_path = None
        status = "proposed"
    shutil.rmtree(temp_dir, ignore_errors=True)
    if not apply:
        shutil.rmtree(working_parent, ignore_errors=True)
    return {
        "schema": SCHEMA,
        "status": status,
        "audioPresent": True,
        "canonicalAudioId": canonical_id,
        "encodedAudioSha256": encoded_sha,
        "canonicalPcmSha256": pcm_sha,
        "chromaprint": chroma,
        "encodedAudio": receipt["encodedAudio"],
        "loudness": loudness,
        "classification": classification,
        "referenceOccurrence": occurrence_id,
        "segmentId": segment_id,
        "exactAudioPath": str(final_exact) if apply else None,
        "receiptPath": str(receipt_path) if receipt_path else None,
        "dedupe": dedupe,
        "proposedMutations": []
        if apply
        else [
            "persist exact encoded reference audio",
            "upsert canonical Audio Radar identity",
            "persist one reference occurrence and exact full-source segment",
        ],
    }


def _persist_audio(
    conn: sqlite3.Connection,
    *,
    canonical_id: str,
    occurrence_id: str,
    segment_id: str,
    cache_object_id: str,
    reference_id: str,
    metadata: dict[str, Any],
    exact: Path,
    source_sha: str,
    duration: float,
    stream: dict[str, Any],
    encoded_sha: str,
    pcm_sha: str,
    chroma: dict[str, Any],
    loudness: dict[str, Any],
    classification: str,
    receipt: dict[str, Any],
) -> None:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    title = str(metadata.get("track") or f"Reference audio {canonical_id[-8:]}")
    artist = str(metadata.get("artist") or "") or None
    platform_sound = _platform_sound_identity(metadata)
    conn.execute(
        """
        INSERT OR IGNORE INTO audio_catalog (
          id,source_audio_id,canonical_track_id,canonical_title,
          canonical_artists_json,variant,title,artist_name,platform,native_audio_id,
          native_audio_url,trend_status,resolved,review_reasons_json,raw_json,
          imported_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            canonical_id,
            pcm_sha,
            canonical_id,
            title,
            json.dumps([artist] if artist else []),
            "reference_exact",
            title,
            artist,
            "reference_audio",
            platform_sound.get("soundId"),
            platform_sound.get("soundUrl"),
            "unknown",
            1 if platform_sound.get("soundId") else 0,
            json.dumps(["reference_audio_reuse_requires_approval"]),
            json.dumps({"source": "reference_url_intake"}, sort_keys=True),
            now,
            now,
        ),
    )
    if platform_sound.get("soundId"):
        sound_id = str(platform_sound["soundId"])
        sound_key = f"{platform_sound['platform']}:{sound_id}"
        sound_row_id = f"sound_{hashlib.sha256(sound_key.encode()).hexdigest()[:20]}"
        conn.execute(
            """
            INSERT OR IGNORE INTO audio_platform_sound_ids
              (id,audio_catalog_id,platform,sound_id,region,detail_url,
               first_seen_at,last_seen_at,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                sound_row_id,
                canonical_id,
                platform_sound["platform"],
                sound_id,
                "",
                platform_sound.get("soundUrl"),
                now,
                now,
                json.dumps(platform_sound, sort_keys=True),
            ),
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO audio_cache_objects (
          id,audio_catalog_id,provider,platform,platform_sound_id,cache_path,
          byte_sha256,acoustic_fingerprint,duration_seconds,size_bytes,codec,
          sample_rate,channels,source_fingerprint,source_metadata_json,cached,
          retrieved_at,created_at,updated_at,encoded_audio_sha256,
          canonical_pcm_sha256,chromaprint,chromaprint_version,
          chromaprint_duration_seconds,container,channel_layout,loudness_json,
          extraction_receipt_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cache_object_id,
            canonical_id,
            "operator_reference",
            str(metadata.get("platform") or "private_reference"),
            str(
                _native_sound_id(metadata)
                or metadata.get("nativeMediaId")
                or reference_id
            ),
            str(exact),
            encoded_sha,
            str(chroma.get("fingerprint") or pcm_sha),
            duration,
            exact.stat().st_size,
            str(stream.get("codec_name") or ""),
            _int(stream.get("sample_rate")),
            _int(stream.get("channels")),
            source_sha,
            json.dumps({"referenceId": reference_id}),
            1,
            now,
            now,
            now,
            encoded_sha,
            pcm_sha,
            chroma.get("fingerprint"),
            chroma.get("version"),
            chroma.get("duration"),
            "matroska",
            stream.get("channel_layout"),
            json.dumps(loudness, sort_keys=True),
            json.dumps(receipt, sort_keys=True),
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO audio_reference_occurrences (
          id,audio_catalog_id,reference_id,source_platform,native_media_id,
          source_video_sha256,encoded_audio_sha256,canonical_pcm_sha256,
          chromaprint,speaking_classification,audio_policy_classification,
          source_start_seconds,source_end_seconds,extraction_receipt_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            occurrence_id,
            canonical_id,
            reference_id,
            str(metadata.get("platform") or "private_reference"),
            metadata.get("nativeMediaId"),
            source_sha,
            encoded_sha,
            pcm_sha,
            chroma.get("fingerprint"),
            "DECLARED_TALKING"
            if classification == "CREATOR_AUDIO_REQUIRED"
            else "UNKNOWN",
            classification,
            0.0,
            duration,
            json.dumps(receipt, sort_keys=True),
            now,
        ),
    )
    end_sample = round(duration * SAMPLE_RATE)
    conn.execute(
        """
        INSERT OR IGNORE INTO audio_segments (
          id,audio_catalog_id,audio_reference_occurrence_id,start_seconds,
          end_seconds,duration_seconds,start_sample,end_sample,sample_rate,
          canonical_pcm_segment_sha256,decoded_fingerprint,onset_beat_json,
          speech_private_voice_status,reuse_status,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            segment_id,
            canonical_id,
            occurrence_id,
            0.0,
            duration,
            duration,
            0,
            end_sample,
            SAMPLE_RATE,
            pcm_sha,
            pcm_sha,
            "{}",
            "private_or_unknown"
            if classification == "CREATOR_AUDIO_REQUIRED"
            else "unknown",
            "analysis_only",
            now,
        ),
    )
    conn.commit()


def _canonical_identity(
    conn: sqlite3.Connection,
    *,
    encoded_sha: str,
    pcm_sha: str,
    chromaprint: str,
    chromaprint_duration: float,
    platform: str,
    native_sound_id: str | None,
) -> tuple[str, dict[str, Any]]:
    checks = (
        ("encoded_sha", "encoded_audio_sha256", encoded_sha),
        ("canonical_pcm_sha", "canonical_pcm_sha256", pcm_sha),
    )
    cache_columns = _table_columns(conn, "audio_cache_objects")
    for method, column, value in checks:
        if column not in cache_columns:
            continue
        row = conn.execute(
            f"SELECT audio_catalog_id FROM audio_cache_objects WHERE {column} = ? LIMIT 1",
            (value,),
        ).fetchone()
        if row:
            return str(row["audio_catalog_id"]), {"method": method, "matched": True}
    if chromaprint and {
        "chromaprint",
        "chromaprint_duration_seconds",
    }.issubset(cache_columns):
        row = conn.execute(
            """
            SELECT audio_catalog_id,chromaprint_duration_seconds
            FROM audio_cache_objects WHERE chromaprint = ? LIMIT 1
            """,
            (chromaprint,),
        ).fetchone()
        if (
            row
            and abs(
                float(row["chromaprint_duration_seconds"] or 0) - chromaprint_duration
            )
            <= 0.25
        ):
            return str(row["audio_catalog_id"]), {
                "method": "chromaprint_duration",
                "matched": True,
            }
    if native_sound_id:
        row = conn.execute(
            "SELECT audio_catalog_id FROM audio_platform_sound_ids WHERE platform = ? AND sound_id = ? LIMIT 1",
            (platform, native_sound_id),
        ).fetchone()
        if row:
            return str(row["audio_catalog_id"]), {
                "method": "platform_sound_id",
                "matched": True,
            }
    canonical_id = f"audio_ref_{pcm_sha[:20]}"
    return canonical_id, {"method": "new_canonical_pcm_identity", "matched": False}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _classification(*, declared_talking: bool, dance_or_synchronized: bool) -> str:
    if declared_talking:
        return "CREATOR_AUDIO_REQUIRED"
    if dance_or_synchronized:
        return "REFERENCE_AUDIO_PREFERRED"
    return "REFERENCE_AUDIO_ELIGIBLE"


def _platform_sound_identity(metadata: dict[str, Any]) -> dict[str, Any]:
    sound_id = _native_sound_id(metadata)
    if not sound_id:
        return {"status": "unresolved"}
    return {
        "status": "resolved",
        "platform": metadata.get("platform"),
        "soundId": sound_id,
        "soundUrl": metadata.get("track_url"),
        "title": metadata.get("track"),
        "artist": metadata.get("artist"),
        "originalAudio": metadata.get("original_audio")
        if isinstance(metadata.get("original_audio"), bool)
        else None,
        "uploader": metadata.get("uploader"),
        "durationSeconds": metadata.get("duration"),
        "resolverEvidence": "yt_dlp_info_json",
    }


def _native_sound_id(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("music_id") or metadata.get("track_id")
    return str(value) if value not in {None, ""} else None


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout or "{}")


def _duration(probe: dict[str, Any]) -> float:
    value = (probe.get("format") or {}).get("duration")
    if value is None:
        streams = probe.get("streams") or []
        value = next((s.get("duration") for s in streams if s.get("duration")), None)
    duration = float(value or 0)
    if duration <= 0:
        raise RuntimeError("reference audio duration is unavailable")
    return round(duration, 6)


def _chromaprint(path: Path) -> dict[str, Any]:
    executable = shutil.which("fpcalc")
    if not executable:
        return {"status": "unavailable", "reason": "fpcalc_missing"}
    result = subprocess.run(
        [executable, "-json", str(path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        return {"status": "unavailable", "reason": "fpcalc_failed"}
    payload = json.loads(result.stdout or "{}")
    return {
        "status": "available",
        "fingerprint": payload.get("fingerprint"),
        "duration": payload.get("duration"),
        "version": _version("fpcalc"),
    }


def _loudness(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    text = result.stderr
    values: dict[str, Any] = {
        "status": "available" if result.returncode == 0 else "unavailable"
    }
    for key in ("mean_volume", "max_volume"):
        marker = f"{key}:"
        if marker in text:
            values[key] = text.split(marker, 1)[1].splitlines()[0].strip()
    return values


def _run(cmd: list[str], message: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _version(name: str) -> str | None:
    executable = shutil.which(name)
    if not executable:
        return None
    args = [executable, "-version"]
    result = subprocess.run(args, capture_output=True, text=True)
    return (
        (result.stdout or result.stderr).splitlines()[0]
        if result.returncode == 0
        else None
    )
