"""
Tests for scoring utilities.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))

import pytest
from scoring.utils import assign_tier, parse_flags
from config import TIER_THRESHOLDS


class TestAssignTier:
    """Tests for lead tier assignment based on score thresholds."""

    def test_hot_threshold_exact(self):
        assert assign_tier(70) == "HOT"

    def test_hot_above(self):
        assert assign_tier(95) == "HOT"
        assert assign_tier(100) == "HOT"

    def test_warm_threshold(self):
        assert assign_tier(50) == "WARM"

    def test_warm_below_hot(self):
        assert assign_tier(69) == "WARM"

    def test_neutral_threshold(self):
        assert assign_tier(35) == "NEUTRAL"

    def test_risky_threshold(self):
        assert assign_tier(20) == "RISKY"

    def test_skip_below_risky(self):
        assert assign_tier(5) == "SKIP"
        assert assign_tier(0) == "SKIP"

    def test_negative_score_still_skip(self):
        # Permit modifier can make total negative
        assert assign_tier(-5) == "SKIP"

    def test_boundary_warm_hot(self):
        assert assign_tier(69.9) == "WARM"
        assert assign_tier(70.0) == "HOT"

    def test_all_tiers_returned_for_valid_scores(self):
        """Test that each tier can be hit with appropriate scores."""
        tiers_found = set()
        # Score 20 maps to RISKY (not 10 — that's SKIP)
        for score in [0, 20, 35, 50, 70, 100]:
            tiers_found.add(assign_tier(score))
        # All tiers should be represented
        assert tiers_found == set(TIER_THRESHOLDS.keys())


class TestParseFlags:
    """Tests for flag parsing utility (red/green flags)."""

    def test_parses_list_identity(self):
        """Already a list → return as-is."""
        flags = ["renovated", "new roof"]
        assert parse_flags(flags) == flags

    def test_parses_json_string(self):
        """JSON string → parsed to list."""
        flags = '["renovated", "new roof"]'
        assert parse_flags(flags) == ["renovated", "new roof"]

    def test_parses_empty_list(self):
        assert parse_flags([]) == []

    def test_parses_empty_json_array(self):
        assert parse_flags("[]") == []

    def test_parses_none(self):
        assert parse_flags(None) == []

    def test_parses_invalid_json_returns_empty(self):
        assert parse_flags("not valid json") == []

    def test_parses_empty_string(self):
        assert parse_flags("") == []

    def test_parses_single_flag(self):
        assert parse_flags('["structural"]') == ["structural"]

    def test_parses_special_chars(self):
        flags = '["foundation issues", "termites"]'
        assert parse_flags(flags) == ["foundation issues", "termites"]

    def test_list_with_mixed_types(self):
        # If list contains non-strings, they're just passed through
        flags = ["renovated", 123, None]
        parsed = parse_flags(flags)
        assert len(parsed) == 3
