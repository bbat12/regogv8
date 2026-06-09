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
    """Tests for lead tier assignment based on score thresholds (3-tier system)."""

    def test_hot_threshold_exact(self):
        """Score >= 100 is HOT."""
        assert assign_tier(100) == "HOT"

    def test_hot_above(self):
        """Scores above 100 (uncapped) are HOT."""
        assert assign_tier(120) == "HOT"
        assert assign_tier(200) == "HOT"

    def test_medium_above_hot_threshold(self):
        """Score 70 was previously HOT, now MEDIUM."""
        assert assign_tier(70) == "MEDIUM"

    def test_medium_threshold(self):
        """Score >= 50 is MEDIUM."""
        assert assign_tier(50) == "MEDIUM"

    def test_medium_below_hot(self):
        """Score 99 is still MEDIUM (below HOT threshold of 100)."""
        assert assign_tier(99) == "MEDIUM"

    def test_warm_below_medium(self):
        """Score 30 is WARM (below MEDIUM threshold of 50)."""
        assert assign_tier(30) == "WARM"

    def test_warm_threshold(self):
        """Score >= 0 is WARM."""
        assert assign_tier(0) == "WARM"

    def test_warm_above_zero(self):
        """Score 25 is WARM."""
        assert assign_tier(25) == "WARM"

    def test_negative_score_skip(self):
        """Negative scores fall through to SKIP."""
        assert assign_tier(-5) == "SKIP"
        assert assign_tier(-1) == "SKIP"

    def test_boundary_medium_hot(self):
        """Score 99.9 is MEDIUM, 100.0 is HOT."""
        assert assign_tier(99.9) == "MEDIUM"
        assert assign_tier(100.0) == "HOT"

    def test_boundary_warm_medium(self):
        """Score 49.9 is WARM, 50.0 is MEDIUM."""
        assert assign_tier(49.9) == "WARM"
        assert assign_tier(50.0) == "MEDIUM"

    def test_all_tiers_returned_for_valid_scores(self):
        """Test that each tier can be hit with appropriate scores."""
        tiers_found = set()
        for score in [0, 50, 100, 120]:
            tiers_found.add(assign_tier(score))
        # Should cover all defined tiers (HOT, MEDIUM, WARM)
        for tier in TIER_THRESHOLDS:
            assert tier in tiers_found, f"Tier {tier} not hit by any score"


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
