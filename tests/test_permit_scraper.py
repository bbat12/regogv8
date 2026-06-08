"""
Tests for permit scraper — keyword inference and risk classification.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))

import pytest
from scrapers.permit_scraper import infer_permits_from_description


class TestInferPermits:
    """Tests for description-based permit inference."""

    def test_no_description(self):
        result = infer_permits_from_description(None)
        assert result["permit_risk"] == "unknown"
        assert not result["unpermitted_additions"]
        assert not result["has_permits"]
        assert result["code_violations"] == []
        assert result["recent_permits"] == []

    def test_unpermitted_addition_detected(self):
        desc = "Beautiful home with unpermitted addition in backyard"
        result = infer_permits_from_description(desc)
        assert result["unpermitted_additions"] is True
        assert result["permit_risk"] == "high"

    def test_no_permit_detected(self):
        desc = "Sold as-is with no permit for garage conversion"
        result = infer_permits_from_description(desc)
        assert result["unpermitted_additions"] is True
        assert result["permit_risk"] == "high"

    def test_code_violation_detected(self):
        desc = "Property has active building code violation notices"
        result = infer_permits_from_description(desc)
        assert len(result["code_violations"]) > 0
        assert result["permit_risk"] == "high"

    def test_red_tagged_property(self):
        desc = "Red-tagged by city — needs major repairs"
        result = infer_permits_from_description(desc)
        assert len(result["code_violations"]) > 0
        assert result["permit_risk"] == "high"

    def test_permitted_renovation_low_risk(self):
        desc = "Fully permitted kitchen remodel with approved plans"
        result = infer_permits_from_description(desc)
        assert result["permit_risk"] == "low"
        assert result["has_permits"] is True
        assert len(result["recent_permits"]) > 0

    def test_building_permit_mentioned(self):
        desc = "All work done with proper building permits"
        result = infer_permits_from_description(desc)
        assert result["permit_risk"] == "low"
        assert result["has_permits"] is True

    def test_no_signals_unknown_risk(self):
        desc = "Charming 3 bed, 2 bath home with hardwood floors"
        result = infer_permits_from_description(desc)
        assert result["permit_risk"] == "unknown"
        assert not result["unpermitted_additions"]
        assert not result["has_permits"]
        assert result["code_violations"] == []
        assert result["recent_permits"] == []

    def test_multiple_violations_accumulated(self):
        desc = "Has unpermitted addition and code violation for electrical"
        result = infer_permits_from_description(desc)
        assert result["unpermitted_additions"] is True
        assert len(result["code_violations"]) >= 2
        assert result["permit_risk"] == "high"

    def test_condemned_property(self):
        desc = "Property is condemned by the city — uninhabitable"
        result = infer_permits_from_description(desc)
        assert any("condemned" in v.lower() for v in result["code_violations"])
        assert result["permit_risk"] == "high"

    def test_case_insensitivity(self):
        desc = "UNPERMITTED ADDITION — needs work"
        result = infer_permits_from_description(desc)
        assert result["unpermitted_additions"] is True

    def test_approved_plans_positive_signal(self):
        desc = "Approved plans for ADU — ready to build"
        result = infer_permits_from_description(desc)
        assert result["permit_risk"] == "low"

    def test_permit_as_positive_not_unpermitted(self):
        """The word 'permit' itself should be a positive signal, not a violation."""
        desc = "New roof with proper permits"
        result = infer_permits_from_description(desc)
        # 'permit' is in RENOVATION_PERMIT_SIGNALS but NOT in UNPERMITTED_SIGNALS
        assert not result["unpermitted_additions"]
        assert result["has_permits"] is True

    def test_mixed_signals_high_risk_wins(self):
        """If both positive and negative signals exist, high risk wins."""
        desc = "Unpermitted garage conversion but renovated kitchen"
        result = infer_permits_from_description(desc)
        assert result["unpermitted_additions"] is True
        # high should win over low
        assert result["permit_risk"] == "high"
