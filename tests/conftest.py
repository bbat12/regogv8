"""
Shared test fixtures for REGOG scoring tests.
"""

import sys
from pathlib import Path

# Add regog directory to sys.path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))


import pytest


@pytest.fixture
def standard_residential():
    """A baseline residential property with typical values."""
    return {
        "comp_count": 10,                     # Enough comps for reliable scoring
        "price_deviation_pct": -10.0,         # 10% below median → good deal
        "days_on_market": 45,                 # 31-90 days bracket → 10 pts
        "assessed_value": 350000,
        "list_price": 300000,                 # Below assessed value → positive gap
        "brain_classification": "standard",
        "flood_zone": "X",                    # Minimal flood risk
        "permit_flags": {"permit_risk": "unknown"},
    }


@pytest.fixture
def hot_deal_residential():
    """A screaming deal — deeply discounted, fresh listing, large assessor gap.
    Must score >= 100 for HOT tier with the new threshold system."""
    return {
        "comp_count": 10,                     # Enough comps for reliable scoring
        "price_deviation_pct": -60.0,         # -60% below median → 40 pts (max)
        "days_on_market": 0,                  # Fresh listing → 15 pts (max)
        "assessed_value": 400000,
        "list_price": 220000,                 # Assessed way above list → 20 pts (max)
        "brain_classification": "standard",    # Standard condition → 15 pts (max)
        "flood_zone": "X",                    # No flood risk → 10 pts (max)
        "permit_flags": {"permit_risk": "low"},  # Permits mentioned → +3 pts
    }


@pytest.fixture
def skip_residential():
    """An overpriced property with no signals."""
    return {
        "comp_count": 10,                     # Enough comps to avoid fallback
        "price_deviation_pct": 15.0,          # 15% above median → bad
        "days_on_market": 5,                  # 0-30 days → 15 pts
        "assessed_value": None,               # No assessor data
        "list_price": 500000,
        "brain_classification": "standard",
        "flood_zone": "AE",                   # High flood risk → penalty
        "permit_flags": {"permit_risk": "high"},  # Permit issues → penalty
    }


@pytest.fixture
def missing_data_residential():
    """Property with most data missing — tests default fallbacks."""
    return {
        "price_deviation_pct": None,
        "days_on_market": None,
        "assessed_value": None,
        "list_price": None,
        "brain_classification": None,
        "flood_zone": None,
        "permit_flags": {},
    }


@pytest.fixture
def distressed_residential():
    """Fire-damaged property — should get DISTRESSED_ prefix."""
    return {
        "comp_count": 10,                     # Enough comps to avoid fallback
        "price_deviation_pct": -30.0,
        "days_on_market": 90,
        "assessed_value": 300000,
        "list_price": 200000,
        "brain_classification": "fire_damage",
        "flood_zone": "X",
        "permit_flags": {"permit_risk": "unknown"},
    }
