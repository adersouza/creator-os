import copy
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caption_render import render_caption_png
from caption_scene_fit import (
    CAPTION_SCENE_FIT_VERSION,
    CAPTION_TOPIC_FIT_VERSION,
    classify_reel_scene_tags,
    infer_caption_topic_for_reel,
)
from graph_builder import build_ffmpeg_cmd, build_video_filter, caption_overlay_enable
from placement_scorer import PlacementSummary, score_lanes
from recipe_loader import load_recipes
from reel_pipeline import (
    DEFAULT_CAPTION_FONT,
    CaptionSet,
    Manifest,
    Recipe,
    _audio_selection_local_path,
    _selected_audio_for_mux,
    apply_caption_fit_to_caption_set,
    apply_creator_style_preset,
    build_avconvert_finalize_cmd,
    build_caption_outcome_context,
    build_caption_placement_qc_row,
    build_phone_finalize_cmd,
    build_single_job_enqueue_cmd,
    caption_set_from_bank_selection,
    centered_static_caption_band,
    compute_job_key,
    effective_placement_mode_for_caption,
    enforce_production_identity_provider,
    ensure_source_asset_lineage,
    limit_render_pool,
    load_asset_prompt_set,
    normalize_rendered_mp4_metadata,
    phone_creation_time,
    reconcile_interrupted_temp_outputs,
    source_lineage_path_for,
    timed_caption_band,
    vary_band_within_lane,
    write_caption_lineage_sidecar,
    write_generated_asset_lineage_sidecar,
    write_required_similarity_audit,
)
from render_plan import RenderPlan

from pipeline_contracts import ContractValidationError, validate_generated_asset_lineage


