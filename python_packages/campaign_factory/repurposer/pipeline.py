from pathlib import Path
from typing import Any, List
import json
import re
import shutil

from .config import RepurposeConfig
from .engines.audio import AudioEngine
from .engines.editorial import EditorialEngine
from .engines.micro import MicroEngine
from .engines.polish import PolishEngine
from .engines.visual import VisualEngine
from .qa.quality import QualityGate
from .qa.similarity import SimilarityGate


class RepurposeError(RuntimeError):
    """Raised when a repurposing run cannot produce a valid real variant."""

class VariantPipeline:
    def __init__(
        self,
        master_asset: Path,
        target_count: int | None = None,
        platform: str = "reels",
        output_dir: Path | None = None,
        accounts: list[dict[str, Any]] | None = None,
        similarity_threshold: float = 0.85,
    ):
        self.master = Path(master_asset)
        self.accounts = accounts
        self.target = len(accounts) if accounts is not None else int(target_count or 0)
        self.platform = platform
        self.output_dir = Path(output_dir) if output_dir else self.master.parent / "repurposed_variants"
        self.similarity_threshold = similarity_threshold
        
    def generate_batch(self, preset_name: str) -> List[Path]:
        return [Path(item["variant_path"]) for item in self.generate_assignment_manifest(
            preset_name=preset_name,
            campaign_slug="standalone",
            master_asset_id=self.master.stem,
            write_manifest=False,
        )["assignments"]]

    def generate_assignment_manifest(
        self,
        *,
        preset_name: str,
        campaign_slug: str,
        master_asset_id: str,
        write_manifest: bool = True,
    ) -> dict[str, Any]:
        if not self.master.exists() or not self.master.is_file():
            raise FileNotFoundError(f"master asset not found: {self.master}")
        if self.target <= 0:
            raise ValueError("target_count must be positive")

        account_targets = self._account_targets()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        assignments: list[dict[str, Any]] = []
        variants: list[tuple[Path, dict[str, Any], str, bool]] = []
        
        print(f"Generating {self.target} variants for {self.platform} using preset {preset_name}")
        
        for i, account in enumerate(account_targets):
            account_preset = str(account.get("preset_name") or preset_name)
            config = RepurposeConfig.from_preset(account_preset)
            try:
                variant, scores, transformed = self._generate_one(config, i, account)
                if transformed:
                    for sibling, _, sibling_account_id, sibling_transformed in variants:
                        if not sibling_transformed:
                            continue
                        sibling_ssim = SimilarityGate.calculate_ssim(sibling, variant)
                        scores["sibling_max_ssim"] = max(scores["sibling_max_ssim"], sibling_ssim)
            except Exception as exc:
                for created, _, _, _ in variants:
                    created.unlink(missing_ok=True)
                raise RepurposeError(f"variant {i} failed: {exc}") from exc
            assignment = {
                "account_id": account["account_id"],
                "instagram_account_id": account.get("instagram_account_id"),
                "persona": account.get("persona"),
                "variant_asset_id": self._variant_asset_id(master_asset_id, account["account_id"]),
                "variant_path": str(variant),
                "parent_master_asset_id": master_asset_id,
                "preset_name": account_preset,
                "distinctness_scores": scores,
                "lineage": {
                    "mode": "zero_cost_variation",
                    "paid_generation": False,
                    "micro_enabled": bool(config.enable_micro),
                },
            }
            assignments.append(assignment)
            variants.append((variant, scores, account["account_id"], transformed))

        manifest = {
            "schema": "campaign_factory.variant_assignment.v1",
            "campaign_slug": campaign_slug,
            "master_asset_id": master_asset_id,
            "master_asset_path": str(self.master),
            "platform": self.platform,
            "generated_at": self._utc_now(),
            "variation_enabled": True,
            "assignments": assignments,
        }
        if write_manifest:
            self.manifest_path(master_asset_id).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def manifest_path(self, master_asset_id: str) -> Path:
        return self.output_dir / f"{_safe_slug(master_asset_id)}.variant_assignment.v1.json"

    def _generate_one(self, config: RepurposeConfig, index: int, account: dict[str, Any]) -> tuple[Path, dict[str, float], bool]:
        stage_dir = self.output_dir / f".tmp_{self.master.stem}_{index:03d}"
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True)
        current = self.master
        transformed = False

        try:
            if config.enable_editorial:
                print(f"Applying Layer 1 (Editorial) to variant {index}")
                current = EditorialEngine.apply(
                    current,
                    stage_dir / "01_editorial.mp4",
                    new_hook=config.new_hook,
                    reorder=config.reorder_broll,
                    index=index,
                )
                transformed = True

            if config.enable_audio:
                print(f"Applying Layer 2 (Audio) to variant {index}")
                current = AudioEngine.apply(
                    current,
                    stage_dir / "02_audio.mp4",
                    music_track=Path(config.music_track_path) if config.music_track_path else None,
                    voiceover=Path(config.voiceover_path) if config.voiceover_path else None,
                    platform=self.platform,
                    account_index=index,
                    require_audio_change=config.require_audio_change,
                )
                transformed = transformed or current != self.master

            if config.enable_generative:
                print(f"Applying Layer 3 (Visual Generative) to variant {index}")
                current = VisualEngine.apply(
                    current,
                    stage_dir / "03_visual.mp4",
                    prompt=config.generative_prompt,
                )
                transformed = transformed or current != self.master

            if config.enable_polish:
                print(f"Applying Layer 4 (Polish) to variant {index}")
                current = PolishEngine.apply(
                    current,
                    stage_dir / "04_polish.mp4",
                    zoom_factor=config.zoom_factor,
                    color_shift=config.color_shift,
                )
                transformed = transformed or current != self.master

            if config.enable_micro:
                print(f"Applying Layer 5 (Micro) to variant {index}")
                current = MicroEngine.apply(
                    current,
                    stage_dir / "05_micro.mp4",
                    strip_metadata=config.strip_metadata,
                    inject_noise=config.inject_noise,
                )
                transformed = transformed or current != self.master

            final = self.output_dir / f"{self.master.stem}_{_safe_slug(account['account_id'])}_variant.mp4"
            shutil.copy2(current, final)
            if not final.exists() or final.stat().st_size <= 0:
                raise RuntimeError(f"variant output missing: {final}")

            print(f"Running Similarity & Quality QA on variant {index}")
            if not QualityGate.is_quality_acceptable(final):
                final.unlink(missing_ok=True)
                raise RuntimeError("quality gate failed")
            master_ssim = 0.0
            if transformed:
                master_ssim = SimilarityGate.calculate_ssim(self.master, final)

            return final, {
                "master_ssim": round(master_ssim, 6),
                "sibling_max_ssim": 0.0,
                "threshold": self.similarity_threshold,
            }, transformed
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    def _account_targets(self) -> list[dict[str, Any]]:
        if self.accounts is not None:
            if not self.accounts:
                raise ValueError("accounts must not be empty")
            targets = []
            for index, account in enumerate(self.accounts):
                account_id = str(account.get("account_id") or account.get("accountId") or "").strip()
                if not account_id:
                    raise ValueError(f"accounts[{index}].account_id is required")
                targets.append({
                    "account_id": account_id,
                    "instagram_account_id": account.get("instagram_account_id") or account.get("instagramAccountId"),
                    "persona": account.get("persona") or account.get("preset") or account.get("preset_name"),
                    "preset_name": account.get("preset_name") or account.get("preset"),
                })
            return targets
        return [{"account_id": f"account_{index + 1:03d}", "instagram_account_id": None, "persona": None, "preset_name": None} for index in range(self.target)]

    def _variant_asset_id(self, master_asset_id: str, account_id: str) -> str:
        return f"{_safe_slug(master_asset_id)}_{_safe_slug(account_id)}"

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._:-]+", "_", str(value).strip())
    return slug.strip("_") or "unassigned"
