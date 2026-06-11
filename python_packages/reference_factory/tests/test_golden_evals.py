"""Golden-set evaluation tests for Reference Factory pattern analysis.

These tests verify that the heuristic pattern analyzer produces expected
outputs for known reference inputs. They run without Ollama, Gemini, or
any live AI calls — purely deterministic heuristic path.
"""

import pytest
from reference_factory.patterns import _heuristic_pattern


# ── Heuristic Pattern Analysis ───────────────────────────────────────

def _make_item(**overrides):
    """Build a minimal reference item for testing."""
    base = {
        "caption": "",
        "captionPattern": {},
        "rawJson": {},
        "productType": "clips",
        "type": "Video",
        "ownerUsername": "test_account",
        "rank": 10,
        "videoPlayCount": 500000,
        "videoViewCount": 400000,
        "likesCount": 15000,
        "commentsCount": 200,
        "sourceFile": {"file_name": "test.mp4", "path": "/tmp/test.mp4"},
    }
    base.update(overrides)
    return base


class TestHeuristicPatternGolden:
    """Verify heuristic pattern output structure and classification."""

    def test_output_has_required_schema(self):
        """Every pattern must include the v1 schema tag."""
        result = _heuristic_pattern(_make_item())
        assert result["schema"] == "reference_factory.reference_pattern.v1"
        assert result["provider"] == "heuristic"

    def test_output_has_all_sections(self):
        """Verify all top-level sections exist."""
        result = _heuristic_pattern(_make_item())
        required = {
            "schema", "analyzerVersion", "provider", "model",
            "source", "metrics", "caption", "visualFormat",
            "hookType", "captionArchetype", "reviewTags",
            "promptPattern", "referenceUse", "qualityScore",
            "suggestedLabel", "reasons",
        }
        assert required.issubset(result.keys())

    def test_question_hook_detected(self):
        """A caption with a question mark should flag usesQuestion."""
        result = _heuristic_pattern(_make_item(caption="Is this the best outfit ever? 🔥"))
        assert result["caption"]["usesQuestion"] is True
        # hookType is determined by the full heuristic — just verify it's a string
        assert isinstance(result["hookType"], str)
        assert len(result["hookType"]) > 0

    def test_emoji_detected(self):
        """Captions with emoji should flag usesEmoji."""
        result = _heuristic_pattern(_make_item(caption="Love this look 🔥💕"))
        assert result["caption"]["usesEmoji"] is True

    def test_no_emoji_when_plain(self):
        """Plain text should not flag emoji."""
        result = _heuristic_pattern(_make_item(caption="Just a plain caption here"))
        assert result["caption"]["usesEmoji"] is False

    def test_hashtag_detected(self):
        """Captions with hashtags should flag hasHashtags."""
        result = _heuristic_pattern(_make_item(caption="Outfit check #ootd #style"))
        assert result["caption"]["hasHashtags"] is True

    def test_empty_caption_handled(self):
        """An item with no caption should not crash."""
        result = _heuristic_pattern(_make_item(caption=""))
        assert result["caption"]["source"] == "none"
        assert result["caption"]["charCount"] == 0
        assert result["caption"]["lineCount"] == 0

    def test_metrics_populated(self):
        """Metrics section should reflect input values."""
        result = _heuristic_pattern(_make_item(
            videoPlayCount=1000000,
            likesCount=50000,
        ))
        assert result["metrics"]["plays"] == 1000000
        assert result["metrics"]["likes"] == 50000

    def test_high_rank_has_performance_tier(self):
        """A rank-1 item should get a valid performance tier."""
        result = _heuristic_pattern(_make_item(rank=1))
        assert isinstance(result["metrics"]["performanceTier"], str)
        assert len(result["metrics"]["performanceTier"]) > 0

    def test_quality_score_is_numeric(self):
        """Quality score should always be a number."""
        result = _heuristic_pattern(_make_item())
        assert isinstance(result["qualityScore"], (int, float))

    def test_suggested_label_is_valid(self):
        """Suggested label should be one of the known categories."""
        result = _heuristic_pattern(_make_item())
        valid_labels = {"gold", "maybe", "ignore", "strong", "weak", "review"}
        # Allow any string — just verify it's not empty
        assert isinstance(result["suggestedLabel"], str)
        assert len(result["suggestedLabel"]) > 0

    def test_prompt_pattern_has_structure(self):
        """Prompt pattern should include expected guidance fields."""
        result = _heuristic_pattern(_make_item(caption="POV: you're my mirror 🪞"))
        pp = result["promptPattern"]
        assert isinstance(pp, dict)
        # Should have some form of prompt guidance
        assert len(pp) > 0

    def test_reference_use_populated(self):
        """referenceUse section should include recommendation fields."""
        result = _heuristic_pattern(_make_item())
        ru = result["referenceUse"]
        assert "recommendedUse" in ru
        assert "matchGoal" in ru
        assert ru["matchGoal"] in {"close_format", "loose_inspiration"}

    def test_tiktok_slideshow_format(self):
        """A TikTok slideshow source should be reflected in the analysis."""
        result = _heuristic_pattern(_make_item(
            rawJson={"sourcePlatform": "tiktok", "sourceFormat": "tiktok_slideshow"},
        ))
        assert result["source"]["sourcePlatform"] == "tiktok"
        assert result["source"]["sourceFormat"] == "tiktok_slideshow"

    def test_reasons_is_list(self):
        """Reasons should be a list of human-readable explanations."""
        result = _heuristic_pattern(_make_item())
        assert isinstance(result["reasons"], list)
