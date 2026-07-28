"""Canonical, deterministic URL/local-video intake for Reference Factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from creator_os_core.sqlite import connect_sqlite

from .config import DEFAULT_DATA_ROOT, DEFAULT_DB_PATH
from .db import connect
from .identity import content_hash, stable_id
from .ocr import run_selected_ocr
from .reference_local_analysis import _detect_scene_cuts, _probe_media

SCHEMA = "reference_factory.url_intake.v1"
IMPLEMENTATION = "reference_anchor_selection.v1"
FRAME_ROLES = (
    "literal_first",
    "literal_final",
    "first_clean",
    "last_clean",
    "best_anchor",
    "best_face_visible",
    "best_body_visible",
    "representative_midpoint",
)


def analyze_url_reference(
    source: Path,
    *,
    metadata: dict[str, Any],
    data_root: Path = DEFAULT_DATA_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    apply: bool = False,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise ValueError("reference source must be a regular local media file")
    source_sha = content_hash(source)
    platform = _safe_segment(str(metadata.get("platform") or "direct_http"))
    native_id = _safe_segment(str(metadata.get("nativeMediaId") or source_sha[:20]))
    reference_id = (
        f"ref_url_{hashlib.sha256(f'{platform}:{native_id}'.encode()).hexdigest()[:20]}"
    )
    canonical_dir = data_root / "url_intake" / platform / native_id
    existing = _find_existing(db_path, platform, native_id, source_sha, writable=apply)
    if existing:
        receipt = _load_receipt(existing, apply=apply)
        return {
            **receipt,
            "ok": True,
            "apply": apply,
            "duplicateResult": existing["duplicateReason"],
            "proposedMutations": [],
        }

    probe = _probe_media(source, ffprobe=shutil.which("ffprobe") or "ffprobe")
    duration = float(probe.get("durationSeconds") or 0)
    if duration <= 0:
        raise ValueError("reference video duration is unavailable")
    destination_root = (
        canonical_dir
        if apply
        else Path(tempfile.mkdtemp(prefix="creator-os-reference-analysis-"))
    )
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination_root, 0o700)
    canonical_source = destination_root / f"reference{source.suffix.lower() or '.mp4'}"
    if apply:
        shutil.copy2(source, canonical_source)
        os.chmod(canonical_source, 0o600)
    else:
        canonical_source = source
    frames_dir = destination_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    scene_cuts = _detect_scene_cuts(
        canonical_source,
        duration=duration,
        ffmpeg=shutil.which("ffmpeg") or "ffmpeg",
    )
    times = _candidate_times(duration, scene_cuts)
    candidates = [
        _extract_and_measure(canonical_source, frames_dir, index, stamp, duration)
        for index, stamp in enumerate(times)
    ]
    visual_evidence = _enrich_visual_evidence(candidates, frames_dir)
    for candidate in candidates:
        if any(
            abs(float(candidate["timeSec"]) - float(cut)) <= 0.04
            for cut in scene_cuts
            if cut > 0
        ):
            candidate["hardBlockers"].append("transition_frame")
    selected = select_anchor(candidates)
    role_map = _role_map(candidates, selected)
    derivatives = _materialize_roles(frames_dir, role_map)
    contact_sheet = _contact_sheet(
        frames_dir, destination_root / "scene_contact_sheet.jpg"
    )
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    toolchain = {
        "ffmpeg": _version("ffmpeg"),
        "ffprobe": _version("ffprobe"),
        "appleVision": visual_evidence["appleVision"],
        "mediaPipe": visual_evidence["mediaPipe"],
    }
    implementation_fingerprint = hashlib.sha256(
        f"{IMPLEMENTATION}|{Path(__file__).read_bytes()!r}".encode()
    ).hexdigest()
    anchor_receipt: dict[str, Any] = {
        "schema": "reference_factory.anchor_selection.v1",
        "referenceId": reference_id,
        "sourceMediaSha256": source_sha,
        "candidateFrames": candidates,
        "selectedFrame": {
            "timeSec": selected["timeSec"],
            "sha256": selected["sha256"],
            "score": selected["score"],
            "path": str(derivatives["best_anchor"]),
        },
        "toolchain": toolchain,
        "implementationFingerprint": implementation_fingerprint,
        "createdAt": now,
    }
    receipt_path = destination_root / "anchor_selection.json"
    atomic_write_text(
        receipt_path,
        json.dumps(anchor_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(receipt_path, 0o600)
    result = {
        "ok": True,
        "schema": SCHEMA,
        "apply": apply,
        "referenceId": reference_id,
        "source": {
            "path": str(canonical_source) if apply else None,
            "sha256": source_sha,
            "platform": platform,
            "nativeMediaId": native_id,
            "originalUrl": metadata.get("originalUrl"),
            "canonicalUrl": metadata.get("canonicalUrl"),
        },
        "media": probe,
        "sourceSpeakingClassification": (
            "DECLARED_TALKING" if metadata.get("declaredTalking") else "UNKNOWN"
        ),
        "sceneCutsSeconds": scene_cuts,
        "frameDerivatives": {
            role: {
                "path": str(path) if apply else None,
                "proposedPath": str(canonical_dir / "frames" / path.name),
                "sha256": content_hash(path),
                "timeSec": role_map[role]["timeSec"],
            }
            for role, path in derivatives.items()
        },
        "contactSheet": {
            "path": str(contact_sheet) if apply and contact_sheet else None,
            "proposedPath": str(canonical_dir / "scene_contact_sheet.jpg"),
            "sha256": content_hash(contact_sheet) if contact_sheet else None,
        },
        "selectedAnchor": {
            **anchor_receipt["selectedFrame"],
            "path": (anchor_receipt["selectedFrame"]["path"] if apply else None),
            "proposedPath": str(
                canonical_dir / "frames" / derivatives["best_anchor"].name
            ),
        },
        "anchorCandidates": [
            {
                "timeSec": candidate["timeSec"],
                "sha256": candidate["sha256"],
                "score": candidate.get("score"),
                "excluded": candidate.get("excluded"),
                "exclusions": candidate.get("exclusions"),
                "measurements": candidate["measurements"],
            }
            for candidate in candidates
        ],
        "visualEvidence": visual_evidence,
        "anchorReceiptPath": str(receipt_path) if apply else None,
        "duplicateResult": "created" if apply else "proposed",
        "proposedMutations": (
            []
            if apply
            else [
                "persist canonical Reference Factory source",
                "persist eight receipt-linked frame derivatives",
                "persist immutable anchor-selection receipt",
            ]
        ),
    }
    if apply:
        _persist(
            db_path=db_path,
            source=canonical_source,
            metadata=metadata,
            result=result,
            candidates=candidates,
            role_map=role_map,
            derivatives=derivatives,
            receipt_path=receipt_path,
            implementation_fingerprint=implementation_fingerprint,
            now=now,
        )
    else:
        shutil.rmtree(destination_root, ignore_errors=True)
    return result


def select_anchor(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Hard-block unsafe frames, then apply the documented weighted score."""
    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        blockers = list(candidate.get("hardBlockers") or [])
        if blockers:
            candidate["excluded"] = True
            candidate["exclusions"] = blockers
            candidate["score"] = 0.0
            continue
        components = candidate["measurements"]
        score = (
            0.25 * float(components["sharpness"])
            + 0.20 * float(components["faceVisibility"])
            + 0.20 * float(components["bodyExtent"])
            + 0.15 * float(components["singlePersonLowOcclusion"])
            + 0.10 * float(components["overlayClear"])
            + 0.10 * float(components["poseRepresentativeness"])
        )
        candidate["excluded"] = False
        candidate["exclusions"] = []
        candidate["score"] = round(score, 6)
        eligible.append(candidate)
    if not eligible:
        raise ValueError(
            "no compatible reference anchor frame remained after hard blockers"
        )
    return sorted(
        eligible, key=lambda item: (-float(item["score"]), float(item["timeSec"]))
    )[0]


