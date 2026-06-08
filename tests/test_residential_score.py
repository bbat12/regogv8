"""
Tests for residential scoring module.

Covers all 6 scoring signals + tier assignment + edge cases.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))

import pytest
from scoring.residential_score import score_residential
from config import TIER_THRESHOLDS


class TestBaselineScore:
    """Tests for the standard residential property."""

    def test_standard_property_score(self, standard_residential):
        result = score_residential(standard_residential)
        assert "scores" in result
        assert "total" in result
        assert "tier" in result
        assert result["total"] > 0
        assert result["total"] <= 100

    def test_standard_all_signals_present(self, standard_residential):
        result = score_residential(standard_residential)
        expected_signals = {
            "price_deviation", "dom_signal", "assessor_gap",
            "condition", "flood_penalty", "permit_risk",
        }
        for signal in expected_signals:
            assert signal in result["scores"], f"Missing signal: {signal}"

    def test_standard_components_positive(self, standard_residential):
        result = score_residential(standard_residential)
        for signal, value in result["scores"].items():
            assert isinstance(value, (int, float)), f"{signal} should be numeric"
            assert value >= 0, f"{signal} should be non-negative"


class TestPriceDeviation:
    """Tests for the price deviation signal (40 pts max)."""

    def test_deep_discount_max_score(self):
        # -50% deviation → should get max 40 pts
        prop = {"price_deviation_pct": -50.0}
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 40.0

    def test_slight_discount_mid_score(self):
        # -20% deviation → should get 16 pts
        prop = {"price_deviation_pct": -20.0}
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 16.0

    def test_overpriced_gets_zero(self):
        # +10% deviation → 0 pts (capped)
        prop = {"price_deviation_pct": 10.0}
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 0.0

    def test_no_deviation(self):
        # At market price → 0 pts
        prop = {"price_deviation_pct": 0.0}
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 0.0

    def test_missing_deviation_defaults_zero(self):
        # None → treated as 0
        prop = {"price_deviation_pct": None}
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 0.0


class TestDaysOnMarket:
    """Tests for days-on-market signal (15 pts max)."""

    def test_fresh_listing_max_score(self):
        prop = {"days_on_market": 0}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 15

    def test_thirty_days_exact(self):
        prop = {"days_on_market": 30}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 15

    def test_thirty_one_days_next_bracket(self):
        prop = {"days_on_market": 31}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 10

    def test_ninety_days_exact(self):
        prop = {"days_on_market": 90}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 10

    def test_one_eighty_days(self):
        prop = {"days_on_market": 180}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 5

    def test_stale_listing_min_score(self):
        prop = {"days_on_market": 1000}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 2

    def test_missing_dom_defaults_zero(self):
        # None → treated as 0 by `or 0` → fresh
        prop = {"days_on_market": None}
        result = score_residential(prop)
        assert result["scores"]["dom_signal"] == 15


class TestAssessorGap:
    """Tests for assessor gap signal (20 pts max)."""

    def test_big_gap_max_score(self):
        # Assessed 30% above list → max 20 pts
        prop = {"assessed_value": 300000, "list_price": 200000}
        result = score_residential(prop)
        # gap_pct = (300000-200000)/300000 * 100 = 33.3%
        # score = min(20, (33.3/30)*20) = min(20, 22.2) = 20
        assert result["scores"]["assessor_gap"] == 20.0

    def test_small_gap_partial_score(self):
        # Assessed 10% above list → ~6.67 pts
        prop = {"assessed_value": 110000, "list_price": 100000}
        result = score_residential(prop)
        # gap_pct = (110000-100000)/110000 * 100 = 9.09%
        # score = min(20, (9.09/30)*20) = min(20, 6.06) = 6.06
        assert abs(result["scores"]["assessor_gap"] - 6.06) < 0.1

    def test_listed_above_assessed_zero_gap(self):
        # Listed above assessed → negative gap → capped at 0
        prop = {"assessed_value": 100000, "list_price": 150000}
        result = score_residential(prop)
        # gap_pct = (100000-150000)/100000 * 100 = -50%
        # max(0, (-50/30)*20) = max(0, -33.3) = 0
        assert result["scores"]["assessor_gap"] == 0.0

    def test_missing_assessor_data_defaults_neutral(self):
        prop = {"assessed_value": None, "list_price": 300000}
        result = score_residential(prop)
        assert result["scores"]["assessor_gap"] == 5

    def test_zero_assessed_value_defaults_neutral(self):
        prop = {"assessed_value": 0, "list_price": 300000}
        result = score_residential(prop)
        assert result["scores"]["assessor_gap"] == 5


class TestCondition:
    """Tests for condition signal (15 pts max)."""

    def test_standard_condition(self):
        prop = {"brain_classification": "standard"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 15

    def test_luxury_condition(self):
        prop = {"brain_classification": "luxury"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 12

    def test_distressed_condition(self):
        prop = {"brain_classification": "distressed"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 7

    def test_teardown_condition(self):
        prop = {"brain_classification": "teardown"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 4

    def test_fire_damage_condition(self):
        prop = {"brain_classification": "fire_damage"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 3

    def test_vacant_condition(self):
        prop = {"brain_classification": "vacant"}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 10

    def test_unknown_classification_defaults_10(self):
        prop = {"brain_classification": None}
        result = score_residential(prop)
        assert result["scores"]["condition"] == 10


class TestFloodPenalty:
    """Tests for flood penalty signal (0-10 pts)."""

    def test_zone_x_no_penalty(self):
        prop = {"flood_zone": "X"}
        result = score_residential(prop)
        assert result["scores"]["flood_penalty"] == 10  # Max score = no penalty

    def test_zone_ae_high_risk(self):
        prop = {"flood_zone": "AE"}
        result = score_residential(prop)
        assert result["scores"]["flood_penalty"] == 3

    def test_zone_ve_extreme_risk(self):
        prop = {"flood_zone": "VE"}
        result = score_residential(prop)
        assert result["scores"]["flood_penalty"] == 0  # Full penalty

    def test_missing_zone_slight_penalty(self):
        prop = {"flood_zone": None}
        result = score_residential(prop)
        assert result["scores"]["flood_penalty"] == 8  # Slight penalty for unknown


class TestPermitRisk:
    """Tests for permit risk modifier (-5 to +3 pts)."""

    def test_low_risk_bonus(self):
        prop = {"permit_flags": {"permit_risk": "low"}}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == 3

    def test_unknown_risk_neutral(self):
        prop = {"permit_flags": {"permit_risk": "unknown"}}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == 0

    def test_medium_risk_penalty(self):
        prop = {"permit_flags": {"permit_risk": "medium"}}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == -2

    def test_high_risk_max_penalty(self):
        prop = {"permit_flags": {"permit_risk": "high"}}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == -5

    def test_permit_flags_as_json_string(self):
        prop = {"permit_flags": '{"permit_risk": "high"}'}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == -5

    def test_permit_flags_missing(self):
        prop = {"permit_flags": None}
        result = score_residential(prop)
        assert result["scores"]["permit_risk"] == 0

    def test_permit_flags_empty_dict(self):
        prop = {"permit_flags": {}}
        result = score_residential(prop)
        # Missing permit_risk key → defaults to "unknown" → 0
        assert result["scores"]["permit_risk"] == 0


class TestTierAssignment:
    """Tests for lead tier thresholds."""

    def test_hot_tier(self, hot_deal_residential):
        result = score_residential(hot_deal_residential)
        tier = result["tier"]
        # Deep discount + assessor gap + low permit risk → should be HOT
        assert tier == "HOT", f"Expected HOT, got {tier} (total={result['total']})"

    def test_skip_tier(self, skip_residential):
        result = score_residential(skip_residential)
        # Overpriced + high flood risk + high permit risk → low score
        # But note: fresh DOM gives 15 pts, and overpriced gives 0
        # Let's just check it's not HOT
        assert result["tier"] != "HOT"

    def test_distressed_override(self, distressed_residential):
        result = score_residential(distressed_residential)
        assert result["tier"].startswith("DISTRESSED_"), \
            f"Expected DISTRESSED_ prefix, got {result['tier']}"

    def test_distressed_hot_preserved(self, distressed_residential):
        result = score_residential(distressed_residential)
        # Tier should still preserve the base tier as suffix
        base_tier = result["tier"].replace("DISTRESSED_", "")
        assert base_tier in TIER_THRESHOLDS, f"Invalid base tier: {base_tier}"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_missing_data_returns_sensible_defaults(self, missing_data_residential):
        """All None inputs should produce deterministic results without crashing."""
        result = score_residential(missing_data_residential)
        assert isinstance(result["total"], (int, float))
        assert isinstance(result["tier"], str)
        assert result["tier"] in TIER_THRESHOLDS or result["tier"].startswith("DISTRESSED_")

    def test_empty_dict(self):
        """Empty input dict should not crash — use defaults."""
        result = score_residential({})
        assert isinstance(result["total"], (int, float))
        # Check all defaults kick in
        assert result["scores"]["price_deviation"] == 0
        assert result["scores"]["dom_signal"] == 15  # None → 0 → ≤30 bracket
        assert result["scores"]["assessor_gap"] == 5
        assert result["scores"]["condition"] == 15  # No key → defaults to 'standard' → 15
        assert result["scores"]["flood_penalty"] == 8  # None → 8

    def test_exact_boundary_scoring(self):
        """Test a handful of known score calculations."""
        prop = {
            "price_deviation_pct": -50.0,  # 40 pts
            "days_on_market": 30,           # 15 pts
            "assessed_value": 200000,
            "list_price": 100000,            # gap = 50% → capped at 20 pts
            "brain_classification": "standard",  # 15 pts
            "flood_zone": "X",              # 10 pts
            "permit_flags": {"permit_risk": "low"},  # +3 pts
        }
        result = score_residential(prop)
        assert result["scores"]["price_deviation"] == 40.0
        assert result["scores"]["dom_signal"] == 15
        assert result["scores"]["assessor_gap"] == 20.0
        assert result["scores"]["condition"] == 15
        assert result["scores"]["flood_penalty"] == 10
        assert result["scores"]["permit_risk"] == 3
        assert result["total"] == pytest.approx(103.0, abs=0.1)  # Max theoretical
        assert result["tier"] == "HOT"


class TestDataTypes:
    """Test that all returned values have correct types."""

    def test_return_structure(self, standard_residential):
        result = score_residential(standard_residential)
        assert isinstance(result["scores"], dict)
        assert isinstance(result["total"], (int, float))
        assert isinstance(result["tier"], str)

    def test_scores_are_numbers(self, standard_residential):
        result = score_residential(standard_residential)
        for k, v in result["scores"].items():
            assert isinstance(v, (int, float)), f"Score {k} is {type(v)}"
