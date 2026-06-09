"""
Commercial Scoring — 0-100 score for commercial properties.
Routes by commercial_subtype for specialized scoring.
"""

import re
from typing import Optional
from config import COMMERCIAL_WEIGHTS, TIER_THRESHOLDS, FLOOD_SCORES, CONDITION_SCORES
from scoring.utils import assign_tier, apply_comp_fallback, cap_score_if_no_comps, apply_confidence_cap, apply_variance_penalty


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

    # 1. Price deviation (35 pts max)
    dev = property_dict.get("price_deviation_pct") or 0
    scores["price_deviation"] = max(0, min(35, (-dev / 50) * 35))

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
    flood_zone = property_dict.get("flood_zone")
    scores["flood_penalty"] = FLOOD_SCORES.get(flood_zone, 8)

    # Apply comp fallback: when comp_count=0, use estimated_value as proxy
    scores = apply_comp_fallback(property_dict, scores)

    # Apply confidence cap: if comp_confidence_label is LOW/MEDIUM, cap price_deviation
    scores = apply_confidence_cap(property_dict, scores)

    # Apply variance penalty: high-variance comps reduce price signal reliability
    scores = apply_variance_penalty(property_dict, scores)

    # Total
    total = sum(scores.values())
    total, _ = cap_score_if_no_comps(total, scores)

    # Lead tier
    tier = assign_tier(total)

    if classification in ("fire_damage", "teardown"):
        tier = f"DISTRESSED_{tier}"

    return {
        "scores": scores,
        "total": round(total, 1),
        "tier": tier,
    }


def _estimate_cap_rate(property_dict: dict) -> float:
    """
    Rough cap rate estimate from listing description.
    Returns 0-20 score.
    """
    description = (property_dict.get("listing_description") or "").lower()
    price = property_dict.get("list_price")

    if not price or price <= 0:
        return 10  # neutral

    # Keyword-based income signals
    income_signals = 0
    if any(kw in description for kw in ["cap rate", "caprate", "noi", "net operating"]):
        income_signals += 2
    if any(kw in description for kw in ["rent", "leased", "tenant", "occupied", "income"]):
        income_signals += 2
    if any(kw in description for kw in ["positive cash flow", "cash flowing"]):
        income_signals += 2

    # If description mentions rent, try to parse it
    rent_patterns = [
        r"\$?(\d[\d,]*)\s*(?:/mo|/month|monthly|per month)",
        r"(?:rent|income|gross).*?\$?(\d[\d,]*)",
    ]
    for pattern in rent_patterns:
        match = re.search(pattern, description)
        if match:
            income_signals += 2
            break

    # Score: 8 base + 2 per signal (max 20)
    return min(20, 8 + income_signals * 2)