class ReelPipelineTests(unittest.TestCase):
    def test_audio_selection_local_path_reads_nested_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected = _audio_selection_local_path(
                root,
                {
                    "track_id": "ranked_1",
                    "metadata": {"local_path": "03_audio_library/ranked.m4a"},
                },
            )

            self.assertEqual(selected, root / "03_audio_library" / "ranked.m4a")

    def test_selected_audio_for_mux_prefers_manual_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("audio_provider.select_audio") as provider:
                selected, selection = _selected_audio_for_mux(
                    root, seed=7, explicit_audio_path="manual.m4a"
                )

            provider.assert_not_called()
            self.assertEqual(selected, "manual.m4a")
            self.assertEqual(selection["track_id"], "manual_manual")

    def test_selected_audio_for_mux_uses_ranked_provider_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "03_audio_library" / "ranked.m4a"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"audio")
            provider_selection = {
                "track_id": "ranked_1",
                "track_name": "Ranked",
                "source": "local_winners",
                "metadata": {"local_path": "03_audio_library/ranked.m4a"},
            }
            with patch("audio_provider.select_audio", return_value=provider_selection):
                selected, selection = _selected_audio_for_mux(
                    root, seed=7, explicit_audio_path=None
                )

            self.assertEqual(selected, str(audio))
            self.assertEqual(selection["track_id"], "ranked_1")
            self.assertEqual(selection["local_path"], str(audio))

    def test_selected_audio_for_mux_allows_random_fallback_when_provider_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider_selection = {
                "track_id": "remote_only",
                "track_name": "Remote Only",
                "source": "cml",
            }
            with patch("audio_provider.select_audio", return_value=provider_selection):
                selected, selection = _selected_audio_for_mux(
                    root, seed=7, explicit_audio_path=None
                )

            self.assertIsNone(selected)
            self.assertEqual(selection["track_id"], "remote_only")

    def test_recipe_default_font_is_instagram_sans_condensed(self):
        recipe = Recipe("v01_original")

        self.assertEqual(recipe.font, DEFAULT_CAPTION_FONT)
        self.assertEqual(DEFAULT_CAPTION_FONT, "Instagram Sans Condensed")

    def test_caption_font_policy_allows_only_instagram_regular_or_bold(self):
        from reel_pipeline import (
            INSTAGRAM_BOLD_CAPTION_FONT,
            resolve_caption_font_policy,
        )

        regular, regular_decision = resolve_caption_font_policy(
            "Sofia Sans Condensed Medium", "ig"
        )
        self.assertEqual(regular, DEFAULT_CAPTION_FONT)
        self.assertEqual(
            regular_decision["reason"], "non_instagram_font_coerced_to_regular"
        )

        downgraded, downgraded_decision = resolve_caption_font_policy(
            INSTAGRAM_BOLD_CAPTION_FONT, "ig"
        )
        self.assertEqual(downgraded, DEFAULT_CAPTION_FONT)
        self.assertEqual(
            downgraded_decision["reason"],
            "bold_downgraded_to_regular_for_non_meme_style",
        )

        bold, bold_decision = resolve_caption_font_policy(
            INSTAGRAM_BOLD_CAPTION_FONT, "meme"
        )
        self.assertEqual(bold, INSTAGRAM_BOLD_CAPTION_FONT)
        self.assertEqual(bold_decision["reason"], "bold_allowed_for_meme_style")

    def test_stacey_static_center_preset_applies_to_larissa_and_stacey_only(self):
        generic = Namespace(
            creator_style_preset="auto",
            caption_mix=None,
            band=None,
            style=None,
            font=None,
            color=None,
        )
        self.assertIsNone(apply_creator_style_preset(generic))
        self.assertIsNone(generic.band)

        larissa = Namespace(
            creator_style_preset="auto",
            caption_mix="Larissa",
            band=None,
            style=None,
            font=None,
            color=None,
        )
        self.assertEqual(apply_creator_style_preset(larissa), "stacey_static_center")
        self.assertEqual(larissa.band, "lower_center")
        self.assertEqual(larissa.style, "ig")
        self.assertEqual(larissa.font, DEFAULT_CAPTION_FONT)
        self.assertEqual(larissa.color, "light")

        stacey = Namespace(
            creator_style_preset="auto",
            caption_mix="Stacey",
            band=None,
            style=None,
            font=None,
            color=None,
        )
        self.assertEqual(apply_creator_style_preset(stacey), "stacey_static_center")
        self.assertEqual(stacey.band, "lower_center")

        lola = Namespace(
            creator_style_preset="auto",
            caption_mix="Lola",
            band=None,
            style=None,
            font=None,
            color=None,
        )
        self.assertIsNone(apply_creator_style_preset(lola))
        self.assertIsNone(lola.band)

    def test_stacey_static_center_preset_does_not_override_explicit_flags(self):
        args = Namespace(
            creator_style_preset="stacey_static_center",
            caption_mix="Lola",
            band="top",
            style="meme",
            font="Instagram Sans Condensed Bold",
            color="dark",
        )

        self.assertEqual(apply_creator_style_preset(args), "stacey_static_center")
        self.assertEqual(args.band, "top")
        self.assertEqual(args.style, "meme")
        self.assertEqual(args.font, "Instagram Sans Condensed Bold")
        self.assertEqual(args.color, "dark")

    def test_caption_placement_qc_records_render_band_separately_from_scored_lane(self):
        summary = PlacementSummary(
            "bottom",
            {"top": 140.0, "center": 88.0, "bottom": 42.0},
            3,
            "bottom selected",
            {
                "captionPlacementPolicy": "focal_safe_v1",
                "captionPlacementDecision": {
                    "status": "passed",
                    "selectedLane": "bottom",
                    "rejectedLanes": ["top"],
                    "scores": {"top": 140.0, "center": 88.0, "bottom": 42.0},
                    "sampleCount": 3,
                },
            },
        )

        row = build_caption_placement_qc_row(
            source_clip="stacey_001",
            placement_summary=summary,
            scored_lane="bottom",
            render_band="lower_center",
            caption_style="ig",
            font=DEFAULT_CAPTION_FONT,
        )

        self.assertEqual(row["schema"], "reel_factory.caption_placement_qc_row.v2")
        self.assertEqual(row["scoredLane"], "bottom")
        self.assertEqual(row["selectedLane"], "bottom")
        self.assertEqual(row["renderBand"], "lower_center")
        self.assertEqual(row["finalBand"], "lower_center")
        self.assertEqual(row["decision"]["selectedLane"], "bottom")

    def test_lower_center_caption_band_sits_between_center_and_bottom(self):
        from caption_render import _caption_xy

        _, top_y = _caption_xy(
            band="top",
            canvas_w=1080,
            canvas_h=1920,
            content_w=400,
            content_h=100,
            safe_top=280,
            safe_bottom=480,
        )
        _, lower_center_y = _caption_xy(
            band="lower_center",
            canvas_w=1080,
            canvas_h=1920,
            content_w=400,
            content_h=100,
            safe_top=280,
            safe_bottom=480,
        )
        _, lower_center_alt_y = _caption_xy(
            band="lower_center_alt",
            canvas_w=1080,
            canvas_h=1920,
            content_w=400,
            content_h=100,
            safe_top=280,
            safe_bottom=480,
        )
        _, center_y = _caption_xy(
            band="center",
            canvas_w=1080,
            canvas_h=1920,
            content_w=400,
            content_h=100,
            safe_top=280,
            safe_bottom=480,
        )

        self.assertGreater(lower_center_y, top_y)
        self.assertGreater(lower_center_y, center_y)
        self.assertGreater(lower_center_alt_y, lower_center_y)

    def test_stacey_timed_caption_bands_stay_lower_center_even_when_center_available(
        self,
    ):
        summary = PlacementSummary(
            "bottom",
            {"top": 140.0, "center": 10.0, "bottom": 42.0},
            3,
            "bottom selected",
            {"captionPlacementDecision": {"rejectedLanes": []}},
        )

        self.assertEqual(timed_caption_band("lower_center", 0, summary), "lower_center")
        self.assertEqual(
            timed_caption_band("lower_center", 1, summary), "lower_center_alt"
        )

    def test_caption_set_reads_timed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip_001.json"
            path.write_text(
                """
                {
                  "hooks": [
                    "plain hook",
                    {"segments": [{"text": "first", "end": 2.0}]}
                  ],
                  "caption_color": "auto"
                }
                """,
                encoding="utf-8",
            )
            cap_set = CaptionSet.from_path(path)
            self.assertEqual(cap_set.hooks[0], "plain hook")
            self.assertEqual(cap_set.hooks[1]["segments"][0]["text"], "first")

    def test_caption_set_blocks_clipped_prefix_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip_001.json"
            path.write_text(
                json.dumps(
                    {
                        "hooks": ["therapy is cute\nbut have you tried"],
                        "hookLineage": {
                            "0": {
                                "rawSourceCaptionText": "therapy is cute\nbut have you tried\nbad decisions?"
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "clipped prefix"):
                CaptionSet.from_path(path)

    def test_caption_bank_selection_builds_caption_set_with_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_dir = root / "01_captions"
            cap_dir.mkdir()
            (cap_dir / "clip_001.json").write_text(
                json.dumps(
                    {
                        "hooks": [
                            "mirror selfie after the light hit different",
                            "gym mirror selfie after the coach said front or back",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            cap_set = caption_set_from_bank_selection(
                root,
                caption_mix="Lola",
                caption_banks=None,
                limit=2,
                seed=4,
            )

            self.assertEqual(len(cap_set.hooks), 2)
            self.assertEqual(len(cap_set.hook_lineage), 2)
            lineage = cap_set.hook_lineage[0]
            self.assertEqual(lineage["schema"], "reel_factory.caption_lineage.v1")
            self.assertEqual(lineage["selectedMix"], "Lola")
            self.assertIn("captionBankSourceHash", lineage)

    def test_caption_bank_selection_blocks_discoverability_unsafe_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_dir = root / "01_captions"
            cap_dir.mkdir()
            (cap_dir / "clip_001.json").write_text(
                json.dumps(
                    {"hooks": ["I respond to DMs. I just don't respond to basic ones"]}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "discoverability unsafe caption"):
                caption_set_from_bank_selection(
                    root,
                    caption_mix="Stacey",
                    caption_banks=None,
                    limit=1,
                    seed=1,
                )

    def test_caption_sidecar_blocks_discoverability_unsafe_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip_001.json"
            path.write_text(
                json.dumps(
                    {"hooks": [{"segments": [{"text": "link in bio", "end": 1.0}]}]}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "discoverability unsafe caption"):
                CaptionSet.from_path(path)

    def test_caption_fit_filters_long_hooks_for_mirror_fullbody(self):
        cap_set = CaptionSet(
            hooks=[
                "wife or girlfriend",
                "I'm so single I end up texting anyone who follows me because I get excited thinking we might become friends",
            ],
            hook_lineage={
                0: {
                    "schema": "reel_factory.caption_lineage.v1",
                    "captionHash": "short",
                    "rawCaptionText": "wife or girlfriend",
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                },
                1: {
                    "schema": "reel_factory.caption_lineage.v1",
                    "captionHash": "long",
                    "rawCaptionText": "I'm so single I end up texting anyone who follows me because I get excited thinking we might become friends",
                    "selectedBanks": ["dm_follow_bait"],
                    "lengthClass": "long",
                    "formatClass": "paragraph",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="mirror_fullbody",
            max_hooks=2,
            seed=1,
            fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["wife or girlfriend"])
        self.assertEqual(fitted.hook_lineage[0]["captionFitVersion"], "v1")
        self.assertEqual(fitted.hook_lineage[0]["suitabilityDecision"], "allowed")
        self.assertTrue(
            any(row["suitabilityDecision"] == "skipped" for row in diagnostics)
        )

    def test_caption_fit_rejects_paragraph_that_cannot_render_legibly(self):
        long_paragraph = "\n".join(
            [
                "3 different ways a guy would ask me out",
                "Smooth: " + "very specific romantic setup " * 6,
                "Nervous: " + "awkward cute overthinking line " * 6,
                "Playful: " + "teasing challenge with extra words " * 6,
            ]
        )
        cap_set = CaptionSet(
            hooks=["short readable hook", long_paragraph],
            hook_lineage={
                0: {
                    "lengthClass": "short",
                    "formatClass": "single_line",
                    "selectedBankWeight": 1,
                },
                1: {
                    "lengthClass": "long",
                    "formatClass": "paragraph",
                    "selectedBankWeight": 100,
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            max_hooks=2,
            seed=1,
            fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["short readable hook"])
        self.assertEqual(diagnostics[1]["suitabilityDecision"], "unrenderable")
        self.assertIn("legible render capacity", diagnostics[1]["reason"])

    def test_caption_fit_off_preserves_old_selection(self):
        cap_set = CaptionSet(
            hooks=["wife or girlfriend", "long caption " * 12],
            hook_lineage={
                0: {"lengthClass": "very_short", "formatClass": "single_line"},
                1: {"lengthClass": "long", "formatClass": "paragraph"},
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="mirror_fullbody",
            max_hooks=2,
            seed=1,
            fit_mode="off",
        )

        self.assertEqual(len(fitted.hooks), 2)
        self.assertTrue(
            all(row["suitabilityDecision"] == "fit_disabled" for row in diagnostics)
        )

    def test_caption_fit_marks_readable_unselected_candidates_as_downweighted(self):
        cap_set = CaptionSet(
            hooks=["one", "two", "three"],
            hook_lineage={
                0: {
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                    "selectedBankWeight": 1,
                },
                1: {
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                    "selectedBankWeight": 1,
                },
                2: {
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                    "selectedBankWeight": 1,
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="wide_fullbody",
            max_hooks=1,
            seed=1,
            fit_mode="auto",
        )

        self.assertEqual(len(fitted.hooks), 1)
        self.assertEqual(
            sum(row["suitabilityDecision"] == "downweighted" for row in diagnostics),
            2,
        )

    def test_caption_scene_fit_blocks_pool_caption_for_indoor_selfie(self):
        cap_set = CaptionSet(
            hooks=[
                "I have a pool too,\nwanna come over?",
                "leave a heart if i'm your type",
            ],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
                1: {
                    "selectedBanks": ["comment_bait"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["indoor_selfie"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["leave a heart if i'm your type"])
        self.assertEqual(diagnostics[0]["sceneCompatibilityDecision"], "blocked")
        self.assertIn("pool", diagnostics[0]["captionSceneTags"])
        self.assertEqual(
            fitted.hook_lineage[0]["captionSceneFitVersion"], CAPTION_SCENE_FIT_VERSION
        )
        self.assertEqual(
            fitted.hook_lineage[0]["sceneCompatibilityDecision"], "allowed"
        )

    def test_caption_scene_fit_allows_gym_caption_for_gym_reel(self):
        cap_set = CaptionSet(
            hooks=["before gym:", "2 mins in a room with me.\nwyd??"],
            hook_lineage={
                0: {
                    "selectedBanks": ["gym_body"],
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                },
                1: {
                    "selectedBanks": ["bedroom_mirror"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="gym_body",
            reel_scene_tags=["gym_body"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["before gym:"])
        self.assertEqual(diagnostics[0]["sceneCompatibilityDecision"], "allowed")
        self.assertEqual(diagnostics[1]["sceneCompatibilityDecision"], "blocked")

    def test_caption_scene_fit_allows_beach_caption_for_beach_pool_reel(self):
        cap_set = CaptionSet(
            hooks=["beach day, pick me up?", "before gym:"],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "single_line",
                },
                1: {
                    "selectedBanks": ["gym_body"],
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="unknown",
            reel_scene_tags=["beach_pool"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["beach day, pick me up?"])
        self.assertEqual(diagnostics[0]["sceneCompatibilityDecision"], "allowed")
        self.assertEqual(diagnostics[1]["sceneCompatibilityDecision"], "blocked")

    def test_caption_scene_fit_allows_bedroom_caption_for_unknown_reel(self):
        # unknown reel scene = undetected, NOT incompatible: bedroom/coded winners
        # must survive instead of falling back to generic captions (finding #2).
        cap_set = CaptionSet(
            hooks=["ngl it's kinda sad\nI'm not in your room rn", "pick me up?"],
            hook_lineage={
                0: {
                    "selectedBanks": ["bedroom_mirror"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
                1: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "very_short",
                    "formatClass": "single_line",
                },
            },
        )

        _fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["unknown"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(
            diagnostics[0]["sceneCompatibilityDecision"], "unknown_allowed"
        )

    def test_caption_scene_fit_off_preserves_old_scene_mismatch_selection(self):
        cap_set = CaptionSet(
            hooks=[
                "I have a pool too,\nwanna come over?",
                "leave a heart if i'm your type",
            ],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
                1: {
                    "selectedBanks": ["comment_bait"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["indoor_selfie"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="off",
        )

        self.assertEqual(fitted.hooks, cap_set.hooks)
        self.assertTrue(
            all(
                row["sceneCompatibilityDecision"] == "fit_disabled"
                for row in diagnostics
            )
        )

    def test_caption_scene_fit_does_not_mutate_caption_bank_rows(self):
        cap_set = CaptionSet(
            hooks=["I have a pool too,\nwanna come over?"],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "multiline",
                }
            },
        )
        original_hooks = list(cap_set.hooks)
        original_lineage = copy.deepcopy(cap_set.hook_lineage)

        apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["indoor_selfie"],
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(cap_set.hooks, original_hooks)
        self.assertEqual(cap_set.hook_lineage, original_lineage)

    def test_caption_topic_fit_blocks_unrelated_caption_banks(self):
        cap_set = CaptionSet(
            hooks=[
                "pov: I'm the girl you rejected in high school",
                "xbox boys still think this is a flex",
            ],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "single_line",
                },
                1: {
                    "selectedBanks": ["comment_bait"],
                    "lengthClass": "short",
                    "formatClass": "single_line",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["indoor_selfie"],
            caption_topic="gaming",
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["xbox boys still think this is a flex"])
        self.assertEqual(diagnostics[0]["suitabilityDecision"], "topic_mismatch")
        self.assertEqual(diagnostics[0]["captionTopicDecision"], "blocked")
        self.assertEqual(diagnostics[0]["captionTopic"], "gaming")
        self.assertEqual(fitted.hook_lineage[0]["captionTopic"], "gaming")
        self.assertEqual(
            fitted.hook_lineage[0]["captionTopicFitVersion"], CAPTION_TOPIC_FIT_VERSION
        )

    def test_caption_topic_fit_returns_no_hooks_when_topic_has_no_match(self):
        cap_set = CaptionSet(
            hooks=["pov: I'm the girl you rejected in high school"],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "single_line",
                },
            },
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=["indoor_selfie"],
            caption_topic="gaming",
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, [])
        self.assertEqual(diagnostics[0]["suitabilityDecision"], "topic_mismatch")
        self.assertIn("requires one of", diagnostics[0]["captionTopicReason"])

    def test_caption_topic_inference_uses_source_specific_hints(self):
        self.assertEqual(
            infer_caption_topic_for_reel(
                frame_type="closeup",
                video_stem="gaming_room_ps5_controller",
                prompt_text="",
            ),
            "gaming",
        )
        self.assertEqual(
            infer_caption_topic_for_reel(
                frame_type="closeup",
                video_stem="bed_spider_plush",
                prompt_text="",
            ),
            "fandom",
        )
        self.assertEqual(
            infer_caption_topic_for_reel(
                frame_type="closeup",
                video_stem="bathroom_read_this_backwards",
                prompt_text="",
            ),
            "reverse_puzzle",
        )
        self.assertIsNone(
            infer_caption_topic_for_reel(
                frame_type="closeup",
                video_stem="single_person_reference_image",
                prompt_text="",
            )
        )

    def test_reel_scene_tags_use_prompt_and_filename_hints(self):
        self.assertIn(
            "beach_pool",
            classify_reel_scene_tags(
                frame_type="unknown",
                video_stem="stacey_ocean_pool_test",
                prompt_text="ocean cliffside with misty sea",
            ),
        )
        self.assertIn(
            "bedroom_mirror",
            classify_reel_scene_tags(
                frame_type="mirror_fullbody",
                video_stem="indoor_room_selfie",
                prompt_text="bedroom mirror selfie",
            ),
        )

    def test_beach_pool_reel_allows_beach_caption_even_with_generic_room_prompt_wording(
        self,
    ):
        cap_set = CaptionSet(
            hooks=["beach day, pick me up?"],
            hook_lineage={
                0: {
                    "selectedBanks": ["shared_girl_next_door"],
                    "lengthClass": "short",
                    "formatClass": "single_line",
                }
            },
        )
        reel_scene_tags = classify_reel_scene_tags(
            frame_type="closeup",
            video_stem="stacey_ocean",
            prompt_text="ocean cliffside scene. Keep the selected panel framing, room, outfit feel stable.",
        )

        fitted, diagnostics = apply_caption_fit_to_caption_set(
            cap_set,
            frame_type="closeup",
            reel_scene_tags=reel_scene_tags,
            max_hooks=None,
            seed=1,
            fit_mode="auto",
            scene_fit_mode="auto",
        )

        self.assertEqual(fitted.hooks, ["beach day, pick me up?"])
        self.assertEqual(diagnostics[0]["sceneCompatibilityDecision"], "allowed")

    def test_caption_lineage_sidecar_writes_next_to_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip_001_h00_v01_original_light_deadbeef.mp4"
            out.write_bytes(b"video")
            path = write_caption_lineage_sidecar(
                out,
                {"schema": "reel_factory.caption_lineage.v1", "captionHash": "abc"},
            )

            self.assertEqual(path, out.with_suffix(".mp4.caption_lineage.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["captionHash"], "abc")

    def test_caption_outcome_context_standardizes_render_lineage_without_selection_changes(
        self,
    ):
        lineage = {
            "schema": "reel_factory.caption_lineage.v1",
            "captionHash": "caption_hash_rendered",
            "rawCaptionText": "caption",
            "selectedBanks": ["question_bank"],
            "sourceBanks": ["fallback_bank"],
            "selectedMix": "Lola",
            "sourceClip": "clip_010",
            "lengthClass": "very_short",
            "formatClass": "single_line",
            "frameType": "mirror_fullbody",
            "captionFitVersion": "v1",
            "suitabilityDecision": "allowed",
            "suitabilityReason": "very_short static caption allowed for mirror_fullbody",
        }

        context = build_caption_outcome_context(
            caption_text="caption",
            caption_lineage=lineage,
            render_recipe="v09_caption_bg",
            source_clip="clip_010",
            rendered_output="/tmp/out.mp4",
            creator_model="lola",
        )

        self.assertEqual(
            context["schema"], "campaign_factory.caption_outcome_context.v1"
        )
        self.assertEqual(context["caption_hash"], "caption_hash_rendered")
        self.assertEqual(context["caption_bank"], "question_bank")
        self.assertEqual(context["caption_banks"], ["question_bank"])
        self.assertEqual(context["creator_mix"], "Lola")
        self.assertEqual(context["creator_model"], "lola")
        self.assertEqual(context["frame_type"], "mirror_fullbody")
        self.assertEqual(context["length_class"], "very_short")
        self.assertEqual(context["format_class"], "single_line")
        self.assertEqual(context["caption_fit_version"], "v1")
        self.assertEqual(context["render_recipe"], "v09_caption_bg")
        self.assertEqual(context["source_clip"], "clip_010")

    def test_caption_lineage_sidecar_embeds_standard_caption_outcome_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip_010_h00_v09_caption_bg_light_deadbeef.mp4"
            out.write_bytes(b"video")
            lineage = {
                "schema": "reel_factory.caption_lineage.v1",
                "captionHash": "caption_hash_rendered",
                "rawCaptionText": "caption",
                "selectedBanks": ["question_bank"],
                "selectedMix": "Lola",
                "lengthClass": "very_short",
                "formatClass": "single_line",
            }

            path = write_caption_lineage_sidecar(
                out,
                lineage,
                render_recipe="v09_caption_bg",
                source_clip="clip_010",
                rendered_output=str(out),
                creator_model="lola",
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["captionHash"], "caption_hash_rendered")
            self.assertEqual(
                payload["captionOutcomeContext"]["caption_hash"],
                "caption_hash_rendered",
            )
            self.assertEqual(
                payload["captionOutcomeContext"]["caption_bank"], "question_bank"
            )
            self.assertEqual(payload["captionOutcomeContext"]["creator_model"], "lola")

    def test_caption_lineage_sidecar_uses_final_rendered_caption_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip_010_h00_v09_caption_bg_light_deadbeef.mp4"
            out.write_bytes(b"video")
            lineage = {
                "schema": "reel_factory.caption_lineage.v1",
                "captionHash": "bank_hash_before_linebreak_rendering",
                "rawCaptionText": "caption\nwith linebreak",
                "selectedBanks": ["question_bank"],
                "selectedMix": "Lola",
            }

            path = write_caption_lineage_sidecar(
                out,
                lineage,
                caption_text="caption\nwith linebreak",
                caption_hash="final_rendered_hash",
                render_recipe="v09_caption_bg",
                source_clip="clip_010",
                rendered_output=str(out),
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["captionHash"], "final_rendered_hash")
            self.assertEqual(
                payload["captionOutcomeContext"]["caption_hash"], "final_rendered_hash"
            )

    def test_static_caption_side_band_falls_back_to_centered_lane(self):
        summary = PlacementSummary(
            "right",
            {
                "side_right": 1.0,
                "side_left": 5.0,
                "top": 20.0,
                "center": 8.0,
                "bottom": 12.0,
            },
            3,
            "right side clearest",
        )

        self.assertEqual(centered_static_caption_band("right", summary), "center")
        self.assertEqual(centered_static_caption_band("left", summary), "center")
        self.assertEqual(centered_static_caption_band("bottom", summary), "bottom")

    def test_static_caption_side_band_can_cycle_centered_safe_lanes(self):
        summary = PlacementSummary(
            "right",
            {
                "side_right": 1.0,
                "side_left": 5.0,
                "top": 20.0,
                "center": 8.0,
                "bottom": 12.0,
            },
            3,
            "right side clearest",
        )

        bands = {
            centered_static_caption_band(
                "right", summary, diversity_key=f"archive-{idx}"
            )
            for idx in range(24)
        }

        self.assertEqual(bands, {"top", "center", "bottom"})

    def _subband_summary(self, lane, rejected):
        return PlacementSummary(
            lane,
            {"top": 5.0, "center": 8.0, "bottom": 6.0},
            3,
            f"{lane} lowest",
            {"captionPlacementDecision": {"rejectedLanes": rejected}},
        )

    def test_vary_band_jitters_within_lane_when_adjacent_clear(self):
        summary = self._subband_summary("bottom", [])
        bands = {
            vary_band_within_lane("bottom", summary, diversity_key=f"clip-{i}")
            for i in range(24)
        }
        # bottom lane offers bottom + lower_center_alt for per-clip variety
        self.assertEqual(bands, {"bottom", "lower_center_alt"})

    def test_vary_band_skips_subband_when_supporting_lane_rejected(self):
        # center rejected → lower_center_alt (needs center+bottom) unavailable,
        # so a bottom-lane caption never drifts up into the subject.
        summary = self._subband_summary("bottom", ["center"])
        bands = {
            vary_band_within_lane("bottom", summary, diversity_key=f"clip-{i}")
            for i in range(24)
        }
        self.assertEqual(bands, {"bottom"})

    def test_vary_band_passes_through_unladdered_bands(self):
        summary = self._subband_summary("bottom", [])
        for band in ("left", "right", "lower_center", "lower_center_alt"):
            self.assertEqual(
                vary_band_within_lane(band, summary, diversity_key="x"), band
            )

    def test_vary_band_is_deterministic(self):
        summary = self._subband_summary("center", [])
        first = vary_band_within_lane("center", summary, diversity_key="stable")
        again = vary_band_within_lane("center", summary, diversity_key="stable")
        self.assertEqual(first, again)

    def test_job_key_changes_when_recipe_changes(self):
        a = compute_job_key("video", "caption", Recipe("v01_original"))
        b = compute_job_key("video", "caption", Recipe("v01_original", zoom=1.01))
        self.assertNotEqual(a, b)

    def test_job_key_tracks_static_caption_centering_policy(self):
        static_key = compute_job_key("video", "caption", Recipe("v01_original"))
        timed_key = compute_job_key(
            "video",
            {"segments": [{"text": "caption", "end": 1.0}]},
            Recipe("v01_original"),
        )

        self.assertNotEqual(static_key, timed_key)

    def test_timed_captions_auto_use_segment_placement(self):
        timed_caption = {
            "segments": [{"text": "first", "end": 1.0}, {"text": "second", "end": 2.0}]
        }

        self.assertEqual(
            effective_placement_mode_for_caption(timed_caption, "source"), "segment"
        )
        self.assertEqual(
            effective_placement_mode_for_caption(timed_caption, "segment"), "segment"
        )
        self.assertEqual(
            effective_placement_mode_for_caption("static caption", "source"), "source"
        )

    def test_focal_safe_scoring_rejects_face_heavy_top_lane(self):
        summary = score_lanes(
            stddev_samples=[(12.0, 18.0, 16.0)],
            face_samples=[(500.0, 0.0, 0.0)],
            focal_samples=[(80.0, 20.0, 10.0)],
            motion_samples=[(1.0, 1.0, 1.0)],
            placement_policy="focal-safe",
        )

        self.assertNotEqual(summary.lane, "top")
        self.assertEqual(summary.metadata["captionPlacementPolicy"], "focal_safe_v1")
        self.assertEqual(
            summary.metadata["captionPlacementDecision"]["status"], "passed"
        )
        self.assertIn(
            "top", summary.metadata["captionPlacementDecision"]["rejectedLanes"]
        )

    def test_focal_safe_scoring_rejects_upper_body_center_lane(self):
        summary = score_lanes(
            stddev_samples=[(14.0, 12.0, 16.0)],
            face_samples=[(0.0, 0.0, 0.0)],
            focal_samples=[(5.0, 800.0, 15.0)],
            motion_samples=[(1.0, 1.0, 1.0)],
            placement_policy="focal-safe",
        )

        self.assertNotEqual(summary.lane, "center")
        self.assertIn(
            "center", summary.metadata["captionPlacementDecision"]["rejectedLanes"]
        )

    def test_focal_safe_prefers_lower_hook_zone_without_face_or_pose_collision(self):
        summary = score_lanes(
            stddev_samples=[(44.129, 44.848, 47.963)],
            focal_samples=[(21.932, 78.502, 114.1)],
            motion_samples=[(23.746, 24.851, 24.821)],
            placement_policy="focal-safe",
        )

        self.assertEqual(summary.lane, "bottom")
        self.assertNotIn(
            "bottom", summary.metadata["captionPlacementDecision"]["rejectedLanes"]
        )

    def test_legacy_scoring_preserves_old_lowest_penalty_path(self):
        summary = score_lanes(
            stddev_samples=[(20.0, 1.0, 20.0)],
            focal_samples=[(0.0, 1000.0, 0.0)],
            placement_policy="legacy",
            center_penalty=0.0,
        )

        self.assertEqual(summary.lane, "center")
        self.assertEqual(summary.metadata.get("captionPlacementPolicy"), "legacy")

    def test_timed_caption_default_job_key_matches_segment_placement(self):
        recipe = Recipe("v01_original")
        timed_caption = {
            "segments": [{"text": "first", "end": 1.0}, {"text": "second", "end": 2.0}]
        }

        self.assertEqual(
            compute_job_key("video", timed_caption, recipe),
            compute_job_key("video", timed_caption, recipe, placement_mode="segment"),
        )
        self.assertNotEqual(
            compute_job_key("video", "static caption", recipe),
            compute_job_key(
                "video", "static caption", recipe, placement_mode="segment"
            ),
        )

    def test_timed_caption_overlay_timing_is_half_open(self):
        recipe = Recipe("v01_original")
        cmd = build_ffmpeg_cmd(
            RenderPlan(
                src=Path("in.mp4"),
                caption_pngs=[
                    (Path("first.png"), 0.0, 1.0),
                    (Path("second.png"), 1.0, 2.0),
                ],
                recipe=recipe,
                out=Path("out.mp4"),
                duration=2.0,
                fonts_dir=Path("fonts"),
                src_hash="abc",
                src_dims=(1080, 1920),
            ),
            "ffmpeg",
        )
        filter_complex = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn(caption_overlay_enable(0.0, 1.0), filter_complex)
        self.assertIn(caption_overlay_enable(1.0, 2.0), filter_complex)
        self.assertNotIn("between(t", filter_complex)

    def test_per_clip_limit_caps_total_outputs_when_many_recipes(self):
        hooks = [(idx, f"hook {idx}") for idx in range(4)]
        recipes = [Recipe(f"v{idx:02d}") for idx in range(9)]

        limited_hooks, limited_recipes = limit_render_pool(
            hooks,
            recipes,
            per_clip=4,
            hook_select="first",
            seed=42,
            recipe_order=recipes,
        )

        self.assertEqual(len(limited_hooks) * len(limited_recipes), 4)
        self.assertEqual(len(limited_hooks), 1)
        self.assertEqual(
            [recipe.name for recipe in limited_recipes], ["v00", "v01", "v02", "v03"]
        )

    def test_manifest_sqlite_exports_json_and_detects_existing_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            source = root / "clip_001.mp4"
            source.write_bytes(b"source")
            output = root / "out.mp4"
            output.write_bytes(b"output")

            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", source, "src-hash", 2.5)
            manifest.add_variation(
                "clip_001",
                recipe,
                "caption",
                output,
                key,
                2.5,
                render_time_sec=1.2,
                lineage={
                    "sourceHash": "src-hash",
                    "captionHash": "cap-hash",
                    "format": "reel_pack",
                    "font": "Instagram Sans Condensed",
                    "captionStyle": "ig",
                    "captionPosition": "center",
                    "generationId": "capgen_1",
                    "renderJobKey": key,
                },
            )
            manifest.save()

            self.assertTrue((root / "manifest.sqlite").exists())
            self.assertTrue((root / "manifest.json").exists())
            self.assertTrue(manifest.has_job(key))
            row = manifest.to_json_data()["videos"]["clip_001"]["variations"][0]
            self.assertEqual(
                row["recipe_params"]["_lineage"]["generationId"], "capgen_1"
            )
            self.assertEqual(row["recipe_params"]["_lineage"]["format"], "reel_pack")
            self.assertEqual(row["recipe_params"]["_target_ratio"], "9:16")
            self.assertEqual(row["encoder"], "h264_videotoolbox")

    def test_manifest_records_actual_encoder_and_target_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            source = root / "clip_001.mp4"
            output = root / "out.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"output")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)

            manifest.upsert_video("clip_001", source, "src-hash", 2.5)
            manifest.add_variation(
                "clip_001",
                recipe,
                "caption",
                output,
                key,
                2.5,
                encoder="cpu_h264_x264",
                target_ratio="9:16",
            )
            row = manifest.to_json_data()["videos"]["clip_001"]["variations"][0]

            self.assertEqual(row["encoder"], "cpu_h264_x264")
            self.assertEqual(row["recipe_params"]["_target_ratio"], "9:16")

    def test_manifest_materializes_cached_job_for_duplicate_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            source_a = root / "clip_001.mp4"
            source_b = root / "clip_002.mp4"
            source_a.write_bytes(b"same-source")
            source_b.write_bytes(b"same-source")
            output = root / "out.mp4"
            output.write_bytes(b"output")

            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", source_a, "src-hash", 2.5)
            manifest.upsert_video("clip_002", source_b, "src-hash", 2.5)
            manifest.add_variation(
                "clip_001",
                recipe,
                "caption",
                output,
                key,
                2.5,
                lineage={"renderJobKey": key},
            )

            self.assertTrue(manifest.materialize_cached_job("clip_002", key))
            manifest.save()

            data = manifest.to_json_data()
            rows = data["videos"]["clip_002"]["variations"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["output_path"], str(output))
            self.assertNotEqual(rows[0]["job_key"], key)
            self.assertEqual(
                rows[0]["recipe_params"]["_lineage"]["cachedFromVideoId"], "clip_001"
            )
            self.assertEqual(
                rows[0]["recipe_params"]["_lineage"]["cachedFromJobKey"], key
            )

    def test_manifest_tracks_failed_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            source = root / "clip_001.mp4"
            source.write_bytes(b"source")

            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.upsert_video("clip_001", source, "src-hash", 2.5)
            manifest.add_failure(
                "clip_001",
                recipe,
                "caption",
                root / "failed.mp4",
                key,
                2.5,
                "ffmpeg exploded",
                render_time_sec=0.4,
            )
            manifest.save()

            data = manifest.to_json_data()
            row = data["videos"]["clip_001"]["variations"][0]
            self.assertEqual(row["status"], "failed")
            self.assertIn("ffmpeg exploded", row["error_message"])
            self.assertFalse(manifest.has_job(key))

    def test_manifest_tracks_render_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            recipe = Recipe("v01_original")
            key = compute_job_key("src-hash", "caption", recipe)
            manifest.add_attempt(
                key=key,
                attempt_no=1,
                status="failed",
                temp_path=root / ".tmp" / "out.mp4",
                final_path=root / "out.mp4",
                ffmpeg_cmd=["ffmpeg", "-i", "in.mp4", "out.mp4"],
                started_at=1,
                ended_at=2,
                error_message="encoder busy",
            )
            row = manifest.conn.execute(
                "SELECT * FROM render_attempts WHERE job_key = ?",
                (key,),
            ).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertIn("encoder busy", row["error_message"])

    def test_default_recipe_config_loads_and_validates(self):
        recipes = load_recipes(Path("recipes/default.json"), Recipe)
        by_name = {recipe.name: recipe for recipe in recipes}
        names = [recipe.name for recipe in recipes]
        self.assertIn("v00_passthrough", names)
        self.assertIn("v01_original", names)
        self.assertIn("v11_colorgrade_cool", names)
        self.assertFalse(by_name["v00_passthrough"].burn_caption)
        self.assertFalse(by_name["v00_passthrough"].camera_variation)
        self.assertFalse(by_name["v09_caption_bg"].camera_variation)

    def test_passthrough_recipe_skips_caption_overlay(self):
        plan = RenderPlan(
            src=Path("in.mp4"),
            caption_pngs=[(Path("cap.png"), 0.0, None)],
            recipe=Recipe(
                "v00_passthrough", burn_caption=False, camera_variation=False
            ),
            out=Path("tmp/out.mp4"),
            duration=3.0,
            fonts_dir=Path("fonts"),
            src_hash="abc",
            src_dims=(1080, 1920),
        )
        cmd = build_ffmpeg_cmd(plan, "ffmpeg")
        joined = " ".join(cmd)
        self.assertNotIn("overlay=", joined)
        self.assertNotIn("cap.png", joined)

    def test_recipe_config_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_recipes.json"
            path.write_text(
                '[{"name": "bad", "speed": 0, "caption_band": "somewhere"}]',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "speed must be > 0"):
                load_recipes(path, Recipe)

    def test_graph_builder_uses_render_plan_output_path(self):
        plan = RenderPlan(
            src=Path("in.mp4"),
            caption_pngs=[(Path("cap.png"), 0.0, None)],
            recipe=Recipe("v01_original"),
            out=Path("tmp/out.mp4"),
            duration=3.0,
            fonts_dir=Path("fonts"),
            src_hash="abc",
            src_dims=(1080, 1920),
        )
        cmd = build_ffmpeg_cmd(plan, "ffmpeg")
        self.assertEqual(cmd[-1], "tmp/out.mp4")
        self.assertIn("-filter_complex", cmd)

    def test_camera_variation_seed_is_account_scoped(self):
        recipe = Recipe("v_seeded", camera_variation=True)
        base = {
            "src": Path("in.mp4"),
            "caption_pngs": [],
            "recipe": recipe,
            "out": Path("tmp/out.mp4"),
            "duration": 3.0,
            "fonts_dir": Path("fonts"),
            "src_hash": "same-source",
            "src_dims": (1080, 1920),
        }
        account_a = build_video_filter(RenderPlan(**base, account_scope="stacey_a"))
        account_a_again = build_video_filter(
            RenderPlan(**base, account_scope="stacey_a")
        )
        account_b = build_video_filter(RenderPlan(**base, account_scope="stacey_b"))

        self.assertEqual(account_a, account_a_again)
        self.assertNotEqual(account_a, account_b)

    def test_production_render_requires_explicit_account_scope(self):
        from render_plan import validate_account_scope

        self.assertEqual(validate_account_scope(None), "local_review")
        self.assertEqual(
            validate_account_scope("stacey_a", production_render=True), "stacey_a"
        )
        with self.assertRaisesRegex(
            ValueError, "production render requires explicit account"
        ):
            validate_account_scope(None, production_render=True)
        with self.assertRaisesRegex(
            ValueError, "production render requires explicit account"
        ):
            validate_account_scope("local_review", production_render=True)

    def test_job_key_includes_account_scope_for_production_accounts(self):
        recipe = Recipe("v_seeded", camera_variation=True)
        account_a = compute_job_key(
            "video", "caption", recipe, account_scope="stacey_a"
        )
        account_b = compute_job_key(
            "video", "caption", recipe, account_scope="stacey_b"
        )
        local_a = compute_job_key("video", "caption", recipe)
        local_b = compute_job_key(
            "video", "caption", recipe, account_scope="local_review"
        )

        self.assertNotEqual(account_a, account_b)
        self.assertEqual(local_a, local_b)

    def test_graph_builder_supports_prores_mezzanine_profile(self):
        plan = RenderPlan(
            src=Path("in.mp4"),
            caption_pngs=[],
            recipe=Recipe("v01_original"),
            out=Path("tmp/out.mov"),
            duration=3.0,
            fonts_dir=Path("fonts"),
            src_hash="abc",
            src_dims=(1080, 1920),
            output_profile="prores_lt",
        )
        cmd = build_ffmpeg_cmd(plan, "ffmpeg")
        self.assertIn("prores_ks", cmd)
        self.assertIn("yuv422p10le", " ".join(cmd))
        self.assertEqual(cmd[-1], "tmp/out.mov")

    def test_graph_builder_supports_4x5_target_ratio(self):
        plan = RenderPlan(
            src=Path("in.mp4"),
            caption_pngs=[],
            recipe=Recipe("v01_original"),
            out=Path("tmp/out.mp4"),
            duration=3.0,
            fonts_dir=Path("fonts"),
            src_hash="abc",
            src_dims=(1080, 1350),
            target_ratio="4:5",
        )
        cmd = build_ffmpeg_cmd(plan, "ffmpeg")
        joined = " ".join(cmd)
        self.assertIn("scale=1080:1350", joined)
        self.assertIn("crop=1080:1350", joined)

    def test_graph_builder_crops_non_9x16_source_to_9x16_without_stretch(self):
        for dims in ((1080, 1440), (1080, 1350)):
            plan = RenderPlan(
                src=Path("in.mp4"),
                caption_pngs=[],
                recipe=Recipe("v01_original"),
                out=Path("tmp/out.mp4"),
                duration=3.0,
                fonts_dir=Path("fonts"),
                src_hash="abc",
                src_dims=dims,
                target_ratio="9:16",
            )
            joined = " ".join(build_ffmpeg_cmd(plan, "ffmpeg"))
            self.assertIn(
                "scale=1080:1920:force_original_aspect_ratio=increase", joined
            )
            self.assertIn("crop=1080:1920", joined)

    def test_caption_png_can_render_to_4x5_target_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cap.png"
            render_caption_png(
                "hello world",
                font_family="Instagram Sans Condensed",
                fonts_dir=Path("fonts"),
                color_scheme="light",
                band="center",
                style="ig",
                out_path=out,
                canvas_w=1080,
                canvas_h=1350,
            )

            from PIL import Image

            with Image.open(out) as img:
                self.assertEqual(img.size, (1080, 1350))

    def test_enqueue_command_recreates_mutated_recipe_job_key(self):
        recipe = Recipe(
            "v01_original",
            caption_color="dark",
            caption_style="ig",
            caption_band="bottom",
            font="Instagram Sans Condensed",
            text_variation="auto",
            text_variation_pack="default",
        )
        args = Namespace(
            output_profile="cpu_h264_x264",
            caption_renderer="pillow",
            placement_signals="pose",
            placement_mode="segment",
            caption_placement_policy="focal-safe",
            mezzanine=True,
            phone_finalize=False,
            rerender_all=True,
            strict_preflight=True,
            asset_prompt_json=None,
        )
        cmd = build_single_job_enqueue_cmd(
            root=Path("/tmp/reel"),
            video_stem="clip_001",
            hook_idx=3,
            recipe=recipe,
            args=args,
            target_ratio="4:5",
        )

        def after(flag: str) -> str:
            return cmd[cmd.index(flag) + 1]

        recreated = Recipe(
            after("--recipes"),
            caption_color=after("--color"),
            caption_style=after("--style"),
            caption_band=after("--band"),
            font=after("--font"),
            text_variation=after("--text-variation"),
            text_variation_pack=after("--variation-pack"),
        )
        self.assertEqual(
            compute_job_key(
                "src",
                "caption",
                recreated,
                placement_mode=after("--placement-mode"),
                target_ratio=after("--target-ratios"),
            ),
            compute_job_key(
                "src",
                "caption",
                recipe,
                placement_mode="segment",
                target_ratio="4:5",
                caption_placement_policy="focal-safe",
            ),
        )
        self.assertIn("--no-phone-finalize", cmd)
        self.assertIn("--mezzanine", cmd)

    def test_enqueue_command_serializes_instagram_font_for_default_recipe(self):
        recipe = Recipe("v01_original")
        args = Namespace(
            output_profile="cpu_h264_x264",
            caption_renderer="pillow",
            placement_signals="basic",
            placement_mode="source",
            caption_placement_policy="focal-safe",
            mezzanine=False,
            phone_finalize=True,
            rerender_all=False,
            strict_preflight=False,
            asset_prompt_json=None,
        )

        cmd = build_single_job_enqueue_cmd(
            root=Path("/tmp/reel"),
            video_stem="clip_001",
            hook_idx=0,
            recipe=recipe,
            args=args,
            target_ratio="9:16",
        )

        self.assertEqual(cmd[cmd.index("--font") + 1], DEFAULT_CAPTION_FONT)

    def test_generated_asset_lineage_sidecar_references_source_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = root / "clean.json"
            src = root / "clip_001.mp4"
            out = root / "out.mp4"
            src.write_bytes(b"source")
            out.write_bytes(b"output")
            clean.write_text(
                '{"higgsfieldGridPrompt":"grid","klingMotionPrompt":"motion","notes":"ok"}',
                encoding="utf-8",
            )
            prompt_set, prompt_path = load_asset_prompt_set(clean)
            source_lineage = ensure_source_asset_lineage(
                src,
                prompt_set=prompt_set,
                prompt_source_path=prompt_path,
            )
            sidecar = write_generated_asset_lineage_sidecar(
                out,
                source_lineage_path=source_lineage,
                render_job_key="job",
                source_hash="src-hash",
            )
            source_data = json.loads(source_lineage.read_text(encoding="utf-8"))
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(source_lineage, source_lineage_path_for(src))
            self.assertEqual(
                source_data["generation"]["prompts"]["higgsfieldGridPrompt"], "grid"
            )
            self.assertEqual(data["source"]["sourceLineagePath"], str(source_lineage))
            self.assertEqual(data["schema"], "reel_factory.generated_asset_lineage.v1")
            self.assertEqual(data["generation"]["tool"], "reel_factory.reel_pipeline")
            self.assertEqual(data["render"]["renderJobKey"], "job")
            self.assertTrue(data["review"]["humanReviewRequired"])

    def test_generated_asset_lineage_contract_rejects_malformed_payload(self):
        with self.assertRaises(ContractValidationError):
            validate_generated_asset_lineage(
                {
                    "schema": "reel_factory.generated_asset_lineage.v1",
                    "source": {},
                    "generation": {},
                    "review": {},
                }
            )

    def test_required_similarity_audit_writes_sidecar_and_blocks_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            out_dir = root / "02_processed" / "source"
            out_dir.mkdir(parents=True)
            source.write_bytes(b"source")

            rows = [
                {
                    "filename": "rendered.mp4",
                    "status": "pass",
                    "max_similarity": 0.25,
                    "verdict": "PASS (distinct content)",
                }
            ]
            self.assertEqual(
                write_required_similarity_audit(
                    source, out_dir, audit_func=lambda _s, _o: rows
                ),
                rows,
            )
            sidecar = json.loads((out_dir / "_similarity.json").read_text())
            self.assertEqual(sidecar[0]["status"], "pass")

            with self.assertRaisesRegex(RuntimeError, "SSCD copy gate failed"):
                write_required_similarity_audit(
                    source,
                    out_dir,
                    audit_func=lambda _s, _o: [
                        {
                            "filename": "copy.mp4",
                            "status": "fail",
                            "verdict": "FAIL (copy detected)",
                        }
                    ],
                )

    def test_generated_asset_lineage_rejects_legacy_prompt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.json"
            legacy.write_text(
                '{"soul_id_2x3_prompt":"grid","kling_video_prompt":"motion","kling_negative_prompt":"bad"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unsupported fields"):
                load_asset_prompt_set(legacy)

    def test_job_key_changes_for_non_default_ratio(self):
        recipe = Recipe("v01_original")
        base = compute_job_key("video", "caption", recipe)
        feed = compute_job_key("video", "caption", recipe, target_ratio="4:5")
        self.assertNotEqual(base, feed)

    def test_phone_finalize_command_normalizes_social_mp4_metadata(self):
        created_at = "2026-05-14T06:30:00Z"
        cmd = build_phone_finalize_cmd(
            Path("tmp/in.mp4"), Path("tmp/out.mp4"), created_at, ffmpeg="ffmpeg"
        )
        joined = " ".join(cmd)

        self.assertEqual(cmd[-1], "tmp/out.mp4")
        self.assertIn("-c:v copy", joined)
        self.assertIn("-an", cmd)
        self.assertIn("-movflags +faststart", joined)
        self.assertIn("-map_metadata -1", joined)
        self.assertIn(f"creation_time={created_at}", cmd)
        self.assertIn("handler_name=Core Media Video", cmd)
        self.assertIn("-brand mp42", joined)

    def test_avconvert_finalize_command_uses_passthrough(self):
        cmd = build_avconvert_finalize_cmd(
            Path("tmp/in.mp4"), Path("tmp/out.mp4"), avconvert="avconvert"
        )
        joined = " ".join(cmd)
        self.assertEqual(cmd[0], "avconvert")
        self.assertIn("--preset PresetPassthrough", joined)
        self.assertIn("--source tmp/in.mp4", joined)
        self.assertIn("--output tmp/out.mp4", joined)
        self.assertIn("--replace", cmd)

    def test_rendered_mp4_metadata_normalization_is_required(self):
        with patch(
            "reel_pipeline.normalize_media_metadata",
            return_value={
                "metadataNormalized": True,
                "metadataWarnings": [],
            },
        ) as normalize:
            result = normalize_rendered_mp4_metadata(Path("tmp/out.mp4"))

        normalize.assert_called_once_with(Path("tmp/out.mp4"), dry_run=False)
        self.assertTrue(result["metadataNormalized"])

        with patch(
            "reel_pipeline.normalize_media_metadata",
            return_value={
                "metadataNormalized": False,
                "metadataWarnings": ["exiftool_unavailable"],
            },
        ):
            with self.assertRaisesRegex(
                RuntimeError, "metadata_normalization_failed:exiftool_unavailable"
            ):
                normalize_rendered_mp4_metadata(Path("tmp/out.mp4"))

    def test_production_render_requires_venv_and_insightface_provider(self):
        class FakeInsightFaceProvider:
            name = "insightface_arcface"

            def available(self):
                return True, "ok"

        class FakeUnavailableProvider:
            name = "unavailable"

            def available(self):
                return False, "missing"

        with patch("reel_pipeline.sys.executable", "/usr/bin/python3"):
            with self.assertRaisesRegex(
                RuntimeError, "production_render_requires_venv_python"
            ):
                enforce_production_identity_provider(True)

        with (
            patch("reel_pipeline.sys.executable", "/repo/.venv/bin/python"),
            patch(
                "reel_pipeline.get_identity_provider",
                return_value=FakeUnavailableProvider(),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "production_render_identity_provider_unavailable"
            ):
                enforce_production_identity_provider(True)

        with (
            patch("reel_pipeline.sys.executable", "/repo/.venv/bin/python"),
            patch(
                "reel_pipeline.get_identity_provider",
                return_value=FakeInsightFaceProvider(),
            ),
        ):
            result = enforce_production_identity_provider(True)

        self.assertEqual(result["provider"], "insightface_arcface")

    def test_phone_creation_time_uses_utc_mp4_timestamp_shape(self):
        created_at = phone_creation_time()
        self.assertIn("T", created_at)
        self.assertTrue(created_at.endswith("Z"))

    def test_reconcile_interrupted_temp_outputs_records_stale_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "02_processed"
            stale = proc / "clip_001" / ".tmp" / "abc123" / "out.mp4"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"partial")
            manifest = Manifest(root / "manifest.json")

            count = reconcile_interrupted_temp_outputs(proc, manifest)

            self.assertEqual(count, 1)
            row = manifest.conn.execute(
                "SELECT status FROM render_attempts WHERE status = 'interrupted'"
            ).fetchone()
            self.assertEqual(row["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
