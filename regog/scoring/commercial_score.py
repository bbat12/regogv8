"""
Commercial Scoring — 0-100 score for commercial properties.
Routes by commercial_subtype for specialized scoring.
"""

import re
from typing import Optional
from config import COMMERCIAL_WEIGHTS, TIER_THRESHOLDS, FLOOD_SCORES, CONDITION_SCORES
from scoring.utils import assign_tier, apply_comp_fallback, cap_score_if_no_comps, apply_confidence_cap, apply_variance_penalty, score_price_deviation


def score_commercial(property_dict: dict) -> dict:
    """
    Score a commercial property from 0-100.

    Routes by commercial_subtype:
    - multifamily: price per unit vs comps
    - hotel/motel: price per room vs comps
    - industrial: price per sqft vs comps
    - office/retail: price per sqft vs comps
    - skyscraper: assessed value gap heavily weighted
    """
    scores = {}
    subtype = (property_dict.get("commercial_subtype") or "").lower()

    # 1. Price deviation (35 pts max, uses percentile-band scoring)
    list_price = property_dict.get("list_price") or 0
    comp_median = property_dict.get("comp_median_price")
    conf_label = property_dict.get("comp_confidence_label", "HIGH")
    if comp_median and list_price > 0:
        raw_pdev = score_price_deviation(
            float(list_price),
            float(comp_median),
            comp_confidence=conf_label or "HIGH",
        )
        # Scale from 40 max to 35 max for commercial
        scores["price_deviation"] = round((raw_pdev / 40.0) * 35.0, 1)
    else:
        scores["price_deviation"] = 0.0

    # 2. Assessor gap (25 pts max — weighted higher for skyscrapers)
    assessed = property_dict.get("assessed_value")
    listed = property_dict.get("list_price")
    if assessed and listed and assessed > 0:
        gap_pct = ((assessed - listed) / assessed) * 100
        if subtype == "skyscraper":
            # For skyscrapers, assessor gap is the primary signal
            scores["assessor_gap"] = max(0, min(25, (gap_pct / 20) * 25))
        else:
            scores["assessor_gap"] = max(0, min(25, (gap_pct / 30) * 25))
    else:
        scores["assessor_gap"] = 8

    # 3. Cap rate estimate (20 pts max)
    # Estimate cap rate from description keywords or price/rent signals
    scores["cap_rate_estimate"] = _estimate_cap_rate(property_dict)

    # 4. Condition (10 pts max)
    classification = property_dict.get("brain_classification", "standard")
    scores["condition"] = CONDITION_SCORES.get(classification, 10) * (10 / 15)  # Scale to 10 pts

    # 5. Flood penalty (10 pts max — deduction)
    # Unknown zone = 0 penalty (Part 1 fix)
    flood_zone = property_dict.get("flood_zone")
    if not flood_zone or flood_zone == "UNKNOWN":
        scores["flood_penalty"] = 0.0
    else:
        scores["flood_penalty"] = FLOOD_SCORES.get(flood_zone, 0)

    # Apply comp fallback: when comp_count=0, use estimated_value as proxy
    scores = apply_comp_fallback(property_dict, scores)

    # Apply confidence cap: if comp_confidence_label is LOW/MEDIUM, cap price_deviation
    scores = apply_confidence_cap(property_dict, scores)

    # Apply variance penalty: high-variance comps reduce price signal reliability
    scores = apply_variance_penalty(property_dict, scores)

    # Total
    # Filter out _fb_ metadata keys (strings, booleans) — only numeric score keys
    total = sum(v for k, v in scores.items() if not k.startswith("_fb_"))
    total, _ = cap_score_if_no_comps(total, scores)

    # Lead tier
    tier = assign_tier(total)

    # NOTE: DISTRESSED_ prefix removed per Part 3 fix.
    # Tier stores ONLY the scoring tier (HOT/WARM/NEUTRAL/RISKY/SKIP).
    # Brain classification is stored separately.

    return {
        "scores": scores,
        "total": round(total, 1),
        "tier": tier,
    }


