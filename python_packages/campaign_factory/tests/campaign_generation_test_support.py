from __future__ import annotations

import json
from pathlib import Path


class FakeVariationPipeline:
    def __init__(self, master_asset, *, accounts, platform, output_dir):
        self.master_asset = Path(master_asset)
        self.accounts = accounts
        self.output_dir = Path(output_dir)

    def generate_assignment_manifest(
        self, *, preset_name, campaign_slug, master_asset_id, write_manifest
    ):
        assert write_manifest is False
        assignments = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for account in self.accounts:
            variant_path = (
                self.output_dir
                / f"{master_asset_id}_{account['account_id']}_variant.mp4"
            )
            variant_path.write_bytes(b"variant")
            assignments.append(
                {
                    "account_id": account["account_id"],
                    "instagram_account_id": account.get("instagram_account_id"),
                    "persona": account.get("persona"),
                    "variant_asset_id": f"{master_asset_id}_{account['account_id']}",
                    "variant_path": str(variant_path),
                    "parent_master_asset_id": master_asset_id,
                    "preset_name": preset_name,
                    "distinctness_scores": {
                        "master_ssim": 0.99,
                        "sibling_max_ssim": 0.99,
                        "threshold": 0.85,
                    },
                    "lineage": {
                        "mode": "zero_cost_variation",
                        "paid_generation": False,
                        "micro_enabled": False,
                    },
                }
            )
        return {
            "schema": "campaign_factory.variant_assignment.v1",
            "campaign_slug": campaign_slug,
            "master_asset_id": master_asset_id,
            "master_asset_path": str(self.master_asset),
            "platform": "reels",
            "generated_at": "2026-06-18T00:00:00Z",
            "variation_enabled": True,
            "assignments": assignments,
        }

    def manifest_path(self, master_asset_id):
        return self.output_dir / f"{master_asset_id}.variant_assignment.v1.json"


def fake_static_mp4_render(
    still_path: Path, output_path: Path, *, dry_run: bool = False
) -> dict:
    return {
        "schema": "reel_factory.static_mp4_render.v1",
        "animationMode": "static_image_mp4",
        "lockedStatic": True,
        "paidGeneration": False,
        "estimatedCostUsd": 0,
        "stillPath": str(still_path),
        "outputPath": str(output_path),
        "durationSeconds": 5.0,
        "audioBurned": False,
        "audioIntentPath": str(
            output_path.with_suffix(output_path.suffix + ".audio_intent.json")
        ),
        "quality": {
            "status": "planned" if dry_run else "passed",
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "durationSeconds": 5.0,
            "warnings": [],
        },
        "ffmpegCommand": ["ffmpeg", "-loop", "1", str(still_path), str(output_path)],
        "humanReviewRequired": True,
        "dryRun": dry_run,
    }


def write_fake_static_mp4_outputs(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"locked-static-mp4")
    output_path.with_suffix(output_path.suffix + ".audio_intent.json").write_text(
        json.dumps(
            {
                "schema": "pipeline.audio_intent.v1",
                "mode": "platform_auto_music",
                "required": True,
                "status": "recommended",
                "platform": "instagram_reels",
                "recommendations": [],
                "gates": {
                    "allow_draft_export": True,
                    "allow_preview_schedule": False,
                    "allow_live_schedule": False,
                    "allow_publish": False,
                },
                "notes": "native audio unresolved",
                "audio_selection": None,
                "createdAt": 1,
            }
        ),
        encoding="utf-8",
    )


def fake_front_generation_result(
    args: list[str], *, output_dir: Path | None = None
) -> dict:
    mode = args[0]
    if mode.startswith("reference-image"):
        still = output_dir / "original.png" if output_dir else None
        if still:
            still.write_bytes(b"original-still")
        return {
            "ok": True,
            "dry_run": mode.endswith("dry-run"),
            "workflow": "higgsfield_direct_reference_image",
            "commands": [["higgsfield", "generate", "create", "text2image_soul_v2"]],
            "lineage_path": "/tmp/direct_reference_lineage.json",
            "lineage": {
                "source": {"soulId": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"},
                "generation": {
                    "capturedHiggsfieldPrompt": "A mirror selfie in a fitted black top.",
                    "imageJobId": "image_original_1",
                },
                "assets": {
                    "localPaths": {"image": str(still)} if still else {},
                },
                "review": {
                    "generatedImageQc": {
                        "status": "passed",
                        "results": (
                            [{"path": str(still), "postable": True}] if still else []
                        ),
                    }
                },
            },
        }
    if mode.startswith("image"):
        still = output_dir / "sexy.png" if output_dir else None
        if still:
            still.write_bytes(b"sexy-still")
        return {
            "ok": True,
            "dry_run": mode.endswith("dry-run"),
            "workflow": "higgsfield_soul_v2_image_only",
            "commands": [["higgsfield", "generate", "create", "text2image_soul_v2"]],
            "lineage_path": "/tmp/sexy_variant_lineage.json",
            "lineage": {
                "source": {"soulId": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"},
                "generation": {
                    "prompts": {
                        "higgsfieldGridPrompt": "A mirror selfie in a fitted black top, 19 years old."
                    },
                    "imageJobId": "image_sexy_1",
                },
                "assets": {
                    "localPaths": {"image": str(still)} if still else {},
                },
                "review": {
                    "generatedImageQc": {
                        "status": "passed",
                        "results": (
                            [{"path": str(still), "postable": True}] if still else []
                        ),
                    }
                },
            },
        }
    if mode.startswith("video"):
        return {
            "ok": True,
            "dry_run": mode.endswith("dry-run"),
            "workflow": "kling3_0_video_from_accepted_still",
            "commands": [["higgsfield", "generate", "create", "kling3_0"]],
            "lineage_path": "/tmp/generated_asset_lineage.json",
        }
    raise AssertionError(f"unexpected generate_assets mode: {mode}")