def _candidate_times(duration: float, cuts: list[float]) -> list[float]:
    end = max(0.0, duration - 0.05)
    values = {
        0.0,
        end,
        duration * 0.15,
        duration * 0.25,
        duration * 0.5,
        duration * 0.75,
        duration * 0.85,
    }
    for cut in cuts:
        if cut > 0:
            values.add(min(end, cut))
            values.add(min(end, cut + 0.08))
            values.add(max(0.0, cut - 0.08))
    return sorted(round(max(0.0, min(end, value)), 3) for value in values)


def _extract_and_measure(
    source: Path, frame_dir: Path, index: int, stamp: float, duration: float
) -> dict[str, Any]:
    path = frame_dir / f"candidate_{index:03d}_{stamp:08.3f}.png"
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-ss",
        f"{stamp:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not path.exists():
        raise RuntimeError(
            result.stderr.strip() or f"could not extract frame at {stamp}"
        )
    os.chmod(path, 0o600)
    pixels = _grayscale_pixels(path)
    mean = sum(pixels) / max(1, len(pixels))
    black_fraction = sum(value < 12 for value in pixels) / max(1, len(pixels))
    gradients = [abs(pixels[i] - pixels[i - 1]) for i in range(1, len(pixels))]
    sharpness = min(1.0, (sum(gradients) / max(1, len(gradients))) / 30.0)
    hard: list[str] = []
    if mean < 10 or black_fraction > 0.92:
        hard.append("black_frame")
    endpoint_penalty = (
        0.85 if stamp in {0.0, round(max(0.0, duration - 0.05), 3)} else 1.0
    )
    return {
        "timeSec": stamp,
        "path": str(path),
        "sha256": content_hash(path),
        "measurements": {
            "meanLuma": round(mean / 255.0, 6),
            "blackFraction": round(black_fraction, 6),
            "sharpness": round(sharpness, 6),
            "faceVisibility": 0.5,
            "faceEvidence": "unknown",
            "bodyExtent": 0.5,
            "bodyEvidence": "unknown",
            "principalPersonCount": None,
            "occlusion": "unknown",
            "singlePersonLowOcclusion": 0.5,
            "overlayClear": 0.5,
            "poseRepresentativeness": endpoint_penalty,
            "poseEvidence": "unknown",
            "framingCompatibility": "unknown",
        },
        "hardBlockers": hard,
    }


