"""Golden-set evaluation tests for Reel Factory deterministic operations.

These tests verify that critical pipeline functions produce expected outputs
for known inputs. They run without live AI calls and should never drift
unless the function behavior intentionally changes.
"""

import pytest
from generate_prompts import (
    clean_direct_higgsfield_prompt,
    normalize_grid_layout,
)

# ── Grid Layout Normalization ────────────────────────────────────────


class TestGridLayoutGolden:
    """Verify grid layout normalization against known golden inputs."""

    def test_default_is_3x2(self):
        result = normalize_grid_layout(None)
        assert result["kind"] == "grid"
        assert result["columns"] == 3
        assert result["rows"] == 2
        assert result["panel_count"] == 6

    def test_empty_string_is_3x2(self):
        result = normalize_grid_layout("")
        assert result["columns"] == 3
        assert result["rows"] == 2

    @pytest.mark.parametrize("alias", ["3x2", "2x3", "six", "six-panel", "sixpanel"])
    def test_six_panel_aliases(self, alias):
        result = normalize_grid_layout(alias)
        assert result["panel_count"] == 6
        assert result["kind"] == "grid"

    def test_single_image(self):
        result = normalize_grid_layout("single")
        assert result["kind"] == "single"
        assert result["columns"] == 1
        assert result["rows"] == 1
        assert result["panel_count"] == 1

    @pytest.mark.parametrize("alias", ["1", "single-image", "singleimage", "1x1"])
    def test_single_aliases(self, alias):
        result = normalize_grid_layout(alias)
        assert result["kind"] == "single"
        assert result["panel_count"] == 1

    def test_custom_grid_4x2(self):
        result = normalize_grid_layout("4x2")
        assert result["columns"] == 4
        assert result["rows"] == 2
        assert result["panel_count"] == 8

    def test_custom_grid_3x3(self):
        result = normalize_grid_layout("3x3")
        assert result["columns"] == 3
        assert result["rows"] == 3
        assert result["panel_count"] == 9

    def test_invalid_grid_raises(self):
        with pytest.raises(ValueError, match="unsupported grid_layout"):
            normalize_grid_layout("banana")

    def test_invalid_large_grid_raises(self):
        with pytest.raises(ValueError):
            normalize_grid_layout("10x10")


# ── Prompt Cleanup ───────────────────────────────────────────────────


class TestPromptCleanupGolden:
    """Verify removal-only prompt cleanup against known golden cases."""

    def test_clean_prompt_passes_through(self):
        """A prompt with no forbidden terms should pass through unchanged."""
        clean = "A woman in a red dress standing by a window, soft natural light"
        result = clean_direct_higgsfield_prompt(clean)
        assert result["cleaned"] == clean
        assert result["changed"] is False
        assert result["valid"] is True
        assert result["diff"] == []

    def test_returns_required_structure(self):
        """Verify all expected keys are present in the result dict."""
        result = clean_direct_higgsfield_prompt("test prompt")
        required_keys = {
            "raw",
            "cleaned",
            "diff",
            "removed",
            "residualForbiddenTerms",
            "valid",
            "changed",
            "policy",
        }
        assert required_keys.issubset(result.keys())

    def test_policy_is_removal_only(self):
        """Confirm the cleanup policy is always removal-only."""
        result = clean_direct_higgsfield_prompt("any prompt")
        assert "removal_only" in result["policy"]

    def test_raw_is_preserved(self):
        """The raw field should always contain the original input."""
        original = "  some prompt with spaces  "
        result = clean_direct_higgsfield_prompt(original)
        assert result["raw"] == original.strip()

    def test_empty_prompt(self):
        """Empty prompt should not crash."""
        result = clean_direct_higgsfield_prompt("")
        assert result["valid"] is True
        assert result["changed"] is False


# ── Lineage Structure ────────────────────────────────────────────────


class TestLineageStructureGolden:
    """Verify that prompt cleanup output has the right shape for lineage."""

    def test_diff_entries_have_action(self):
        """If any diff entries exist, each must have an action field."""
        result = clean_direct_higgsfield_prompt("test with flawless skin glow")
        for entry in result["diff"]:
            assert "action" in entry
            assert entry["action"] in {"remove", "replace", "repair_punctuation"}

    def test_removed_list_matches_diff(self):
        """The removed list should match remove-action diffs."""
        result = clean_direct_higgsfield_prompt("test prompt")
        remove_count = sum(1 for d in result["diff"] if d["action"] == "remove")
        assert len(result["removed"]) == remove_count