def estimate_cap_rate(property_dict: dict) -> dict:
    """
    Estimate cap rate using Gross Rent Multiplier (GRM) method.
    Uses market-average rent estimates — no external API needed.
    Returns dict with estimated NOI, GRM, and cap rate.
    """
    list_price = property_dict.get("list_price") or 0
    style = (property_dict.get("style") or "").upper()
    city = property_dict.get("city") or ""
    state = (property_dict.get("state") or "").upper()
    sqft = property_dict.get("sqft")
    units = property_dict.get("units") or property_dict.get("beds")

    if list_price <= 0:
        return {
            "estimated_noi": 0,
            "estimated_cap_rate": 0,
            "estimated_grm": 0,
            "rent_psf_used": 0,
            "is_estimated": True,
        }

    # Market rent estimates per sqft per month (conservative)
    MARKET_RENTS_PSF = {
        ("CA", "MULTI_FAMILY"): 2.50,
        ("NY", "MULTI_FAMILY"): 3.00,
        ("IL", "MULTI_FAMILY"): 1.50,
        ("TX", "MULTI_FAMILY"): 1.20,
        ("FL", "MULTI_FAMILY"): 1.40,
        ("GA", "MULTI_FAMILY"): 1.10,
        ("DEFAULT", "MULTI_FAMILY"): 1.25,
        ("DEFAULT", "RETAIL"): 1.50,
        ("DEFAULT", "OFFICE"): 1.75,
        ("DEFAULT", "INDUSTRIAL"): 0.75,
        ("DEFAULT", "MIXED_USE"): 1.40,
        ("DEFAULT", "CONDOS"): 1.50,
        ("DEFAULT", "TOWNHOMES"): 1.30,
        ("DEFAULT", "MOBILE"): 0.60,
        ("DEFAULT", "APARTMENT"): 1.25,
    }

    key = (state, style)
    default_key = ("DEFAULT", style)
    fallback_key = ("DEFAULT", "MULTI_FAMILY")
    rent_psf = (
        MARKET_RENTS_PSF.get(key)
        or MARKET_RENTS_PSF.get(default_key)
        or MARKET_RENTS_PSF.get(fallback_key)
    )

    # Estimate sqft from price if missing (rough: $150-300/sqft)
    if not sqft or sqft <= 0:
        sqft = list_price / 200

    # Estimate Gross Rental Income
    monthly_gross = sqft * rent_psf
    annual_gross = monthly_gross * 12

    # Apply vacancy rate (10% standard)
    effective_gross = annual_gross * 0.90

    # Apply expense ratio (40% standard for multifamily)
    expense_ratio = 0.40
    noi = effective_gross * (1 - expense_ratio)

    # Cap rate = NOI / Price
    cap_rate = (noi / list_price) * 100 if list_price > 0 else 0

    # GRM = Price / Annual Gross Rent
    grm = list_price / annual_gross if annual_gross > 0 else 0

    return {
        "estimated_noi": round(noi, 2),
        "estimated_annual_gross": round(annual_gross, 2),
        "estimated_cap_rate": round(cap_rate, 2),
        "estimated_grm": round(grm, 2),
        "rent_psf_used": rent_psf,
        "sqft_used": round(sqft, 0),
        "is_estimated": True,
    }


def score_commercial_cap_rate(cap_rate: float) -> float:
    """
    Score cap rate for commercial properties.
    Higher cap rate = better return = higher score.
    Max: 20 points (replaces the dead-weight 0).
    """
    if cap_rate <= 0:
        return 0.0
    elif cap_rate >= 10:
        return 20.0
    elif cap_rate >= 8:
        return 16.0
    elif cap_rate >= 6:
        return 12.0
    elif cap_rate >= 4:
        return 7.0
    elif cap_rate >= 2:
        return 3.0
    else:
        return 0.0


def _estimate_cap_rate(property_dict: dict) -> float:
    """
    Wrapper: compute cap rate estimate and return the score.
    Uses the new GRM-based estimator.
    """
    result = estimate_cap_rate(property_dict)
    cap_rate = result.get("estimated_cap_rate", 0)
    # Store cap rate data on the property dict so it flows to the UI
    property_dict["cap_rate_data"] = result
    return score_commercial_cap_rate(cap_rate)