def _grayscale_pixels(path: Path) -> list[int]:
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        "scale=96:96,format=gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("could not compute deterministic frame pixels")
    return list(result.stdout)


def _enrich_visual_evidence(
    candidates: list[dict[str, Any]], frame_dir: Path
) -> dict[str, Any]:
    manifest = [
        {"identifier": index, "path": candidate["path"]}
        for index, candidate in enumerate(candidates)
    ]
    manifest_path = frame_dir / ".reference-frame-manifest.json"
    atomic_write_text(
        manifest_path, json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    apple = _apple_vision(manifest_path)
    media_pipe = _mediapipe(manifest_path)
    apple_frames = {
        int(item.get("identifier", -1)): item for item in apple.get("frames", [])
    }
    media_frames = {
        int(item.get("identifier", -1)): item for item in media_pipe.get("frames", [])
    }
    body_extents: list[float] = []
    for index, candidate in enumerate(candidates):
        frame = apple_frames.get(index)
        measurements = candidate["measurements"]
        if frame and frame.get("available") is True:
            faces = list(frame.get("faces") or [])
            bodies = list(frame.get("bodies") or [])
            face_area = max(
                (
                    float(face.get("width") or 0) * float(face.get("height") or 0)
                    for face in faces
                ),
                default=0.0,
            )
            body_extent, point_count = _body_extent(bodies)
            body_extents.append(body_extent)
            ocr = run_selected_ocr(
                Path(str(candidate["path"])), requested_engine="apple_vision"
            )
            text_chars = sum(
                len(str(item.get("ocrText") or "")) for item in ocr.get("boxes") or []
            )
            measurements.update(
                {
                    "faceVisibility": round(
                        min(1.0, face_area / 0.05) if face_area else 0.0, 6
                    ),
                    "faceEvidence": {
                        "provider": "apple_vision",
                        "count": len(faces),
                        "largestNormalizedArea": round(face_area, 6),
                    },
                    "bodyExtent": round(min(1.0, body_extent / 0.55), 6),
                    "bodyEvidence": {
                        "provider": "apple_vision",
                        "count": len(bodies),
                        "qualifiedPointCount": point_count,
                        "normalizedExtent": round(body_extent, 6),
                        "handCount": int(frame.get("handCount") or 0),
                    },
                    "principalPersonCount": max(len(bodies), len(faces)),
                    "occlusion": (
                        "low"
                        if point_count >= 8
                        else "possible"
                        if point_count >= 4 or faces
                        else "severe"
                    ),
                    "singlePersonLowOcclusion": (
                        1.0
                        if len(bodies) <= 1
                        and len(faces) <= 1
                        and (point_count >= 4 or faces)
                        else 0.0
                    ),
                    "overlayClear": round(max(0.0, 1.0 - min(1.0, text_chars / 80)), 6),
                    "overlayEvidence": {
                        "provider": "contentforge_apple_vision_ocr",
                        "engine": ocr.get("engine"),
                        "available": ocr.get("available"),
                        "recognizedCharacters": text_chars,
                    },
                    "framingCompatibility": (
                        "compatible"
                        if body_extent > 0.02 or face_area > 0.01
                        else "incompatible"
                    ),
                }
            )
            if len(bodies) > 1 or len(faces) > 1:
                candidate["hardBlockers"].append("multiple_principal_people")
            if not bodies and not faces:
                candidate["hardBlockers"].append("intended_subject_unresolved")
            if measurements["occlusion"] == "severe":
                candidate["hardBlockers"].append("severe_occlusion")
            if measurements["framingCompatibility"] == "incompatible":
                candidate["hardBlockers"].append("incompatible_framing")
        media = media_frames.get(index)
        if media and media.get("available") is True:
            measurements["mediaPipePlacement"] = {
                "verticalCoverage": media.get("verticalCoverage"),
                "sideCoverage": media.get("sideCoverage"),
            }
        else:
            measurements["mediaPipePlacement"] = {
                "available": False,
                "reason": (media_pipe.get("provenance") or {}).get("reason")
                or "measurement_unavailable",
            }
    if body_extents:
        ordered = sorted(body_extents)
        median_extent = ordered[len(ordered) // 2]
        for candidate in candidates:
            extent = float(
                (
                    (candidate["measurements"].get("bodyEvidence") or {}).get(
                        "normalizedExtent"
                    )
                )
                or 0
            )
            if extent > 0:
                candidate["measurements"]["poseRepresentativeness"] = round(
                    max(0.0, 1.0 - abs(extent - median_extent)), 6
                )
                candidate["measurements"]["poseEvidence"] = (
                    "apple_vision_body_extent_cohort_distance"
                )
    manifest_path.unlink(missing_ok=True)
    return {
        "appleVision": {
            "available": apple.get("available") is True,
            "reason": apple.get("reason"),
            "provider": apple.get("provider"),
            "requests": apple.get("requests"),
            "scriptSha256": content_hash(
                Path(__file__).with_name("reference_frame_vision.swift")
            ),
            "platform": platform.platform(),
        },
        "mediaPipe": media_pipe.get("provenance")
        or {"available": False, "reason": "placement_evidence_unavailable"},
    }


def _body_extent(bodies: list[dict[str, Any]]) -> tuple[float, int]:
    best_extent = 0.0
    best_count = 0
    for body in bodies:
        points = [
            item
            for item in body.get("points") or []
            if float(item.get("confidence") or 0) >= 0.35
        ]
        if len(points) < 2:
            continue
        xs = [float(point["x"]) for point in points]
        ys = [float(point["y"]) for point in points]
        extent = max(0.0, max(xs) - min(xs)) * max(0.0, max(ys) - min(ys))
        if extent > best_extent:
            best_extent, best_count = extent, len(points)
    return best_extent, best_count


def _apple_vision(manifest_path: Path) -> dict[str, Any]:
    if platform.system() != "Darwin" or not shutil.which("swift"):
        return {"available": False, "reason": "apple_vision_requires_macos"}
    script = Path(__file__).with_name("reference_frame_vision.swift")
    try:
        result = subprocess.run(
            [shutil.which("swift") or "swift", str(script), str(manifest_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": type(exc).__name__}
    if result.returncode != 0:
        return {
            "available": False,
            "reason": "apple_vision_runtime_failed",
            "error": result.stderr[-500:],
        }
    return payload


def _mediapipe(manifest_path: Path) -> dict[str, Any]:
    uv = shutil.which("uv")
    if not uv:
        return {"available": False, "provenance": {"reason": "uv_missing"}}
    source_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            uv,
            "run",
            "--package",
            "reel-factory",
            "python",
            "-m",
            "reel_factory.reference_frame_placement",
            "--manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        cwd=source_root,
    )
    if result.returncode != 0:
        return {
            "available": False,
            "provenance": {"reason": "mediapipe_subprocess_failed"},
        }
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "available": False,
            "provenance": {"reason": "mediapipe_output_invalid"},
        }


def _role_map(
    candidates: list[dict[str, Any]], selected: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    clean = [item for item in candidates if not item.get("hardBlockers")] or candidates
    first_clean = min(clean, key=lambda item: float(item["timeSec"]))
    last_clean = max(clean, key=lambda item: float(item["timeSec"]))
    midpoint = min(
        clean,
        key=lambda item: abs(
            float(item["timeSec"]) - float(candidates[-1]["timeSec"]) / 2
        ),
    )
    best_face = max(
        clean,
        key=lambda item: (
            float(item["measurements"]["faceVisibility"]),
            -float(item["timeSec"]),
        ),
    )
    best_body = max(
        clean,
        key=lambda item: (
            float(item["measurements"]["bodyExtent"]),
            -float(item["timeSec"]),
        ),
    )
    return {
        "literal_first": candidates[0],
        "literal_final": candidates[-1],
        "first_clean": first_clean,
        "last_clean": last_clean,
        "best_anchor": selected,
        "best_face_visible": best_face,
        "best_body_visible": best_body,
        "representative_midpoint": midpoint,
    }


def _materialize_roles(
    frame_dir: Path, role_map: dict[str, dict[str, Any]]
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for role, candidate in role_map.items():
        path = frame_dir / f"{role}.png"
        shutil.copy2(Path(candidate["path"]), path)
        os.chmod(path, 0o600)
        paths[role] = path
    return paths


def _contact_sheet(frame_dir: Path, output: Path) -> Path | None:
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-pattern_type",
        "glob",
        "-i",
        str(frame_dir / "candidate_*.png"),
        "-vf",
        "scale=270:-1,tile=4x2",
        "-frames:v",
        "1",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not output.exists():
        return None
    os.chmod(output, 0o600)
    return output


def _find_existing(
    db_path: Path,
    platform: str,
    native_id: str,
    source_sha: str,
    *,
    writable: bool,
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    if writable:
        conn = connect(db_path)
    else:
        conn = connect_sqlite(db_path, readonly=True, wal=False)
        conn.execute("PRAGMA query_only = ON")
    try:
        try:
            row = conn.execute(
                "SELECT * FROM source_files WHERE source_platform = ? AND native_media_id = ?",
                (platform, native_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        reason = "reused_platform_media_id"
        if row is None:
            row = conn.execute(
                "SELECT * FROM source_files WHERE content_hash = ? ORDER BY created_at LIMIT 1",
                (source_sha,),
            ).fetchone()
            reason = "reused_downloaded_sha"
        if row is None:
            return None
        receipt = conn.execute(
            "SELECT receipt_path FROM reference_anchor_receipts WHERE reference_id = ? ORDER BY created_at DESC LIMIT 1",
            (row["reference_id"],),
        ).fetchone()
        return {
            **dict(row),
            "receipt_path": receipt["receipt_path"] if receipt else None,
            "duplicateReason": reason,
        }
    finally:
        conn.close()


def _load_receipt(existing: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    receipt_path = Path(str(existing.get("receipt_path") or ""))
    payload: dict[str, Any] = {}
    if receipt_path.is_file():
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    return {
        "schema": SCHEMA,
        "referenceId": existing["reference_id"],
        "apply": apply,
        "source": {
            "path": existing["path"],
            "sha256": existing["content_hash"],
            "platform": existing.get("source_platform"),
            "nativeMediaId": existing.get("native_media_id"),
            "originalUrl": existing.get("original_url"),
            "canonicalUrl": existing.get("canonical_url"),
        },
        "selectedAnchor": payload.get("selectedFrame"),
        "anchorReceiptPath": str(receipt_path) if receipt_path.is_file() else None,
        "frameDerivatives": {},
    }


def _persist(
    *,
    db_path: Path,
    source: Path,
    metadata: dict[str, Any],
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    role_map: dict[str, dict[str, Any]],
    derivatives: dict[str, Path],
    receipt_path: Path,
    implementation_fingerprint: str,
    now: str,
) -> None:
    conn = connect(db_path)
    reference_id = result["referenceId"]
    try:
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id,path,account,file_name,extension,kind,size_bytes,mtime,
              path_hash,content_hash,source_views,source_likes,source_comments,
              source_posted_at,source_platform,native_media_id,original_url,
              canonical_url,extractor,extractor_version,intake_metadata_json,
              intake_receipt_path,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                reference_id,
                str(source),
                metadata.get("uploader"),
                source.name,
                source.suffix.lower(),
                "video",
                source.stat().st_size,
                datetime.fromtimestamp(source.stat().st_mtime, UTC).isoformat(),
                hashlib.sha256(str(source).encode()).hexdigest(),
                result["source"]["sha256"],
                metadata.get("view_count"),
                metadata.get("like_count"),
                metadata.get("comment_count"),
                metadata.get("timestamp") or metadata.get("upload_date"),
                result["source"]["platform"],
                result["source"]["nativeMediaId"],
                metadata.get("originalUrl"),
                metadata.get("canonicalUrl"),
                metadata.get("extractor"),
                metadata.get("extractorVersion"),
                json.dumps(_metadata_allowlist(metadata), sort_keys=True),
                str(receipt_path),
                now,
                now,
            ),
        )
        selected_sample_id = ""
        for role in FRAME_ROLES:
            candidate = role_map[role]
            sample_id = stable_id("frame_sample", reference_id, role)
            if role == "best_anchor":
                selected_sample_id = sample_id
            conn.execute(
                """
                INSERT INTO frame_samples
                  (id,reference_id,time_sec,role,frame_path,width,height,created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    sample_id,
                    reference_id,
                    candidate["timeSec"],
                    role,
                    str(derivatives[role]),
                    result["media"].get("width"),
                    result["media"].get("height"),
                    now,
                ),
            )
        selected = result["selectedAnchor"]
        conn.execute(
            """
            INSERT INTO reference_anchor_receipts
              (id,reference_id,source_media_sha256,selected_frame_sample_id,
               selected_frame_sha256,selected_time_sec,score,
               candidate_measurements_json,toolchain_json,
               implementation_fingerprint,receipt_path,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                stable_id("anchor_receipt", reference_id, implementation_fingerprint),
                reference_id,
                result["source"]["sha256"],
                selected_sample_id,
                selected["sha256"],
                selected["timeSec"],
                selected["score"],
                json.dumps(candidates, sort_keys=True),
                json.dumps(
                    {"ffmpeg": _version("ffmpeg"), "ffprobe": _version("ffprobe")}
                ),
                implementation_fingerprint,
                str(receipt_path),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _metadata_allowlist(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "platform",
        "nativeMediaId",
        "originalUrl",
        "canonicalUrl",
        "extractor",
        "extractorVersion",
        "uploader",
        "uploader_id",
        "description",
        "upload_date",
        "timestamp",
        "view_count",
        "like_count",
        "comment_count",
        "repost_count",
        "duration",
        "width",
        "height",
        "fps",
        "vcodec",
        "acodec",
        "downloadedSha256",
        "redirectSummary",
        "cookieFallbackUsed",
        "track",
        "track_id",
        "artist",
        "music_id",
        "original_audio",
        "caption",
        "declaredTalking",
    }
    return {key: metadata[key] for key in sorted(keys) if metadata.get(key) is not None}


def _safe_segment(value: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "._-")[:100]
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("reference platform/media identity is unsafe")
    return cleaned


def _version(name: str) -> str | None:
    executable = shutil.which(name)
    if not executable:
        return None
    result = subprocess.run([executable, "-version"], capture_output=True, text=True)
    return (
        (result.stdout or result.stderr).splitlines()[0]
        if result.returncode == 0
        else None
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    print(
        json.dumps(
            analyze_url_reference(
                args.source,
                metadata=metadata,
                data_root=args.data_root,
                db_path=args.db,
                apply=args.apply,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
