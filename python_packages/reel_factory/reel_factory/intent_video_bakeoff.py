"""Like-for-like visual bakeoff planning for explicit video candidates.

This is a comparison manifest, not a provider router. It binds each candidate
to the same approved input files and leaves selection to the operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text
from .higgsfield_production import (
    REVIEW_FIELDS,
    discover_higgsfield_production_capabilities,
    higgsfield_candidate_catalog,
)
from .higgsfield_production import (
    main as higgsfield_main,
)
from .video_provider_models import video_model_catalog

SCHEMA = "reel_factory.intent_video_bakeoff_manifest.v1"
_EXPECTED_SAMPLE_COUNTS = {
    "passiveSelfie": 3,
    "motionCopy": 2,
    "talkingSelfie": 2,
    "talkingMotionCopy": 1,
}


def build_intent_video_bakeoff_manifest(
    spec: dict[str, Any],
    *,
    review_root: Path,
    higgsfield_capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic, review-only matrix from approved local inputs."""

    samples: dict[str, list[dict[str, Any]]] = {}
    for cohort, expected in _EXPECTED_SAMPLE_COUNTS.items():
        rows = spec.get(cohort)
        if not isinstance(rows, list) or len(rows) != expected:
            raise ValueError(f"{cohort} requires exactly {expected} approved samples")
        samples[cohort] = [
            _normalize_sample(cohort, row, index=index)
            for index, row in enumerate(rows, start=1)
        ]

    candidates = _candidate_matrix(higgsfield_capabilities)
    outputs: list[dict[str, Any]] = []
    for cohort, rows in samples.items():
        for sample in rows:
            for candidate in candidates[cohort]:
                outputs.append(
                    {
                        "outputId": (
                            f"{sample['sampleId']}__{candidate['candidateId']}"
                        ),
                        "intent": cohort,
                        "sampleId": sample["sampleId"],
                        "inputFingerprint": sample["inputFingerprint"],
                        "provider": candidate["provider"],
                        "candidateId": candidate["candidateId"],
                        "pipeline": candidate["pipeline"],
                        "status": (
                            "planned" if candidate["available"] else "unavailable"
                        ),
                        "unavailableReason": candidate.get("unavailableReason"),
                        "outputPath": None,
                        "outputSha256": None,
                        "generationId": None,
                        "review": {field: None for field in REVIEW_FIELDS},
                    }
                )

    root = review_root.expanduser().resolve()
    return {
        "schema": SCHEMA,
        "createdAt": datetime.now(tz=UTC).isoformat(),
        "reviewFolder": str(root),
        "operatorVisualSelectionRequired": True,
        "productionDefaultsSelected": False,
        "sameInputRequiredWithinSample": True,
        "samples": samples,
        "candidates": candidates,
        "outputs": outputs,
        "paidExecution": {
            "mode": "best_motion",
            "confirmed": False,
            "higgsfieldCreditCap": None,
            "wavespeedDollarCap": None,
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
        "runtimePromotionAllowed": False,
    }


def write_intent_video_bakeoff_manifest(
    spec_path: Path,
    *,
    review_root: Path,
    output_path: Path,
    higgsfield_capabilities: dict[str, Any],
) -> dict[str, Any]:
    spec_file = spec_path.expanduser().resolve()
    if not spec_file.is_file():
        raise FileNotFoundError(f"bakeoff spec is missing: {spec_file}")
    try:
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("bakeoff spec is not valid JSON") from exc
    if not isinstance(spec, dict):
        raise ValueError("bakeoff spec must be a JSON object")
    manifest = build_intent_video_bakeoff_manifest(
        spec,
        review_root=review_root,
        higgsfield_capabilities=higgsfield_capabilities,
    )
    target = output_path.expanduser().resolve()
    root = review_root.expanduser().resolve()
    if target.parent != root:
        raise ValueError("bakeoff manifest must be written directly in review folder")
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        target,
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _candidate_matrix(
    higgsfield_capabilities: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    hf = higgsfield_candidate_catalog(higgsfield_capabilities)

    def hf_candidate(
        candidate_id: str,
        recipe_id: str,
        *,
        pipeline: list[str] | None = None,
    ) -> dict[str, Any]:
        candidate = hf[recipe_id]
        return {
            "candidateId": candidate_id,
            "provider": "higgsfield",
            "pipeline": pipeline or [candidate_id],
            "available": candidate.status == "available",
            "unavailableReason": candidate.unavailable_reason,
            "actualTool": candidate.actual_tool,
            "actualJobType": candidate.exposed_job_type,
        }

    def wavespeed(candidate_id: str, *pipeline: str) -> dict[str, Any]:
        return {
            "candidateId": candidate_id,
            "provider": "wavespeed",
            "pipeline": list(pipeline or (candidate_id,)),
            "available": True,
            "unavailableReason": None,
        }

    return {
        "passiveSelfie": [
            hf_candidate("higgsfield_kling3_i2v", "higgsfield_passive_selfie"),
            hf_candidate("higgsfield_seedance2_i2v", "higgsfield_passive_selfie"),
            wavespeed("wavespeed_kling_o3_pro_i2v"),
            wavespeed("wavespeed_vidu_q3_i2v_pro"),
        ],
        "motionCopy": [
            hf_candidate(
                "higgsfield_kling3_motion_control",
                "higgsfield_motion_copy_animate",
            ),
            hf_candidate(
                "higgsfield_replace",
                "higgsfield_motion_copy_replace",
            ),
            wavespeed("wavespeed_kling_v3_pro_motion_control"),
        ],
        "talkingSelfie": [
            hf_candidate("higgsfield_speak", "higgsfield_talking_speak"),
            hf_candidate("higgsfield_veo31_talking", "higgsfield_talking_veo"),
            wavespeed("wavespeed_infinitetalk"),
            wavespeed("wavespeed_longcat_avatar15"),
        ],
        "talkingMotionCopy": [
            hf_candidate(
                "higgsfield_motion_transfer_plus_lipsync",
                "higgsfield_talking_motion_copy",
                pipeline=[
                    "higgsfield_kling3_motion_control",
                    "higgsfield_lipsync",
                ],
            ),
            wavespeed(
                "wavespeed_motion_control_plus_sync2",
                "wavespeed_kling_v3_pro_motion_control",
                "wavespeed_sync_lipsync2_pro",
            ),
            wavespeed(
                "wavespeed_motion_control_plus_sync3",
                "wavespeed_kling_v3_pro_motion_control",
                "wavespeed_sync_lipsync3",
            ),
        ],
    }


def _normalize_sample(
    cohort: str,
    raw: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{cohort} sample {index} must be an object")
    creator = _required_text(raw, "creator", cohort, index)
    soul_id = _required_text(raw, "soulId", cohort, index)
    source_approval = _required_text(raw, "sourceApproval", cohort, index)
    source = _asset_identity(raw.get("sourceImage"), "source image")
    normalized: dict[str, Any] = {
        "sampleId": f"{cohort}_{index}",
        "creator": creator,
        "soulId": soul_id,
        "sourceApproval": source_approval,
        "sourceImage": source,
        "drivingVideo": None,
        "drivingApproval": None,
        "speechAudio": None,
        "speechApproval": None,
        "script": None,
    }
    if cohort in {"motionCopy", "talkingMotionCopy"}:
        normalized["drivingVideo"] = _asset_identity(
            raw.get("drivingVideo"), "driving video"
        )
        normalized["drivingApproval"] = _required_text(
            raw, "drivingApproval", cohort, index
        )
    if cohort in {"talkingSelfie", "talkingMotionCopy"}:
        normalized["speechAudio"] = _asset_identity(
            raw.get("speechAudio"), "speech audio"
        )
        normalized["speechApproval"] = _required_text(
            raw, "speechApproval", cohort, index
        )
        normalized["script"] = _required_text(raw, "script", cohort, index)
    normalized["inputFingerprint"] = _fingerprint(normalized)
    return normalized


def _required_text(
    row: dict[str, Any],
    key: str,
    cohort: str,
    index: int,
) -> str:
    value = " ".join(str(row.get(key) or "").split())
    if not value:
        raise ValueError(f"{cohort} sample {index} requires {key}")
    return value


def _asset_identity(value: Any, label: str) -> dict[str, Any]:
    path = Path(str(value or "")).expanduser()
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is missing: {resolved}")
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or inspect the explicit Higgsfield/WaveSpeed visual bakeoff; "
            "never schedules or publishes."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--spec", type=Path, required=True)
    manifest.add_argument("--review-folder", type=Path, required=True)
    manifest.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    if arguments[:1] in (["plan"], ["run"]):
        return higgsfield_main(arguments)
    try:
        args = _parser().parse_args(arguments)
        capabilities = discover_higgsfield_production_capabilities()
        if args.command == "capabilities":
            payload = {
                "schema": "reel_factory.intent_video_bakeoff_capabilities.v1",
                "higgsfield": capabilities,
                "videoModels": video_model_catalog(),
                "candidates": _candidate_matrix(capabilities),
            }
        else:
            payload = write_intent_video_bakeoff_manifest(
                args.spec,
                review_root=args.review_folder,
                output_path=args.out,
                higgsfield_capabilities=capabilities,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
