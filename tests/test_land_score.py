"""
Tests for land scoring module.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))

import pytest
from scoring.land_score import score_land


class TestLandScore:
    """Tests for land property scoring."""

    def test_buildable_zoning_max_bonus(self):
        prop = {"zoning": "R1", "acres": 5, "price_deviation_pct": 0, "flood_zone": "X"}
        result = score_land(prop)
        assert result["scores"]["zoning_bonus"] == 20
        assert result["scores"]["acreage_premium"] == 8  # 1 < 5 ≤ 5 bracket → 8 pts
        assert result["total"] > 0

    def test_non_buildable_zoning_penalty(self):
        prop = {"zoning": "AG", "acres": 10, "price_deviation_pct": 0, "flood_zone": "X"}
        result = score_land(prop)
        assert result["scores"]["zoning_bonus"] == 2

    def test_small_parcel_premium(self):
        prop = {"acres": 0.5, "price_deviation_pct": 0, "flood_zone": "X"}
        result = score_land(prop)
        assert result["scores"]["acreage_premium"] == 10

    def test_large_parcel_discount(self):
        prop = {"acres": 50, "price_deviation_pct": 0, "flood_zone": "X"}
        result = score_land(prop)
        assert result["scores"]["acreage_premium"] == 2

    def test_empty_dict_defaults(self):
        result = score_land({})
        assert isinstance(result["total"], (int, float))
        assert isinstance(result["tier"], str)
