from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable


class FinishedVideoRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Any,
        *,
        slugify: Callable[[str], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Any], str],
        probe_video_shape: Callable[[Any], dict[str, Any]],
        json_load: Callable[[Any, Any], Any],
        utc_now: Callable[[], str],
        make_batch: Callable[..., dict[str, Any]],
        creative_plan: Callable[[str], dict[str, Any]],
        load_source_lineage: Callable[[Path | None], dict[str, Any]],
        record_creative_plan_event: Callable[..., None],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._slugify = slugify
        self._media_type_for_path = media_type_for_path
        self._sha256_file = sha256_file
        self._probe_video_shape = probe_video_shape
        self._json_load = json_load
        self._utc_now = utc_now
        self._make_batch = make_batch
        self._creative_plan = creative_plan
        self._load_source_lineage = load_source_lineage
        self._record_creative_plan_event = record_creative_plan_event

    def finished_video_hooks(self, format_type: str, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        pools = {
            "mirror_selfie": [
                "he thinks this was for him",
                "outfit said enough",
                "not sending this twice",
                "this one stays in drafts",
                "he saw it and folded",
            ],
            "selfie_video": [
                "say less",
                "this is your sign",
                "he knows exactly why",
                "not explaining this one",
                "too calm for what just happened",
            ],
            "pov": [
                "pov: he thought you were joking",
                "pov: this is where he folded",
                "pov: you already know",
                "pov: the part he replays",
                "pov: it was never casual",
            ],
            "spicy_lifestyle": [
                "soft life, hard launch",
                "this view did not need a caption",
                "some days explain themselves",
                "casual, allegedly",
                "he would have stayed too",
            ],
        }
        fallback = pools["selfie_video"]
        candidates = pools.get(format_type, fallback)
        hooks = []
        for idx in range(max(1, count)):
            text = candidates[idx % len(candidates)]
            hooks.append({
                "text": text,
                "referenceClusterKey": pattern["clusterKey"],
                "referenceLabel": pattern["label"],
                "hookType": "finished_video_native_hook",
                "captionArchetype": f"{format_type}_native",
                "audioRecommendations": pattern.get("audioRecommendations") or {},
                "formulaIndex": idx % len(candidates),
                "candidateKind": "finished_video_caption",
                "source": "campaign_factory_finished_video",
                "formatType": format_type,
            })
        return hooks

    def intake_finished_video(
        self,
        *,
        input_path: Path,
        model_slug: str,
        platform: str = "instagram",
        goal: str = "reach",
        reference_pattern: str | None = "auto",
        campaign_slug: str | None = None,
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        variant_count: int = 10,
        workers: int = 3,
        recipes: list[str] | None = None,
        creative_plan: str | None = None,
        style_lane: str | None = None,
        source_lineage_path: Path | None = None,
    ) -> dict[str, Any]:
        source = Path(input_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"finished video not found: {source}")
        media_type = self._media_type_for_path(source)
        if media_type != "video":
            raise ValueError("finished-video intake requires a video file")
        campaign = self._slugify(campaign_slug or f"finished_{source.stem}")
        digest = self._sha256_file(source)
        source_probe = self._probe_video_shape(source)
        source_preflight = self.finished_video_preflight(source_probe)
        intake_dir = self.settings.campaigns_dir / "_finished_video_intake" / f"{campaign}_{digest[:10]}"
        intake_dir.mkdir(parents=True, exist_ok=True)
        staged = intake_dir / f"{self._slugify(source.stem)}_{digest[:10]}{source.suffix.lower()}"
        if not staged.exists():
            shutil.copy2(source, staged)
        style_lane_format = self.finished_video_style_lane_format(style_lane)
        format_type = style_lane_format or self.classify_finished_video_format(source)
        creative_plan_payload = self._creative_plan(creative_plan) if creative_plan else None
        creative_plan_id = creative_plan_payload["id"] if creative_plan_payload else None
        source_lineage = self._load_source_lineage(source_lineage_path)
        generation = source_lineage.get("generation") if isinstance(source_lineage.get("generation"), dict) else {}
        source_meta = source_lineage.get("source") if isinstance(source_lineage.get("source"), dict) else {}
        if not style_lane_format and source_meta.get("formatType"):
            format_type = str(source_meta["formatType"])
        generated_lineage = source_lineage if source_lineage.get("schema") == "campaign_factory.generated_asset_lineage.v1" else {
            "schema": "campaign_factory.generated_asset_lineage.v1",
            "pipelineTraceId": f"trace_finished_video_{digest[:16]}",
            "source": {
                "referenceId": None,
                "patternCardId": None,
                "promptId": None,
                "formatType": format_type,
                "referencePattern": reference_pattern or "auto",
            },
            "generation": {
                "tool": "manual_finished_video",
                "modelProfile": model_slug,
                "assetPath": str(source),
            },
            "review": {
                "humanReviewRequired": True,
                "status": "draft",
            },
            "quality": {
                "copyRisk": "unknown",
            },
        }
        generated_lineage.setdefault("source", {}).setdefault("formatType", format_type)
        generated_lineage.setdefault("generation", {}).setdefault("assetPath", str(source))
        generated_lineage.setdefault("generation", {}).setdefault("modelProfile", model_slug)
        generated_lineage.setdefault("review", {}).setdefault("humanReviewRequired", True)
        generated_lineage.setdefault("review", {}).setdefault("status", "draft")
        source_prompt = json.dumps(
            {
                "schema": "campaign_factory.finished_video_intake.v1",
                "creativePlanId": creative_plan_id,
                "creativePlanName": creative_plan_payload["name"] if creative_plan_payload else None,
                "styleLane": style_lane or format_type,
                "inputPath": str(source),
                "stagedPath": str(staged),
                "platform": platform,
                "goal": goal,
                "referencePattern": reference_pattern or source_meta.get("referencePattern") or "auto",
                "patternCardId": source_meta.get("patternCardId"),
                "promptId": source_meta.get("promptId"),
                "generationTool": generation.get("tool"),
                "modelProfile": generation.get("modelProfile") or model_slug,
                "formatType": format_type,
                "strategy": {
                    "distributionPriority": "instagram_reels_first" if platform == "instagram" else platform,
                    "primaryMetric": "views_reach",
                    "humanReviewRequired": True,
                    "nativeAudioRequired": platform == "instagram",
                    "useReferenceBank": True,
                },
                "sourcePreflight": {
                    "probe": source_probe,
                    "warnings": source_preflight,
                },
                "generatedAssetLineage": generated_lineage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        result = self._make_batch(
            folder=intake_dir,
            campaign_slug=campaign,
            model_slug=model_slug,
            output_format="reel",
            variant_count=variant_count,
            reference_pattern=reference_pattern,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            workers=workers,
            recipes=recipes,
            auto_approve_warning_only=True,
            source_prompt=source_prompt,
            import_notes="finished-video intake source import",
        )
        result["finishedVideoIntake"] = {
            "schema": "campaign_factory.finished_video_intake.v1",
            "inputPath": str(source),
            "stagedFolder": str(intake_dir),
            "stagedPath": str(staged),
            "campaign": campaign,
            "model": model_slug,
            "platform": platform,
            "goal": goal,
            "formatType": format_type,
            "sourcePrompt": self._json_load(source_prompt, {}),
            "sourceLineagePath": str(source_lineage_path) if source_lineage_path else None,
            "sourcePreflight": source_preflight,
            "creativePlan": creative_plan_payload,
            "draftFirst": True,
            "humanReviewRequired": True,
        }
        if creative_plan_payload and campaign:
            self.conn.execute(
                "UPDATE creative_plans SET linked_campaign_slug = ?, updated_at = ? WHERE id = ?",
                (campaign, self._utc_now(), creative_plan_id),
            )
            self._record_creative_plan_event(
                creative_plan_id,
                "finished_video_ingested",
                status="success",
                message=f"Finished video ingested: {source.name}",
                metadata={"campaign": campaign, "inputPath": str(source)},
            )
        return result

    def finished_video_preflight(self, probe: dict[str, Any]) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        aspect = probe.get("effectiveAspectRatio")
        if isinstance(aspect, (int, float)) and aspect > 0:
            if aspect < 0.48 or aspect > 0.66:
                warnings.append(
                    {
                        "code": "finished_video_not_reels_canvas",
                        "message": "Finished video is not close to a clean 9:16 Reels canvas; check for platform UI, borders, or screen-recorded wrapper before posting.",
                    }
                )
        elif not probe:
            warnings.append(
                {
                    "code": "finished_video_probe_unavailable",
                    "message": "Could not probe finished video dimensions before intake.",
                }
            )
        return warnings

    def finished_video_style_lane_format(self, style_lane: str | None) -> str | None:
        normalized = self._slugify(style_lane or "")
        aliases = {
            "mirror": "mirror_selfie",
            "mirror_selfie": "mirror_selfie",
            "selfie": "selfie_video",
            "selfie_video": "selfie_video",
            "pov": "pov",
            "pov_relationship": "pov",
            "lifestyle": "spicy_lifestyle",
            "lifestyle_scene": "spicy_lifestyle",
            "spicy_lifestyle": "spicy_lifestyle",
            "amateur_native": "selfie_video",
            "slideshow": "slideshow",
            "slideshow_story": "slideshow",
        }
        return aliases.get(normalized)

    def finished_video_caption_band(self, format_type: str) -> str:
        if format_type in {"mirror_selfie", "selfie_video", "pov", "spicy_lifestyle"}:
            return "auto"
        return "center"

    def finished_video_caption_font(self, format_type: str) -> str:
        if format_type in {"mirror_selfie", "selfie_video", "pov", "spicy_lifestyle"}:
            return "Instagram Sans Condensed"
        return "Instagram Sans Condensed"

    def classify_finished_video_format(self, path: Path) -> str:
        text = str(path).lower()
        if "mirror" in text:
            return "mirror_selfie"
        if "selfie" in text:
            return "selfie_video"
        if any(token in text for token in ("bedroom", "car", "lifestyle", "fit", "glam")):
            return "spicy_lifestyle"
        if "slide" in text:
            return "slideshow"
        return "selfie_video"
