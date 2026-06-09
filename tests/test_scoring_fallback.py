"""
Tests for the comp_count=0 fallback path in residential and commercial scoring.

Verifies that the scoring functions handle the edge case where no comparable
sales exist but an estimated_value is available as a proxy. The apply_comp_fallback()
utility adds "_fb_" prefixed metadata keys to the scores dict, and both scorers
must filter those out before summing.

Covers the fix applied to:
  - residential_score.py: sum(v for k, v in scores.items() if not k.startswith("_fb_"))
  - commercial_score.py: sum(v for k, v in scores.items() if not k.startswith("_fb_"))
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))

import pytest
from scoring.residential_score import score_residential
from scoring.commercial_score import score_commercial


class TestResidentialFallback:
    """Tests for score_residential() with comp_count=0 and estimated_value present."""

    def test_fallback_with_estimated_value(self):
        """comp_count=0 with valid estimated_value should return numeric total, no TypeError."""
        prop = {
            "comp_count": 0,
            "estimated_value": 250000,
            "list_price": 200000,
            "days_on_market": 45,
            "assessed_value": None,
            "brain_classification": "standard",
            "flood_zone": "X",
            "permit_flags": {"permit_risk": "unknown"},
        }
        result = score_residential(prop)
        assert isinstance(result["total"], (int, float))
        assert result["total"] >= 0
        assert "scores" in result
        assert "tier" in result

    def test_fallback_with_zero_estimated_value(self):
        """comp_count=0 with estimated_value=0 should still produce valid numeric total."""
        prop = {
            "comp_count": 0,
            "estimated_value": 0,
            "list_price": 200000,
            "days_on_market": 45,
            "assessed_value": None,
            "brain_classification": "standard",
            "flood_zone": "X",
            "permit_flags": {"permit_risk": "unknown"},
        }
        result = score_residential(prop)
        assert isinstance(result["total"], (int, float))
        assert "scores" in result
        assert "tier" in result

    def test_fallback_scores_are_numeric(self):
        """Non-metadata score components should be numbers, not strings."""
        prop = {
            "comp_count": 0,
            "estimated_value": 250000,
            "list_price": 200000,
            "days_on_market": 45,
            "assessed_value": None,
            "brain_classification": "standard",
            "flood_zone": "X",
            "permit_flags": {"permit_risk": "unknown"},
        }
        result = score_residential(prop)
        # Only check non-metadata keys (skip _fb_ metadata fields)
        for key, value in result["scores"].items():
            if key.startswith("_fb_"):
                continue
            assert isinstance(value, (int, float)), (
                f"Score component '{key}' is {type(value).__name__}, expected numeric. "
                f"Value: {value!r}"
            )


class TestCommercialFallback:
    """Tests for score_commercial() with comp_count=0 and estimated_value present."""

    def test_fallback_with_estimated_value(self):
        """comp_count=0 with valid estimated_value should return numeric total, no TypeError."""
        prop = {
            "comp_count": 0,
            "estimated_value": 500000,
            "list_price": 400000,
            "commercial_subtype": "multifamily",
            "assessed_value": None,
            "brain_classification": "standard",
            "flood_zone": "X",
            "style": "MULTI_FAMILY",
            "city": "Dallas",
            "state": "TX",
        }
        result = score_commercial(prop)
        assert isinstance(result["total"], (int, float))
        assert result["total"] >= 0
        assert "scores" in result
        assert "tier" in result

    def test_fallback_scores_are_numeric(self):
        """Non-metadata score components should be numbers, not strings, after fallback."""
        prop = {
            "comp_count": 0,
            "estimated_value": 500000,
            "list_price": 400000,
            "commercial_subtype": "multifamily",
            "assessed_value": None,
            "brain_classification": "standard",
            "flood_zone": "X",
            "style": "MULTI_FAMILY",
            "city": "Dallas",
            "state": "TX",
        }
        result = score_commercial(prop)
        # Only check non-metadata keys (skip _fb_ metadata fields)
        for key, value in result["scores"].items():
            if key.startswith("_fb_"):
                continue
            assert isinstance(value, (int, float)), (
                f"Score component '{key}' is {type(value).__name__}, expected numeric. "
                f"Value: {value!r}"
            )
